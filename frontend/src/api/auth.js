// [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 认证 API
import http from '@/api/http'

export function register(payload) {
  return http.post('/auth/register', payload)
}

export function login(payload) {
  return http.post('/auth/login', payload)
}

export function fetchMe() {
  return http.get('/auth/me')
}
