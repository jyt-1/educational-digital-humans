<!-- [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 生成页（SSE 流式） -->
<template>
  <el-row :gutter="16">
    <!-- 左：生成参数 -->
    <el-col :span="9">
      <div class="page-card">
        <h3 style="margin-top: 0">生成参数</h3>
        <el-form :model="form" label-width="90px" size="default">
          <el-form-item label="内容类型">
            <el-select v-model="form.content_type" style="width: 100%">
              <el-option v-for="t in CONTENT_TYPES" :key="t" :label="t" :value="t" />
            </el-select>
          </el-form-item>

          <el-form-item label="课程名">
            <el-input v-model="form.course_name" placeholder="如：人工智能导论" />
          </el-form-item>

          <el-form-item label="学科/专业">
            <el-input v-model="form.subject" placeholder="如：人工智能" />
          </el-form-item>

          <el-form-item label="章节">
            <el-input v-model="form.chapter" placeholder="如：第3章 神经网络" />
          </el-form-item>

          <el-form-item label="知识点">
            <el-select
              v-model="form.knowledge_points"
              multiple
              filterable
              allow-create
              default-first-option
              placeholder="输入后回车添加，可多个"
              style="width: 100%"
            >
              <el-option
                v-for="kp in COMMON_KPS"
                :key="kp"
                :label="kp"
                :value="kp"
              />
            </el-select>
          </el-form-item>

          <el-form-item label="难度">
            <el-radio-group v-model="form.difficulty">
              <el-radio-button value="简单">简单</el-radio-button>
              <el-radio-button value="中等">中等</el-radio-button>
              <el-radio-button value="困难">困难</el-radio-button>
            </el-radio-group>
          </el-form-item>

          <el-form-item label="绑定班级">
            <el-select
              v-model="form.class_id"
              clearable
              placeholder="不绑定则不使用学情"
              style="width: 100%"
              @change="loadClassPreview"
            >
              <el-option
                v-for="item in classes"
                :key="item.id"
                :label="`${item.name}（${item.student_count} 人）`"
                :value="item.id"
              />
            </el-select>
            <div v-if="classBrief" class="class-brief">
              <div class="class-brief-head">将注入模型的学情（可核对）</div>
              <pre>{{ classBrief }}</pre>
            </div>
            <div v-else-if="form.class_id" class="class-brief-empty">
              该班暂无作答数据，生成时不会注入学情。
            </div>
          </el-form-item>

          <el-form-item label="教学目标">
            <el-select
              v-model="form.objectives"
              multiple
              filterable
              allow-create
              default-first-option
              placeholder="输入后回车添加"
              style="width: 100%"
            />
          </el-form-item>

          <el-form-item label="补充要求">
            <el-input
              v-model="form.extra"
              type="textarea"
              :rows="2"
              placeholder="选填，如：多举企业实战例子"
            />
          </el-form-item>

          <el-form-item>
            <el-button
              type="primary"
              :loading="generating"
              :disabled="generating"
              @click="handleGenerate"
            >
              {{ generating ? '生成中…' : '开始生成' }}
            </el-button>
            <el-button v-if="generating" @click="handleAbort">中断</el-button>
          </el-form-item>
        </el-form>
      </div>
    </el-col>

    <!-- 右：流式渲染 -->
    <el-col :span="15">
      <div class="page-card">
        <div style="display: flex; justify-content: space-between; align-items: center">
          <h3 style="margin: 0">生成结果</h3>
          <div>
            <el-tag v-if="status === 'streaming'" type="warning" size="small">流式中</el-tag>
            <el-tag v-else-if="status === 'done'" type="success" size="small">已完成</el-tag>
            <el-tag v-else-if="status === 'error'" type="danger" size="small">失败</el-tag>
            <el-tag v-else type="info" size="small">待生成</el-tag>
            <span v-if="charCount" style="margin-left: 10px; color: #909399; font-size: 12px">
              {{ charCount }} 字
            </span>
          </div>
        </div>

        <el-alert
          v-if="status === 'error'"
          type="error"
          :closable="false"
          style="margin: 12px 0"
          :title="errorMsg"
        />

        <el-alert
          v-if="status === 'done'"
          type="success"
          :closable="false"
          style="margin: 12px 0"
          :title="doneMsg"
        />

        <div ref="streamBox" class="stream-box" style="margin-top: 12px">
          {{ streamText || emptyHint }}
        </div>

        <div v-if="planId" style="margin-top: 12px">
          <el-button type="primary" @click="goEdit">进入编辑与导出</el-button>
          <el-button @click="reset">再生成一个</el-button>
        </div>
      </div>
    </el-col>
  </el-row>
</template>

<script setup>
import { ElMessage } from 'element-plus'
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { streamGenerate } from '@/api/lesson'
import { getInsight, listClasses } from '@/api/teach'
import { isTeacher } from '@/store/user'

const route = useRoute()
const router = useRouter()

const CONTENT_TYPES = ['教案', '课件', '习题', '案例', '试题']

// 常用知识点快捷选项（可自由输入，仅作提示）
const COMMON_KPS = [
  '矩阵运算',
  '神经网络',
  '反向传播',
  '梯度下降',
  '激活函数',
  '损失函数',
  '过拟合',
  '卷积神经网络',
  '循环神经网络',
  '注意力机制',
  'Transformer',
]

const form = reactive({
  content_type: '教案',
  course_name: '人工智能导论',
  subject: '人工智能',
  chapter: '',
  knowledge_points: [],
  difficulty: '中等',
  objectives: [],
  extra: '',
  class_id: null,
})

const classes = ref([])
const classBrief = ref('')

async function loadClasses() {
  if (!isTeacher()) return
  try {
    const data = await listClasses()
    classes.value = data.items || []
  } catch {
    /* 拦截器已提示 */
  }
}

async function loadClassPreview() {
  if (!form.class_id) {
    classBrief.value = ''
    return
  }
  try {
    const data = await getInsight(form.class_id, { top_n: 6 })
    classBrief.value = data.brief || ''
  } catch {
    classBrief.value = ''
  }
}

const generating = ref(false)
const status = ref('idle') // idle | streaming | done | error
const streamText = ref('')
const errorMsg = ref('')
const planId = ref(null)
const doneMsg = ref('')
const streamBox = ref(null)
let controller = null

const charCount = computed(() => streamText.value.length)
const emptyHint = computed(() =>
  status.value === 'idle' ? '填写左侧参数后点击「开始生成」，内容将在此逐字流式显示。' : '',
)

async function handleGenerate() {
  if (!form.course_name) {
    ElMessage.warning('请填写课程名')
    return
  }

  generating.value = true
  status.value = 'streaming'
  streamText.value = ''
  errorMsg.value = ''
  doneMsg.value = ''
  planId.value = null
  controller = new AbortController()

  try {
    const { done, error } = await streamGenerate(
      { ...form },
      {
        signal: controller.signal,
        onEvent: (event, data) => {
          if (event === 'delta') {
            streamText.value += data.text
            scrollToBottom()
          } else if (event === 'error') {
            status.value = 'error'
            errorMsg.value = data.msg
          }
        },
      },
    )

    if (error) {
      status.value = 'error'
      errorMsg.value = error.msg
    } else if (done) {
      status.value = 'done'
      planId.value = done.plan_id
      doneMsg.value =
        `《${done.title}》生成完成，已保存为版本 v${done.version}` +
        (done.question_count ? `，共 ${done.question_count} 道题目已入库` : '')
      ElMessage.success('生成完成')
    }
  } catch (err) {
    if (err.name === 'AbortError') {
      status.value = 'idle'
      ElMessage.info('已中断生成')
    } else {
      status.value = 'error'
      errorMsg.value = err.message || '生成失败'
    }
  } finally {
    generating.value = false
    controller = null
  }
}

function handleAbort() {
  controller?.abort()
}

function scrollToBottom() {
  nextTick(() => {
    const box = streamBox.value
    if (box) box.scrollTop = box.scrollHeight
  })
}

function goEdit() {
  router.push({ name: 'lesson-edit', params: { id: planId.value } })
}

function reset() {
  status.value = 'idle'
  streamText.value = ''
  planId.value = null
  doneMsg.value = ''
  errorMsg.value = ''
}

onMounted(async () => {
  await loadClasses()
  // 看板「按学情备课」跳转过来时预选班级，省掉教师再选一次
  const fromQuery = Number(route.query.class_id)
  if (fromQuery && classes.value.some((item) => item.id === fromQuery)) {
    form.class_id = fromQuery
    await loadClassPreview()
  }
})
</script>
