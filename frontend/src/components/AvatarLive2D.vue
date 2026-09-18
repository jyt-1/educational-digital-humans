<!-- [工单20] 数字人形象层 —— Live2D 二次元档渲染（音量驱动口型）
     与写实照片档共用同一条音频管线（speech.getVolume()），只是渲染层换成 WebGL 模型。 -->
<template>
  <div class="avatar-live2d-box">
    <canvas ref="canvasRef" class="avatar-live2d" :aria-label="`数字人形象（${face.name}）`"></canvas>
    <div v-if="!ready" class="avatar-live2d-mask">
      <span v-if="failed">Live2D 加载失败，已回退静态待机</span>
      <span v-else>形象加载中…</span>
    </div>
  </div>
</template>

<script setup>
// 性能红线：ticker 里只读 speech.getVolume() / avatarState.speaking（普通数值），
// 不触发任何 Vue 响应式更新。
//
// 懒加载：pixi.js（约 450KB）与 Cubism2 core 只在用户真正选中 Live2D 形象时才下载，
// 写实照片档的用户完全不受影响。
import { onBeforeUnmount, onMounted, ref } from 'vue'

import { avatarState, speech } from '@/store/avatar'

const props = defineProps({
  /** 形象清单项（type: 'live2d'，含 model 路径），见 avatar/faces.js */
  face: { type: Object, required: true },
  thinking: { type: Boolean, default: false },
  listening: { type: Boolean, default: false },
})

const canvasRef = ref(null)
const ready = ref(false)
const failed = ref(false)

let app = null
let model = null
let coreModel = null
let lastW = 0
let lastH = 0
let t0 = 0
let corePromise = null

/** Cubism2 运行时 core（全局脚本，window.Live2D），本地托管不依赖外网 CDN。 */
function loadCore() {
  if (window.Live2D) return Promise.resolve()
  if (!corePromise) {
    corePromise = new Promise((resolve, reject) => {
      const s = document.createElement('script')
      s.src = '/live2d/core/live2d.min.js'
      s.onload = () => resolve()
      s.onerror = () => reject(new Error('live2d core 加载失败'))
      document.head.appendChild(s)
    })
  }
  return corePromise
}

function fit() {
  if (!model || !app) return
  const rw = app.renderer.width / app.renderer.resolution
  const rh = app.renderer.height / app.renderer.resolution
  const mh = model.internalModel.height || model.height || 1
  const mw = model.internalModel.width || model.width || 1
  const s = Math.min((rh * 0.96) / mh, (rw * 0.92) / mw)
  model.scale.set(s)
  model.anchor.set(0.5, 0.5)
  model.x = rw / 2
  model.y = rh / 2
}

/** 安全写模型参数：不同模型参数名可能缺失，缺了不该让整个 ticker 抛错。 */
function setParam(name, value) {
  try {
    coreModel?.setParamFloat(name, value)
  } catch {
    /* 参数不存在：忽略 */
  }
}

async function mount() {
  try {
    await loadCore()
    const [PIXI, { Live2DModel }] = await Promise.all([
      import('pixi.js'),
      import('pixi-live2d-display/cubism2'),
    ])
    // pixi-live2d-display 的内部动效系统依赖全局 PIXI（官方 README 要求）
    window.PIXI = PIXI

    const canvas = canvasRef.value
    if (!canvas) return
    app = new PIXI.Application({
      view: canvas,
      autoStart: true,
      backgroundAlpha: 0,
      resizeTo: canvas.parentElement,
      antialias: true,
      resolution: Math.min(window.devicePixelRatio || 1, 2),
    })

    model = await Live2DModel.from(props.face.model, { autoInteract: false })
    coreModel = model.internalModel.coreModel
    app.stage.addChild(model)
    fit()
    ready.value = true

    t0 = performance.now()
    app.ticker.add(() => {
      if (!app || !model) return
      // 容器尺寸变化（窗口缩放 / 切布局）时重新适配
      const w = app.renderer.width
      const h = app.renderer.height
      if (w !== lastW || h !== lastH) {
        lastW = w
        lastH = h
        fit()
      }
      const t = performance.now() - t0
      const state = avatarState.speaking
        ? 'speaking'
        : props.listening
          ? 'listening'
          : props.thinking
            ? 'thinking'
            : 'idle'
      // 口型：音量直接映射张嘴参数（与照片档同源，真实音频驱动）
      setParam('PARAM_MOUTH_OPEN_Y', state === 'speaking' ? speech.getVolume() : 0)
      // 微动作：说话时轻摆、聆听时慢速侧倾 + 轻微点头（表示「在听」）
      const angleZ =
        state === 'speaking'
          ? Math.sin((t / 1100) * Math.PI * 2) * 3
          : state === 'listening'
            ? Math.sin((t / 2600) * Math.PI * 2) * 2.5
            : 0
      setParam('PARAM_ANGLE_Z', angleZ)
      setParam('PARAM_ANGLE_Y', state === 'listening' ? Math.sin((t / 1600) * Math.PI * 2) * 1.5 : 0)
      setParam('PARAM_ANGLE_X', state === 'thinking' ? 3 : 0)
    })
  } catch (e) {
    console.warn('[数字人] Live2D 加载失败：', e)
    failed.value = true
  }
}

onMounted(mount)

onBeforeUnmount(() => {
  try {
    app?.ticker?.stop()
    model?.destroy()
    app?.destroy(true, { children: true })
  } catch {
    /* 卸载异常不影响页面 */
  }
  app = null
  model = null
  coreModel = null
})
</script>

<style scoped>
.avatar-live2d-box {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 180px;
}

.avatar-live2d {
  width: 100%;
  height: 100%;
  display: block;
}

.avatar-live2d-mask {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: #909399;
  background: rgba(255, 255, 255, 0.55);
}
</style>
