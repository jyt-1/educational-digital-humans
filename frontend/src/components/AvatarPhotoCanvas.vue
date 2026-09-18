<!-- [工单20] 数字人形象层 —— 写实照片渲染（talking-photo，音量驱动口型）
     形象由 props.face（faces.js 清单项）决定：换形象 = 换图 + 换几何标定，绘制逻辑通用。 -->
<template>
  <canvas ref="canvasRef" class="avatar-photo" :aria-label="`数字人形象（${face.name}）`"></canvas>
</template>

<script setup>
// 为什么不用 SVG：照片是位图，口型/眨眼只能靠 canvas 逐帧重绘。
// 性能红线与 AvatarSpotlight 相同：**绝不触碰 Vue 响应式**——只读 speech.getVolume()
// （普通数值）并直接写 canvas / style，问答页的热路径（Markdown 全量重渲染）不受影响。
// 形象数据刻意复制到模块级普通变量（imgReady/geo），rAF 循环里不读 props。
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { avatarState, speech } from '@/store/avatar'

const props = defineProps({
  /** 形象清单项（含 img 与 geometry），见 avatar/faces.js */
  face: { type: Object, required: true },
  /** 是否正在生成回答（生成中且未出声 = 思考态） */
  thinking: { type: Boolean, default: false },
  /** 是否正在语音识别收音（聆听态：provider 里对应慢速注意力侧倾） */
  listening: { type: Boolean, default: false },
})

const canvasRef = ref(null)

const BLINK_MS = 150

// ---------------------------------------------------------------- 素材加载
// ⭐ 模块级普通变量：rAF 只读它们（不碰响应式）
let img = new Image()
let imgReady = false
let geo = props.face.geometry
// 分层缓存（必须在 loadFace 首次调用前声明，避免 TDZ）：
let lidPatches = [] // 眨眼：每只眼一个「眼睑覆层」
let jawLayer = null // 口型：唇线以下的下颌层（jaw-drop）
let jawTopY = 0
let mouthCv = null // 口型：口腔暗部离屏缓冲（每帧重绘内容、复用画布）

function loadFace(face) {
  imgReady = false
  geo = face.geometry
  lidPatches = []
  jawLayer = null
  mouthCv = null
  const next = new Image()
  next.onload = () => {
    img = next
    imgReady = true
    syncCanvasSize()
    buildFaceLayers()
  }
  next.onerror = () => {
    // 素材缺失不该让页面白屏：画不出就静止，状态文字与控制按钮照常
    console.warn('[数字人] 形象照片加载失败：', face.img)
  }
  next.src = face.img
}

function syncCanvasSize() {
  const canvas = canvasRef.value
  if (!canvas || !imgReady) return
  // 内部分辨率按素材原始尺寸，CSS 缩放展示——清晰度绰绰有余
  canvas.width = img.naturalWidth || 768
  canvas.height = Math.round((img.naturalHeight || 1024) * geo.cropBottom)
}

loadFace(props.face)
watch(
  () => props.face,
  (f) => {
    if (f) loadFace(f)
  },
)

// ---------------------------------------------------------------- 眨眼调度
let nextBlinkAt = 0
let blinkAt = -1

function scheduleNextBlink(t) {
  const base = avatarState.speaking ? 4500 : 2500
  nextBlinkAt = t + base + Math.random() * 3500
}

function blinkAmount(t) {
  // DEV 取证钩子：浏览器 e2e 截图抓不到 150ms 瞬态，可定格闭眼帧检验眼睑覆层
  if (import.meta.env.DEV && window.__avatarBlinkHold) return 1
  if (blinkAt >= 0) {
    const p = (t - blinkAt) / BLINK_MS
    if (p >= 1) {
      blinkAt = -1
      scheduleNextBlink(t)
      return 0
    }
    return p < 0.5 ? p * 2 : (1 - p) * 2
  }
  if (t >= nextBlinkAt) blinkAt = t
  return 0
}

// ---------------------------------------------------------------- 分层构建（换形象时一次性）
function buildFaceLayers() {
  buildLidPatches()
  buildJawLayer()
  buildMouthBuffer()
}

/**
 * 眨眼 = 眼睑覆层。
 * 旧画法（压扁眼区 + 从眼睛**下方**挖皮肤补缝）会出「一块一块的色块」：
 * 脸颊皮肤的色调纹理和眼皮不一致，且矩形补丁有硬边。
 * 新画法：从眼睛**上方**取眼皮皮肤（色调与闭眼眼睑天然一致）做成四周羽化的覆层，
 * 眨眼时覆层从上往下盖下来——就是眼睑真的合上；覆层底缘自带一条柔和睫毛阴影。
 * 眼球内容不压扁：覆层没盖到的下方露出的是原图下眼睑，物理上正确。
 */
function buildLidPatches() {
  const { naturalWidth: W, naturalHeight: H } = img
  lidPatches = geo.eyes.map((eye) => {
    const ew = geo.eyeHalfW * 2 * W
    const eh = geo.eyeHalfH * 2 * H
    const padX = Math.max(4, ew * 0.12)
    const padB = Math.max(3, eh * 0.4)
    const w = Math.round(ew + padX * 2)
    const h = Math.round(eh + padB)
    const cv = document.createElement('canvas')
    cv.width = w
    cv.height = h
    const c = cv.getContext('2d')
    // 皮肤来源：眼睛上方的眼皮区（比眼高 10% 起向上取 1.1 倍眼高），轻模糊 hides 睫毛/眉杂纹
    const sy = (eye.cy - geo.eyeHalfH) * H - eh * 1.1
    c.filter = 'blur(0.8px)'
    c.drawImage(img, eye.cx * W - ew / 2, sy, ew, eh * 1.1, padX, 0, ew, h)
    c.filter = 'none'
    // 羽化：左右 15% 渐隐；纵向顶部 35% 渐隐、底缘 92% 后快速收（睫毛线位置）
    c.globalCompositeOperation = 'destination-in'
    const gh = c.createLinearGradient(0, 0, w, 0)
    gh.addColorStop(0, 'rgba(0,0,0,0)')
    gh.addColorStop(0.15, 'rgba(0,0,0,1)')
    gh.addColorStop(0.85, 'rgba(0,0,0,1)')
    gh.addColorStop(1, 'rgba(0,0,0,0)')
    c.fillStyle = gh
    c.fillRect(0, 0, w, h)
    const gv = c.createLinearGradient(0, 0, 0, h)
    gv.addColorStop(0, 'rgba(0,0,0,0)')
    gv.addColorStop(0.35, 'rgba(0,0,0,1)')
    gv.addColorStop(0.92, 'rgba(0,0,0,0.9)')
    gv.addColorStop(1, 'rgba(0,0,0,0)')
    c.fillStyle = gv
    c.fillRect(0, 0, w, h)
    c.globalCompositeOperation = 'source-over'
    // 睫毛阴影线：画在覆层底缘上方一点，随覆层一起落下（闭眼时的「睫毛」）
    c.fillStyle = 'rgba(62,36,30,0.42)'
    c.filter = 'blur(1px)'
    c.fillRect(padX + ew * 0.1, h - padB - 1.2, ew * 0.8, 1.5)
    c.filter = 'none'
    return { cv, w, padX }
  })
}

function drawBlink(ctx, eye, blink, patch) {
  if (!patch) return
  const { naturalWidth: W, naturalHeight: H } = img
  const ew = geo.eyeHalfW * 2 * W
  const eh = geo.eyeHalfH * 2 * H
  const ex = (eye.cx - geo.eyeHalfW) * W
  const eyTop = (eye.cy - geo.eyeHalfH) * H
  // 眼睑覆层从上盖下：高度 = 眼高 × blink。覆层没盖到的下方露出原图（下眼睑/下巩膜），
  // 物理正确且没有补丁色块。
  const lidH = eh * blink + 1
  ctx.save()
  ctx.filter = 'blur(0.5px)'
  ctx.drawImage(patch.cv, ex - patch.padX, eyTop - 1, patch.w, lidH)
  ctx.restore()
}

// ---------------------------------------------------------------- 口型（jaw-drop，v2）
// v1 两处翻车（用户实测截图）：① 口腔暗部是半透明径向渐变 → 底图唇齿透出来成「灰糊」；
// ② 下颌层顶部羽化过宽（12px+）→ 下移的嘴唇与原位嘴唇交叉淡化成叠影。
// v2：口腔改为**不透明**（clip 椭圆内填实色竖向渐变，仅边缘羽化）、宽度按真实嘴宽
// （maxRx×1.45）、下移量上限压到 1.6% 图高、下颌层顶部羽化收窄到 6px。
function buildJawLayer() {
  const { naturalWidth: W, naturalHeight: H } = img
  jawTopY = Math.round(geo.mouth.cy * H)
  const h = Math.round(H * geo.cropBottom) - jawTopY
  if (h <= 24) {
    jawLayer = null
    return
  }
  jawLayer = document.createElement('canvas')
  jawLayer.width = W
  jawLayer.height = h
  const jc = jawLayer.getContext('2d')
  jc.drawImage(img, 0, jawTopY, W, h, 0, 0, W, h)
  // 羽化：左右 12%（背景/发丝处交叉淡化无痕）；顶部仅 6px（唇线处要「硬」，
  // 否则下移的嘴唇和原嘴唇叠影——v1 灰糊的元凶之一）
  jc.globalCompositeOperation = 'destination-in'
  const gh = jc.createLinearGradient(0, 0, W, 0)
  gh.addColorStop(0, 'rgba(0,0,0,0)')
  gh.addColorStop(0.12, 'rgba(0,0,0,1)')
  gh.addColorStop(0.88, 'rgba(0,0,0,1)')
  gh.addColorStop(1, 'rgba(0,0,0,0)')
  jc.fillStyle = gh
  jc.fillRect(0, 0, W, h)
  const gv = jc.createLinearGradient(0, 0, 0, h)
  gv.addColorStop(0, 'rgba(0,0,0,0)')
  gv.addColorStop(6 / h, 'rgba(0,0,0,1)')
  gv.addColorStop(1, 'rgba(0,0,0,1)')
  jc.fillStyle = gv
  jc.fillRect(0, 0, W, h)
  jc.globalCompositeOperation = 'source-over'
}

function buildMouthBuffer() {
  const { naturalWidth: W, naturalHeight: H } = img
  const rx = geo.mouth.maxRx * W * 1.45
  mouthCv = document.createElement('canvas')
  mouthCv.width = Math.max(8, Math.ceil(rx * 2))
  mouthCv.height = Math.ceil(H * 0.016) + 14
}

function drawMouth(ctx, open) {
  if (!jawLayer || !mouthCv) return
  const { naturalWidth: W, naturalHeight: H } = img
  const mx = geo.mouth.cx * W
  const my = geo.mouth.cy * H
  const rx = geo.mouth.maxRx * W * 1.45
  // 开合度 → 下颌位移；上限 1.6% 图高（约 16px@1024，防「惊吓下巴」）
  const drop = Math.min(open * geo.mouth.maxRy * H * 0.85, H * 0.016)
  if (drop < 1) return // 微噪声不画，避免嘴部抖动

  const mc = mouthCv.getContext('2d')
  const cw = mouthCv.width
  const ch = mouthCv.height
  mc.clearRect(0, 0, cw, ch)
  const cyL = drop * 0.5 + 2 // 腔体中心（局部坐标；缓冲区顶边对应图像 y = my-2）
  const ryL = drop * 0.6 + 2

  // ① 不透明口腔：椭圆 clip 内填竖向渐变（上暗下稍亮），底图唇齿完全不透出
  mc.save()
  mc.beginPath()
  mc.ellipse(cw / 2, cyL, rx * 0.98, ryL, 0, 0, Math.PI * 2)
  mc.clip()
  const gv = mc.createLinearGradient(0, cyL - ryL, 0, cyL + ryL)
  gv.addColorStop(0, '#2a0908')
  gv.addColorStop(0.45, '#3f100d')
  gv.addColorStop(1, '#5a2019')
  mc.fillStyle = gv
  mc.fillRect(0, 0, cw, ch)
  // ② 上排牙：开口明显时贴上唇（亮度提高，因为腔体现在是实心的）
  if (drop > 4) {
    mc.fillStyle = 'rgba(238,230,222,0.85)'
    mc.filter = 'blur(1.2px)'
    mc.beginPath()
    mc.ellipse(cw / 2, cyL - ryL * 0.62, rx * 0.66, Math.min(drop * 0.32, 4.5), 0, 0, Math.PI * 2)
    mc.fill()
    mc.filter = 'none'
  }
  mc.restore()

  // ③ 腔体边缘羽化（径向渐变 destination-in，椭圆纵向压扁）
  mc.globalCompositeOperation = 'destination-in'
  mc.save()
  mc.translate(cw / 2, cyL)
  mc.scale(1, ryL / rx)
  const rg = mc.createRadialGradient(0, 0, 0, 0, 0, rx)
  rg.addColorStop(0, 'rgba(0,0,0,1)')
  rg.addColorStop(0.7, 'rgba(0,0,0,1)')
  rg.addColorStop(1, 'rgba(0,0,0,0)')
  mc.fillStyle = rg
  mc.fillRect(-rx - 2, -rx - 2, rx * 2 + 4, rx * 2 + 4)
  mc.restore()
  mc.globalCompositeOperation = 'source-over'

  // ④ 合成：腔体顶边贴唇线，随后下颌下移盖上（下唇压住腔体底缘）
  ctx.drawImage(mouthCv, mx - cw / 2, my - 2)
  ctx.drawImage(jawLayer, 0, jawTopY + drop)
}

// ---------------------------------------------------------------- 主循环
let rafId = 0
let t0 = 0

function loop(now) {
  rafId = requestAnimationFrame(loop)
  const canvas = canvasRef.value
  if (!canvas || !imgReady) return
  const ctx = canvas.getContext('2d')
  const t = now - t0

  const state = avatarState.speaking
    ? 'speaking'
    : props.listening
      ? 'listening'
      : props.thinking
        ? 'thinking'
        : 'idle'
  const blink = blinkAmount(t)
  const pose = avatarState.provider.computePose({ volume: speech.getVolume(), state, t, blink })

  // 底图：裁掉底部水印带（cropBottom，见 faces.js 注释）
  const { naturalWidth: W, naturalHeight: H } = img
  ctx.drawImage(img, 0, 0, W, H * geo.cropBottom, 0, 0, W, H * geo.cropBottom)

  if (blink > 0.03) {
    for (let i = 0; i < geo.eyes.length; i++) drawBlink(ctx, geo.eyes[i], blink, lidPatches[i])
  }
  if (pose.open > 0.02) {
    drawMouth(ctx, pose.open)
  }

  // 头部微动走 CSS transform（合成器线程），不重绘画布
  canvas.style.transform = `translateY(${(pose.bodyY * 0.4).toFixed(2)}px) rotate(${pose.headTilt.toFixed(2)}deg)`
}

onMounted(() => {
  syncCanvasSize()
  t0 = performance.now()
  scheduleNextBlink(0)
  rafId = requestAnimationFrame(loop)
})

onBeforeUnmount(() => {
  cancelAnimationFrame(rafId)
  rafId = 0
})
</script>

<style scoped>
.avatar-photo {
  width: 100%;
  height: auto;
  display: block;
  border-radius: 4px;
  transform-origin: 50% 55%;
  will-change: transform;
}
</style>
