// [阶段二] 人工智能NLP-Agent数字人项目-教育智能体-数字人形象层 —— 形象驱动 provider
//
// 这是 CLAUDE.md 第 19 行要求的「形象驱动 / TTS 各一个接口」中的**形象驱动接口**。
// 沿用本仓库既有的函数式 provider 范式（见 backend/app/services/embedding.py）：
// 具名实现 + 字符串开关 + 查找函数 + 未知值回退并告警，**不引入抽象类/工厂**。
//
// 契约：provider = { name, palette, computePose({ volume, state, t, blink }) → Pose }
//   - `state`: 'idle' | 'thinking' | 'speaking'
//   - `volume`: 0~1，由 Web Audio 的 AnalyserNode 实测（**不是假动画**）
//   - `t`: 毫秒时间戳，用于呼吸/摆动等周期动作
//   - `blink`: 0~1，眨眼闭合度，由舞台按随机间隔调度
//   → Pose: { mouth, eyeScaleY, browY, pupilX, pupilY, headTilt, bodyY }
//
// **阶段三接云端数字人（臻灵 / 讯飞）时**：新增一个实现并在此登记，把 .env 里的
// AVATAR_PROVIDER 改掉即可，问答页与舞台代码不动。届时云端 SDK 多半自带渲染容器，
// 需要给契约补一个可选的 mount(container) —— 那是阶段三的扩展点，本期不预先实现。

/** 本地实现的名字，也是默认值（与 .env 的 AVATAR_PROVIDER 对应）。 */
export const SVG_FACE = 'svg-face'

const PALETTE = {
  skin: '#fbdcc4',
  skinLine: '#e8b79a',
  hair: '#3b3a4a',
  eyeWhite: '#ffffff',
  pupil: '#2f3542',
  mouth: '#c0554d',
  blush: '#f7a8a0',
}

/** 嘴部 path：闭嘴时是一条唇线，张嘴时下唇下凹成椭圆口型。 */
function mouthPath(open) {
  const h = 2 + open * 15 // 至少 2px，否则闭嘴时形状退化成不可见的零面积
  const w = 20 + open * 4 // 张嘴时嘴角略微拉开
  return `M ${100 - w} 148 Q 100 ${148 - h * 0.1} ${100 + w} 148 Q 100 ${148 + h} ${100 - w} 148 Z`
}

function clamp01(v) {
  return v < 0 ? 0 : v > 1 ? 1 : v
}

/** 本地实现：纯代码绘制的卡通脸（零素材依赖，见 docs/设计文档-工单16.md 阶段二）。 */
export const svgFaceProvider = {
  name: SVG_FACE,
  palette: PALETTE,
  mouthPath,

  computePose({ volume, state, t, blink }) {
    // 只有说话时才张嘴；音量已在上游做过「快开慢合」平滑
    const open = state === 'speaking' ? clamp01(volume) : 0
    // 呼吸：仅静息时上下浮动 ~1px，4 秒一个周期
    const bodyY = state === 'idle' ? Math.sin((t / 4000) * Math.PI * 2) * 1 : 0
    // 说话时头部 ±1.5° 轻摆，避免像张静止图片
    const headTilt = state === 'speaking' ? Math.sin((t / 900) * Math.PI * 2) * 1.5 : 0
    // 思考时瞳孔看向右上、眉毛上扬
    const thinking = state === 'thinking'

    return {
      mouth: mouthPath(open),
      eyeScaleY: 1 - blink * 0.94, // 留 0.06 免得眼睛缩成一条绝对直线，像闭眼又像没有
      browY: thinking ? -4 : 0,
      pupilX: thinking ? 3 : 0,
      pupilY: thinking ? -3 : 0,
      headTilt,
      bodyY,
    }
  },
}

const PROVIDERS = { [SVG_FACE]: svgFaceProvider }

/** 按名字取实现；未知名字回退默认并告警（改错 .env 不该让页面白屏）。 */
export function pickAvatarProvider(name) {
  const key = String(name || '').trim()
  if (PROVIDERS[key]) return PROVIDERS[key]
  if (key) {
    console.warn(`[数字人] 未知的形象 provider「${key}」，已回退到 ${SVG_FACE}`)
  }
  return PROVIDERS[SVG_FACE]
}
