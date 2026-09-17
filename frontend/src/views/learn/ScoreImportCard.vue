<!-- [工单19] 人工智能NLP-Agent数字人项目-教育智能体-个性化学习推荐任务 —— 历史成绩导入（初始化画像） -->
<!--
  工单原文要求"支持导入历史成绩初始化画像"。两条路径共用同一份校验管线：
    ① 上传 xlsx（模板只有 知识点/得分/满分 三列，**不含学号姓名**——导入的是本人成绩）
    ② 手工新增一行（走 JSON 载荷），适用于只补录一两条的场景
  **匹配失败的行不入库**：混进「未归类」会直接脏掉初始画像，而画像是整条推荐链的起点。
-->
<template>
  <el-card shadow="never">
    <template #header>
      <div class="import-header">
        <span>历史成绩导入</span>
        <span class="import-tip">
          用于初始化画像：导入后系统才知道你哪些知识点已经会了，推荐才不会从零开始
        </span>
      </div>
    </template>

    <div class="import-actions">
      <el-upload
        :auto-upload="false"
        :show-file-list="false"
        accept=".xlsx"
        :on-change="handleFile"
      >
        <el-button type="primary" :loading="uploading">上传 Excel（xlsx）</el-button>
      </el-upload>
      <el-button @click="downloadTemplate">下载模板</el-button>
      <el-button @click="manualVisible = true">手工新增一行</el-button>
      <el-button link type="primary" @click="loadBatches">刷新批次</el-button>
    </div>

    <!-- 导入结果：成功与失败都要看得见，失败必须给可执行的原因 -->
    <el-alert
      v-if="report"
      :type="report.failure_count ? 'warning' : 'success'"
      :closable="false"
      show-icon
      style="margin-top: 12px"
    >
      <template #title>
        批次 {{ shortId(report.batch_id) }}：成功 {{ report.success_count }} 行，
        失败 {{ report.failure_count }} 行（匹配失败的行**没有入库**）
      </template>
    </el-alert>

    <el-table
      v-if="report?.failures?.length"
      :data="report.failures"
      size="small"
      style="margin-top: 8px"
    >
      <el-table-column prop="row" label="Excel 行号" width="100" />
      <el-table-column prop="raw_label" label="知识点" min-width="160" />
      <el-table-column prop="reason" label="失败原因" min-width="240" />
    </el-table>

    <el-collapse v-if="batches.length" style="margin-top: 12px">
      <el-collapse-item :title="`已导入批次（${batches.length}）`" name="batches">
        <el-table :data="batches" size="small">
          <el-table-column label="批次" width="130">
            <template #default="{ row }">{{ shortId(row.batch_id) }}</template>
          </el-table-column>
          <el-table-column prop="count" label="条数" width="70" />
          <el-table-column prop="source_file" label="来源文件" min-width="160">
            <template #default="{ row }">{{ row.source_file || '手工录入' }}</template>
          </el-table-column>
          <el-table-column label="知识点明细" min-width="260">
            <template #default="{ row }">
              <el-tag
                v-for="item in row.rows"
                :key="item.id"
                size="small"
                effect="plain"
                style="margin: 2px 4px 2px 0"
              >
                {{ item.kp_name || item.raw_label }} {{ item.score }}/{{ item.total }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-button link type="danger" size="small" @click="revoke(row)">整批撤销</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-collapse-item>
    </el-collapse>

    <!-- 手工新增一行 -->
    <el-dialog v-model="manualVisible" title="手工新增一行成绩" width="460px" append-to-body>
      <el-form label-width="80px">
        <el-form-item label="知识点">
          <el-select
            v-model="manualForm.kp"
            filterable
            allow-create
            default-first-option
            placeholder="选图谱节点，或直接输入名称（须能匹配）"
            style="width: 100%"
          >
            <el-option v-for="name in kpNames" :key="name" :label="name" :value="name" />
          </el-select>
        </el-form-item>
        <el-form-item label="得分">
          <el-input-number v-model="manualForm.score" :min="0" :max="manualForm.total" />
        </el-form-item>
        <el-form-item label="满分">
          <el-input-number v-model="manualForm.total" :min="1" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="manualVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="submitManual">提交</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import {
  downloadImportTemplate,
  importScores,
  importScoresFile,
  listImportBatches,
  listKnowledgePoints,
  deleteImportBatch,
} from '@/api/learn'

const emit = defineEmits(['imported'])

const uploading = ref(false)
const report = ref(null)
const batches = ref([])
const kpNames = ref([])
const manualVisible = ref(false)
const manualForm = ref({ kp: '', score: 0, total: 100 })

const shortId = (id) => (id ? String(id).slice(0, 8) : '—')

async function handleFile(uploadFile) {
  const file = uploadFile?.raw
  if (!file) return
  uploading.value = true
  try {
    report.value = await importScoresFile(file)
    afterImport()
  } catch {
    /* 拦截器已提示 */
  } finally {
    uploading.value = false
  }
}

async function submitManual() {
  if (!manualForm.value.kp) {
    ElMessage.warning('请填写知识点')
    return
  }
  uploading.value = true
  try {
    report.value = await importScores({ rows: [manualForm.value] })
    manualVisible.value = false
    afterImport()
  } catch {
    /* 拦截器已提示 */
  } finally {
    uploading.value = false
  }
}

function afterImport() {
  if (report.value.failure_count) {
    ElMessage.warning(`成功 ${report.value.success_count} 行，失败 ${report.value.failure_count} 行`)
  } else {
    ElMessage.success(`导入成功 ${report.value.success_count} 行`)
  }
  loadBatches()
  emit('imported')
}

async function loadBatches() {
  try {
    const data = await listImportBatches()
    batches.value = data.items || []
  } catch {
    /* 拦截器已提示 */
  }
}

async function revoke(row) {
  try {
    const data = await deleteImportBatch(row.batch_id)
    ElMessage.success(`已撤销 ${data.deleted ?? row.count} 条，画像已同步更新`)
    await loadBatches()
    emit('imported')
  } catch {
    /* 拦截器已提示 */
  }
}

async function downloadTemplate() {
  try {
    const response = await downloadImportTemplate()
    const url = URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.download = '历史成绩导入模板.xlsx'
    link.click()
    URL.revokeObjectURL(url)
  } catch {
    /* 拦截器已提示 */
  }
}

async function loadKpNames() {
  try {
    const data = await listKnowledgePoints()
    kpNames.value = (data.items || []).map((item) => item.name)
  } catch {
    /* 拦截器已提示 */
  }
}

onMounted(() => {
  loadBatches()
  loadKpNames()
})
</script>

<style scoped>
.import-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}

.import-tip {
  color: #909399;
  font-size: 12px;
  font-weight: 400;
}

.import-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
</style>
