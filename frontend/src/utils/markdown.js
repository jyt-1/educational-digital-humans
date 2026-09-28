// [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— Markdown + LaTeX 统一渲染
/**
 * 全站唯一的「Markdown + 公式」渲染入口。
 *
 * 在它之前，同一个渲染逻辑抄了 6 份，且抄漏了公式：
 * - `views/assistant/Chat.vue`（问答页，唯一一份完整的：占位符 + KaTeX + 流式降级）
 * - `views/lecture/Room.vue`（讲课页，只认 `$..$`，`$$x$$` 会渲染成「$ + 行内 x + $」）
 * - `components/CitationList.vue`（引用卡摘要与「查看原文」弹层）
 * - `views/learn/Mistakes.vue`（题干 / AIGC 解析 / 变式题）
 * - `views/learn/Practice.vue`（题干 / 选项 / 解析）
 * - `views/lesson/Edit.vue`（备课预览）
 *
 * 后 5 处都只做 `marked.parse`，没有公式——而工单17/18/19 的产出一路都是 LLM 生成的
 * 教学内容，`\frac` 这类 LaTeX 会**原样显示成源码**。所以统一收口到这里。
 *
 * ⚠️ 两条不变量，改动前先读（写错了页面不报错，只是公式悄悄变成一串乱码）：
 *
 * 1. **公式必须先抽成占位符，再交给 marked**，两步都不能省：
 *    - 直接进 marked：`$x_1$` 的 `_` 被当斜体、`$a*b$` 的 `*` 被当强调，公式被拆烂；
 *    - 先渲染 KaTeX 再进 marked：KaTeX 输出的 HTML 标签会被 marked 转义成可见源码。
 * 2. **行内 `$..$` 要过 `looksLikeMath` 守卫**（行间不设防）。散文里也有成对美元号
 *    （「价格 $5 到 $10」），不设防会把价格区间吃成公式。
 *    该守卫与后端 `services/tts.py::_looks_like_math` 是**同一条规则**：两种语言没法共用
 *    代码，**改一处请连同另一处一起改**——页面渲染与语音朗读必须给出同一个判断，
 *    否则会出现「页面把价格渲染成公式、语音却照常念」的错位。
 */
import katex from 'katex'
import 'katex/dist/katex.min.css'
import { marked } from 'marked'

import '@/styles/markdown.css'

marked.setOptions({ breaks: true, gfm: true })

// 公式匹配：先 `$$..$$` / `\[..\]`（行间）再 `$..$` / `\(..\)`（行内）。**顺序不能反**，
// 否则 `$$x$$` 会被行内规则从第一个 $ 就开始吞，切出半个公式。
// 行内一组用 [^$\n] 限制不跨行——跨行的 `$` 基本是散文里被误配的一对。
export const TEX_SPAN_RE = /\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)|\$([^$\n]+?)\$/g

// 占位符用 U+0000 包裹：Markdown 不碰控制字符，marked 会原样透出到 HTML 里
const TEX_SLOT = '\u0000'

const CJK_RE = /[一-鿿]/
const MATH_SIGNAL_RE = /[\\^_=]/
const SHORT_TOKEN_RE = /^[A-Za-z0-9.,]{1,5}$/

export function looksLikeMath(tex) {
  if (CJK_RE.test(tex)) return false
  return MATH_SIGNAL_RE.test(tex) || SHORT_TOKEN_RE.test(tex.trim())
}

export function escapeHtml(text) {
  return String(text).replace(
    /[&<>"]/g,
    (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[ch],
  )
}

/**
 * 一段公式 → HTML。
 *
 * `settled=false`（流式进行中）时**不渲染 KaTeX**，只把公式占位成灰色源码片：
 * 半截公式按 HTML 渲染会闪红字，且每个 delta 都重排一遍 KaTeX 太贵（此刻正逐字追加）。
 * 代价是写完瞬间有一次「源码 → 公式」的跳变，这是刻意的取舍。
 */
export function renderTex(tex, display, settled) {
  if (settled) {
    try {
      return katex.renderToString(tex.trim(), { throwOnError: false, displayMode: display })
    } catch {
      /* 落到下面的源码兜底 */
    }
  }
  return `<code class="tex-pending">${escapeHtml(tex.trim())}</code>`
}

/**
 * Markdown 文本 → 可直接 `v-html` 的 HTML（含公式）。
 *
 * @param {string} text       原始 Markdown（可能含 LaTeX）
 * @param {object} [options]
 * @param {boolean} [options.settled=true] 内容是否已写完。流式未结束时传 `false`，
 *        公式只占位成源码片（见 `renderTex`）。非流式场景用默认值即可。
 * @param {(html: string) => string} [options.transformHtml]
 *        marked 产出后、公式还原**之前**的改写钩子。问答页用它把 `[1]` 换成可点角标——
 *        必须卡在这个位置：公式还原之后再做，正则就可能命中 KaTeX 生成的 HTML。
 * @returns {string} HTML；入参为空返回空串，marked 抛错则退回转义后的纯文本
 */
export function renderMarkdown(text, { settled = true, transformHtml } = {}) {
  if (!text) return ''
  const source = String(text)
  const slots = []
  const withSlots = source.replace(TEX_SPAN_RE, (whole, d1, d2, d3, inline) => {
    const display = inline === undefined
    const tex = (display ? (d1 ?? d2 ?? d3) : inline) || ''
    if (!display && !looksLikeMath(tex)) return whole
    slots.push(renderTex(tex, display, settled))
    return `${TEX_SLOT}${slots.length - 1}${TEX_SLOT}`
  })

  let html
  try {
    html = marked.parse(withSlots)
  } catch {
    return escapeHtml(source) // 兜底也要干净：占位符还原不了，就退回纯文本
  }
  if (typeof transformHtml === 'function') html = transformHtml(html) || html

  // 行间公式被 marked 包进 <p> 会多一层段落外边距，单独成段时把壳剥掉
  html = html.replace(
    new RegExp(`<p>\\s*${TEX_SLOT}(\\d+)${TEX_SLOT}\\s*</p>`, 'g'),
    (whole, i) => (slots[Number(i)].startsWith('<span class="katex-display') ? slots[Number(i)] : whole),
  )
  return html.replace(new RegExp(`${TEX_SLOT}(\\d+)${TEX_SLOT}`, 'g'), (_, i) => slots[Number(i)])
}
