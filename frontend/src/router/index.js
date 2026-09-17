// [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 路由（工单18/19 增补各模块页面）
import { createRouter, createWebHashHistory } from 'vue-router'

import { isLoggedIn } from '@/store/user'

const routes = [
  { path: '/', redirect: '/lesson' },
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true, title: '登录' },
  },

  // ---- 工单17 智能备课 ----
  {
    path: '/lesson',
    name: 'lesson-generate',
    component: () => import('@/views/lesson/Generate.vue'),
    meta: { title: '智能备课', group: '智能备课' },
  },
  {
    path: '/lesson/plans',
    name: 'lesson-plans',
    component: () => import('@/views/lesson/Plans.vue'),
    meta: { title: '我的备课', group: '智能备课' },
  },
  {
    path: '/lesson/plans/:id',
    name: 'lesson-edit',
    component: () => import('@/views/lesson/Edit.vue'),
    meta: { title: '编辑与导出', group: '智能备课', hidden: true },
  },

  // ---- 工单18 智能助教 ----
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

  // ---- 工单19 个性化学习推荐 ----
  { path: '/learn', redirect: '/learn/dashboard' },
  {
    path: '/learn/dashboard',
    name: 'learn-dashboard',
    component: () => import('@/views/learn/Dashboard.vue'),
    meta: { title: '学习仪表盘', group: '个性化学习' },
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
    meta: { title: '练习与试卷', group: '个性化学习' },
  },
  {
    path: '/learn/mistakes',
    name: 'learn-mistakes',
    component: () => import('@/views/learn/Mistakes.vue'),
    meta: { title: '错题本', group: '个性化学习' },
  },

  { path: '/:pathMatch(.*)*', redirect: '/lesson' },
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
    return { path: '/lesson' }
  }
  return true
})

export default router
