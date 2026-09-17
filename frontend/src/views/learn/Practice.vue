<!-- [工单19] 人工智能NLP-Agent数字人项目-教育智能体-个性化学习推荐任务 —— 自适应练习与试卷模式 -->
<!--
  两种模式刻意放在同一页（设计文档 3.2.2 抉择2 → A）：
    练习 = 训练：逐题作答、即时反馈、连对 3 题升档、答错降档、答错进错题本
    试卷 = 测量：一次性交卷、按分值算总分、**不动难度档**
  两者共用同一套判分与落库逻辑（后端 `learn_answer` 收敛在一处），
  否则最容易出现的偏差是练习把 "A" 判对、试卷把 "A. 链式法则" 判错。
-->
<template>
  <div class="learn-page">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>自适应练习</span>
          <el-radio-group v-model="mode" size="small" @change="onModeChange">
            <el-radio-button value="practice">练习（训练，会升降难度档）</el-radio-button>
            <el-radio-button value="exam">试卷（测量，不影响难度档）</el-radio-button>
          </el-radio-group>
        </div>
      </template>

      <!-- -------------------------------------------------- 练习模式 -->
      <template v-if="mode === 'practice'">
        <div class="toolbar">
          <el-select
            v-model="kpId"
            filterable
            clearable
            placeholder="选择知识点（留空则取推荐路径的第一个）"
            style="width: 320px"
            @change="loadPractice"
          >
            <el-option v-for="node in nodes" :key="node.kp_id" :label="node.name" :value="node.kp_id" />
          </el-select>
          <el-input-number v-model="count" :min="1" :max="20" size="default" />
          <el-button type="primary" :loading="loading" @click="loadPractice">取题</el-button>
          <el-tag v-if="meta.difficulty" size="small" :type="difficultyTag(meta.difficulty)" effect="dark">
            当前难度 {{ meta.difficulty }}
          </el-tag>
          <el-tag v-if="meta.promote_streak" size="small" type="info" effect="plain">
            连对 {{ streak }} / {{ meta.promote_streak }} 升档
          </el-tag>
        </div>

        <el-alert
          v-if="emptyMessage"
          type="warning"
          :closable="false"
          show-icon
          :title="emptyMessage"
          style="margin-bottom: 12px"
        />

        <div v-for="(question, index) in questions" :key="question.question_id" class="question-block">
          <div class="question-head">
            <span class="q-index">第 {{ index + 1 }} 题</span>
            <el-tag size="small" :type="difficultyTag(question.difficulty)" effect="plain">
              {{ question.difficulty }}
            </el-tag>
            <el-tag size="small" type="info" effect="plain">{{ question.qtype }}</el-tag>
          </div>

          <div class="q-stem rendered-md" v-html="render(question.stem)"></div>

          <!-- 有选项：多选/单选；无选项：文本输入 -->
          <el-checkbox-group
            v-if="question.options?.length && isMulti(question)"
            v-model="answers[question.question_id]"
            :disabled="!!results[question.question_id]"
            class="q-options"
          >
            <el-checkbox
              v-for="option in question.options"
              :key="option"
              :value="letterOf(option)"
              class="q-option"
            >
              {{ option }}
            </el-checkbox>
          </el-checkbox-group>
          <el-radio-group
            v-else-if="question.options?.length"
            v-model="answers[question.question_id]"
            :disabled="!!results[question.question_id]"
            class="q-options"
          >
            <el-radio
              v-for="option in question.options"
              :key="option"
              :value="letterOf(option)"
              class="q-option"
            >
              {{ option }}
            </el-radio>
          </el-radio-group>
          <el-input
            v-else
            v-model="answers[question.question_id]"
            :disabled="!!results[question.question_id]"
            placeholder="填写答案"
            style="max-width: 420px"
          />

          <div class="q-actions">
            <el-button
              type="primary"
              size="small"
              :loading="submitting === question.question_id"
              :disabled="!!results[question.question_id]"
              @click="submitOne(question)"
            >
              提交作答
            </el-button>
            <el-button
              v-if="results[question.question_id]?.mistake_id"
              link
              type="danger"
              size="small"
              @click="goMistake(results[question.question_id].mistake_id)"
            >
              查看 AI 错题分析
            </el-button>
          </div>

          <!-- 即时反馈 -->
          <el-alert
            v-if="results[question.question_id]"
            :type="results[question.question_id].is_correct ? 'success' : 'error'"
            :closable="false"
            show-icon
            style="margin-top: 8px"
          >
            <template #title>
              {{ results[question.question_id].is_correct ? '回答正确' : '回答错误' }}
              <span v-if="!results[question.question_id].is_correct" class="feedback-answer">
                正确答案：{{ results[question.question_id].correct_answer }}
              </span>
              <span v-if="results[question.question_id].mastery != null" class="feedback-mastery">
                该知识点掌握度 {{ (results[question.question_id].mastery * 100).toFixed(0) }}%
              </span>
            </template>
            <div
              v-if="results[question.question_id].analysis"
              class="rendered-md"
              v-html="render(results[question.question_id].analysis)"
            ></div>
          </el-alert>
        </div>
      </template>

      <!-- -------------------------------------------------- 试卷模式 -->
      <template v-else>
        <div class="toolbar">
          <el-button type="primary" :loading="loading" @click="loadExam">取最近一套试卷</el-button>
          <template v-if="exam.plan_id">
            <span class="exam-title">{{ exam.title }}</span>
            <el-tag size="small" type="info" effect="plain">
              共 {{ exam.question_count }} 题 · 满分 {{ exam.total_score }}
            </el-tag>
          </template>
        </div>

        <el-alert
          v-if="emptyMessage"
          type="warning"
          :closable="false"
          show-icon
          :title="emptyMessage"
          style="margin-bottom: 12px"
        />

        <div v-for="(question, index) in exam.questions || []" :key="question.question_id" class="question-block">
          <div class="question-head">
            <span class="q-index">第 {{ index + 1 }} 题</span>
            <el-tag size="small" type="warning" effect="plain">{{ question.score }} 分</el-tag>
            <el-tag size="small" type="info" effect="plain">{{ question.qtype }}</el-tag>
          </div>
          <div class="q-stem rendered-md" v-html="render(question.stem)"></div>
          <el-checkbox-group
            v-if="question.options?.length && isMulti(question)"
            v-model="examAnswers[question.question_id]"
            :disabled="!!examResult"
            class="q-options"
          >
            <el-checkbox
              v-for="option in question.options"
              :key="option"
              :value="letterOf(option)"
              class="q-option"
            >
              {{ option }}
            </el-checkbox>
          </el-checkbox-group>
          <el-radio-group
            v-else-if="question.options?.length"
            v-model="examAnswers[question.question_id]"
            :disabled="!!examResult"
            class="q-options"
          >
            <el-radio
              v-for="option in question.options"
              :key="option"
              :value="letterOf(option)"
              class="q-option"
            >
              {{ option }}
            </el-radio>
          </el-radio-group>
          <el-input
            v-else
            v-model="examAnswers[question.question_id]"
            :disabled="!!examResult"
            placeholder="填写答案"
            style="max-width: 420px"
          />

          <!-- 交卷后逐题回看 -->
          <el-alert
            v-if="itemResult(question.question_id)"
            :type="itemResult(question.question_id).is_correct ? 'success' : 'error'"
            :closable="false"
            show-icon
            style="margin-top: 8px"
          >
            <template #title>
              得 {{ itemResult(question.question_id).earned }} / {{ itemResult(question.question_id).score }} 分
              <span class="feedback-answer">
                正确答案：{{ itemResult(question.question_id).correct_answer || '（无）' }}
              </span>
            </template>
            <div
              v-if="itemResult(question.question_id).analysis"
              class="rendered-md"
              v-html="render(itemResult(question.question_id).analysis)"
            ></div>
          </el-alert>
        </div>

        <div v-if="exam.questions?.length && !examResult" class="exam-submit">
          <el-button type="primary" :loading="submitting === 'exam'" @click="submitPaper">交卷</el-button>
          <span class="exam-tip">未作答的题按错处理 —— 跳过就是没拿到分，画像理应反映这一点</span>
        </div>

        <el-alert
          v-if="examResult"
          type="success"
          :closable="false"
          show-icon
          :title="`得分 ${examResult.score} / ${examResult.total_score}，答对 ${examResult.correct_count} / ${examResult.question_count} 题`"
          description="试卷是「测量」不是「训练」，因此本次作答不会改变自适应练习的难度档。"
          style="margin-top: 12px"
        />
      </template>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { marked } from 'marked'

import { getExam, getPractice, listKnowledgePoints, submitAnswer, submitExam } from '@/api/learn'
import { authState } from '@/store/user'

const route = useRoute()
const router = useRouter()

const mode = ref('practice')
const loading = ref(false)
const submitting = ref(null)
const nodes = ref([])
const kpId = ref(null)
const count = ref(5)
const questions = ref([])
const answers = reactive({})
const results = reactive({})
const meta = reactive({ difficulty: null, promote_streak: 3, streak_correct: 0 })
const emptyMessage = ref('')

const exam = ref({})
const examAnswers = reactive({})
const examResult = ref(null)

const isStudent = computed(() => authState.user?.role === 'student')
const streak = computed(() => {
  const last = Object.values(results).pop()
  return last?.streak_correct ?? meta.streak_correct
})

const DIFF_TAGS = { 简单: 'success', 中等: 'warning', 困难: 'danger' }
const difficultyTag = (difficulty) => DIFF_TAGS[difficulty] ?? 'info'

function render(text) {
  if (!text) return ''
  try {
    return marked.parse(String(text), { breaks: true })
  } catch {
    return String(text)
  }
}

// "A. 链式法则" → "A"。后端判分两种写法都认，这里统一取字母，避免同一题出现两种答案格式
function letterOf(option) {
  const matched = String(option).match(/^([a-zA-Z0-9])[.、．)）:：]/)
  return matched ? matched[1].toUpperCase() : option
}

// 多选题必须用多选框：它的正确答案形如 "ABC"，用单选控件无论怎么选都选中不了第二个字母，
// 学生会一直被判错——而判错会写进画像、拉低掌握度、改推荐路径，等于把演示数据污染成假的。
// 判据用 qtype（题目自带的类型字段），不靠猜。
function isMulti(question) {
  return question?.qtype === '多选'
}

// 答案归一：多选在界面上是数组，提交前拼成 "ABC"（后端按集合比较，"CBA" 同样判对，排序只为日志好看）
function collect(value) {
  if (Array.isArray(value)) return value.length ? [...value].sort().join('') : null
  return value || null
}

// 多选的 v-model 必须是数组，undefined 会让多选框组拿不到初值
function initAnswerSlots(store, list) {
  ;(list || []).forEach((question) => {
    if (isMulti(question)) store[question.question_id] = []
  })
}

function resetFeedback() {
  Object.keys(answers).forEach((key) => delete answers[key])
  Object.keys(results).forEach((key) => delete results[key])
}

async function loadNodes() {
  try {
    const data = await listKnowledgePoints()
    nodes.value = data.items || []
  } catch {
    /* 拦截器已提示 */
  }
}

async function loadPractice() {
  loading.value = true
  emptyMessage.value = ''
  resetFeedback()
  try {
    const params = { count: count.value }
    if (kpId.value) params.kp_id = kpId.value
    const data = await getPractice(params)
    questions.value = data.questions || []
    initAnswerSlots(answers, questions.value)
    meta.difficulty = data.difficulty || null
    meta.promote_streak = data.promote_streak || 3
    meta.streak_correct = data.streak_correct || 0
    if (!questions.value.length) {
      emptyMessage.value = data.message || '没有取到题目'
    } else if (data.kp_name) {
      kpId.value = data.kp_id
    }
  } catch {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}

async function submitOne(question) {
  submitting.value = question.question_id
  try {
    const data = await submitAnswer({
      question_id: question.question_id,
      user_answer: collect(answers[question.question_id]),
    })
    results[question.question_id] = data
    meta.difficulty = data.difficulty || meta.difficulty
    if (data.mistake_id) {
      ElMessage.warning('答错了，已收进错题本，可点「查看 AI 错题分析」')
    }
  } catch {
    /* 拦截器已提示 */
  } finally {
    submitting.value = null
  }
}

async function loadExam() {
  loading.value = true
  emptyMessage.value = ''
  examResult.value = null
  Object.keys(examAnswers).forEach((key) => delete examAnswers[key])
  try {
    const data = await getExam({})
    exam.value = data
    initAnswerSlots(examAnswers, data.questions)
    if (!data.questions?.length) {
      emptyMessage.value = data.message || '还没有可用的试卷'
    }
  } catch {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}

function itemResult(questionId) {
  return examResult.value?.items?.find((item) => item.question_id === questionId)
}

async function submitPaper() {
  if (!exam.value.plan_id) return
  submitting.value = 'exam'
  try {
    const data = await submitExam({
      plan_id: exam.value.plan_id,
      answers: (exam.value.questions || []).map((question) => ({
        question_id: question.question_id,
        user_answer: collect(examAnswers[question.question_id]),
      })),
    })
    examResult.value = data
    ElMessage.success(`交卷完成：${data.score} / ${data.total_score} 分`)
  } catch {
    /* 拦截器已提示 */
  } finally {
    submitting.value = null
  }
}

function goMistake(mistakeId) {
  router.push({ path: '/learn/mistakes', query: { id: mistakeId } })
}

function onModeChange() {
  emptyMessage.value = ''
  if (mode.value === 'exam' && !exam.value.plan_id) {
    loadExam()
  }
}

onMounted(() => {
  if (!isStudent.value) {
    emptyMessage.value = '学生账号才能作答。教师可到「学习路径」页做知识点治理。'
    return
  }
  loadNodes()
  const preset = Number(route.query.kp_id)
  if (preset) kpId.value = preset
  loadPractice()
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

.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.question-block {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 12px 14px;
  margin-bottom: 14px;
}

.question-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.q-index {
  font-weight: 600;
  color: #409eff;
}

.q-stem {
  color: #303133;
  margin-bottom: 10px;
}

.q-stem :deep(p) {
  margin: 4px 0;
}

.q-options {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
}

.q-option {
  height: auto;
  white-space: normal;
}

/* 多选框组也用 .q-options 排成竖列，去掉 EP 默认的右外边距免得对不齐 */
.q-options :deep(.el-checkbox) {
  margin-right: 0;
}

.q-actions {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.feedback-answer {
  margin-left: 12px;
  color: #606266;
  font-weight: 400;
}

.feedback-mastery {
  margin-left: 12px;
  color: #909399;
  font-weight: 400;
  font-size: 12px;
}

.exam-title {
  font-weight: 600;
  color: #303133;
}

.exam-submit {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
}

.exam-tip {
  color: #909399;
  font-size: 12px;
}
</style>
