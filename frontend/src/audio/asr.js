// [阶段二] 人工智能NLP-Agent数字人项目-教育智能体-数字人形象层 —— 语音识别（麦克风 → 文字）
//
// 方案：Web Speech API（Chrome/Edge 内置，识别走浏览器系统服务，零费用、零后端改动）。
// 局限：Firefox 与旧 Safari 不支持 → isAsrSupported() 返回 false，
// UI 层据此降级：麦克风按钮隐藏或点了提示，键盘输入照常，问答主链路不受影响。
//
// 两点设计说明：
// 1. **continuous=false，一次收一句**：final 结果一到就回调 onFinal 并自动停。
//    不用连续模式的原因——连续模式会把手写体一段话切成多个 final 段，
//    上层若「每段自动发送」就会把一句话拆成几条提问，观感混乱。
//    一次一句的节奏正好匹配「提问 → 数字人回答」的课堂对话形态。
// 2. **interimResults=true**：中间结果实时上屏，学生能看见「我的话被听成了什么」，
//    这正是竞品（小奈式语音识别面板）观感的关键来源。

/** 当前浏览器是否支持语音识别（SSR/极老浏览器安全兜底）。 */
export function isAsrSupported() {
  return typeof window !== 'undefined' && Boolean(window.SpeechRecognition || window.webkitSpeechRecognition)
}

/** error.code → 中文提示。UI 层直接展示，不再自己翻译一遍。 */
const ERROR_TEXT = {
  'not-allowed': '麦克风权限被拒绝，请在浏览器地址栏允许麦克风后重试',
  'service-not-allowed': '语音识别服务不可用，请检查浏览器权限设置',
  'audio-capture': '没有检测到麦克风设备',
  'no-speech': '没听清，请靠近麦克风再说一次',
  network: '语音识别服务需要联网，请检查网络',
  aborted: '', // 用户主动停止，不算错误，静默即可
}

/**
 * 创建一个识别器实例。
 *
 * @param {object} handlers
 * @param {(text: string) => void} [handlers.onInterim] 中间结果（实时、会被后续覆盖）
 * @param {(text: string) => void} [handlers.onFinal] 最终结果（一句说完；触发后识别器自动停）
 * @param {(code: string, message: string) => void} [handlers.onError] 识别出错
 * @param {() => void} [handlers.onStart] 真正开始收音（权限通过后）
 * @param {(byUser: boolean) => void} [handlers.onEnd] 结束（无论正常/出错/手动停止）
 * @param {string} [lang] 识别语言，默认简体中文
 */
export function createAsr({ onInterim, onFinal, onError, onStart, onEnd, lang = 'zh-CN' } = {}) {
  const Ctor = typeof window !== 'undefined' ? window.SpeechRecognition || window.webkitSpeechRecognition : null

  let rec = null
  let active = false
  let gotFinal = false

  /** 开始收音。重复调用无害（已在收音时忽略）。 */
  function start() {
    if (!Ctor || active) return
    gotFinal = false
    rec = new Ctor()
    rec.lang = lang
    rec.continuous = false
    rec.interimResults = true
    rec.maxAlternatives = 1

    rec.onstart = () => {
      active = true
      onStart?.()
    }

    rec.onresult = (event) => {
      let interim = ''
      let finalText = ''
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i]
        if (result.isFinal) finalText += result[0].transcript
        else interim += result[0].transcript
      }
      if (interim) onInterim?.(interim)
      const trimmed = finalText.trim()
      if (trimmed) {
        gotFinal = true
        onFinal?.(trimmed)
        stop() // 一句即止：final 之后浏览器也会自然结束，这里主动收，别等 onend 再拖一拍
      }
    }

    rec.onerror = (event) => {
      const code = event?.error || 'unknown'
      const message = ERROR_TEXT[code] ?? `识别出错：${code}`
      if (message) onError?.(code, message)
    }

    rec.onend = () => {
      active = false
      onEnd?.(gotFinal) // byUser 语义复用为「已出结果/已手动停」：上层据此决定是否自动发送
    }

    try {
      rec.start()
    } catch {
      /* start 抛异常 = 实例已在收音（InvalidStateError），忽略 */
    }
  }

  /** 停止收音。已收到 final 时是「收尾」，否则是「取消」。 */
  function stop() {
    if (!rec || !active) return
    try {
      rec.stop()
    } catch {
      /* 已经停了 */
    }
  }

  return { start, stop, isActive: () => active }
}
