<!-- [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— 知识库管理页 -->
<template>
  <div class="page-card">
    <div class="kb-head">
      <div>
        <h3 class="kb-title">知识库</h3>
        <p class="kb-desc">
          支持 PDF / Word / PPT / Excel / 图像的解析入库，表格转 Markdown、图片单独抽取、
          公式保留原文位置。公共库所有师生可检索{{ isTeacher() ? '（你可在公共库上传）' : '（学生只读）' }}，
          私有库仅本人可见。
        </p>
      </div>
      <el-button type="primary" @click="openUpload">上传文档</el-button>
    </div>

    <el-tabs v-model="activeScope" @tab-change="loadDocs">
      <el-tab-pane label="公共知识库" name="public" />
      <el-tab-pane label="我的私有库" name="private" />
    </el-tabs>

    <el-table v-loading="loading" :data="docs" border stripe>
      <el-table-column prop="filename" label="文件名" min-width="240" show-overflow-tooltip />
      <el-table-column prop="file_type" label="类型" width="80" />
      <el-table-column label="大小" width="100">
        <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
      </el-table-column>
      <el-table-column v-if="activeScope === 'public'" label="上传者" width="110">
        <template #default="{ row }">{{ row.owner_name || '-' }}</template>
      </el-table-column>
      <el-table-column label="解析状态" width="150">
        <template #default="{ row }">
          <el-tag :type="statusTag(row.parse_status)" size="small">
            {{ statusLabel(row.parse_status) }}
          </el-tag>
          <el-tooltip v-if="row.parse_status === 'failed'" :content="row.parse_error || '解析失败'" placement="top">
            <el-icon class="kb-warn"><WarningFilled /></el-icon>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column prop="chunk_count" label="内容块" width="80" />
      <el-table-column label="上传时间" width="170">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="openDetail(row)">详情</el-button>
          <el-button
            link
            type="primary"
            size="small"
            :disabled="!canWrite(row)"
            :loading="reparsingId === row.id"
            @click="handleReparse(row)"
          >
            重新解析
          </el-button>
          <el-button link type="danger" size="small" :disabled="!canWrite(row)" @click="handleDelete(row)">
            删除
          </el-button>
        </template>
      </el-table-column>
      <template #empty>暂无文档，点击右上角「上传文档」开始构建知识库</template>
    </el-table>
  </div>

  <!-- 上传弹窗 -->
  <el-dialog v-model="uploadVisible" title="上传文档" width="560px" @closed="resetUpload">
    <el-radio-group v-model="uploadScope" :disabled="uploading">
      <el-radio-button value="private">我的私有库</el-radio-button>
      <el-radio-button value="public" :disabled="!isTeacher()">公共知识库</el-radio-button>
    </el-radio-group>
    <p class="kb-hint">
      <template v-if="isTeacher()">公共库全体师生可检索；私有库仅本人可见。</template>
      <template v-else>学生只能上传到私有库；公共知识库由教师维护。</template>
    </p>

    <el-upload
      ref="uploadRef"
      drag
      :auto-upload="false"
      :limit="1"
      :on-change="onFileChange"
      :on-exceed="onExceed"
      accept=".pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.png,.jpg,.jpeg,.gif,.bmp,.webp,.tiff"
    >
      <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
      <div class="el-upload__text">拖拽文件到此处，或<em>点击选择</em></div>
      <template #tip>
        <div class="el-upload__tip">
          支持 PDF、DOC/DOCX、PPT/PPTX、XLS/XLSX、图像；单个文件不超过 50MB。
        </div>
      </template>
    </el-upload>

    <el-progress v-if="uploading || uploadPercent > 0" :percentage="uploadPercent" :stroke-width="14" />
    <div v-if="parseHint" class="kb-hint">{{ parseHint }}</div>

    <template #footer>
      <el-button :disabled="uploading" @click="uploadVisible = false">取消</el-button>
      <el-button type="primary" :loading="uploading" :disabled="!pickedFile" @click="submitUpload">
        上传
      </el-button>
    </template>
  </el-dialog>

  <!-- 详情抽屉 -->
  <el-drawer v-model="detailVisible" :title="detail?.filename || '文档详情'" size="620px">
    <div v-if="detail" v-loading="detailLoading">
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="解析状态">
          <el-tag :type="statusTag(detail.parse_status)" size="small">
            {{ statusLabel(detail.parse_status) }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="内容块总数">{{ detail.chunk_count }}</el-descriptions-item>
        <el-descriptions-item label="类型">{{ detail.file_type }}</el-descriptions-item>
        <el-descriptions-item label="大小">{{ formatSize(detail.file_size) }}</el-descriptions-item>
        <el-descriptions-item label="归属">
          {{ detail.scope === 'public' ? '公共知识库' : '私有知识库' }}
        </el-descriptions-item>
        <el-descriptions-item label="上传者">{{ detail.owner_name || '系统' }}</el-descriptions-item>
      </el-descriptions>

      <el-alert
        v-if="detail.parse_status === 'failed'"
        type="error"
        :title="detail.parse_error || '解析失败'"
        :closable="false"
        show-icon
        style="margin-top: 12px"
      />

      <div class="kb-stats">
        <span>正文 {{ detail.chunk_stats?.text || 0 }}</span>
        <span>表格 {{ detail.chunk_stats?.table || 0 }}</span>
        <span>图片 {{ detail.chunk_stats?.image || 0 }}</span>
        <span>公式 {{ detail.chunk_stats?.formula || 0 }}</span>
      </div>

      <h4 class="kb-sub">内容块预览（最多 50 块）</h4>
      <div class="kb-chunks">
        <div v-for="chunk in detail.chunks" :key="chunk.id" class="kb-chunk">
          <div class="kb-chunk-head">
            <span class="kb-chunk-index">#{{ chunk.chunk_index + 1 }}</span>
            <el-tag size="small" :type="chunkTag(chunk.chunk_type)">{{ chunkTypeLabel(chunk.chunk_type) }}</el-tag>
            <span v-if="chunk.page_no" class="kb-chunk-page">第 {{ chunk.page_no }} 页</span>
          </div>
          <el-image
            v-if="chunk.chunk_type === 'image' && chunkImages[chunk.id]"
            :src="chunkImages[chunk.id]"
            :preview-src-list="[chunkImages[chunk.id]]"
            preview-teleported
            fit="contain"
            class="kb-chunk-image"
          />
          <pre class="kb-chunk-text">{{ chunk.content }}</pre>
        </div>
        <el-empty v-if="!detail.chunks?.length" description="暂无内容块" :image-size="70" />
      </div>
    </div>
  </el-drawer>
</template>

<script setup>
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { UploadFilled, WarningFilled } from '@element-plus/icons-vue'

import {
  deleteDoc,
  fetchChunkImage,
  getDoc,
  listDocs,
  reparseDoc,
  uploadDoc,
} from '@/api/kb'
import { isTeacher } from '@/store/user'

const activeScope = ref('public')
const docs = ref([])
const loading = ref(false)

const uploadVisible = ref(false)
const uploadScope = ref('private')
const uploadRef = ref(null)
const pickedFile = ref(null)
const uploadPercent = ref(0)
const uploading = ref(false)
const parseHint = ref('')
const reparsingId = ref(null)

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref(null)
const chunkImages = reactive({})

let pollTimer = null

const STATUS_LABELS = { pending: '排队中', parsing: '解析中', done: '已完成', failed: '解析失败' }
const STATUS_TAGS = { pending: 'info', parsing: 'warning', done: 'success', failed: 'danger' }
const CHUNK_LABELS = { text: '正文', table: '表格', image: '图片', formula: '公式' }
const CHUNK_TAGS = { text: '', table: 'success', image: 'warning', formula: 'danger' }

function statusLabel(status) {
  return STATUS_LABELS[status] || status
}

function statusTag(status) {
  return STATUS_TAGS[status] || 'info'
}

function chunkTypeLabel(type) {
  return CHUNK_LABELS[type] || type
}

function chunkTag(type) {
  return CHUNK_TAGS[type] ?? ''
}

function formatSize(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

function formatTime(value) {
  if (!value) return '-'
  return String(value).replace('T', ' ').slice(0, 19)
}

/** 公共库学生只读、私有库仅本人可写，与后端 can_write 规则一致 */
function canWrite(row) {
  if (row.scope === 'public') return isTeacher()
  return true
}

async function loadDocs() {
  loading.value = true
  try {
    docs.value = await listDocs(activeScope.value)
    ensurePolling()
  } finally {
    loading.value = false
  }
}

// ---------------------------------------------------------------- 解析状态轮询

function ensurePolling() {
  const busy = docs.value.some((doc) => doc.parse_status === 'pending' || doc.parse_status === 'parsing')
  if (busy && !pollTimer) {
    pollTimer = setInterval(refreshBusyDocs, 2000)
  } else if (!busy && pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function refreshBusyDocs() {
  const busy = docs.value.filter((doc) => doc.parse_status === 'pending' || doc.parse_status === 'parsing')
  if (!busy.length) {
    ensurePolling()
    return
  }
  for (const doc of busy) {
    try {
      const fresh = await getDoc(doc.id)
      Object.assign(doc, {
        parse_status: fresh.parse_status,
        parse_error: fresh.parse_error,
        chunk_count: fresh.chunk_count,
      })
    } catch {
      /* 单条轮询失败不影响其他文档 */
    }
  }
  ensurePolling()
}

// ---------------------------------------------------------------- 上传

function openUpload() {
  uploadVisible.value = true
}

function onFileChange(file) {
  pickedFile.value = file.raw || file
}

function onExceed(files) {
  uploadRef.value?.clearFiles()
  uploadRef.value?.handleStart(files[0])
  pickedFile.value = files[0]
}

function resetUpload() {
  pickedFile.value = null
  uploadPercent.value = 0
  parseHint.value = ''
  uploadRef.value?.clearFiles()
}

async function submitUpload() {
  if (!pickedFile.value) return
  uploading.value = true
  uploadPercent.value = 0
  parseHint.value = ''
  try {
    const doc = await uploadDoc(pickedFile.value, uploadScope.value, (percent) => {
      uploadPercent.value = percent
    })
    parseHint.value = `「${doc.filename}」上传成功，正在后台解析，完成后自动刷新状态。`
    ElMessage.success('上传成功，正在解析')
    activeScope.value = uploadScope.value
    await loadDocs()
    // 解析完成后关闭弹窗，让用户直接看到列表里的状态流转
    setTimeout(async () => {
      await refreshBusyDocs()
      uploadVisible.value = false
    }, 1200)
  } catch {
    uploading.value = false
    return
  }
  uploading.value = false
}

// ---------------------------------------------------------------- 操作

async function handleReparse(row) {
  reparsingId.value = row.id
  try {
    await reparseDoc(row.id)
    row.parse_status = 'pending'
    ElMessage.success('已开始重新解析')
    ensurePolling()
  } catch {
    /* 拦截器已提示 */
  } finally {
    reparsingId.value = null
  }
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(`确认删除「${row.filename}」及其全部向量索引？`, '删除确认', {
      type: 'warning',
    })
  } catch {
    return
  }
  await deleteDoc(row.id)
  ElMessage.success('已删除')
  await loadDocs()
}

async function openDetail(row) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    const full = await getDoc(row.id)
    detail.value = full
    full.chunks
      .filter((chunk) => chunk.chunk_type === 'image')
      .forEach((chunk) => {
        fetchChunkImage(chunk.id)
          .then((url) => {
            chunkImages[chunk.id] = url
          })
          .catch(() => {
            /* 图片缺失不影响其它内容 */
          })
      })
  } finally {
    detailLoading.value = false
  }
}

onMounted(loadDocs)

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
  Object.values(chunkImages).forEach((url) => URL.revokeObjectURL(url))
})
</script>

<style scoped>
.kb-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.kb-title {
  margin: 0 0 6px;
}

.kb-desc {
  margin: 0 0 12px;
  color: #909399;
  font-size: 13px;
  line-height: 1.7;
  max-width: 900px;
}

.kb-hint {
  color: #909399;
  font-size: 12px;
  margin: 8px 0;
}

.kb-warn {
  color: #f56c6c;
  margin-left: 6px;
  vertical-align: middle;
}

.kb-stats {
  display: flex;
  gap: 16px;
  margin: 12px 0;
  color: #606266;
  font-size: 13px;
}

.kb-sub {
  margin: 12px 0 8px;
}

.kb-chunks {
  max-height: 52vh;
  overflow-y: auto;
}

.kb-chunk {
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 8px 10px;
  margin-bottom: 8px;
}

.kb-chunk-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.kb-chunk-index {
  color: #909399;
  font-size: 12px;
}

.kb-chunk-page {
  color: #909399;
  font-size: 12px;
}

.kb-chunk-text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #303133;
  max-height: 200px;
  overflow-y: auto;
}

.kb-chunk-image {
  max-width: 260px;
  max-height: 180px;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  margin-bottom: 6px;
  display: block;
}
</style>
