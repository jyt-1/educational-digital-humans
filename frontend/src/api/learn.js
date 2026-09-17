// [工单19] 人工智能NLP-Agent数字人项目-教育智能体-个性化学习推荐任务 —— 个性化学习 API
//
// 响应结构统一由 `http.js` 拦截器拆成 `data`，故这里直接返回 Promise<data>。
import http from '@/api/http'

// ------------------------------------------------------------ 图谱与画像

export const listKnowledgePoints = (params) => http.get('/learn/knowledge-points', { params })

export const getProfile = () => http.get('/learn/profile')

export const getPath = (params) => http.get('/learn/path', { params })

// ------------------------------------------------------------ 练习与试卷

export const getPractice = (params) => http.get('/learn/practice', { params })

export const submitAnswer = (payload) => http.post('/learn/answer', payload)

export const getExam = (params) => http.get('/learn/exam', { params })

export const submitExam = (payload) => http.post('/learn/exam/submit', payload)

// ------------------------------------------------------------ 错题本

export const listMistakes = (params) => http.get('/learn/mistakes', { params })

export const getMistake = (id) => http.get(`/learn/mistakes/${id}`)

// AIGC 分析要等一次 LLM 调用，超时放宽到 3 分钟，否则前端会先报"网络异常"
export const analyzeMistake = (id) =>
  http.post(`/learn/mistakes/${id}/analyze`, {}, { timeout: 180000 })

export const answerVariant = (id, payload) =>
  http.post(`/learn/mistakes/${id}/variant-answer`, payload, { timeout: 180000 })

// ------------------------------------------------------------ 联动助教（三出口）

export const getRelated = (kpId) => http.get('/learn/related', { params: { kp_id: kpId } })

// ------------------------------------------------------------ 历史成绩导入

export const importScores = (payload) => http.post('/learn/profile/import', payload)

export const importScoresFile = (file) => {
  const form = new FormData()
  form.append('file', file)
  return http.post('/learn/profile/import', form)
}

export const listImportBatches = () => http.get('/learn/profile/import-batches')

export const deleteImportBatch = (batchId) =>
  http.delete(`/learn/profile/import-batches/${batchId}`)

// 模板下载要走 blob；`http.js` 对非 JSON 响应直接放行，拿到的就是原始 response
export const downloadImportTemplate = () =>
  http.get('/learn/profile/import-template', { responseType: 'blob' })

// ------------------------------------------------------------ 教师侧：题库与归并

export const syncKnowledge = (target = 'questions') =>
  http.post('/learn/kp/sync', null, { params: { target }, timeout: 180000 })

export const listUnclassified = () => http.get('/learn/kp/unclassified')

export const listAliases = (params) => http.get('/learn/kp/aliases', { params })

export const mergeAlias = (payload) => http.post('/learn/kp/merge', payload)
