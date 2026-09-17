// [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— axios 实例与拦截器
// 统一注入 JWT、统一处理 {code,msg,data} 响应结构、401 自动跳登录。
// 注意：SSE 流式请求不走本实例（axios 无法按 chunk 消费），见 streamGenerate。
import axios from 'axios'
import { ElMessage } from 'element-plus'

import { clearAuth, getToken } from '@/store/user'

const http = axios.create({
  baseURL: '/api', // 开发期由 Vite proxy 转发到 http://localhost:8000
  timeout: 60000,
})

http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (response) => {
    // 文件下载等非 JSON 响应直接放行
    const contentType = response.headers['content-type'] || ''
    if (!contentType.includes('application/json')) {
      return response
    }
    const body = response.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code !== 0) {
        ElMessage.error(body.msg || '请求失败')
        return Promise.reject(new Error(body.msg || '请求失败'))
      }
      return body.data
    }
    return body
  },
  (error) => {
    const status = error.response?.status
    const msg = error.response?.data?.msg || error.message || '网络异常'

    // 增强类接口（阶段二语音合成）可传 silent: true 静默失败：
    // 语音不可用时前端逐句降级跳过即可，不该每句弹一次 toast 打断阅读。
    // 注意 401 仍要照常处理——登录过期必须跳登录页。
    if (error.config?.silent && status !== 401) {
      return Promise.reject(error)
    }

    if (status === 401) {
      clearAuth()
      ElMessage.error('登录已过期，请重新登录')
      // 避免在登录页重复跳转
      if (!window.location.hash.includes('/login')) {
        window.location.hash = '#/login'
      }
    } else {
      ElMessage.error(msg)
    }
    return Promise.reject(error)
  },
)

export default http
