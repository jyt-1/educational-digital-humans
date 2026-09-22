// [阶段二] 人工智能NLP-Agent数字人项目-教育智能体-数字人形象层 —— 语音播放管线（切句 + 合成队列 + 音量分析）
//
// 职责边界：**前端只管「在哪切」，后端只管「怎么念」。**
// 切句必须在这里做——要低延迟，只能在 SSE delta 到达时就地判断，
// 等后端来回一趟首句就慢了；而 Markdown 清洗放后端（前端无测试框架，那段最易出错）。
//
// 三条容易踩的坑，改代码前先读：
// 1. **AudioContext 必须在用户手势的同步栈里创建/恢复**。一旦中间 await 过，
//    浏览器就认为不是用户发起的，autoplay 策略会直接挂起音频。
// 2. **decodeAudioData 不可取消**。stop() 之后在途的解码回调仍会回来，
//    靠世代计数器（generation）让所有过期回调失效，否则会有残留声音。
// 3. **音量绝不能进 Vue 响应式**。问答页每次 delta 都全量重渲染 Markdown，
//    已是热路径；音量再逐帧触发重渲染会直接卡死。这里暴露的是普通数值，供 rAF 轮询。

import { speak } from '@/api/tts'
import { createSentenceSplitter } from '@/audio/sentenceSplitter'

// 连续失败这么多句就认定语音服务不可用，本轮不再尝试（避免对断网的后端连发上百次请求）
const FAILURE_LIMIT = 3

// 音量平滑系数：快开慢合。开合对称的话嘴部会明显抖动
const ATTACK = 0.5
const RELEASE = 0.15

/**
 * 创建一个语音队列。问答页每次会话共用一个实例（`createSpeechQueue()` 的结果）。
 *
 * @returns {{
 *   warmup: () => void,
 *   setEnabled: (v: boolean) => void,
 *   isEnabled: () => boolean,
 *   setVoice: (v: string) => void,
 *   setTuning: (t: {rate?: string, pitch?: string}) => void,
 *   start: () => void,
 *   feed: (delta: string) => void,
 *   flush: () => void,
 *   stop: () => void,
 *   getVolume: () => number,
 *   isSpeaking: () => boolean,
 *   onStateChange: (cb: (state: string) => void) => void,
 * }}
 */
export function createSpeechQueue() {
  // ---- 音频图。懒创建：warmup() 里在用户手势栈内建 ----
  let ctx = null
  let analyser = null
  let dataArray = null

  // ---- 播放状态 ----
  let enabled = true
  let voice = ''
  // 形象级音色风格（如小满的萌音）。空对象 = 用后端默认（.env 的 TTS_RATE + 不加音调）
  let tuning = { rate: '', pitch: '' }
  let volume = 0
  let speaking = false
  let stateCb = null

  // ---- 队列 ----
  let generation = 0
  let queue = []
  let pumping = false
  let failing = 0
  let controller = null
  let playing = null
  let rafId = 0

  // ---- 切句（纯逻辑单独成模块，便于用 node 直接校验） ----
  const splitter = createSentenceSplitter(enqueue)

  // 供浏览器取证脚本断言「口型确由声音驱动」，仅 DEV 构建挂载（见 capture_evidence.py）
  const probe = { played: 0, volumePeak: 0 }
  if (import.meta.env.DEV) {
    window.__speechProbe = probe
  }

  // ================================================================ 音频图

  function warmup() {
    if (!enabled) return
    if (!ctx) {
      const Ctor = window.AudioContext || window.webkitAudioContext
      if (!Ctor) {
        enabled = false // 极老浏览器：直接放弃语音，正文与形象照常
        return
      }
      ctx = new Ctor()
      analyser = ctx.createAnalyser()
      // 1024 个采样点足够算 RMS；smoothingTimeConstant 再补一道平滑
      analyser.fftSize = 1024
      analyser.smoothingTimeConstant = 0.6
      dataArray = new Uint8Array(analyser.fftSize)
      analyser.connect(ctx.destination)
    }
    // 被浏览器挂起时恢复。**不 await**：await 之后就脱离用户手势栈了。
    if (ctx.state === 'suspended') {
      ctx.resume().catch(() => {
        /* 恢复失败就是没声音，不影响问答 */
      })
    }
  }

  function tick() {
    rafId = 0
    if (analyser) {
      analyser.getByteTimeDomainData(dataArray)
      let sum = 0
      for (let i = 0; i < dataArray.length; i += 1) {
        const v = (dataArray[i] - 128) / 128
        sum += v * v
      }
      const rms = Math.sqrt(sum / dataArray.length)
      // 语音 RMS 常在 0.1~0.3，乘 3.5 映射到 0~1。系数别调太大：
      // 实测乘 6 时峰值长期顶在 1.0，嘴一直是全张的，反而没有表情。
      const target = Math.min(1, rms * 3.5)
      volume += (target - volume) * (target > volume ? ATTACK : RELEASE)
    }
    if (import.meta.env.DEV && volume > probe.volumePeak) probe.volumePeak = volume
    // 播完后再跑几帧让音量衰减到 0，之后停掉循环省电
    if (speaking || volume > 0.01) {
      rafId = requestAnimationFrame(tick)
    } else {
      volume = 0
    }
  }

  function ensureTick() {
    if (!rafId && ctx) rafId = requestAnimationFrame(tick)
  }

  function setSpeaking(next) {
    if (speaking === next) return
    speaking = next
    stateCb?.(next ? 'speaking' : 'idle')
  }

  // ================================================================ 入队

  /** 切句回调：把一句原始 Markdown 放进合成队列（清洗交给后端）。 */
  function enqueue(text) {
    if (!enabled) return
    queue.push({ text, gen: generation, promise: null, buffer: null })
    prefetch()
    pump().catch(() => {
      /* 单句播放异常不应冒泡成 unhandled rejection */
    })
  }

  // ================================================================ 合成与播放

  /** 合成（幂等：同一句只请求一次）。失败返回 null，由调用方跳过该句。 */
  function ensure(item) {
    // ctx 为空说明 warmup() 没成功（非用户手势栈内调用，或浏览器不支持）
    if (!ctx) return Promise.resolve(null)
    if (!item.promise) {
      item.promise = speak(item.text, {
        voice: voice || undefined,
        rate: tuning.rate || undefined,
        pitch: tuning.pitch || undefined,
        signal: controller?.signal,
      })
        .then((raw) => (raw?.byteLength ? ctx.decodeAudioData(raw) : null))
        .then((decoded) => {
          failing = 0
          return decoded
        })
        .catch((err) => {
          // 400 = 这句话没有可朗读的内容（表格行、纯符号），属**正常的跳过**，
          // 不能算失败。早先把它计入失败，一句回答里出现 3 个表格行就会把整个
          // 语音功能误判为「服务不可用」而停掉，后面的正文全不念了。
          if (err?.status !== 400) {
            failing += 1
            if (failing >= FAILURE_LIMIT) {
              // 语音服务真的不可用：本轮不再尝试，正文与形象不受影响
              enabled = false
              stop()
            }
          }
          return null
        })
    }
    return item.promise
  }

  /** 预取窗口：正在播的那句 + 下一句，最多 2 个在途请求。 */
  function prefetch() {
    for (let i = 0; i < Math.min(queue.length, 2); i += 1) ensure(queue[i])
  }

  /**
   * 串行泵：逐句等播放结束再播下一句。
   *
   * ⚠️ 这里**不能**用「pumpGen === generation 就直接 return」来防重入。
   * 大模型是**一阵一阵**吐字的：一波句子播完、队列暂时空了，泵就退出了；
   * 等下一波 delta 到达时，若判定条件仍是「本轮已有泵在跑」，新句子会被无声丢弃
   * ——表现为只念了开头几句就再也没声（真踩过，且极难从表象看出来）。
   * 故用布尔量，并在正常排空时清掉它；被换代（start/stop）打断的旧泵
   * 在 finally 里不清理，避免误清掉新泵的标志。
   */
  async function pump() {
    if (pumping) return
    pumping = true
    const gen = generation

    try {
      while (queue.length && gen === generation) {
        const item = queue[0]
        const buffer = await ensure(item)
        if (gen !== generation) return
        queue.shift()
        if (!buffer) continue

        prefetch() // 开播的同时把下一句的合成也发出去
        setSpeaking(true)
        ensureTick()
        await play(buffer)
        if (gen !== generation) return
      }
      if (gen === generation) setSpeaking(false)
    } finally {
      if (gen === generation) pumping = false
    }
  }

  function play(buffer) {
    return new Promise((resolve) => {
      const source = ctx.createBufferSource()
      source.buffer = buffer
      source.connect(analyser)
      source.onended = () => {
        // 只有**自然播完**的那句才计数。stop() 也会触发 onended（此时 playing 已被
        // 置空），若无条件自增，取消类的取证就会看到「点了停止之后又播了一句」的假象。
        if (playing === source) {
          playing = null
          probe.played += 1
        }
        resolve()
      }
      playing = source
      playing.onerror = () => resolve()
      source.start()
    })
  }

  // ================================================================ 对外接口

  /** 新的一轮问答开始：清空上一轮残留，换一个新的取消令牌。 */
  function start() {
    generation += 1
    queue = []
    splitter.reset()
    pumping = false // 旧泵已被换代作废（它的 finally 不会再动这个标志）
    failing = 0
    controller = new AbortController()
    warmup()
  }

  /** 收到 SSE delta。 */
  function feed(delta) {
    if (!enabled || !delta) return
    splitter.feed(delta)
  }

  /** 回答结束：把缓冲区里的尾巴念完。 */
  function flush() {
    if (!enabled) return
    splitter.flush()
  }

  /** 立刻静音并清空一切在途状态。四处清理点都要调（见 Chat.vue）。 */
  function stop() {
    generation += 1 // 让所有在途 async 回调失效
    queue = []
    splitter.reset()
    pumping = false
    try {
      playing?.stop()
    } catch {
      /* 已经播完了 */
    }
    playing = null
    controller?.abort()
    controller = null
    volume = 0
    setSpeaking(false)
  }

  return {
    warmup,
    start,
    feed,
    flush,
    stop,
    getVolume: () => volume,
    isSpeaking: () => speaking,
    isEnabled: () => enabled,
    setVoice: (v) => {
      voice = v || ''
    },
    /** 形象级音色风格：只影响之后新入队的句子（已在播的不受影响）。 */
    setTuning: ({ rate, pitch } = {}) => {
      tuning = { rate: rate || '', pitch: pitch || '' }
    },
    setEnabled: (v) => {
      enabled = Boolean(v)
      if (!enabled) stop()
    },
    onStateChange: (cb) => {
      stateCb = cb
    },
  }
}
