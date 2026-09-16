<!-- [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 登录 / 注册页 -->
<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <h2 style="margin: 0 0 4px">教育智能体平台</h2>
      <p style="margin: 0 0 20px; color: #909399; font-size: 13px">
        阶段一 · 智能备课 / 智能助教 / 个性化学习 / 面试AI复盘
      </p>

      <el-tabs v-model="tab">
        <el-tab-pane label="登录" name="login">
          <el-form :model="loginForm" label-width="70px" @submit.prevent="handleLogin">
            <el-form-item label="用户名">
              <el-input v-model="loginForm.username" placeholder="请输入用户名" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input
                v-model="loginForm.password"
                type="password"
                show-password
                placeholder="请输入密码"
                @keyup.enter="handleLogin"
              />
            </el-form-item>
            <el-button type="primary" :loading="loading" style="width: 100%" @click="handleLogin">
              登录
            </el-button>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="注册" name="register">
          <el-form :model="registerForm" label-width="70px" @submit.prevent="handleRegister">
            <el-form-item label="用户名">
              <el-input v-model="registerForm.username" placeholder="至少 3 个字符" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input
                v-model="registerForm.password"
                type="password"
                show-password
                placeholder="至少 6 个字符"
              />
            </el-form-item>
            <el-form-item label="角色">
              <el-radio-group v-model="registerForm.role">
                <el-radio value="teacher">教师</el-radio>
                <el-radio value="student">学生</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="显示名">
              <el-input v-model="registerForm.display_name" placeholder="如：张老师" />
            </el-form-item>
            <el-button
              type="primary"
              :loading="loading"
              style="width: 100%"
              @click="handleRegister"
            >
              注册并登录
            </el-button>
          </el-form>
        </el-tab-pane>
      </el-tabs>

      <el-alert type="info" :closable="false" style="margin-top: 16px">
        <template #title>
          <span style="font-size: 12px">
            首次使用请先注册<strong>教师</strong>账号（智能备课仅教师可用）
          </span>
        </template>
      </el-alert>
    </el-card>
  </div>
</template>

<script setup>
import { ElMessage } from 'element-plus'
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { login, register } from '@/api/auth'
import { setAuth } from '@/store/user'

const route = useRoute()
const router = useRouter()

const tab = ref('login')
const loading = ref(false)

const loginForm = reactive({ username: '', password: '' })
const registerForm = reactive({
  username: '',
  password: '',
  role: 'teacher',
  display_name: '',
})

function afterLogin(data) {
  setAuth(data.access_token, data.user)
  ElMessage.success(`欢迎，${data.user.display_name || data.user.username}`)
  router.push(route.query.redirect || '/lesson')
}

async function handleLogin() {
  if (!loginForm.username || !loginForm.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    afterLogin(await login({ ...loginForm }))
  } catch {
    /* 错误提示已由拦截器统一处理 */
  } finally {
    loading.value = false
  }
}

async function handleRegister() {
  if (registerForm.username.length < 3) {
    ElMessage.warning('用户名至少 3 个字符')
    return
  }
  if (registerForm.password.length < 6) {
    ElMessage.warning('密码至少 6 个字符')
    return
  }
  loading.value = true
  try {
    await register({ ...registerForm })
    // 注册成功后自动登录，省去一次手工操作
    afterLogin(await login({ username: registerForm.username, password: registerForm.password }))
  } catch {
    /* 错误提示已由拦截器统一处理 */
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #001529 0%, #003a70 100%);
}

.login-card {
  width: 420px;
  padding: 8px 12px;
}
</style>
