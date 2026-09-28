// [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 路由（工单18/19 增补各模块页面）
// [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 追加：路由角色门禁（覆盖工单17/19/23）
// `meta.roles` 是唯一事实来源——侧边栏按它过滤（App.vue），守卫按它拦截，
// 与后端 `require_teacher` / `require_student` 一一对应。缺省/空数组 = 登录即可访问。
// `meta.title` 是页面标题（进顶栏），`meta.menu` 是侧边栏项文字，缺省取 title——
// 两者不同的只有两处：/lesson（顶栏「智能备课」/ 菜单「内容生成」）、
// /lecture（顶栏「虚拟教室」/ 菜单「数字人讲课」）。
import { createRouter, createWebHashHistory } from 'vue-router'
import { ElMessage } from 'element-plus'

import { currentRole, hasRole, homePath, isLoggedIn } from '@/store/user'

const TEACHER = ['teacher']
const STUDENT = ['student']
const ROLE_LABEL = { teacher: '教师', student: '学生', admin: '管理员' }

function roleLabel(roles) {
  const names = (roles || []).map((role) => ROLE_LABEL[role] || role)
  return names.length ? `仅${names.join('/')}` : ''
}

const routes = [
  { path: '/', redirect: () => homePath() },
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true, title: '登录' },
  },

  // ---- 工单17 智能备课（后端 /api/lesson/* 全 require_teacher） ----
  {
    path: '/lesson',
    name: 'lesson-generate',
    component: () => import('@/views/lesson/Generate.vue'),
    meta: { title: '智能备课', menu: '内容生成', group: '智能备课', roles: TEACHER },
  },
  {
    path: '/lesson/plans',
    name: 'lesson-plans',
    component: () => import('@/views/lesson/Plans.vue'),
    meta: { title: '我的备课', group: '智能备课', roles: TEACHER },
  },
  {
    path: '/lesson/plans/:id',
    name: 'lesson-edit',
    component: () => import('@/views/lesson/Edit.vue'),
    meta: { title: '编辑与导出', group: '智能备课', hidden: true, roles: TEACHER },
  },

  // ---- 工单18 智能助教（登录即可；公共库写权限在页面内按角色收窄） ----
  { path: '/assistant', redirect: '/assistant/chat' },
  {
    path: '/assistant/chat',
    name: 'assistant-chat',
    component: () => import('@/views/assistant/Chat.vue'),
    meta: { title: '智能问答', group: '智能助教' },
  },
  {
    path: '/assistant/kb',
    name: 'assistant-kb',
    component: () => import('@/views/assistant/Knowledge.vue'),
    meta: { title: '知识库', group: '智能助教' },
  },
  {
    path: '/assistant/search',
    name: 'assistant-search',
    component: () => import('@/views/assistant/Search.vue'),
    meta: { title: '检索调试', group: '智能助教' },
  },

  // ---- 工单23 班级学情闭环（教师侧：/api/teach/* 均 require_teacher） ----
  {
    path: '/teach/class',
    name: 'teach-class',
    component: () => import('@/views/teach/ClassInsight.vue'),
    meta: { title: '我的班级', group: '班级学情', roles: TEACHER },
  },

  // ---- 工单21 虚拟教室（学生看课：/api/lecture/courses 登录即可） ----
  {
    path: '/lecture',
    name: 'lecture-room',
    component: () => import('@/views/lecture/Room.vue'),
    meta: { title: '虚拟教室', menu: '数字人讲课', group: '虚拟教室' },
  },

  // ---- 工单19 个性化学习推荐 ----
  // 画像/练习/错题按 user_id 隔离，教师账号进去只有自己的（空）数据；
  // 路径页是教师侧「知识点治理」的入口，故两个角色都保留。
  {
    path: '/learn',
    redirect: () => (currentRole() === 'student' ? '/learn/dashboard' : '/learn/path'),
  },
  {
    path: '/learn/dashboard',
    name: 'learn-dashboard',
    component: () => import('@/views/learn/Dashboard.vue'),
    meta: { title: '学习仪表盘', group: '个性化学习', roles: STUDENT },
  },
  {
    path: '/learn/path',
    name: 'learn-path',
    component: () => import('@/views/learn/Path.vue'),
    meta: { title: '学习路径', group: '个性化学习' },
  },
  {
    path: '/learn/practice',
    name: 'learn-practice',
    component: () => import('@/views/learn/Practice.vue'),
    meta: { title: '练习与试卷', group: '个性化学习', roles: STUDENT },
  },
  {
    path: '/learn/mistakes',
    name: 'learn-mistakes',
    component: () => import('@/views/learn/Mistakes.vue'),
    meta: { title: '错题本', group: '个性化学习', roles: STUDENT },
  },

  { path: '/:pathMatch(.*)*', redirect: () => homePath() },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

router.beforeEach((to) => {
  if (!to.meta.public && !isLoggedIn()) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && isLoggedIn()) {
    return { path: homePath() }
  }
  if (!hasRole(to.meta.roles)) {
    const fallback = homePath()
    // 落地页本身也判不符 → 说明 roles 声明与 homePath 自相矛盾，放行以免重定向死循环
    if (to.path === fallback) return true
    ElMessage.warning(`「${to.meta.title || to.path}」${roleLabel(to.meta.roles)}可用，已为你跳转`)
    return { path: fallback }
  }
  return true
})

export default router
