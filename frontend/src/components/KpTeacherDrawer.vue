<!-- [工单19] 人工智能NLP-Agent数字人项目-教育智能体-个性化学习推荐任务 —— 教师侧知识点治理抽屉 -->
<!--
  三个页签对应设计文档 3.2.5 的三个动作：
    题库汇入（一次性把工单17 的题灌进统一题库）
    未归类清单（词典没命中的标签，按出现次数降序 —— 只给占比教师不知道该补哪条）
    全部别名（**误挂的纠正入口**：词典最长子串必然把"随机梯度下降"挂到"梯度下降"，
              这类错误不在未归类清单里，只能从全量列表改判）
-->
<template>
  <el-drawer v-model="visible" title="知识点治理（教师）" size="760px" @open="reload">
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="题库汇入是把工单17 生成的习题/试题导入统一题库的唯一入口"
      description="不执行它，练习页与试卷模式都抽不到题。接口可重跑，重复执行不会让题量翻倍。"
      style="margin-bottom: 12px"
    />

    <div class="drawer-actions">
      <el-button type="primary" :loading="syncing" @click="runSync">重新汇入题库</el-button>
      <span v-if="lastReport" class="sync-report">
        导入 {{ lastReport.imported }} / 更新 {{ lastReport.updated }} / 共 {{ lastReport.total }} 道，
        未归类 {{ lastReport.unclassified }} 道（{{ percent(lastReport.unclassified_ratio) }}）
      </span>
    </div>

    <el-tabs v-model="tab">
      <!-- ① 未归类 -->
      <el-tab-pane name="unclassified">
        <template #label>未归类（{{ unclassified.length }}）</template>
        <el-empty v-if="!unclassified.length" description="没有未归类的标签" :image-size="70" />
        <el-table v-else :data="unclassified" size="small" height="380">
          <el-table-column prop="raw_label" label="标签原文" min-width="200" show-overflow-tooltip />
          <el-table-column prop="hit_count" label="出现次数" width="90" sortable />
          <el-table-column prop="source" label="来源" width="110" />
          <el-table-column label="操作" width="110" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openMerge(row)">归并到…</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ② 全部别名（含误挂改判） -->
      <el-tab-pane name="aliases">
        <template #label>全部别名（{{ aliases.length }}）</template>
        <el-table :data="aliases" size="small" height="380">
          <el-table-column prop="raw_label" label="标签原文" min-width="180" show-overflow-tooltip />
          <el-table-column label="当前挂靠" min-width="150">
            <template #default="{ row }">
              <el-tag v-if="row.is_placeholder" size="small" type="danger" effect="plain">未归类</el-tag>
              <span v-else>{{ row.kp_name }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="hit_count" label="题目数" width="80" />
          <el-table-column prop="confidence" label="置信度" width="90" />
          <el-table-column prop="source" label="来源" width="110" />
          <el-table-column label="操作" width="110" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openMerge(row)">改判到…</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- 目标知识点选择：只列真实节点，占位节点不能作为归并目标 -->
    <el-dialog v-model="mergeVisible" title="归并到知识点" width="480px" append-to-body>
      <el-form label-width="90px">
        <el-form-item label="标签">
          <el-tag>{{ mergeForm.raw_label }}</el-tag>
        </el-form-item>
        <el-form-item label="目标知识点">
          <el-select
            v-model="mergeForm.target_kp_id"
            filterable
            placeholder="输入名称筛选"
            style="width: 100%"
          >
            <el-option
              v-for="node in nodes"
              :key="node.kp_id"
              :label="node.name"
              :value="node.kp_id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="mergeVisible = false">取消</el-button>
        <el-button type="primary" :loading="merging" @click="submitMerge">确定归并</el-button>
      </template>
    </el-dialog>
  </el-drawer>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

import {
  listAliases,
  listKnowledgePoints,
  listUnclassified,
  mergeAlias,
  syncKnowledge,
} from '@/api/learn'

const visible = defineModel({ type: Boolean, default: false })
const emit = defineEmits(['changed'])

const tab = ref('unclassified')
const syncing = ref(false)
const merging = ref(false)
const mergeVisible = ref(false)
const lastReport = ref(null)
const unclassified = ref([])
const aliases = ref([])
const nodes = ref([])
const mergeForm = ref({ raw_label: '', target_kp_id: null })

const percent = (ratio) => `${((ratio || 0) * 100).toFixed(1)}%`

async function reload() {
  await Promise.all([loadNodes(), loadUnclassified(), loadAliases()])
}

async function loadNodes() {
  try {
    const data = await listKnowledgePoints()
    nodes.value = data.items || []
  } catch {
    /* 拦截器已提示 */
  }
}

async function loadUnclassified() {
  try {
    const data = await listUnclassified()
    unclassified.value = data.items || []
  } catch {
    /* 拦截器已提示 */
  }
}

async function loadAliases() {
  try {
    const data = await listAliases()
    aliases.value = (data.items || []).map((item) => ({
      ...item,
      // 置信度后端给的是 0~1 的小数，列表里按百分比读更快
      confidence: item.confidence == null ? '—' : `${(item.confidence * 100).toFixed(0)}%`,
    }))
  } catch {
    /* 拦截器已提示 */
  }
}

async function runSync() {
  syncing.value = true
  try {
    const report = await syncKnowledge('all')
    lastReport.value = report.questions
    ElMessage.success(
      `汇入完成：新增 ${report.questions.imported}，更新 ${report.questions.updated}`,
    )
    await reload()
    emit('changed')
  } catch {
    /* 拦截器已提示 */
  } finally {
    syncing.value = false
  }
}

function openMerge(row) {
  mergeForm.value = { raw_label: row.raw_label, target_kp_id: null }
  mergeVisible.value = true
}

async function submitMerge() {
  if (!mergeForm.value.target_kp_id) {
    ElMessage.warning('请选择目标知识点')
    return
  }
  merging.value = true
  try {
    const report = await mergeAlias({
      raw_label: mergeForm.value.raw_label,
      target_kp_id: mergeForm.value.target_kp_id,
    })
    ElMessage.success(
      `已归并到「${report.target_kp_name}」，迁移题目 ${report.moved_questions} 道、挂靠 ${report.moved_messages} 条`,
    )
    mergeVisible.value = false
    await reload()
    emit('changed')
  } catch {
    /* 拦截器已提示 */
  } finally {
    merging.value = false
  }
}
</script>

<style scoped>
.drawer-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.sync-report {
  color: #606266;
  font-size: 12px;
}
</style>
