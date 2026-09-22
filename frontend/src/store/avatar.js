// [阶段二] 人工智能NLP-Agent数字人项目-教育智能体-数字人形象层 —— 数字人状态
// 轻量实现：localStorage + Vue reactive，不引入 Pinia（沿用 store/user.js 的约定）。
//
// 注意 `speech` **刻意放在 reactive 之外**：队列里持有 AudioContext / AudioBuffer 等
// 重量级对象，若被 Vue 深度代理，每次访问都会走 Proxy 陷阱，逐帧读音量时性能无谓变差。

import { reactive } from 'vue'

import { fetchTtsConfig, fetchVoices } from '@/api/tts'
import { createSpeechQueue } from '@/audio/speechQueue'
import { pickAvatarProvider, PHOTO_FACE } from '@/avatar/provider'
import { DEFAULT_FACE_ID, pickFace } from '@/avatar/faces'

// 键名 v2：v1 键里残留了试用期的「已静音」与「男声·Yunxi」选择，与女教师形象性别不符，
// 导致演示时数字人是「静音照片 + 男声」。升键让后端默认（TTS_VOICE=女声·晓晓、默认出声）
// 重新生效一次；用户之后改的开关/音色照常记住。
const ENABLED_KEY = 'edu_agent_tts_enabled_v2'
const VOICE_KEY = 'edu_agent_tts_voice_v2'
// [工单20] 当前形象 id（形象库：写实照片档 + Live2D 二次元档）
const FACE_KEY = 'edu_agent_face_v2'

export const avatarState = reactive({
  ready: false,
  /** 后端是否启用了 TTS（TTS_ENABLED + provider 合法） */
  available: true,
  /** 用户自己的朗读开关，跨会话记住 */
  enabled: localStorage.getItem(ENABLED_KEY) !== '0',
  voice: localStorage.getItem(VOICE_KEY) || '',
  voices: [],
  /** 形象 provider 实现，由后端下发的 AVATAR_PROVIDER 决定（photo / live2d）；
   *  未知值回退 photo —— svg-face 卡通脸已于 2026-09-18 退役。 */
  provider: pickAvatarProvider(PHOTO_FACE),
  /** [工单20] 当前形象（faces.js 清单里的一项） */
  faceId: localStorage.getItem(FACE_KEY) || DEFAULT_FACE_ID,
  face: pickFace(localStorage.getItem(FACE_KEY) || DEFAULT_FACE_ID),
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
  // 音色风格随形象走（如小满的萌音）；用户手动改音色不改风格——风格是形象的嗓音调性
  speech.setTuning(avatarState.face?.voiceStyle || {})
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

/**
 * [工单20] 切换数字人形象（写实照片档 / Live2D 二次元档）。
 * 声音自动配对：跟随形象的 defaultVoice——从机制上杜绝「女脸配男声」。
 * 音色列表已加载且不含目标音色时不动（避免把队列指向不存在的音色）；
 * 用户之后手动改音色仍可覆盖。
 */
export function setFace(id) {
  const face = pickFace(id)
  avatarState.faceId = face.id
  avatarState.face = face
  localStorage.setItem(FACE_KEY, face.id)
  const known = avatarState.voices.length
    ? avatarState.voices.some((v) => v.short_name === face.defaultVoice)
    : true
  if (face.defaultVoice && known) setVoice(face.defaultVoice)
  else syncQueue() // 音色不动时也要把新形象的 voiceStyle（如小满的萌音）推给队列
}
