<!-- [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 根组件（侧边栏导航四模块） -->
<template>
  <router-view v-if="isLoginPage" />

  <div v-else class="app-layout">
    <aside class="app-aside">
      <div class="app-logo">
        教育智能体平台
        <small>阶段一 · 工单16~20</small>
      </div>
      <el-menu
        :default-active="activeMenu"
        background-color="#001529"
        text-color="rgba(255,255,255,0.72)"
        active-text-color="#ffffff"
        router
      >
        <el-menu-item index="/lesson">
          <span>智能备课</span>
        </el-menu-item>
        <el-menu-item index="/lesson/plans">
          <span>我的备课</span>
        </el-menu-item>
        <el-menu-item index="/assistant">
          <span>智能助教</span>
        </el-menu-item>
        <el-menu-item index="/learn">
          <span>个性化学习</span>
        </el-menu-item>
        <el-menu-item index="/interview">
          <span>面试AI复盘</span>
        </el-menu-item>
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

import { authState, clearAuth } from '@/store/user'

const route = useRoute()
const router = useRouter()

const isLoginPage = computed(() => route.name === 'login')
const pageTitle = computed(() => route.meta.title || '教育智能体平台')

// 详情页高亮其所属列表菜单
const activeMenu = computed(() => {
  if (route.path.startsWith('/lesson/plans')) return '/lesson/plans'
  return route.path
})

function handleLogout() {
  clearAuth()
  router.push({ name: 'login' })
}
</script>
