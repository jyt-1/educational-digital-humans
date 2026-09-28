// [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 登录态存储
// [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 追加：角色判据与落地页（覆盖工单17/19/23）
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

export function currentRole() {
  return authState.user?.role || null
}

// 路由 meta.roles 的统一判据。roles 缺省/空 = 登录即可访问。
// admin 与后端一致地绕过角色校验（见 `backend/app/auth.py::require_role`）——
// 前端若不做这一条，admin 会看到空菜单，而后端其实一路放行。
export function hasRole(roles) {
  if (!roles || roles.length === 0) return true
  const role = currentRole()
  if (!role) return false
  if (role === 'admin') return true
  return roles.includes(role)
}

// 角色各自的落地页。学生落到 /lesson 会被守卫弹回，登录后直接给对，少一次往返。
export function homePath() {
  return currentRole() === 'student' ? '/learn/dashboard' : '/lesson'
}
