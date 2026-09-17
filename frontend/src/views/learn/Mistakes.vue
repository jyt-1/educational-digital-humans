<!-- [工单19] 人工智能NLP-Agent数字人项目-教育智能体-个性化学习推荐任务 —— AIGC 错题本 -->
<!--
  详情区四块内容直接对应设计文档 3.2.7 的 Prompt 结构：
    ① 你的作答 vs 正确答案（对照，不先给答案就无从谈起"错在哪"）
    ② 深入浅出解析（analysis）
    ③ 错误原因诊断（misconception，并标明来源是"预设"还是"现场推断"）
    ④ 2~3 道同知识点变式题（可再答，**再错则重新分析**——重跑后整个详情要刷新，
       因为新的诊断大概率指向另一个错因，旧诊断留在屏幕上会自相矛盾）
  右侧挂 RelatedPanel：错题不是终点，从这里回到助教提问 / 资料 / 继续练。
-->
<template>
  <div class="learn-page">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>错题本</span>
          <div class="header-actions">
            <el-select
              v-model="kpFilter"
              filterable
              clearable
              placeholder="按知识点筛选"
              size="small"
              style="width: 220px"
              @change="load"
            >
              <el-option v-for="node in nodes" :key="node.kp_id" :label="node.name" :value="node.kp_id" />
            </el-select>
            <el-button size="small" link type="primary" @click="load">刷新</el-button>
          </div>
        </div>
      </template>

      <el-empty v-if="!items.length" description="错题本是空的 —— 练习里答错的题会自动收进来" />
      <el-table v-else :data="items" size="small" @row-click="openDetail">
        <el-table-column label="题干" min-width="320" show-overflow-tooltip>
          <template #default="{ row }">{{ plain(row.stem) }}</template>
        </el-table-column>
        <el-table-column prop="kp_name" label="知识点" width="150">
          <template #default="{ row }">{{ row.kp_name || '未归类' }}</template>
        </el-table-column>
        <el-table-column prop="difficulty" label="难度" width="80" />
        <el-table-column label="AI 分析" width="110">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.analysis_status)" size="small" effect="plain">
              {{ statusText(row.analysis_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="variant_tries" label="变式作答" width="90" />
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click.stop="openDetail(row)">
              查看解析
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 详情：左侧解析与变式题，右侧三个出口 -->
    <el-dialog
      v-model="detailVisible"
      :title="detail.kp_name ? `错题解析 · ${detail.kp_name}` : '错题解析'"
      width="1080px"
      top="5vh"
      destroy-on-close
    >
      <div v-loading="detailLoading" class="detail-wrap">
        <div class="detail-main">
          <!-- ① 题目与作答对照 -->
          <div class="detail-block">
            <div class="block-title">题目</div>
            <div class="rendered-md" v-html="render(detail.stem)"></div>
            <div v-if="detail.options?.length" class="detail-options">
              <div v-for="option in detail.options" :key="option" class="detail-option">{{ option }}</div>
            </div>
            <div class="answer-compare">
              <el-tag type="danger" effect="plain">你的作答：{{ detail.user_answer || '未作答' }}</el-tag>
              <el-tag type="success" effect="plain">正确答案：{{ detail.correct_answer || '—' }}</el-tag>
            </div>
          </div>

          <!-- ②③ AIGC 分析 -->
          <div class="detail-block">
            <div class="block-title">
              AI 错题分析
              <el-tag :type="statusTag(detail.analysis_status)" size="small" effect="plain" style="margin-left: 8px">
                {{ statusText(detail.analysis_status) }}
              </el-tag>
            </div>

            <el-alert
              v-if="analysisError"
              type="error"
              :closable="false"
              show-icon
              :title="`分析失败：${analysisError}`"
              description="失败原因通常是 LLM 接口超时或额度不足，点下方按钮可重试。"
              style="margin-bottom: 10px"
            />

            <template v-if="analysis">
              <div class="analysis-section">
                <div class="section-label">深入浅出解析</div>
                <div class="rendered-md" v-html="render(analysis.analysis)"></div>
              </div>
              <div class="analysis-section">
                <div class="section-label">
                  错误原因诊断
                  <el-tag size="small" :type="analysis.misconception_source === 'preset' ? 'info' : 'warning'" effect="plain">
                    {{ analysis.misconception_source === 'preset' ? '命中常见误区预设' : '现场推断' }}
                  </el-tag>
                  <el-tag v-if="analysis.misconception_type" size="small" effect="plain" style="margin-left: 6px">
                    {{ analysis.misconception_type }}
                  </el-tag>
                </div>
                <div class="rendered-md" v-html="render(analysis.misconception)"></div>
                <ul v-if="analysis.inferred_misconceptions?.length" class="misconception-list">
                  <li v-for="(item, index) in analysis.inferred_misconceptions" :key="index">{{ item }}</li>
                </ul>
              </div>
            </template>

            <el-empty
              v-else-if="!analysisError"
              :image-size="70"
              description="还没有生成分析。点下面的按钮，AI 会给出解析、错因诊断和 2~3 道变式题。"
            />

            <el-button
              type="primary"
              size="small"
              :loading="analyzing"
              style="margin-top: 10px"
              @click="runAnalyze"
            >
              {{ analysis ? '重新生成分析' : '生成 AI 分析' }}
            </el-button>
          </div>

          <!-- ④ 变式题 -->
          <div v-if="detail.variant_questions?.length" class="detail-block">
            <div class="block-title">
              变式题（同知识点）
              <span class="block-tip">答错会自动重新分析，错因会换一个角度看</span>
            </div>

            <div v-for="(variant, index) in detail.variant_questions" :key="variant.question_id" class="variant">
              <div class="variant-head">变式 {{ index + 1 }}</div>
              <div class="rendered-md" v-html="render(variant.stem)"></div>
              <el-checkbox-group
                v-if="variant.options?.length && isMultiVariant(variant)"
                v-model="variantAnswers[variant.question_id]"
                :disabled="!!variantResults[variant.question_id]"
                class="variant-options"
              >
                <el-checkbox
                  v-for="option in variant.options"
                  :key="option"
                  :value="letterOf(option)"
                  class="variant-option"
                >
                  {{ option }}
                </el-checkbox>
              </el-checkbox-group>
              <el-radio-group
                v-else-if="variant.options?.length"
                v-model="variantAnswers[variant.question_id]"
                :disabled="!!variantResults[variant.question_id]"
                class="variant-options"
              >
                <el-radio
                  v-for="option in variant.options"
                  :key="option"
                  :value="letterOf(option)"
                  class="variant-option"
                >
                  {{ option }}
                </el-radio>
              </el-radio-group>
              <el-input
                v-else
                v-model="variantAnswers[variant.question_id]"
                :disabled="!!variantResults[variant.question_id]"
                placeholder="填写答案"
                style="max-width: 380px"
              />

              <div class="variant-actions">
                <el-button
                  type="primary"
                  size="small"
                  :loading="submittingVariant === variant.question_id"
                  :disabled="!!variantResults[variant.question_id]"
                  @click="submitVariant(variant)"
                >
                  提交
                </el-button>
                <el-button
                  v-if="!variantResults[variant.question_id]"
                  link
                  size="small"
                  @click="revealVariant(variant)"
                >
                  看答案与解析
                </el-button>
              </div>

              <el-alert
                v-if="variantResults[variant.question_id]"
                :type="variantAlertType(variantResults[variant.question_id])"
                :closable="false"
                show-icon
                style="margin-top: 8px"
              >
                <template #title>
                  {{ variantAlertTitle(variantResults[variant.question_id]) }}
                  <span class="feedback-answer">
                    正确答案：{{ variantResults[variant.question_id].correct_answer || '—' }}
                  </span>
                </template>
                <div
                  v-if="variantResults[variant.question_id].analysis"
                  class="rendered-md"
                  v-html="render(variantResults[variant.question_id].analysis)"
                ></div>
                <div v-if="variantResults[variant.question_id].reanalyzed" class="reanalyze-tip">
                  已根据这次的错误重新生成分析，上方诊断已更新。
                </div>
                <div v-else-if="variantResults[variant.question_id].error" class="reanalyze-tip">
                  重新分析失败：{{ variantResults[variant.question_id].error }}（作答已记录）
                </div>
              </el-alert>
            </div>
          </div>
        </div>

        <!-- 右侧三出口 -->
        <div v-if="detail.kp_id" class="detail-side">
          <div class="block-title">继续学习</div>
          <RelatedPanel :kp-id="detail.kp_id" :kp-name="detail.kp_name" />
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { marked } from 'marked'

import RelatedPanel from '@/components/RelatedPanel.vue'
import {
  analyzeMistake,
  answerVariant,
  getMistake,
  listKnowledgePoints,
  listMistakes,
} from '@/api/learn'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const items = ref([])
const nodes = ref([])
const kpFilter = ref(null)

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref({})
const analysis = ref(null)
const analysisError = ref('')
const analyzing = ref(false)
const submittingVariant = ref(null)
const variantAnswers = reactive({})
const variantResults = reactive({})

const STATUS_TAGS = { done: 'success', analyzing: 'warning', failed: 'danger' }
const STATUS_TEXT = { done: '已分析', analyzing: '分析中', failed: '分析失败', pending: '待分析' }
const statusTag = (status) => STATUS_TAGS[status] ?? 'info'
const statusText = (status) => STATUS_TEXT[status] ?? '待分析'

function render(text) {
  if (!text) return ''
  try {
    return marked.parse(String(text), { breaks: true })
  } catch {
    return String(text)
  }
}

// 列表里的题干只做纯文本预览：表格单元格里跑 Markdown 会撑破行高
function plain(text) {
  return String(text || '').replace(/[#*`>\-]/g, '').slice(0, 80)
}

function letterOf(option) {
  const matched = String(option).match(/^([a-zA-Z0-9])[.、．)）:：]/)
  return matched ? matched[1].toUpperCase() : option
}

// 变式题的答案就在本地（「看答案与解析」是客户端揭示），所以这里直接据答案判定是否多选。
// 只认"全由选项字母组成且不止一个"的答案：这样 "ABCD" 是多选，而 "Adam"、"链式法则" 这类
// 文本答案里恰好带字母的不会被误判成多选。
function isMultiVariant(variant) {
  const answer = String(variant?.answer || '').toUpperCase()
  if (answer.length < 2) return false
  const letters = (variant?.options || []).map((option) => letterOf(option))
  return [...answer].every((char) => letters.includes(char))
}

// 答案归一：多选在界面上是数组，提交前拼成 "ABC"（后端按集合比较，"CBA" 同样判对）
function collect(value) {
  if (Array.isArray(value)) return value.length ? [...value].sort().join('') : null
  return value || null
}

// 多选的 v-model 必须是数组；详情每次重载都会换一批变式题，槽位跟着重来
function initVariantSlots(list) {
  ;(list || []).forEach((variant) => {
    if (isMultiVariant(variant)) variantAnswers[variant.question_id] = []
  })
}

async function load() {
  loading.value = true
  try {
    const params = {}
    if (kpFilter.value) params.kp_id = kpFilter.value
    const data = await listMistakes(params)
    items.value = data.items || []
  } catch {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}

async function loadNodes() {
  try {
    const data = await listKnowledgePoints()
    nodes.value = data.items || []
  } catch {
    /* 拦截器已提示 */
  }
}

function applyDetail(data) {
  detail.value = data
  initVariantSlots(data.variant_questions)
  analysis.value = data.analysis || null
  if (!data.analysis && data.analysis_status === 'failed') {
    analysisError.value = '上次分析未成功，可重试'
  } else {
    analysisError.value = ''
  }
}

async function openDetail(row) {
  const mistakeId = row?.mistake_id ?? row
  if (!mistakeId) return
  detailVisible.value = true
  detailLoading.value = true
  Object.keys(variantAnswers).forEach((key) => delete variantAnswers[key])
  Object.keys(variantResults).forEach((key) => delete variantResults[key])
  try {
    applyDetail(await getMistake(mistakeId))
    // 详情用 query 记住，刷新页面还能回到同一条
    router.replace({ path: '/learn/mistakes', query: { id: mistakeId } })
  } catch {
    detailVisible.value = false
  } finally {
    detailLoading.value = false
  }
}

async function runAnalyze() {
  analyzing.value = true
  analysisError.value = ''
  try {
    const mistakeId = detail.value.mistake_id
    await analyzeMistake(mistakeId)
    // 分析接口返回的是"分析结果"，详情接口返回的是"错题 + 分析 + 变式题"三种结构拼好的页面数据。
    // 这里重取一次详情，避免前端自己拼两套结构——拼错的那套只有肉眼能发现。
    applyDetail(await getMistake(mistakeId))
    ElMessage.success('分析已生成')
    load()
  } catch (error) {
    analysisError.value = error?.message || '未知错误'
  } finally {
    analyzing.value = false
  }
}

async function submitVariant(variant) {
  submittingVariant.value = variant.question_id
  try {
    const data = await answerVariant(detail.value.mistake_id, {
      question_id: variant.question_id,
      user_answer: collect(variantAnswers[variant.question_id]),
    })
    variantResults[variant.question_id] = data
    // 再错会触发重新分析 → 整条详情都要换掉，否则旧诊断与新变式题对不上
    if (!data.is_correct) {
      // 但重新分析会**换一批变式题**，刚作答的那道就从列表里消失了——
      // 判分、正确答案、这道题的解析会跟着一起不见，学生点完「提交」只看到题目被换掉，
      // 等于白答。所以把答过的那道留在列表最前（它的结果还在 variantResults 里，
      // 控件自动置灰、反馈块照常显示），新题排在后面。
      const answered = { ...variant }
      applyDetail(data.mistake)
      const list = detail.value.variant_questions || []
      if (!list.some((item) => item.question_id === answered.question_id)) {
        detail.value.variant_questions = [answered, ...list]
      }
      ElMessage.warning('又答错了，已重新分析')
      load()
    }
  } catch {
    /* 拦截器已提示 */
  } finally {
    submittingVariant.value = null
  }
}

// 主动看答案与答错是两回事：前者不该染成红色（红色=做错了，会把"我只是想看解析"读成失败）
function variantAlertType(result) {
  if (result.revealed) return 'info'
  return result.is_correct ? 'success' : 'error'
}

function variantAlertTitle(result) {
  if (result.revealed) return '答案与解析'
  return result.is_correct ? '回答正确' : '又答错了'
}

function revealVariant(variant) {
  variantResults[variant.question_id] = {
    is_correct: false,
    correct_answer: variant.answer,
    analysis: variant.analysis,
    revealed: true,
  }
}

onMounted(() => {
  load()
  loadNodes()
  const preset = Number(route.query.id)
  if (preset) openDetail(preset)
})
</script>

<style scoped>
.learn-page {
  padding-bottom: 24px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.detail-wrap {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.detail-main {
  flex: 1;
  min-width: 0;
}

.detail-side {
  width: 320px;
  flex-shrink: 0;
  border-left: 1px solid #ebeef5;
  padding-left: 14px;
}

.detail-block {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 12px 14px;
  margin-bottom: 14px;
}

.block-title {
  display: flex;
  align-items: center;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}

.block-tip {
  margin-left: 10px;
  color: #909399;
  font-size: 12px;
  font-weight: 400;
}

.detail-options {
  margin: 8px 0;
}

.detail-option {
  color: #606266;
  line-height: 1.9;
}

.answer-compare {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 10px;
}

.analysis-section {
  margin-bottom: 12px;
}

.section-label {
  display: flex;
  align-items: center;
  color: #409eff;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
}

.misconception-list {
  margin: 6px 0 0;
  padding-left: 20px;
  color: #606266;
  font-size: 13px;
  line-height: 1.8;
}

.variant {
  border-top: 1px dashed #ebeef5;
  padding-top: 10px;
  margin-top: 10px;
}

.variant-head {
  font-weight: 600;
  color: #e6a23c;
  margin-bottom: 6px;
}

.variant-options {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  margin-top: 6px;
}

.variant-option {
  height: auto;
  white-space: normal;
}

/* 多选框组也用 .variant-options 排成竖列，去掉 EP 默认的右外边距免得对不齐 */
.variant-options :deep(.el-checkbox) {
  margin-right: 0;
}

.variant-actions {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.feedback-answer {
  margin-left: 12px;
  color: #606266;
  font-weight: 400;
}

.reanalyze-tip {
  margin-top: 6px;
  color: #909399;
  font-size: 12px;
}
</style>
