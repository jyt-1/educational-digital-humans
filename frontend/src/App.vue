<!-- [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 根组件（侧边栏导航四模块，工单18/19 增补子菜单） -->
<!-- [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 追加：侧边栏角色门禁（覆盖工单17/19/23）
     菜单由路由 `meta`（group / title / hidden / roles）派生，不再手写可见性判断：
     页面归属与角色门禁只有一处声明，菜单与守卫不会各自漂移。 -->
<template>
  <router-view v-if="isLoginPage" />

  <div v-else class="app-layout">
    <aside class="app-aside">
      <div class="app-logo">
        育智平台
        <small>AI 教学智能体</small>
      </div>
      <el-menu
        :default-active="activeMenu"
        :default-openeds="openedGroups"
        background-color="#001529"
        text-color="rgba(255,255,255,0.72)"
        active-text-color="#ffffff"
        router
      >
        <el-sub-menu v-for="group in menuGroups" :key="group.key" :index="group.key">
          <template #title><span>{{ group.title }}</span></template>
          <el-menu-item v-for="item in group.items" :key="item.path" :index="item.path">
            {{ item.title }}
          </el-menu-item>
        </el-sub-menu>
      </el-menu>
    </aside>

    <div class="app-main">
      <header class="app-header">
        <div>{{ pageTitle }}</div>
        <div v-if="authState.user">
          <el-tag size="small" :type="authState.user.role === 'teacher' ? 'success' : 'info'">
            {{ authState.user.role === 'teacher' ? '教师' : '学生' }}
          </el-tag>
          <span style="margin: 0 12px 0 8px">{{ authState.user.display_name }}</span>
          <el-button link type="primary" @click="handleLogout">退出</el-button>
        </div>
      </header>

      <main class="app-content">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { authState, clearAuth, hasRole } from '@/store/user'

// 分组顺序是导航设计，不属于路由事实，故在此显式声明；`title` 必须与路由 meta.group 逐字一致。
const MENU_GROUPS = [
  { key: 'lesson', title: '智能备课' },
  { key: 'assistant', title: '智能助教' },
  { key: 'lecture', title: '虚拟教室' },
  { key: 'learn', title: '个性化学习' },
  { key: 'teach', title: '班级学情' },
]

const route = useRoute()
const router = useRouter()

const isLoginPage = computed(() => route.name === 'login')
const pageTitle = computed(() => route.meta.title || '育智平台')

// 用 router.options.routes（声明顺序）而不是 getRoutes()——后者顺序无保证，
// 菜单项会变成按字典序排（仪表盘/错题本/路径/练习），与设计不符。
const menuGroups = computed(() =>
  MENU_GROUPS.map((group) => ({
    key: group.key,
    title: group.title,
    items: router.options.routes
      .filter(
        (record) =>
          record.meta?.group === group.title &&
          !record.meta?.hidden &&
          record.meta?.title &&
          hasRole(record.meta?.roles),
      )
      .map((record) => ({ path: record.path, title: record.meta.menu || record.meta.title })),
  })).filter((group) => group.items.length > 0),
)

const openedGroups = computed(() => menuGroups.value.map((group) => group.key))

// 详情页（如 /lesson/plans/5，meta.hidden）高亮其所属列表项——取最长前缀命中的可见菜单项。
const activeMenu = computed(() => {
  const paths = menuGroups.value.flatMap((group) => group.items.map((item) => item.path))
  const hit = paths
    .filter((path) => route.path === path || route.path.startsWith(`${path}/`))
    .sort((a, b) => b.length - a.length)[0]
  return hit || route.path
})

function handleLogout() {
  clearAuth()
  router.push({ name: 'login' })
}
</script>
