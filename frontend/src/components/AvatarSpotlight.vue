<!-- [工单22] 沉浸式数字人舞台 —— 助教台右侧主区
     结构：柔光虚拟背景 → 数字人容器（占高 80%）→ 悬浮胶囊状态标签 → 播放时声波可视化
     右上角「设置」管形象/音色/朗读。
     渲染分发走 avatar/provider.js 的 pickRender(face, provider) —— 前端形象侧唯一的
     「渲染层名 → 组件」入口（照片档 canvas / Live2D 档 WebGL），不在这里另立一套判断。 -->
<template>
  <section class="spot-stage">
    <!-- 柔和虚拟背景：浅蓝→粉紫渐变 + 模糊光斑（纯 CSS，无图片依赖、无网络请求） -->
    <div class="spot-bg" aria-hidden="true">
      <span class="spot-blob blob-a"></span>
      <span class="spot-blob blob-b"></span>
      <span class="spot-blob blob-c"></span>
      <div class="spot-floor"></div>
    </div>

    <!-- 右上角工具：形象 / 音色 / 朗读，一个入口全管 -->
    <div class="spot-tools">
      <button class="spot-tool" title="切换形象与音色" @click="settingsOpen = true">
        <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
          <line x1="2" y1="4.5" x2="14" y2="4.5" stroke="currentColor" stroke-width="1.4" />
          <circle cx="6" cy="4.5" r="2" fill="currentColor" />
          <line x1="2" y1="11.5" x2="14" y2="11.5" stroke="currentColor" stroke-width="1.4" />
          <circle cx="10.5" cy="11.5" r="2" fill="currentColor" />
        </svg>
        <span>形象设置</span>
      </button>
      <button
        class="spot-tool"
        :class="{ off: !avatarState.enabled }"
        :disabled="!avatarState.available"
        :title="avatarState.enabled ? '点击静音' : '点击开启朗读'"
        @click="toggleSpeech"
      >
        <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
          <path d="M3 6h2.5L9 3.2v9.6L5.5 10H3z" fill="currentColor" />
          <path v-if="avatarState.enabled" d="M11 5.5a3.5 3.5 0 0 1 0 5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
          <line v-else x1="11" y1="6" x2="14" y2="10" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
          <line v-if="!avatarState.enabled" x1="14" y1="6" x2="11" y2="10" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
        </svg>
        <span>{{ avatarState.enabled ? '朗读中' : '已静音' }}</span>
      </button>
    </div>

    <!-- 数字人容器：舞台高度的 80% 起，底部与「地面」相接 -->
    <div class="spot-figure">
      <div class="spot-capsule" :class="stateKey">
        <span class="spot-capsule-dot"></span>
        <span>{{ statusText }}</span>
      </div>

      <div class="spot-canvas">
        <AvatarPhotoCanvas
          v-if="render === 'photo'"
          :face="face"
          :thinking="thinking"
          :listening="listening"
        />
        <AvatarLive2D v-else :face="face" :thinking="thinking" :listening="listening" />
      </div>

      <!-- 声波可视化：仅播放中显示，高度由真实播放音量驱动（不占 Vue 响应式） -->
      <div v-show="avatarState.speaking" class="spot-wave" aria-hidden="true">
        <span v-for="i in WAVE_BARS" :key="i" :ref="setWaveBar" class="spot-wave-bar"></span>
      </div>
    </div>

    <!-- 形象 + 音色设置（毛玻璃卡片） -->
    <el-dialog v-model="settingsOpen" title="数字人形象与声音" width="560px" append-to-body>
      <p class="set-hint">
        切换形象会自动配对音色，也可以手动改。<br />
        当前形象驱动：{{ avatarState.provider.name }}（由 .env 的 AVATAR_PROVIDER 指定）
      </p>
      <div class="face-grid">
        <button
          v-for="f in FACES"
          :key="f.id"
          class="face-card"
          :class="{ active: f.id === avatarState.faceId }"
          @click="chooseFace(f.id)"
        >
          <div class="face-thumb">
            <img v-if="f.render === 'photo'" :src="f.img" :alt="f.name" />
            <svg v-else viewBox="0 0 40 48" class="face-thumb-svg" aria-hidden="true">
              <circle cx="20" cy="17" r="8" fill="#ed93b1" />
              <path d="M11 46q9-13 18 0z" fill="#afa9ec" />
              <circle cx="17" cy="16" r="1.2" fill="#4b1528" />
              <circle cx="23" cy="16" r="1.2" fill="#4b1528" />
            </svg>
          </div>
          <div class="face-name">{{ f.name }}</div>
          <div class="face-desc">{{ f.desc }}</div>
          <span v-if="f.id === avatarState.faceId" class="face-current">使用中</span>
        </button>
      </div>

      <div class="set-row">
        <span class="set-label">朗读</span>
        <el-switch
          :model-value="avatarState.enabled"
          :disabled="!avatarState.available"
          @change="toggleSpeech"
        />
        <span v-if="!avatarState.available" class="set-off-hint">语音服务未启用，形象仍会眨眼/呼吸</span>
      </div>
      <div class="set-row">
        <span class="set-label">音色</span>
        <el-select v-model="voiceModel" size="small" style="width: 240px" :disabled="!avatarState.available">
          <el-option
            v-for="item in avatarState.voices"
            :key="item.short_name"
            :label="`${item.gender === 'Female' ? '女声' : '男声'} · ${item.short_name.split('-').pop()}`"
            :value="item.short_name"
          />
        </el-select>
        <!-- 试听：不换形象也能立刻听到「这个音色 + 这个形象的嗓音调性」是什么效果。
             萌音这类 prosody 参数光看标签体会不到，必须给个出声的入口。 -->
        <el-button
          size="small"
          :icon="VideoPlay"
          :disabled="!avatarState.available"
          title="用当前音色试听一句话"
          @click="previewVoice"
        >
          试听
        </el-button>
        <!-- 音色风格随形象自动应用（如小满的萌音）；这里显性标注，否则用户不知道为何听感不同 -->
        <el-tag v-if="voiceStyleLabel" size="small" type="warning" effect="light">
          {{ voiceStyleLabel }}
        </el-tag>
      </div>
      <template #footer>
        <el-button @click="settingsOpen = false">完成</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { VideoPlay } from '@element-plus/icons-vue'

import { FACES } from '@/avatar/faces'
import { pickRender } from '@/avatar/provider'
import AvatarLive2D from '@/components/AvatarLive2D.vue'
import AvatarPhotoCanvas from '@/components/AvatarPhotoCanvas.vue'
import { avatarState, setFace, setSpeechEnabled, setVoice, speech } from '@/store/avatar'

const props = defineProps({
  /** 是否正在生成回答（生成中且未出声 = 思考态） */
  thinking: { type: Boolean, default: false },
  /** 是否正在语音识别收音（聆听态） */
  listening: { type: Boolean, default: false },
})

const settingsOpen = ref(false)
const face = computed(() => avatarState.face)

/** 渲染组件分派：形象自带 render 优先，provider.render 兜底，未知回退照片档。 */
const render = computed(() => pickRender(face.value, avatarState.provider))

const voiceModel = computed({
  get: () => avatarState.voice,
  set: (v) => setVoice(v),
})

/** 形象自带的音色风格标注（小满的萌音：音调 +30Hz、语速 +8%）。 */
const voiceStyleLabel = computed(() => {
  const s = face.value?.voiceStyle
  if (!s) return ''
  const parts = []
  if (s.pitch) parts.push(`音调 ${s.pitch}`)
  if (s.rate) parts.push(`语速 ${s.rate}`)
  return parts.length ? `萌音·${parts.join(' / ')}` : ''
})

const statusText = computed(() => {
  if (props.listening) return '倾听中'
  if (avatarState.speaking) return '回复中'
  if (props.thinking) return '思考中'
  return '待命中'
})

const stateKey = computed(() => {
  if (props.listening) return 'is-listening'
  if (avatarState.speaking) return 'is-speaking'
  if (props.thinking) return 'is-thinking'
  return 'is-idle'
})

function toggleSpeech() {
  setSpeechEnabled(!avatarState.enabled)
}

function chooseFace(id) {
  setFace(id)
}

/** 试听文本：带上形象名字，顺带验证「形象 ↔ 声音」配对是否对得上（女脸不该出男声）。 */
const previewText = computed(
  () => `同学们好呀，我是${face.value?.name || '你们的老师'}，今天我们一起把这个知识点弄明白。`,
)

/**
 * 用当前音色 + 当前形象的嗓音调性（如小满的萌音）+ 试听一句话。
 *
 * ⚠️ `speech.start()` 必须在用户点击的**同步栈**里调用（它负责建 AudioContext 并
 * resume）——放进 await/Promise 之后就会脱离手势栈，浏览器按 autoplay 策略挂起，
 * 点了没声。这与问答页 warmup 的红线是同一条。
 */
function previewVoice() {
  if (!avatarState.available) return
  // 静音状态下点试听：顺手把朗读打开，否则用户点了半天没动静只会以为是坏的
  if (!avatarState.enabled) setSpeechEnabled(true)
  speech.stop()
  speech.start()
  speech.feed(previewText.value)
  speech.flush()
}

// ---------------------------------------------------------------- 声波可视化
// ⭐ 与口型同一条红线：只读 speech.getVolume()（普通数值），直接写 DOM style，
// 不触发任何响应式更新。
const WAVE_BARS = 24
const waveBars = []
function setWaveBar(el) {
  if (el) waveBars.push(el)
}

let rafId = 0
let t0 = 0
function loop(now) {
  rafId = requestAnimationFrame(loop)
  if (!waveBars.length) return
  const t = now - t0
  const v = speech.getVolume()
  for (let i = 0; i < waveBars.length; i++) {
    const bar = waveBars[i]
    if (!bar) continue
    // 中间高两侧低的包络 × 音量 × 相位错开的呼吸
    const center = 1 - Math.abs(i - (waveBars.length - 1) / 2) / ((waveBars.length - 1) / 2)
    const envelope = 0.35 + 0.65 * center
    const phase = 0.55 + 0.45 * Math.abs(Math.sin(t / 260 + i * 0.55))
    const h = 4 + v * 46 * envelope * phase
    bar.style.height = `${h.toFixed(1)}px`
  }
}

onMounted(() => {
  t0 = performance.now()
  rafId = requestAnimationFrame(loop)
})

onBeforeUnmount(() => {
  cancelAnimationFrame(rafId)
  rafId = 0
  waveBars.length = 0
})
</script>

<style scoped>
.spot-stage {
  position: relative;
  width: 100%;
  height: 100%;
  border-radius: 16px;
  overflow: hidden;
  background: linear-gradient(180deg, #eef3fd 0%, #f6f1fb 58%, #eef4fb 100%);
}

/* ---------------- 柔光背景 ---------------- */
.spot-bg {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.spot-blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(46px);
}

.blob-a {
  width: 46%;
  padding-top: 46%;
  left: -8%;
  top: -10%;
  background: rgba(133, 183, 235, 0.5);
}

.blob-b {
  width: 40%;
  padding-top: 40%;
  right: -6%;
  top: 6%;
  background: rgba(206, 203, 246, 0.55);
}

.blob-c {
  width: 36%;
  padding-top: 36%;
  left: 26%;
  bottom: -14%;
  background: rgba(244, 192, 209, 0.42);
}

.spot-floor {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 34%;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0) 0%, rgba(255, 255, 255, 0.72) 100%);
}

/* ---------------- 右上角工具 ---------------- */
.spot-tools {
  position: absolute;
  top: 14px;
  right: 16px;
  display: flex;
  gap: 8px;
  z-index: 3;
}

.spot-tool {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  font-size: 12px;
  color: #5a5f6b;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid rgba(255, 255, 255, 0.9);
  border-radius: 999px;
  cursor: pointer;
  backdrop-filter: blur(8px);
  transition: color 0.2s, background 0.2s;
}

.spot-tool:hover {
  background: #fff;
  color: #303133;
}

.spot-tool:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.spot-tool.off {
  color: #a8abb2;
}

/* ---------------- 数字人容器 ---------------- */
.spot-figure {
  position: absolute;
  left: 50%;
  bottom: 5%;
  transform: translateX(-50%);
  height: 80%;
  min-height: 260px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
}

.spot-canvas {
  height: 100%;
  display: flex;
  align-items: flex-end;
  justify-content: center;
}

/* 照片档：按容器高度缩放、宽度自适应（不撑破舞台） */
.spot-canvas :deep(.avatar-photo) {
  width: auto;
  height: 100%;
  max-width: 42vw;
  object-fit: contain;
  border-radius: 10px;
  box-shadow: 0 18px 48px rgba(89, 106, 168, 0.18);
}

/* Live2D 档：WebGL canvas 填满容器 */
.spot-canvas :deep(.avatar-live2d-box) {
  height: 100%;
  min-width: 320px;
}

/* 胶囊状态标签：悬浮在数字人上方 */
.spot-capsule {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 10px;
  padding: 6px 16px;
  font-size: 13px;
  color: #4a4f5c;
  background: rgba(255, 255, 255, 0.82);
  border: 1px solid rgba(255, 255, 255, 0.95);
  border-radius: 999px;
  backdrop-filter: blur(10px);
  box-shadow: 0 6px 18px rgba(89, 106, 168, 0.12);
  white-space: nowrap;
  z-index: 2;
}

.spot-capsule-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #909399;
}

.is-idle .spot-capsule-dot {
  background: #909399;
}

.is-listening .spot-capsule-dot {
  background: #f56c6c;
  animation: capsule-pulse 1.1s ease-in-out infinite;
}

.is-thinking .spot-capsule-dot {
  background: #e6a23c;
  animation: capsule-pulse 1.4s ease-in-out infinite;
}

.is-speaking .spot-capsule-dot {
  background: #7f77dd;
  animation: capsule-pulse 0.8s ease-in-out infinite;
}

.is-listening {
  color: #b3453f;
}

.is-speaking {
  color: #5b52c4;
}

.is-thinking {
  color: #9a6b1f;
}

@keyframes capsule-pulse {
  0%,
  100% {
    transform: scale(1);
    opacity: 1;
  }
  50% {
    transform: scale(1.5);
    opacity: 0.55;
  }
}

/* ---------------- 声波可视化 ---------------- */
.spot-wave {
  display: flex;
  align-items: flex-end;
  justify-content: center;
  gap: 3px;
  height: 52px;
  margin-top: 6px;
  padding-bottom: 4px;
}

.spot-wave-bar {
  width: 3px;
  height: 4px;
  border-radius: 2px;
  background: linear-gradient(180deg, #9b8ff0 0%, #7ea6ea 100%);
  transition: height 60ms linear;
}

/* ---------------- 设置弹层 ---------------- */
.set-hint {
  margin: 0 0 12px;
  font-size: 12px;
  color: #909399;
}

.face-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}

.face-card {
  position: relative;
  padding: 8px;
  text-align: center;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 10px;
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.face-card:hover {
  border-color: #c6d4f2;
  box-shadow: 0 4px 14px rgba(89, 106, 168, 0.1);
}

.face-card.active {
  border-color: #7f77dd;
  box-shadow: 0 0 0 2px rgba(127, 119, 221, 0.16);
}

.face-thumb {
  width: 100%;
  height: 96px;
  border-radius: 8px;
  overflow: hidden;
  background: linear-gradient(180deg, #eef3fd, #f6f1fb);
  display: flex;
  align-items: flex-end;
  justify-content: center;
}

.face-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: top;
}

.face-thumb-svg {
  width: 52px;
  height: 62px;
}

.face-name {
  margin-top: 6px;
  font-size: 13px;
  font-weight: 500;
  color: #303133;
}

.face-desc {
  font-size: 11px;
  color: #a8abb2;
  line-height: 1.4;
}

.face-current {
  position: absolute;
  top: 12px;
  right: 12px;
  padding: 1px 7px;
  font-size: 11px;
  color: #fff;
  background: #7f77dd;
  border-radius: 8px;
}

.set-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
  font-size: 13px;
  color: #4a4f5c;
}

.set-label {
  width: 40px;
  color: #909399;
}

.set-off-hint {
  font-size: 11px;
  color: #c0c4cc;
}
</style>
