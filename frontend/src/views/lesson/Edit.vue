<!-- [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 备课详情：在线编辑 / 版本回溯 / 导出 -->
<template>
  <div v-loading="loading">
    <div class="page-card">
      <div style="display: flex; justify-content: space-between; align-items: flex-start">
        <div>
          <h3 style="margin: 0 0 6px">{{ plan.title || plan.course_name }}</h3>
          <div style="color: #909399; font-size: 13px">
            <el-tag size="small">{{ plan.content_type }}</el-tag>
            <span style="margin-left: 8px">{{ metaLine }}</span>
            <span style="margin-left: 8px">当前版本 v{{ plan.current_version }}</span>
          </div>
        </div>
        <div>
          <el-button @click="$router.back()">返回</el-button>
          <el-button type="primary" :loading="saving" :disabled="!dirty" @click="handleSave">
            {{ dirty ? '保存（生成新版本）' : '已保存' }}
          </el-button>
          <el-dropdown style="margin-left: 12px" @command="handleExport">
            <el-button type="success">导出 ▾</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="docx">导出 docx</el-dropdown-item>
                <el-dropdown-item v-if="plan.content_type === '课件'" command="pptx">
                  导出 pptx
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
    </div>

    <el-row :gutter="16">
      <!-- 左：编辑器 -->
      <el-col :span="17">
        <div class="page-card">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px">
            <h4 style="margin: 0">
              {{ editorTitle }}
              <span v-if="dirty" style="color: #e6a23c; font-size: 12px; margin-left: 6px">
                ● 有未保存的修改
              </span>
            </h4>
            <el-radio-group v-model="viewMode" size="small">
              <el-radio-button value="edit">编辑</el-radio-button>
              <el-radio-button value="preview">预览</el-radio-button>
            </el-radio-group>
          </div>

          <!-- 教案 / 案例：Markdown 正文 -->
          <template v-if="isTextType">
            <el-input
              v-if="viewMode === 'edit'"
              v-model="content.raw"
              type="textarea"
              :rows="22"
              placeholder="教案正文（Markdown）"
              @input="dirty = true"
            />
            <!-- eslint-disable-next-line vue/no-v-html -- 预览内容来自本平台 LLM 生成并经教师确认 -->
            <div v-else class="rendered-md" v-html="renderedRaw" />
          </template>

          <!-- 课件：幻灯片逐页编辑 -->
          <template v-else-if="isSlideType">
            <el-empty v-if="!content.items.length" description="该课件没有幻灯片" />
            <div v-for="(slide, i) in content.items" :key="i" class="slide-card">
              <div class="slide-head">
                <span>第 {{ i + 1 }} 页</span>
                <el-button
                  link
                  type="danger"
                  size="small"
                  @click="removeSlide(i)"
                >
                  删除本页
                </el-button>
              </div>
              <el-input
                v-model="slide.title"
                placeholder="页面标题"
                style="margin-bottom: 8px"
                @input="dirty = true"
              />
              <el-input
                v-model="slide.bulletsText"
                type="textarea"
                :rows="4"
                placeholder="要点，每行一条"
                @input="syncBullets(slide)"
              />
              <el-input
                v-model="slide.notes"
                type="textarea"
                :rows="2"
                placeholder="讲稿备注（导出 pptx 时写入备注区，不上幻灯片）"
                style="margin-top: 8px"
                @input="dirty = true"
              />
            </div>
            <el-button style="margin-top: 8px" @click="addSlide">＋ 新增一页</el-button>
          </template>

          <!-- 习题 / 试题：结构化编辑 -->
          <template v-else>
            <el-alert type="info" :closable="false" style="margin-bottom: 12px">
              <template #title>
                <span style="font-size: 12px">
                  共 <strong>{{ content.items.length }}</strong> 道题。
                  保存时会同步刷新题目表，工单19 自适应练习抽取的就是这里的题目。
                </span>
              </template>
            </el-alert>
            <QuestionEditor :items="content.items" @change="dirty = true" />
          </template>
        </div>
      </el-col>

      <!-- 右：版本历史 -->
      <el-col :span="7">
        <div class="page-card">
          <h4 style="margin-top: 0">版本历史</h4>
          <el-timeline>
            <el-timeline-item
              v-for="v in versions"
              :key="v.id"
              :timestamp="formatTime(v.created_at)"
              placement="top"
              :type="v.version_no === plan.current_version ? 'primary' : ''"
              :hollow="v.version_no !== plan.current_version"
            >
              <div style="display: flex; justify-content: space-between; align-items: center">
                <div>
                  <strong>v{{ v.version_no }}</strong>
                  <el-tag
                    v-if="v.version_no === plan.current_version"
                    size="small"
                    type="success"
                    style="margin-left: 6px"
                  >
                    当前
                  </el-tag>
                  <div style="color: #909399; font-size: 12px">{{ v.remark || '—' }}</div>
                </div>
                <el-button
                  v-if="v.version_no !== plan.current_version"
                  link
                  type="primary"
                  size="small"
                  :loading="rollingBack === v.id"
                  @click="handleRollback(v)"
                >
                  回滚到此版本
                </el-button>
              </div>
            </el-timeline-item>
          </el-timeline>
          <el-empty v-if="!versions.length" description="暂无版本" :image-size="60" />
          <el-alert type="info" :closable="false" style="margin-top: 8px">
            <template #title>
              <span style="font-size: 12px">
                回滚不会删除历史：系统会把所选版本的内容<strong>追加</strong>为一个新版本。
              </span>
            </template>
          </el-alert>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'
import { marked } from 'marked'
import { useRoute, useRouter } from 'vue-router'

import {
  downloadExport,
  getPlan,
  listVersions,
  rollbackVersion,
  updatePlan,
} from '@/api/lesson'
import QuestionEditor from '@/components/QuestionEditor.vue'

const route = useRoute()
const router = useRouter()
const planId = Number(route.params.id)

const loading = ref(false)
const saving = ref(false)
const dirty = ref(false)
const rollingBack = ref(0)
const viewMode = ref('edit')

const plan = reactive({
  id: null,
  title: '',
  content_type: '',
  course_name: '',
  subject: '',
  chapter: '',
  difficulty: '',
  current_version: 0,
})

// 统一内容结构：{ format, raw: string, items: [] }
// format 由后端 build_content_payload 写入（markdown|json），保存时必须原样带回，否则会丢
const content = reactive({ format: '', raw: '', items: [] })
const versions = ref([])

const isTextType = computed(() => ['教案', '案例'].includes(plan.content_type))
const isSlideType = computed(() => plan.content_type === '课件')

const editorTitle = computed(() => {
  if (plan.content_type === '案例') return '案例正文（Markdown）'
  if (isTextType.value) return '教案正文（Markdown）'
  if (isSlideType.value) return '课件页面'
  return '题目列表'
})

const metaLine = computed(
  () =>
    [plan.subject, plan.course_name, plan.chapter, plan.difficulty].filter(Boolean).join(' · ') ||
    '—',
)

const renderedRaw = computed(() => marked.parse(content.raw || ''))

/** 幻灯片要点：编辑时用「每行一条」的文本，保存前拆回数组 */
function bulletsToText(bullets) {
  return Array.isArray(bullets) ? bullets.join('\n') : String(bullets || '')
}

function syncBullets(slide) {
  slide.bullets = slide.bulletsText
    .split('\n')
    .map((s) => s.trim().replace(/^[-•*]\s*/, ''))
    .filter(Boolean)
  dirty.value = true
}

function addSlide() {
  content.items.push({ title: '新页面', bullets: [], bulletsText: '', notes: '' })
  dirty.value = true
}

function removeSlide(index) {
  content.items.splice(index, 1)
  dirty.value = true
}

function formatTime(value) {
  if (!value) return '-'
  return String(value).replace('T', ' ').slice(0, 16)
}

/** 把后端返回的 content 装配进可编辑状态。加载详情与版本回滚共用。 */
function applyContent(payload) {
  const data = typeof payload === 'string' ? { raw: payload } : payload || {}
  content.format = data.format || ''
  content.raw = data.raw || ''
  content.items = (data.items || []).map((item) => ({
    ...item,
    bulletsText: bulletsToText(item.bullets), // 幻灯片要点：编辑态用「每行一条」
    notes: item.notes || '',
  }))
}

async function load() {
  loading.value = true
  try {
    const detail = await getPlan(planId)
    Object.assign(plan, {
      id: detail.id,
      title: detail.title,
      content_type: detail.content_type,
      course_name: detail.course_name,
      subject: detail.subject,
      chapter: detail.chapter,
      difficulty: detail.difficulty,
      current_version: detail.current_version,
    })

    applyContent(detail.content)

    versions.value = await listVersions(planId)
    dirty.value = false
  } catch {
    ElMessage.error('加载备课详情失败')
    router.replace({ name: 'lesson-plans' })
  } finally {
    loading.value = false
  }
}

async function handleSave() {
  saving.value = true
  try {
    // 幻灯片把 bulletsText 拆好的数组提交，不把编辑用的临时字段带进库
    const items = content.items.map(({ bulletsText, ...rest }) => rest)
    const detail = await updatePlan(
      planId,
      { format: content.format, raw: content.raw, items },
      '教师手动编辑',
    )
    Object.assign(plan, { current_version: detail.current_version })
    versions.value = await listVersions(planId)
    dirty.value = false
    ElMessage.success(`已保存为 v${detail.current_version}`)
  } catch {
    /* 提示已由拦截器处理 */
  } finally {
    saving.value = false
  }
}

async function handleRollback(version) {
  try {
    await ElMessageBox.confirm(
      `确认回滚到 v${version.version_no}？当前内容会被该版本覆盖，历史版本仍保留。`,
      '版本回滚',
      { type: 'warning', confirmButtonText: '确认回滚', cancelButtonText: '取消' },
    )
  } catch {
    return
  }

  rollingBack.value = version.id
  try {
    const detail = await rollbackVersion(planId, version.id)
    Object.assign(plan, { current_version: detail.current_version })
    applyContent(detail.content)
    versions.value = await listVersions(planId)
    dirty.value = false
    ElMessage.success(`已回滚，生成新版本 v${detail.current_version}`)
  } catch {
    /* 提示已由拦截器处理 */
  } finally {
    rollingBack.value = 0
  }
}

async function handleExport(format) {
  if (dirty.value) {
    ElMessage.warning('有未保存的修改，请先保存再导出（导出的是已入库版本）')
    return
  }
  try {
    const filename = await downloadExport(planId, format)
    ElMessage.success(`已导出 ${filename}`)
  } catch (err) {
    ElMessage.error(err.message || '导出失败')
  }
}

onMounted(load)
</script>

<style scoped>
.slide-card {
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 12px;
  margin-bottom: 12px;
  background: #fafafa;
}

.slide-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: #606266;
  font-size: 13px;
  margin-bottom: 8px;
}

</style>
