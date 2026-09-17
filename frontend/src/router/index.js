// [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 路由
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

  // ---- 工单19/20 占位（后续工单实现） ----
  {
    path: '/learn',
    name: 'learn',
    component: () => import('@/views/Placeholder.vue'),
    meta: { title: '个性化学习', group: '个性化学习', ticket: '工单19' },
  },
  {
    path: '/interview',
    name: 'interview',
    component: () => import('@/views/Placeholder.vue'),
    meta: { title: '面试AI复盘', group: '面试AI复盘', ticket: '工单20' },
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
