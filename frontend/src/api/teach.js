// [工单23] 人工智能NLP-Agent数字人项目-教育智能体-班级学情闭环 —— 教师侧班级 API
//
// 响应结构统一由 `http.js` 拦截器拆成 `data`，故这里直接返回 Promise<data>。
import http from '@/api/http'

export const listClasses = () => http.get('/teach/classes')

export const createClass = (payload) => http.post('/teach/classes', payload)

export const addMembers = (classId, usernames) =>
  http.post(`/teach/classes/${classId}/members`, { usernames })

export const removeMember = (classId, studentId) =>
  http.delete(`/teach/classes/${classId}/members/${studentId}`)

export const getInsight = (classId, params) =>
  http.get(`/teach/classes/${classId}/insight`, { params })

export const listStudents = (classId) => http.get(`/teach/classes/${classId}/students`)
