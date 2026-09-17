// [阶段二] 人工智能NLP-Agent数字人项目-教育智能体-数字人形象层 —— 数字人语音 API
import http from '@/api/http'

/** 读一次数字人配置：是否开启朗读、默认音色、用哪个形象 provider。 */
export function fetchTtsConfig() {
  return http.get('/tts/config')
}

/** 可用音色清单（后端静态返回，不联网）。 */
export function fetchVoices() {
  return http.get('/tts/voices')
}

/**
 * 合成一句话，返回 MP3 的 ArrayBuffer。
 *
 * 与其它接口的两点不同：
 * 1. 走 `responseType: 'arraybuffer'`——响应是音频字节流，不包 {code,msg,data}；
 * 2. 传 `silent: true`——语音是增强项，不可用时调用方静默跳过，不弹错误提示。
 *
 * @param {string} text 原始 Markdown，清洗在后端做
 * @param {{voice?: string, signal?: AbortSignal}} opts
 * @returns {Promise<ArrayBuffer>}
 */
export async function speak(text, { voice, signal } = {}) {
  try {
    const resp = await http.post(
      '/tts/speak',
      { text, voice },
      { responseType: 'arraybuffer', timeout: 30000, silent: true, signal },
    )
    return resp.data
  } catch (error) {
    throw new Error(readErrorMessage(error))
  }
}

/**
 * 错误响应体也是 ArrayBuffer（因为 responseType 是 arraybuffer），
 * 需手工解回 JSON 才能拿到后端的 {code,msg,data} 中文提示。
 */
function readErrorMessage(error) {
  if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') {
    return '已取消'
  }
  const raw = error?.response?.data
  if (raw instanceof ArrayBuffer) {
    try {
      const parsed = JSON.parse(new TextDecoder('utf-8').decode(raw))
      if (parsed?.msg) return parsed.msg
    } catch {
      /* 非 JSON，落到默认提示 */
    }
  }
  return error?.message || '语音合成失败'
}
