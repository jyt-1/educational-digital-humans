// [阶段二] 人工智能NLP-Agent数字人项目-教育智能体-数字人形象层 —— 流式文本切句
//
// 从零散到达的 SSE delta 里切出完整句子。**纯逻辑、零依赖**——刻意不做任何 import，
// 这样它可以直接用 node 跑校验（本仓库前端没有测试框架，见 docs/进度记录.md）。
//
// 切句为什么在前端：要「边生成边念」，第一句必须在整篇写完之前就开念。
// 这要求 delta 一到就就地判断，等后端来回一趟首句就慢了。
//
// 已经踩过的坑（改这里前先读）：
// - 小数点 `3.14`、缩写 `etc.` 不能切；
// - `……`、`！！！` 要等连完再切，否则会切出一堆单字句；
// - `他说：“你好。”然后走了。` 要在引号闭合后再切，否则引号被甩到下一句开头；
// - 代码围栏 ```` ``` ```` 要整段丢弃，且围栏可能跨多个 delta 到达 → 必须用**状态机**。

// 句末终止符
const TERMINATORS = new Set(['。', '！', '？', '；', '!', '?', ';', '\n'])
// 收尾符：闭合引号/括号，`。”` 要在引号闭合后再切
const CLOSERS = new Set(['”', '’', '」', '』', '）', ')', '】', '》', '"', "'"])

/**
 * @param {(sentence: string) => void} onSentence 每切出一句回调一次（参数已 trim）
 * @returns {{feed: (delta: string) => void, flush: () => void, reset: () => void}}
 */
export function createSentenceSplitter(onSentence) {
  let pending = ''
  let inFence = false

  /** 扫描缓冲区，逐句吐出；`atEnd` 为 true 时把尾巴也算一句。 */
  function scan(atEnd) {
    let i = 0
    let buf = ''
    while (i < pending.length) {
      // 围栏标记：进出都要先把已缓冲的正文吐出去（"代码如下：```…" 里那半句是真的要念的）
      if (pending.startsWith('```', i) || pending.startsWith('~~~', i)) {
        inFence = !inFence
        i += 3
        emit(buf)
        buf = ''
        continue
      }
      if (inFence) {
        i += 1 // 围栏内整段丢弃，与后端 to_speakable 形成双保险
        continue
      }
      buf += pending[i]
      i += 1
      if (isCut(buf, pending.slice(i), atEnd)) {
        emit(buf)
        buf = ''
      }
    }
    pending = buf
    if (atEnd) {
      emit(pending)
      pending = ''
    }
  }

  /** 刚吃进来的字符是否构成句末。`rest` 是其后尚未消费的文本。 */
  function isCut(buf, rest, atEnd) {
    const ch = buf[buf.length - 1]
    const next = rest[0]

    if (ch === '.') {
      if (next !== undefined && /[0-9A-Za-z]/.test(next)) return false // 3.14 / etc.
      if (next === undefined) return atEnd
      return /[\s"'”’）】]/.test(next)
    }

    if (ch === '…') {
      return next !== undefined && next !== '…' // 等省略号连完
    }

    if (CLOSERS.has(ch)) {
      // 引号闭合了且闭合前就是句末 → 在此切，引号留在本句
      return buf.length >= 2 && TERMINATORS.has(buf[buf.length - 2])
    }

    if (!TERMINATORS.has(ch)) return false

    if (next === undefined) return atEnd
    if (TERMINATORS.has(next) || next === '…') return false // 连用终止符，等连完
    if (CLOSERS.has(next)) return false // 引号未闭合，等闭合后再切
    return true
  }

  /** 过滤后回调：太短或没有可朗读内容的丢弃。 */
  function emit(raw) {
    const text = (raw || '').trim()
    if (text.length < 2) return
    if (!/[一-龥A-Za-z0-9]/.test(text)) return
    onSentence(text)
  }

  return {
    feed(delta) {
      if (!delta) return
      pending += delta
      scan(false)
    },
    flush() {
      scan(true)
    },
    reset() {
      pending = ''
      inFence = false
    },
  }
}
