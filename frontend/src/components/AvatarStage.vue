<!-- [阶段二] 人工智能NLP-Agent数字人项目-教育智能体-数字人形象层 —— 2D 形象舞台（音量驱动口型） -->
<template>
  <aside class="avatar-stage">
    <div class="avatar-frame">
      <svg class="avatar-svg" viewBox="0 0 200 230" role="img" aria-label="数字人助教形象">
        <g ref="headRef">
          <!-- 脖子 -->
          <path d="M 88 166 L 88 188 Q 100 194 112 188 L 112 166 Z" :fill="palette.skin" />
          <!-- 耳朵 -->
          <ellipse cx="39" cy="108" rx="7" ry="11" :fill="palette.skin" :stroke="palette.skinLine" />
          <ellipse cx="161" cy="108" rx="7" ry="11" :fill="palette.skin" :stroke="palette.skinLine" />
          <!-- 头 -->
          <ellipse
            cx="100"
            cy="104"
            rx="62"
            ry="68"
            :fill="palette.skin"
            :stroke="palette.skinLine"
            stroke-width="1.5"
          />
          <!-- 头发 -->
          <path
            d="M 38 98 Q 36 34 100 32 Q 164 34 162 98 Q 152 60 100 56 Q 48 60 38 98 Z"
            :fill="palette.hair"
          />
          <!-- 腮红 -->
          <ellipse cx="64" cy="128" rx="11" ry="6" :fill="palette.blush" opacity="0.45" />
          <ellipse cx="136" cy="128" rx="11" ry="6" :fill="palette.blush" opacity="0.45" />
          <!-- 眉毛 -->
          <g ref="browRef">
            <path
              d="M 64 80 Q 77 72 91 79"
              fill="none"
              :stroke="palette.hair"
              stroke-width="3.5"
              stroke-linecap="round"
            />
            <path
              d="M 109 79 Q 123 72 136 80"
              fill="none"
              :stroke="palette.hair"
              stroke-width="3.5"
              stroke-linecap="round"
            />
          </g>
          <!-- 眼睛（整组做 scaleY 眨眼） -->
          <g ref="eyeLeftRef">
            <ellipse cx="78" cy="100" rx="11.5" ry="12.5" :fill="palette.eyeWhite" />
            <g ref="pupilLeftRef">
              <circle cx="78" cy="100" r="5.5" :fill="palette.pupil" />
            </g>
          </g>
          <g ref="eyeRightRef">
            <ellipse cx="122" cy="100" rx="11.5" ry="12.5" :fill="palette.eyeWhite" />
            <g ref="pupilRightRef">
              <circle cx="122" cy="100" r="5.5" :fill="palette.pupil" />
            </g>
          </g>
          <!-- 鼻子 -->
          <path d="M 100 112 L 100 122" :stroke="palette.skinLine" stroke-width="2" stroke-linecap="round" />
          <!-- 嘴：d 由 rAF 直接改写，**不经过 Vue 响应式** -->
          <path ref="mouthRef" data-avatar-mouth d="" :fill="palette.mouth" />
        </g>
      </svg>
      <div class="avatar-status">{{ statusText }}</div>
    </div>

    <div class="avatar-controls">
      <el-button
        class="avatar-toggle"
        size="small"
        :type="avatarState.enabled ? 'primary' : 'default'"
        :plain="!avatarState.enabled"
        :disabled="!avatarState.available"
        @click="toggleSpeech"
      >
        {{ avatarState.enabled ? '🔊 朗读中' : '🔇 已静音' }}
      </el-button>
      <el-select
        v-model="voiceModel"
        size="small"
        placeholder="音色"
        :disabled="!avatarState.available"
        class="avatar-voice"
      >
        <el-option
          v-for="item in avatarState.voices"
          :key="item.short_name"
          :label="`${item.gender === 'Female' ? '女声' : '男声'} · ${item.short_name.split('-').pop()}`"
          :value="item.short_name"
        />
      </el-select>
      <div v-if="!avatarState.available" class="avatar-hint">语音服务未启用，形象仍会眨眼</div>
    </div>
  </aside>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { avatarState, setSpeechEnabled, setVoice, speech } from '@/store/avatar'

const props = defineProps({
  /** 是否正在生成回答（生成中且未出声 = 思考态） */
  thinking: { type: Boolean, default: false },
})

// 部件引用。rAF 循环直接对这些 DOM 写属性——见下方性能说明。
const headRef = ref(null)
const browRef = ref(null)
const eyeLeftRef = ref(null)
const eyeRightRef = ref(null)
const pupilLeftRef = ref(null)
const pupilRightRef = ref(null)
const mouthRef = ref(null)

const palette = computed(() => avatarState.provider.palette)

const voiceModel = computed({
  get: () => avatarState.voice,
  set: (v) => setVoice(v),
})

const statusText = computed(() => {
  if (!avatarState.available) return '语音未启用'
  if (!avatarState.enabled) return '已静音'
  if (avatarState.speaking) return '正在讲解'
  return props.thinking ? '思考中…' : '待命中'
})

function toggleSpeech() {
  setSpeechEnabled(!avatarState.enabled)
}

// ---------------------------------------------------------------- 口型驱动
//
// ⭐ 性能红线：本循环**绝不触碰 Vue 响应式**。问答页每个 delta 都会全量重跑
// marked.parse() 重渲染消息（Chat.vue 的 renderAnswer），已是热路径；
// 口型若再逐帧触发组件重渲染，长回答会直接卡死。
// 因此这里只读 `speech.getVolume()`（普通数字）并直接写 SVG 属性。

const BLINK_MS = 150 // 一次眨眼的时长

let rafId = 0
let t0 = 0
let nextBlinkAt = 0
let blinkAt = -1

function scheduleNextBlink(t) {
  // 说话时降低眨眼频率，免得眼睛的动作和口型抢注意力
  const base = avatarState.speaking ? 4500 : 2500
  nextBlinkAt = t + base + Math.random() * 3500
}

/** 眼睛整组绕自身中心做纵向缩放，模拟眼皮闭合。 */
function eyeTransform(cx, cy, scaleY) {
  return `translate(${cx} ${cy}) scale(1 ${scaleY}) translate(${-cx} ${-cy})`
}

function loop(now) {
  rafId = requestAnimationFrame(loop)
  const t = now - t0
  const provider = avatarState.provider

  // 眨眼调度：0 → 1 → 0 的三角波
  let blink = 0
  if (blinkAt >= 0) {
    const p = (t - blinkAt) / BLINK_MS
    if (p >= 1) {
      blinkAt = -1
      scheduleNextBlink(t)
    } else {
      blink = p < 0.5 ? p * 2 : (1 - p) * 2
    }
  } else if (t >= nextBlinkAt) {
    blinkAt = t
  }

  const state = avatarState.speaking ? 'speaking' : props.thinking ? 'thinking' : 'idle'
  const pose = provider.computePose({ volume: speech.getVolume(), state, t, blink })

  mouthRef.value?.setAttribute('d', pose.mouth)
  headRef.value?.setAttribute(
    'transform',
    `translate(0 ${pose.bodyY.toFixed(2)}) rotate(${pose.headTilt.toFixed(2)} 100 104)`,
  )
  browRef.value?.setAttribute('transform', `translate(0 ${pose.browY})`)
  const eyeT = eyeTransform(78, 100, pose.eyeScaleY)
  const eyeT2 = eyeTransform(122, 100, pose.eyeScaleY)
  eyeLeftRef.value?.setAttribute('transform', eyeT)
  eyeRightRef.value?.setAttribute('transform', eyeT2)
  const pupilT = `translate(${pose.pupilX} ${pose.pupilY})`
  pupilLeftRef.value?.setAttribute('transform', pupilT)
  pupilRightRef.value?.setAttribute('transform', pupilT)
}

onMounted(() => {
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
.avatar-stage {
  width: 220px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.avatar-frame {
  background: #fff;
  border-radius: 6px;
  padding: 12px 12px 6px;
  text-align: center;
}

.avatar-svg {
  width: 100%;
  height: auto;
  display: block;
}

.avatar-status {
  font-size: 12px;
  color: #909399;
  padding: 6px 0 2px;
}

.avatar-controls {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.avatar-toggle {
  width: 100%;
}

.avatar-voice {
  width: 100%;
}

.avatar-hint {
  font-size: 11px;
  color: #c0c4cc;
  line-height: 1.5;
}
</style>
