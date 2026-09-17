// [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— SSE 流式请求通用工具
//
// 为什么不用 EventSource：浏览器原生 EventSource 只支持 GET，而问答/生成接口都是
// POST + JSON body，因此用 fetch + ReadableStream 手工解析 SSE 帧，能真正做到边收边渲染。
// axios 基于 XHR，拿不到分块响应，故流式接口一律不走 axios 实例。
import { clearAuth, getToken } from '@/store/user'

const BASE = '/api'

/** 解析单个 SSE 帧（"event: x\ndata: {...}"），空帧返回 null。 */
export function parseFrame(raw) {
  let event = 'message'
  const dataLines = []
  for (const line of raw.split('\n')) {
    const trimmed = line.replace(/\r$/, '')
    if (trimmed.startsWith('event:')) {
      event = trimmed.slice(6).trim()
    } else if (trimmed.startsWith('data:')) {
      dataLines.push(trimmed.slice(5).trim())
    }
  }
  if (!dataLines.length) return null
  const joined = dataLines.join('\n')
  let data = null
  try {
    data = JSON.parse(joined)
  } catch {
    data = joined
  }
  return { event, data }
}

/**
 * 发起 POST 流式请求并逐帧回调。
 *
 * @param {string} path 形如 '/assistant/chat'
 * @param {object} payload 请求体
 * @param {(event: string, data: any) => void} onEvent 事件回调
 * @param {AbortSignal} signal 用于中断
 * @returns {Promise<{done: any, error: any}>} 收尾事件（done / error）的数据
 */
export async function streamPost(path, payload, { onEvent, signal } = {}) {
  const resp = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${getToken()}`,
    },
    body: JSON.stringify(payload),
    signal,
  })

  if (resp.status === 401) {
    clearAuth()
    throw new Error('登录已过期，请重新登录')
  }
  if (!resp.ok) {
    let msg = `请求失败（${resp.status}）`
    try {
      const body = await resp.json()
      msg = body.msg || msg
    } catch {
      /* 保持默认提示 */
    }
    throw new Error(msg)
  }
  if (!resp.body) {
    throw new Error('当前浏览器不支持流式读取响应')
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let doneData = null
  let errorData = null

  const emit = (frame) => {
    if (!frame) return
    if (frame.event === 'done') doneData = frame.data
    if (frame.event === 'error') errorData = frame.data
    onEvent?.(frame.event, frame.data)
  }

  // SSE 以空行分帧，兼容 \n\n 与 \r\n\r\n
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split(/\r?\n\r?\n/)
    buffer = frames.pop() ?? ''
    frames.forEach((frame) => emit(parseFrame(frame)))
  }
  if (buffer.trim()) emit(parseFrame(buffer))

  return { done: doneData, error: errorData }
}
