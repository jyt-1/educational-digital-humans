<!-- [工单21] 人工智能NLP-Agent数字人项目-教育智能体-虚拟教室/讲课页 —— 课件+数字人讲课视频联动（离线 Wav2Lip 管线产物） -->
<template>
  <div class="lecture-room" :class="{ 'is-studio': isStudio }" v-loading="loading">
    <template v-if="course">
      <div class="lr-courseware">
        <div class="lr-course-head">
          <el-select
            v-model="currentId"
            style="width: 260px"
            @change="onCourseChange"
          >
            <el-option v-for="c in courses" :key="c.courseId" :label="c.title" :value="c.courseId" />
          </el-select>
          <el-tag size="small" type="info" effect="plain">{{ course.subject }}</el-tag>
          <el-tag v-if="isStudio" size="small" effect="plain" type="success">演播室版</el-tag>
        </div>

        <div class="lr-page-card">
          <h2 class="lr-page-title">{{ pages[activePage]?.title }}</h2>
          <div class="lr-page-body" v-html="renderedBodies[activePage]"></div>
          <div v-if="pages[activePage]?.note" class="lr-page-note">
            <el-icon><InfoFilled /></el-icon>{{ pages[activePage].note }}
          </div>
        </div>

        <div class="lr-page-dots">
          <button
            v-for="(p, i) in pages"
            :key="i"
            class="lr-dot"
            :class="{ active: i === activePage }"
            @click="jumpToPage(i)"
          >{{ i + 1 }}</button>
        </div>
      </div>

      <div class="lr-stage">
        <div class="lr-video-card">
          <video
            ref="videoRef"
            class="lr-video"
            :src="videoSrc"
            preload="auto"
            playsinline
            @timeupdate="onTimeUpdate"
            @ended="playing = false"
            @play="playing = true"
            @pause="playing = false"
            @error="onVideoError"
          ></video>
          <div v-if="videoError" class="lr-video-fallback">
            视频未生成：请先在 wav2lip/ 下运行 gen_lecture.py
          </div>
        </div>

        <div class="lr-subtitle" v-if="currentSeg && !isStudio">{{ currentSeg.text }}</div>

        <div class="lr-controls">
          <el-button
            type="primary"
            circle
            :icon="playing ? VideoPause : VideoPlay"
            @click="togglePlay"
          />
          <el-slider
            v-model="progress"
            :max="duration || 1"
            :step="0.1"
            :format-tooltip="(v) => fmt(v)"
            style="flex: 1"
            @change="onSeek"
          />
          <span class="lr-time">{{ fmt(progress) }} / {{ fmt(duration) }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
// [工单21] 讲稿引擎：video.timeupdate → 命中 timeline 段 → 翻课件页 + 同步字幕；点页码可跳转视频
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { InfoFilled, VideoPause, VideoPlay } from '@element-plus/icons-vue'
import katex from 'katex'
import 'katex/dist/katex.min.css'

import { listLectureCourses } from '@/api/lecture'

// 多课程：列表来自 GET /api/lecture/courses（内置静态课 + 教师成课产物），base 决定资源前缀
const loading = ref(true)
const courses = ref([])
const currentId = ref('')
const course = ref(null)
const timeline = ref([])
const videoRef = ref(null)
const playing = ref(false)
const progress = ref(0)
const duration = ref(0)
const videoError = ref(false)
const activePage = ref(0)
const currentIdx = ref(-1)

const currentCourse = computed(() => courses.value.find((c) => c.courseId === currentId.value))
// 演播室版式（video-studio.mp4，compose_studio.py 产物）优先；加载失败自动回退原始 video.mp4
const studioFallback = ref(false)
const isStudio = computed(() => !!currentCourse.value?.studio && !studioFallback.value)
const videoSrc = computed(() => {
  if (!currentCourse.value) return ''
  return isStudio.value
    ? `${currentCourse.value.base}/video-studio.mp4`
    : `${currentCourse.value.base}/video.mp4`
})

function onVideoError() {
  if (isStudio.value) {
    studioFallback.value = true
    videoError.value = false
  } else {
    videoError.value = true
  }
}

const pages = computed(() => course.value?.pages || [])
const currentSeg = computed(() => timeline.value[currentIdx.value] || null)

// ---- 渲染：先替换 $...$ 为 KaTeX HTML，再交给 marked（保留内联 HTML） ----
function renderBody(raw) {
  if (!window.__marked) return ''
  const withTex = String(raw || '').replace(/\$([^$]+)\$/g, (_, tex) => {
    try {
      return katex.renderToString(tex.trim(), { throwOnError: false, displayMode: false })
    } catch {
      return tex
    }
  })
  return window.__marked.parse(withTex)
}

const renderedBodies = computed(() => pages.value.map((p) => renderBody(p.body)))

function resetPlayer() {
  progress.value = 0
  duration.value = 0
  currentIdx.value = -1
  activePage.value = 0
  playing.value = false
  videoError.value = false
  studioFallback.value = false
}

async function onCourseChange() {
  videoRef.value?.pause()
  await load()
}

async function load() {
  const c = currentCourse.value
  if (!c) {
    videoError.value = true
    loading.value = false
    return
  }
  loading.value = true
  resetPlayer()
  try {
    const [cc, t] = await Promise.all([
      fetch(`${c.base}/course.json`).then((r) => (r.ok ? r.json() : Promise.reject(r.status))),
      fetch(`${c.base}/timeline.json`).then((r) => (r.ok ? r.json() : Promise.reject(r.status))),
    ])
    course.value = cc
    timeline.value = t
  } catch (e) {
    course.value = null
    timeline.value = []
    videoError.value = true
    ElMessage.warning('课程数据加载失败')
  } finally {
    loading.value = false
  }
}

function segIndexAt(t) {
  const list = timeline.value
  for (let i = 0; i < list.length; i++) {
    if (t >= list[i].start && t < list[i].end) return i
  }
  return t >= (list.at(-1)?.end || 0) && list.length ? list.length - 1 : -1
}

function onTimeUpdate() {
  const v = videoRef.value
  if (!v) return
  progress.value = v.currentTime
  duration.value = v.duration || 0
  const idx = segIndexAt(v.currentTime)
  if (idx >= 0 && idx !== currentIdx.value) {
    currentIdx.value = idx
    activePage.value = timeline.value[idx].page - 1
  }
}

function togglePlay() {
  const v = videoRef.value
  if (!v) return
  if (v.paused) v.play().catch(() => {})
  else v.pause()
}

function onSeek(val) {
  const v = videoRef.value
  if (!v) return
  v.currentTime = val
  const idx = segIndexAt(val)
  if (idx >= 0) {
    currentIdx.value = idx
    activePage.value = timeline.value[idx].page - 1
  }
}

function jumpToPage(i) {
  const seg = timeline.value.find((s) => s.page === i + 1)
  if (seg) onSeek(seg.start)
}

function fmt(s) {
  s = Math.max(0, Math.round(s))
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

onMounted(async () => {
  // marked 挂到非响应式全局（与 speechQueue 单例同思路）
  if (!window.__marked) {
    const { marked } = await import('marked')
    window.__marked = marked
  }
  try {
    courses.value = await listLectureCourses()
  } catch {
    /* 提示已由拦截器处理 */
  }
  // 内置静态课在前（后端保证顺序），默认选第一门
  if (courses.value.length) currentId.value = courses.value[0].courseId
  await load()
})
onBeforeUnmount(() => {
  videoRef.value?.pause()
})
</script>

<style scoped>
.lecture-room {
  display: flex;
  gap: 20px;
  height: calc(100vh - 130px);
  min-height: 520px;
  padding: 4px 2px;
}
/* 默认（基础版式）：左右对半，竖屏人像不被放大 */
.lr-courseware {
  flex: 1.15;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
/* 演播室版：左栏缩为窄条导航，视频占其余全部宽度 */
.lecture-room.is-studio .lr-courseware {
  flex: 0 0 320px;
}
.lr-course-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.lr-title {
  font-size: 20px;
  font-weight: 700;
}
.lr-page-card {
  flex: 1;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 12px;
  padding: 28px 32px;
  overflow-y: auto;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.04);
}
.lecture-room.is-studio .lr-page-card {
  padding: 16px 18px;
}
.lr-page-title {
  margin: 0 0 18px;
  font-size: 22px;
  border-left: 4px solid #409eff;
  padding-left: 12px;
}
.lecture-room.is-studio .lr-page-title {
  margin: 0 0 12px;
  font-size: 16px;
  padding-left: 10px;
}
.lr-page-body {
  font-size: 16px;
  line-height: 1.9;
  color: #303133;
}
.lecture-room.is-studio .lr-page-body {
  font-size: 13px;
  line-height: 1.75;
}
.lr-page-body :deep(p) {
  margin: 0 0 14px;
}
.lr-page-body :deep(.katex) {
  font-size: 1.15em;
}
.lr-page-body :deep(strong) {
  color: #409eff;
}
.lr-page-note {
  margin-top: 18px;
  padding: 10px 14px;
  background: #f4f8ff;
  border-radius: 8px;
  color: #5a7bb5;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.lr-page-dots {
  display: flex;
  gap: 10px;
  justify-content: center;
  padding: 14px 0 0;
}
.lecture-room.is-studio .lr-page-dots {
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px 0 0;
}
.lr-dot {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  border: 1px solid #dcdfe6;
  background: #fff;
  cursor: pointer;
  font-size: 13px;
  color: #606266;
}
.lecture-room.is-studio .lr-dot {
  width: 26px;
  height: 26px;
  font-size: 12px;
}
.lr-dot.active {
  background: #409eff;
  border-color: #409eff;
  color: #fff;
}
.lr-stage {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 380px;
}
.lecture-room.is-studio .lr-stage {
  min-width: 0;
}
.lr-video-card {
  position: relative;
  flex: 1;
  border-radius: 12px;
  overflow: hidden;
  background: linear-gradient(160deg, #0f1c33, #1c3350);
  display: flex;
  align-items: center;
  justify-content: center;
}
.lr-video {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.lr-video-fallback {
  position: absolute;
  color: rgba(255, 255, 255, 0.75);
  font-size: 13px;
}
.lr-subtitle {
  margin-top: 12px;
  padding: 12px 16px;
  background: #fff;
  border-radius: 10px;
  border: 1px solid #e4e7ed;
  min-height: 58px;
  font-size: 14px;
  line-height: 1.7;
  color: #303133;
}
.lr-controls {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 12px;
  padding: 0 4px;
}
.lr-time {
  font-size: 12px;
  color: #909399;
  white-space: nowrap;
}
</style>
