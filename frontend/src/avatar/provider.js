// [阶段二] 人工智能NLP-Agent数字人项目-教育智能体-数字人形象层 —— 形象驱动 provider
//
// 这是 CLAUDE.md 第 19 行要求的「形象驱动 / TTS 各一个接口」中的**形象驱动接口**。
// 沿用本仓库既有的函数式 provider 范式（见 backend/app/services/embedding.py）：
// 具名实现 + 字符串开关 + 查找函数 + 未知值回退并告警，**不引入抽象类/工厂**。
//
// 契约：provider = { name, render, computePose({ volume, state, t, blink }) → Pose }
//   - `render`: 'photo' | 'live2d'，渲染层标记；与形象库 faces.js 里每个形象的
//     `render` 是同一套词汇（前端形象侧只有一张「渲染层名 → 组件」的对照表）
//   - `state`: 'idle' | 'thinking' | 'speaking' | 'listening'
//     （'listening' = 语音识别收音中：静息呼吸 + 慢速轻微侧倾，表示「在注意听」）
//   - `volume`: 0~1，由 Web Audio 的 AnalyserNode 实测（**不是假动画**）
//   - `t`: 毫秒时间戳，用于呼吸/摆动等周期动作
//   - `blink`: 0~1，眨眼闭合度，由舞台按随机间隔调度
//   → Pose: { mouth, eyeScaleY, browY, pupilX, pupilY, headTilt, bodyY }
//
// 2026-09-18：**svg-face 卡通脸已正式退役**（用户拍板，观感"不叫数字人"）。
// 形象侧只剩两档：photo（写实照片 talking-photo）与 live2d（二次元）。
//
// **阶段三接云端数字人（臻灵 / 讯飞）时**：新增一个 cloud 实现并在此登记，
// 同时给形象库（faces.js）补上 render:'cloud' 的形象，再把 .env 的 AVATAR_PROVIDER 改掉。
// ⚠️ 但**「只改配置」并不成立**——云端返回的是**视频流（像素）而非口型参数**，还要动三处：
//   ① 渲染层新增视频播放分支（届时给契约补可选的 mount(container)，见下）；
//   ② 停用本地口型与朗读管线（否则和云端视频双声），声波改取视频音轨音量；
//   ③ 后端加起流/停流接口，管住 stream_url 与会话配额（别把 stream_url 直接给前端）。
// 背景与采购清单见 docs/讲解文档-平台说明.md 第 6.1 节。

/**
 * 兜底实现的名字：未知 / 空 provider 一律回退到它。
 * 对应 .env 的 `AVATAR_PROVIDER=photo`。
 */
export const PHOTO_FACE = 'photo'

/**
 * 写实照片数字人（talking-photo）：一张正面人像 + canvas 逐帧口型/眨眼。
 * 与 live2d 档共用同一条音频管线（speech.getVolume()），只是渲染层不同。
 * 素材与逐形象的几何标定在 avatar/faces.js（几何随形象走，不在这里）。
 */
export const LIVE2D_FACE = 'live2d'

/** 已登记的实现表。photo / live2d 在下方各自注册。 */
const PROVIDERS = {}

function clamp01(v) {
  return v < 0 ? 0 : v > 1 ? 1 : v
}

// ================================================================ photo 实现
const photoProvider = {
  name: PHOTO_FACE,
  /** 渲染层标记：AvatarSpotlight 据此挂载 AvatarPhotoCanvas（canvas 逐帧口型） */
  render: 'photo',

  /**
   * photo 档的 Pose：只提供开合度与头部位姿（眨眼由渲染组件按 blink 参数算）。
   * 口型/眨眼的实际绘制在 AvatarPhotoCanvas，这里只做数值。
   */
  computePose({ volume, state, t, blink }) {
    const open = state === 'speaking' ? clamp01(volume) : 0
    // 说话时头部 ±0.8° 轻摆——照片比卡通更怕"完全静止"，但幅度要比卡通小，
    // 大了会像 PPT 抖动。聆听时更慢更小（±0.5°），静息时只剩呼吸。
    const headTilt =
      state === 'speaking'
        ? Math.sin((t / 1100) * Math.PI * 2) * 0.8
        : state === 'listening'
          ? Math.sin((t / 2600) * Math.PI * 2) * 0.5
          : 0
    const bodyY = state === 'idle' || state === 'listening' ? Math.sin((t / 4000) * Math.PI * 2) * 1 : 0
    return {
      open,
      headTilt,
      bodyY,
      // photo 渲染层用不到 SVG 专用字段，给默认值保持契约完整
      mouth: '',
      eyeScaleY: 1 - blink * 0.94,
      browY: 0,
      pupilX: 0,
      pupilY: 0,
    }
  },
}

PROVIDERS[PHOTO_FACE] = photoProvider

// ================================================================ live2d 实现
//
// [工单20] Live2D 二次元档：WebGL 渲染（pixi-live2d-display + Cubism2 core），
// 实际渲染组件在 components/AvatarLive2D.vue。与 photo 档共用同一条音频管线
// （speech.getVolume() 映射模型的 PARAM_MOUTH_OPEN_Y），只是渲染层换皮。
// 形象件（模型路径）由 avatar/faces.js 清单下发，这里只登记渲染类型。
const live2dProvider = {
  name: LIVE2D_FACE,
  /** 渲染层标记：AvatarSpotlight 据此挂载 AvatarLive2D（WebGL） */
  render: 'live2d',

  /** 与 photo 档相同的数值语义：开合度 + 头部位姿（模型微动作在渲染组件里做）。 */
  computePose({ volume, state, t, blink }) {
    const open = state === 'speaking' ? clamp01(volume) : 0
    const headTilt =
      state === 'speaking'
        ? Math.sin((t / 1100) * Math.PI * 2) * 0.8
        : state === 'listening'
          ? Math.sin((t / 2600) * Math.PI * 2) * 0.5
          : 0
    const bodyY = state === 'idle' || state === 'listening' ? Math.sin((t / 4000) * Math.PI * 2) * 1 : 0
    return {
      open,
      headTilt,
      bodyY,
      mouth: '',
      eyeScaleY: 1 - blink * 0.94,
      browY: 0,
      pupilX: 0,
      pupilY: 0,
    }
  },
}

PROVIDERS[LIVE2D_FACE] = live2dProvider

/** 按名字取实现；未知 / 空名字回退 photo 并告警（改错 .env 不该让页面白屏）。 */
export function pickAvatarProvider(name) {
  const key = String(name || '').trim()
  if (PROVIDERS[key]) return PROVIDERS[key]
  if (key) {
    console.warn(`[数字人] 未知的形象 provider「${key}」，已回退到 ${PHOTO_FACE}`)
  }
  return PROVIDERS[PHOTO_FACE]
}

/**
 * 渲染层判定 —— 前端形象侧**唯一**的「该用哪个组件画」入口。
 *
 * 优先级：形象的 `render`（素材自带：照片档只能用照片逐帧画，Live2D 档必须有模型件）
 *       → provider 的 `render`（.env 的 AVATAR_PROVIDER，部署级默认值）
 *       → 'photo'（兜底）
 *
 * 之所以以形象自带值为准：**一张脸只能用一种方式渲染**，素材决定它怎么画。
 * `.env` 的 AVATAR_PROVIDER 决定的是本部署把哪套驱动作为默认档（阶段三换成 cloud 时，
 * 形象库整体换成 render:'cloud' 的云端形象，而不是把现有照片档强行指到 cloud）。
 *
 * 返回值一定是已登记的渲染层名，绝不返回空值——否则舞台白屏。
 */
export function pickRender(face, provider) {
  const wanted = (face && face.render) || (provider && provider.render) || PHOTO_FACE
  return PROVIDERS[wanted] ? wanted : PHOTO_FACE
}
