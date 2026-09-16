// [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 备课 API
//
// 关于 SSE 的实现说明：
//   浏览器原生 EventSource 只支持 GET，而生成接口是 POST + JSON body
//   （知识点/教学目标是数组，不适合塞进 URL），因此这里用 fetch + ReadableStream
//   手工解析 SSE 帧——同样是逐块消费，能真正做到边生成边渲染。
//   axios 基于 XHR，拿不到分块响应，整段生成会被攒到最后一次性返回，故不用于流式接口。
import http from '@/api/http'
import { getToken, clearAuth } from '@/store/user'

const BASE = '/api'

/** 解析单个 SSE 帧（"event: x\ndata: {...}"） */
function parseFrame(raw) {
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
  let data = null
  const joined = dataLines.join('\n')
  try {
    data = JSON.parse(joined)
  } catch {
    data = joined
  }
  return { event, data }
}

/**
 * 流式生成备课内容。
 * @param {object} payload 生成参数
 * @param {(event: string, data: any) => void} onEvent 事件回调：
 *        start / delta / done / error
 * @param {AbortSignal} signal 用于中断生成
 * @returns {Promise<{done: any|null, error: any|null}>}
 */
export async function streamGenerate(payload, { onEvent, signal } = {}) {
  const resp = await fetch(`${BASE}/lesson/generate`, {
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

  const emitFrame = (frame) => {
    if (!frame) return
    if (frame.event === 'done') doneData = frame.data
    if (frame.event === 'error') errorData = frame.data
    onEvent?.(frame.event, frame.data)
  }

  // SSE 以空行分帧；同时兼容 \n\n 与 \r\n\r\n
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let sep
    while ((sep = buffer.search(/\r?\n\r?\n/)) !== -1) {
      const raw = buffer.slice(0, sep)
      buffer = buffer.slice(sep).replace(/^\r?\n\r?\n/, '')
      emitFrame(parseFrame(raw))
    }
  }
  if (buffer.trim()) emitFrame(parseFrame(buffer))

  return { done: doneData, error: errorData }
}

// ---------------------------------------------------------------- 普通接口

export function listPlans(params) {
  return http.get('/lesson/plans', { params })
}

export function getPlan(planId) {
  return http.get(`/lesson/plans/${planId}`)
}

export function updatePlan(planId, content, remark) {
  return http.put(`/lesson/plans/${planId}`, { content, remark })
}

export function listVersions(planId) {
  return http.get(`/lesson/plans/${planId}/versions`)
}

export function rollbackVersion(planId, versionId) {
  return http.post(`/lesson/plans/${planId}/versions/${versionId}/rollback`)
}

export function searchResources(keyword, limit = 5) {
  return http.post('/lesson/resources/search', { keyword, limit })
}

export function fetchStats() {
  return http.get('/lesson/stats')
}

/**
 * 下载导出文件。
 * 不能直接用 <a href>：接口需要 Authorization 头，故先取 blob 再触发下载。
 */
export async function downloadExport(planId, format = 'docx') {
  const resp = await fetch(`${BASE}/lesson/plans/${planId}/export?format=${format}`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  })
  if (!resp.ok) {
    let msg = `导出失败（${resp.status}）`
    try {
      const body = await resp.json()
      msg = body.msg || msg
    } catch {
      /* 保持默认提示 */
    }
    throw new Error(msg)
  }

  // 从 Content-Disposition 解析文件名（后端用 RFC 5987 编码中文名）
  const disposition = resp.headers.get('content-disposition') || ''
  let filename = `导出文件.${format}`
  const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i)
  if (utf8Match) {
    filename = decodeURIComponent(utf8Match[1])
  }

  const blob = await resp.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
  return filename
}
