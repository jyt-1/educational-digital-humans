<!-- [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 备课记录列表 -->
<template>
  <div class="page-card">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px">
      <h3 style="margin: 0">我的备课记录</h3>
      <el-button type="primary" @click="$router.push({ name: 'lesson-generate' })">
        新建生成
      </el-button>
    </div>

    <el-form :inline="true" @submit.prevent="load">
      <el-form-item label="内容类型">
        <el-select v-model="query.content_type" clearable placeholder="全部" style="width: 130px">
          <el-option v-for="t in CONTENT_TYPES" :key="t" :label="t" :value="t" />
        </el-select>
      </el-form-item>
      <el-form-item label="课程名">
        <el-input v-model="query.course_name" clearable placeholder="模糊匹配" style="width: 180px" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="load">查询</el-button>
        <el-button @click="handleReset">重置</el-button>
      </el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="rows" border stripe>
      <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
      <el-table-column prop="content_type" label="类型" width="80" align="center">
        <template #default="{ row }">
          <el-tag size="small">{{ row.content_type }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="course_name" label="课程" width="140" show-overflow-tooltip />
      <el-table-column prop="chapter" label="章节" width="140" show-overflow-tooltip />
      <el-table-column prop="difficulty" label="难度" width="70" align="center" />
      <el-table-column label="版本" width="70" align="center">
        <template #default="{ row }">v{{ row.current_version }}</template>
      </el-table-column>
      <el-table-column label="更新时间" width="160">
        <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="230" align="center">
        <template #default="{ row }">
          <el-button link type="primary" @click="goEdit(row)">编辑</el-button>
          <el-button link type="primary" :loading="exporting === row.id" @click="handleExport(row)">
            导出
          </el-button>
          <el-button
            v-if="row.content_type === '课件'"
            link
            type="primary"
            :loading="exporting === -row.id"
            @click="handleExport(row, 'pptx')"
          >
            pptx
          </el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="暂无备课记录，先去「智能备课」生成一个" />
      </template>
    </el-table>

    <div style="margin-top: 12px; text-align: right">
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="load"
      />
    </div>
  </div>
</template>

<script setup>
import { ElMessage } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { downloadExport, listPlans } from '@/api/lesson'

const CONTENT_TYPES = ['教案', '课件', '习题', '案例', '试题']

const router = useRouter()
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 10
const exporting = ref(0) // 正在导出的行 id；pptx 用负数标记以免与 docx 冲突

const query = reactive({ content_type: '', course_name: '' })

function formatTime(value) {
  if (!value) return '-'
  return String(value).replace('T', ' ').slice(0, 16)
}

async function load() {
  loading.value = true
  try {
    const params = { limit: pageSize, offset: (page.value - 1) * pageSize }
    if (query.content_type) params.content_type = query.content_type
    if (query.course_name) params.course_name = query.course_name
    rows.value = await listPlans(params)
    total.value = rows.value.length + (page.value - 1) * pageSize
  } catch {
    /* 提示已由拦截器处理 */
  } finally {
    loading.value = false
  }
}

function handleReset() {
  query.content_type = ''
  query.course_name = ''
  page.value = 1
  load()
}

function goEdit(row) {
  router.push({ name: 'lesson-edit', params: { id: row.id } })
}

async function handleExport(row, format = 'docx') {
  exporting.value = format === 'pptx' ? -row.id : row.id
  try {
    const filename = await downloadExport(row.id, format)
    ElMessage.success(`已导出 ${filename}`)
  } catch (err) {
    ElMessage.error(err.message || '导出失败')
  } finally {
    exporting.value = 0
  }
}

onMounted(load)
</script>
