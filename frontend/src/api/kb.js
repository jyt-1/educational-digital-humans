// [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— 知识库 API
import http from '@/api/http'
import { getToken } from '@/store/user'

/** 文档列表；scope 传 public / private 可只看其一，不传为全部可见 */
export function listDocs(scope) {
  return http.get('/kb/docs', { params: scope ? { scope } : {} })
}

export function getDoc(docId) {
  return http.get(`/kb/docs/${docId}`)
}

export function deleteDoc(docId) {
  return http.delete(`/kb/docs/${docId}`)
}

export function reparseDoc(docId) {
  return http.post(`/kb/docs/${docId}/reparse`)
}

export function getChunk(chunkId) {
  return http.get(`/kb/chunks/${chunkId}`)
}

/**
 * 上传文档（多部分表单，带进度）。
 * 解析在后端异步进行，上传成功即返回，前端轮询 parse_status。
 */
export function uploadDoc(file, scope, onProgress) {
  const form = new FormData()
  form.append('file', file)
  form.append('scope', scope)
  return http.post('/kb/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300000, // 大文件上传留足时间
    onUploadProgress: (event) => {
      if (onProgress && event.total) {
        onProgress(Math.round((event.loaded / event.total) * 100))
      }
    },
  })
}

/** 混合检索（向量 + 关键词 + 可选重排） */
export function searchKb(payload) {
  return http.post('/kb/search', payload)
}

/**
 * 取图片块原图。图片接口需要 JWT，<img src> 不会带 Authorization 头，
 * 因此用 fetch 取回 blob 再转成本地对象 URL（用完记得 revokeObjectURL）。
 */
export async function fetchChunkImage(chunkId) {
  const resp = await fetch(`/api/kb/chunks/${chunkId}/image`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  })
  if (!resp.ok) throw new Error('图片加载失败')
  return URL.createObjectURL(await resp.blob())
}
