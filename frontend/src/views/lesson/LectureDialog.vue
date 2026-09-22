<!-- [工单21] 人工智能NLP-Agent数字人项目-教育智能体-虚拟教室/讲课页 —— 「生成讲课视频」弹层 -->
<template>
  <el-dialog
    v-model="visible"
    title="生成讲课视频"
    width="720px"
    :close-on-click-modal="!submitting"
    @open="onOpen"
  >
    <div v-loading="drafting" class="lc-body">
      <template v-if="!job">
        <el-alert type="info" :closable="false" show-icon style="margin-bottom: 14px">
          从备课内容（教案正文 / 课件页面与讲稿备注）预填课件页与讲稿，可编辑后提交。生成走 CPU 离线管线，
          一段讲稿约几十秒，整课需数分钟——提交后本弹窗会显示进度。
        </el-alert>

        <el-form label-width="64px" size="default">
          <el-row :gutter="12">
            <el-col :span="14">
              <el-form-item label="课程名">
                <el-input v-model="form.title" maxlength="60" />
              </el-form-item>
            </el-col>
            <el-col :span="10">
              <el-form-item label="学科">
                <el-input v-model="form.subject" maxlength="40" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="形象">
            <el-select v-model="form.avatar" style="width: 240px">
              <el-option
                v-for="f in avatarOptions"
                :key="f.id"
                :label="`${f.name} · ${f.desc}`"
                :value="f.id"
              />
            </el-select>
          </el-form-item>
        </el-form>

        <div class="lc-section-title">课件页与讲稿</div>
        <div v-for="(seg, i) in form.segments" :key="i" class="lc-seg">
          <div class="lc-seg-head">
            <span class="lc-seg-index">段 {{ i + 1 }}</span>
            <el-select v-model="seg.page" size="small" style="width: 130px">
              <el-option
                v-for="p in form.pages"
                :key="p.__key"
                :label="`页${p.__page}：${p.title.slice(0, 12)}`"
                :value="p.__page"
              />
            </el-select>
            <el-button size="small" text type="danger" @click="form.segments.splice(i, 1)">删除</el-button>
          </div>
          <el-input
            v-model="seg.text"
            type="textarea"
            :rows="3"
            maxlength="2000"
            show-word-limit
            placeholder="这一段的讲稿，数字人会照着念"
          />
        </div>
        <el-button size="small" @click="addSegment">＋ 加一段讲稿</el-button>
      </template>

      <template v-else>
        <div class="lc-progress">
          <el-progress
            :percentage="job.progress"
            :status="job.status === 'error' ? 'exception' : job.status === 'done' ? 'success' : undefined"
          />
          <div class="lc-progress-msg">
            <template v-if="job.status === 'running'">⏳ {{ job.message }}（生成期间请保持本窗口开启）</template>
            <template v-else-if="job.status === 'done'">✅ 讲课视频已生成，去「虚拟教室」观看</template>
            <template v-else>❌ 生成失败：{{ job.error }}</template>
          </div>
          <el-button v-if="job.status === 'done'" type="primary" @click="goRoom">去虚拟教室</el-button>
        </div>
      </template>
    </div>

    <template #footer>
      <template v-if="!job">
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" :disabled="!canSubmit" @click="handleSubmit">
          提交生成
        </el-button>
      </template>
      <el-button v-else :disabled="job.status === 'running'" @click="reset">关 闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
// 成课弹层：draft 预填 → 编辑 → generate → 轮询 job 进度。仅教师入口（Plans.vue 按 content_type 显示）。
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { draftLecture, generateLecture, getLectureJob } from '@/api/lecture'
import { FACES } from '@/avatar/faces'

const props = defineProps({ plan: { type: Object, default: null } })
const visible = defineModel({ type: Boolean, default: false })
const router = useRouter()

const avatarOptions = FACES.filter((f) => f.render === 'photo')
const drafting = ref(false)
const submitting = ref(false)
const job = ref(null)
const form = ref(emptyForm())

function emptyForm() {
  return { title: '', subject: '', avatar: 'xiaowen', pages: [], segments: [] }
}

async function onOpen() {
  job.value = null
  if (!props.plan) return
  form.value = emptyForm()
  drafting.value = true
  try {
    const d = await draftLecture(props.plan.id)
    // __key/__page：pages 需要稳定 key 与连续页码（弹层内编辑用，提交前剥掉）
    form.value = {
      title: d.title || '',
      subject: d.subject || '',
      avatar: 'xiaowen',
      pages: d.pages.map((p, i) => ({ ...p, __key: i + 1, __page: i + 1 })),
      segments: d.segments.map((s) => ({ ...s })),
    }
  } catch {
    visible.value = false
  } finally {
    drafting.value = false
  }
}

function addSegment() {
  const last = form.value.segments.at(-1)
  form.value.segments.push({ page: last?.page ?? 1, text: '' })
}

const canSubmit = computed(
  () =>
    form.value.title.trim() &&
    form.value.pages.length > 0 &&
    form.value.segments.length > 0 &&
    form.value.segments.every((s) => s.text.trim()),
)

async function handleSubmit() {
  submitting.value = true
  try {
    const spec = {
      plan_id: props.plan?.id ?? null,
      title: form.value.title.trim(),
      subject: form.value.subject.trim(),
      avatar: form.value.avatar,
      pages: form.value.pages.map((p) => ({ title: p.title, body: p.body })),
      segments: form.value.segments.map((s) => ({ page: s.page, text: s.text.trim() })),
    }
    job.value = await generateLecture(spec)
    poll()
  } finally {
    submitting.value = false
  }
}

function poll() {
  const timer = setInterval(async () => {
    try {
      const j = await getLectureJob(job.value.job_id)
      job.value = j
      if (j.status !== 'running') clearInterval(timer)
    } catch {
      clearInterval(timer)
    }
  }, 2500)
}

function reset() {
  visible.value = false
  job.value = null
}

function goRoom() {
  reset()
  router.push('/lecture')
}
</script>

<style scoped>
.lc-body {
  max-height: 60vh;
  overflow: auto;
}
.lc-section-title {
  font-weight: 600;
  margin: 4px 0 10px;
}
.lc-seg {
  margin-bottom: 14px;
}
.lc-seg-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}
.lc-seg-index {
  font-size: 13px;
  color: #909399;
}
.lc-progress {
  display: flex;
  flex-direction: column;
  gap: 14px;
  align-items: center;
  padding: 24px 8px;
}
.lc-progress-msg {
  color: #606266;
  font-size: 14px;
}
</style>
