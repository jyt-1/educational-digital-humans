<!-- [工单20] 数字人形象层 —— 写实照片渲染（talking-photo）
     v3：全像素形变（slice warp）。v2 的教训：眨眼覆层（从上方取皮肤贴图）与画出来的
     口腔，本质都是「往照片上添加像素」，色调纹理和脸对不齐 → 用户看到的「一块一块」。
     v3 口型和眨眼**零新增像素**：
       口型 = 唇线以下位移场（smoothstep 渐变），下巴整体下移、中间像素连续拉伸，
             唇缝的暗线被拉伸成「开口」，色调就是照片自己的；
       眨眼 = 眼睑上方皮肤按位移场下压覆盖眼球，无贴图、无补丁边。
     形象由 props.face（faces.js 清单项）决定：换形象 = 换图 + 换几何标定，绘制逻辑通用。 -->
<template>
  <canvas ref="canvasRef" class="avatar-photo" :aria-label="`数字人形象（${face.name}）`"></canvas>
</template>

<script setup>
// 为什么不用 SVG：照片是位图，口型/眨眼只能靠 canvas 逐帧重绘。
// 性能红线与 AvatarSpotlight 相同：**绝不触碰 Vue 响应式**——只读 speech.getVolume()
// （普通数值）并直接写 canvas / style，问答页的热路径（Markdown 全量重渲染）不受影响。
// 形象数据刻意复制到模块级普通变量（imgReady/geo/warp 层），rAF 循环里不读 props。
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
// warp 层（必须在 loadFace 首次调用前声明，避免 TDZ）：
let mouthWarp = null // 口型层 { src,out,mask,x0,top,bw,bh,lipY,jawZone,upZone,maxDrop }
let eyeWarps = [] // 眨眼层，每眼一个

function loadFace(face) {
  imgReady = false
  geo = face.geometry
  mouthWarp = null
  eyeWarps = []
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
  // DEV 取证钩子：浏览器 e2e 截图抓不到 150ms 瞬态，可定格闭眼帧检验眼睑形变
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

// ---------------------------------------------------------------- warp 基建
// smoothstep：位移场的缓动核——t=0 处导数为 0（唇线/眼睑缘「贴住」，不产生叠影）
function sstep(t) {
  const x = t < 0 ? 0 : t > 1 ? 1 : t
  return x * x * (3 - 2 * x)
}

/** 四周羽化的蒙版：warp 区域贴回主画布时左右/上下渐隐，消除矩形硬边 */
function makeFeatherMask(w, h, fx, fyT, fyB) {
  const cv = document.createElement('canvas')
  cv.width = w
  cv.height = h
  const c = cv.getContext('2d')
  c.fillStyle = '#fff'
  c.fillRect(0, 0, w, h)
  c.globalCompositeOperation = 'destination-in'
  const gx = c.createLinearGradient(0, 0, w, 0)
  gx.addColorStop(0, 'rgba(0,0,0,0)')
  gx.addColorStop(fx, 'rgba(0,0,0,1)')
  gx.addColorStop(1 - fx, 'rgba(0,0,0,1)')
  gx.addColorStop(1, 'rgba(0,0,0,0)')
  c.fillStyle = gx
  c.fillRect(0, 0, w, h)
  const gy = c.createLinearGradient(0, 0, 0, h)
  gy.addColorStop(0, 'rgba(0,0,0,0)')
  gy.addColorStop(fyT, 'rgba(0,0,0,1)')
  gy.addColorStop(1 - fyB, 'rgba(0,0,0,1)')
  gy.addColorStop(1, 'rgba(0,0,0,0)')
  c.fillStyle = gy
  c.fillRect(0, 0, w, h)
  return cv
}

/**
 * 建一个 warp 层：src（每帧从原图重取的干净源）+ out（逐行重排的输出）+ mask。
 * field(dy, amt) => 源 y：目标行 dy 的内容来自源图第 field(dy) 行——
 * 位移场只依赖 y（竖向），横向靠 mask 羽化过渡，因此逐行采样即可（step=2px）。
 */
function makeWarpLayer(x0, top, bw, bh, fx, fyT, fyB, field) {
  const src = document.createElement('canvas')
  src.width = bw
  src.height = bh
  const out = document.createElement('canvas')
  out.width = bw
  out.height = bh
  return { src, out, mask: makeFeatherMask(bw, bh, fx, fyT, fyB), x0, top, bw, bh, field }
}

/** 执行一次 warp：重取源 → 逐行按位移场重排 → mask 羽化 → 贴回主画布 */
function applyWarp(ctx, layer, amt) {
  const { src, out, mask, bw, bh } = layer
  const sc = src.getContext('2d')
  sc.clearRect(0, 0, bw, bh)
  sc.drawImage(img, layer.x0, layer.top, bw, bh, 0, 0, bw, bh)
  const oc = out.getContext('2d')
  oc.clearRect(0, 0, bw, bh)
  const step = 2
  for (let dy = 0; dy < bh; dy += step) {
    const sy = Math.max(0, Math.min(bh - 1, layer.field(dy, amt)))
    oc.drawImage(src, 0, sy, bw, Math.min(step, bh - sy), 0, dy, bw, step)
  }
  oc.globalCompositeOperation = 'destination-in'
  oc.drawImage(mask, 0, 0)
  oc.globalCompositeOperation = 'source-over'
  ctx.drawImage(out, layer.x0, layer.top)
}

// ---------------------------------------------------------------- 分层构建（换形象时一次性）
function buildFaceLayers() {
  buildMouthWarp()
  buildEyeWarps()
}

/**
 * 口型层 = 下颌位移场。
 * 唇线以上：上唇轻微上移（drop×0.28，让开口更饱满）；
 * 唇线以下：位移从 0（唇线，导数 0 → 无叠影）平滑涨到 drop（下巴整体下移），
 * 中间像素被连续拉伸——原唇缝的暗线随之拉开成「口腔」，不需要画任何暗色。
 */
function buildMouthWarp() {
  const { naturalWidth: W, naturalHeight: H } = img
  const m = geo.mouth
  const mx = m.cx * W
  const my = m.cy * H
  const ryH = m.maxRy * H
  const rw = Math.max(m.maxRx * W * 1.6, ryH * 1.3)
  const x0 = Math.max(0, Math.round(mx - rw))
  const bw = Math.min(W, Math.round(mx + rw)) - x0
  const top = Math.max(0, Math.round(my - ryH * 2.0))
  const bot = Math.min(Math.round(H * geo.cropBottom), Math.round(my + ryH * 3.4))
  const bh = bot - top
  if (bh < 16 || bw < 16) {
    mouthWarp = null
    return
  }
  const lipY = my - top
  const jawZone = ryH * 2.0
  const upZone = ryH * 1.3
  const maxDrop = Math.min(H * 0.021, ryH * 1.3)
  mouthWarp = makeWarpLayer(
    x0,
    top,
    bw,
    bh,
    0.16,
    0.08,
    0.08,
    (dy, drop) => {
      const rel = dy - lipY
      if (rel < 0) return dy + drop * 0.4 * sstep(-rel / upZone)
      return dy - drop * sstep(rel / jawZone)
    },
  )
  mouthWarp.lipY = lipY
  mouthWarp.maxDrop = maxDrop
}

/**
 * 眨眼层 = 眼睑下压位移场。
 * 眼下缘以下不动；从下缘往上位移平滑增大（smoothstep），到眼顶饱和为整块下压——
 * 上方皮肤被连续拉下来盖住眼球，就是眼睑真的合上。
 * 上界在眉毛下（cy-1.0eh）再乘一个衰减因子：位移集中收在眼眶内，眉毛不被拽下来。
 */
function buildEyeWarps() {
  const { naturalWidth: W, naturalHeight: H } = img
  eyeWarps = geo.eyes.map((eye) => {
    const ew = geo.eyeHalfW * 2 * W
    const eh = geo.eyeHalfH * 2 * H
    const rw = ew * 0.78
    const x0 = Math.max(0, Math.round(eye.cx * W - rw))
    const bw = Math.min(W, Math.round(eye.cx * W + rw)) - x0
    const top = Math.max(0, Math.round(eye.cy * H - eh * 1.6))
    const bh = Math.round(eh * 3.5)
    const lidBotRel = eye.cy * H + eh * 0.9 - top
    const browRel = eye.cy * H - eh * 1.0 - top
    const browFade = eh * 0.8
    const lidZone = eh
    const maxLid = eh * 0.95
    const layer = makeWarpLayer(
      x0,
      top,
      bw,
      bh,
      0.2,
      0.18,
      0.1,
      (dy, blink) => dy - blink * maxLid * sstep((lidBotRel - dy) / lidZone) * sstep((dy - browRel) / browFade),
    )
    return layer
  })
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
  // DEV 取证钩子：定格张嘴度（0~1）便于截图检验形变，与 __avatarBlinkHold 同性质
  if (import.meta.env.DEV && typeof window.__avatarMouthHold === 'number') {
    pose.open = window.__avatarMouthHold
  }

  // 底图：裁掉底部水印带（cropBottom，见 faces.js 注释）
  const { naturalWidth: W, naturalHeight: H } = img
  ctx.drawImage(img, 0, 0, W, H * geo.cropBottom, 0, 0, W, H * geo.cropBottom)

  if (blink > 0.03) {
    for (let i = 0; i < eyeWarps.length; i++) applyWarp(ctx, eyeWarps[i], blink)
  }
  if (mouthWarp) {
    const drop = pose.open * mouthWarp.maxDrop
    if (drop > 0.8) applyWarp(ctx, mouthWarp, drop)
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
