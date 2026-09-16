// [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 登录态存储
// 轻量实现：localStorage + Vue reactive，不引入 Pinia。
import { reactive } from 'vue'

const TOKEN_KEY = 'edu_agent_token'
const USER_KEY = 'edu_agent_user'

function readUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null')
  } catch {
    return null
  }
}

export const authState = reactive({
  token: localStorage.getItem(TOKEN_KEY) || '',
  user: readUser(),
})

export function getToken() {
  return authState.token
}

export function setAuth(token, user) {
  authState.token = token
  authState.user = user
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearAuth() {
  authState.token = ''
  authState.user = null
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export function isLoggedIn() {
  return Boolean(authState.token)
}

export function isTeacher() {
  return authState.user?.role === 'teacher'
}
