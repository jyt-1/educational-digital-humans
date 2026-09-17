// [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— 智能问答 API
import http from '@/api/http'
import { streamPost } from '@/api/sse'

/**
 * 流式问答。
 * 事件序列：sources（引用来源，先于答案下发）→ delta（逐字增量）→ done / error
 *
 * @param {object} payload { question, conversation_id?, scope?, top_k?, use_rerank? }
 * @param {(event: string, data: any) => void} onEvent
 * @param {AbortSignal} signal 中断当前回答
 */
export function chatStream(payload, { onEvent, signal } = {}) {
  return streamPost('/assistant/chat', payload, { onEvent, signal })
}

export function listConversations() {
  return http.get('/assistant/conversations')
}

export function getConversation(conversationId) {
  return http.get(`/assistant/conversations/${conversationId}`)
}

export function deleteConversation(conversationId) {
  return http.delete(`/assistant/conversations/${conversationId}`)
}
