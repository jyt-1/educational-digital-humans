// [阶段二] 人工智能NLP-Agent数字人项目-教育智能体-数字人形象层 —— 数字人状态
// 轻量实现：localStorage + Vue reactive，不引入 Pinia（沿用 store/user.js 的约定）。
//
// 注意 `speech` **刻意放在 reactive 之外**：队列里持有 AudioContext / AudioBuffer 等
// 重量级对象，若被 Vue 深度代理，每次访问都会走 Proxy 陷阱，逐帧读音量时性能无谓变差。

import { reactive } from 'vue'

import { fetchTtsConfig, fetchVoices } from '@/api/tts'
import { createSpeechQueue } from '@/audio/speechQueue'
import { pickAvatarProvider, SVG_FACE } from '@/avatar/provider'

const ENABLED_KEY = 'edu_agent_tts_enabled'
const VOICE_KEY = 'edu_agent_tts_voice'

export const avatarState = reactive({
  ready: false,
  /** 后端是否启用了 TTS（TTS_ENABLED + provider 合法） */
  available: true,
  /** 用户自己的朗读开关，跨会话记住 */
  enabled: localStorage.getItem(ENABLED_KEY) !== '0',
  voice: localStorage.getItem(VOICE_KEY) || '',
  voices: [],
  /** 形象 provider 实现，由后端下发的 AVATAR_PROVIDER 决定 */
  provider: pickAvatarProvider(SVG_FACE),
  /** 是否正在出声。**由队列回调更新**，变化频率极低，可以走响应式 */
  speaking: false,
})

/** 语音队列：全应用单例（一个 AudioContext 足够，多开会互相抢设备）。 */
export const speech = createSpeechQueue()

// 只注册一次：队列的出声状态同步进响应式，供头像切换表情
speech.onStateChange((state) => {
  avatarState.speaking = state === 'speaking'
})

function syncQueue() {
  speech.setEnabled(avatarState.available && avatarState.enabled)
  speech.setVoice(avatarState.voice)
}

/** 问答页挂载时调一次。失败不抛：语音是增强项，不可用时页面照常。 */
export async function initAvatar() {
  if (avatarState.ready) return
  try {
    const cfg = await fetchTtsConfig()
    avatarState.available = Boolean(cfg.enabled)
    avatarState.provider = pickAvatarProvider(cfg.avatar_provider)
    avatarState.defaultVoice = cfg.voice
    if (!avatarState.voice) avatarState.voice = cfg.voice
    avatarState.voices = await fetchVoices()
  } catch {
    // 后端没起来或未登录：静默降级，不打断问答
    avatarState.available = false
  }
  avatarState.ready = true
  syncQueue()
}

export function setSpeechEnabled(value) {
  avatarState.enabled = Boolean(value)
  localStorage.setItem(ENABLED_KEY, avatarState.enabled ? '1' : '0')
  syncQueue()
}

export function setVoice(voice) {
  avatarState.voice = voice || ''
  localStorage.setItem(VOICE_KEY, avatarState.voice)
  syncQueue()
}
