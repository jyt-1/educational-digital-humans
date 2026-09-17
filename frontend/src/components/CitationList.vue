<!-- [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— 引用来源卡片列表（问答页与检索页共用） -->
<template>
  <div class="citation-list">
    <div v-if="citations.length" class="citation-title">
      引用来源（{{ citations.length }}）<span class="citation-tip">点击卡片查看原文，图片块可直接预览</span>
    </div>

    <div
      v-for="item in citations"
      :key="item.chunk_id"
      :ref="(el) => setCardRef(item.index, el)"
      class="citation-card"
      :class="{ 'is-active': item.index === activeIndex }"
    >
      <div class="citation-head">
        <span class="cite-index">[{{ item.index }}]</span>
        <span class="cite-file" :title="item.filename">{{ item.filename }}</span>
        <el-tag v-if="item.page_no" size="small" type="info" effect="plain">
          第 {{ item.page_no }} 页
        </el-tag>
        <el-tag size="small" :type="typeTag(item.chunk_type)">{{ typeLabel(item.chunk_type) }}</el-tag>
        <template v-if="debug">
          <el-tag v-if="(item.matched_by || []).length" size="small" effect="plain" type="warning">
            {{ item.matched_by.join(' + ') }}
          </el-tag>
          <span v-if="typeof item.score === 'number'" class="cite-score">
            score {{ item.score.toFixed(4) }}
          </span>
        </template>
        <el-button link type="primary" size="small" @click="openOrigin(item)">查看原文</el-button>
      </div>

      <div class="citation-body">
        <el-image
          v-if="item.chunk_type === 'image' && imageUrls[item.chunk_id]"
          :src="imageUrls[item.chunk_id]"
          :preview-src-list="[imageUrls[item.chunk_id]]"
          preview-teleported
          fit="contain"
          class="cite-image"
        />
        <div class="rendered-md cite-text" v-html="render(textOf(item))"></div>
      </div>
    </div>

    <el-dialog v-model="originVisible" title="原文片段" width="760px">
      <div v-if="originChunk" class="rendered-md origin-body" v-html="render(originChunk.content)"></div>
      <template #footer>
        <span v-if="originChunk" class="origin-meta">
          {{ originChunk.filename }}
          <template v-if="originChunk.page_no"> · 第 {{ originChunk.page_no }} 页</template>
          · {{ typeLabel(originChunk.chunk_type) }}
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onBeforeUnmount, reactive, ref, watch } from 'vue'
import { marked } from 'marked'

import { fetchChunkImage, getChunk } from '@/api/kb'

const props = defineProps({
  citations: { type: Array, default: () => [] },
  // 是否展示检索调试信息（召回通道、重排分数）——检索页展示，问答页不展示
  debug: { type: Boolean, default: false },
})

const activeIndex = ref(null)
const cardRefs = new Map()
const imageUrls = reactive({})
const originVisible = ref(false)
const originChunk = ref(null)

function setCardRef(index, el) {
  if (el) cardRefs.set(index, el)
  else cardRefs.delete(index)
}

const TYPE_LABELS = { text: '正文', table: '表格', image: '图片', formula: '公式' }
const TYPE_TAGS = { text: '', table: 'success', image: 'warning', formula: 'danger' }

function typeLabel(type) {
  return TYPE_LABELS[type] || type || '正文'
}

function typeTag(type) {
  return TYPE_TAGS[type] ?? ''
}

function render(text) {
  if (!text) return ''
  try {
    return marked.parse(String(text), { breaks: true })
  } catch {
    return String(text)
  }
}

// 检索结果里片段字段叫 snippet，切块详情里叫 content，两者兼容
function textOf(item) {
  return item?.snippet ?? item?.content ?? ''
}

/** 点击正文里的 [n] 角标时高亮对应引用卡片（由父组件通过 expose 调用） */
function highlight(index) {
  activeIndex.value = index
  const el = cardRefs.get(index)
  if (el?.scrollIntoView) {
    el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }
  setTimeout(() => {
    if (activeIndex.value === index) activeIndex.value = null
  }, 2000)
}

async function openOrigin(item) {
  originChunk.value = null
  originVisible.value = true
  try {
    originChunk.value = await getChunk(item.chunk_id)
  } catch {
    originVisible.value = false
  }
}

function loadImage(chunkId, chunkType) {
  if (chunkType !== 'image' || !chunkId || imageUrls[chunkId]) return
  fetchChunkImage(chunkId)
    .then((url) => {
      imageUrls[chunkId] = url
    })
    .catch(() => {
      /* 图片缺失不阻断文本展示 */
    })
}

// 图片块在检索结果里直接内联缩略图，便于验收时确认「多模态内容能回显」。
// 用 watch 而非 setup 期一次性 forEach：引用是流式问答返回后才赋上来的，
// 只在 setup 时跑一遍会让图片永远停在空白占位。
watch(
  () => props.citations,
  (list) => {
    ;(list || []).forEach((item) => loadImage(item.chunk_id, item.chunk_type))
  },
  { immediate: true, deep: true },
)

onBeforeUnmount(() => {
  Object.values(imageUrls).forEach((url) => URL.revokeObjectURL(url))
})

defineExpose({ highlight })
</script>

<style scoped>
.citation-list {
  margin-top: 10px;
}

.citation-title {
  font-size: 13px;
  color: #606266;
  margin-bottom: 8px;
}

.citation-tip {
  margin-left: 10px;
  color: #a8abb2;
  font-size: 12px;
}

.citation-card {
  border: 1px solid #e4e7ed;
  border-left: 3px solid #409eff;
  border-radius: 4px;
  padding: 8px 10px;
  margin-bottom: 8px;
  background: #fafcff;
  transition: box-shadow 0.2s, border-color 0.2s;
}

.citation-card.is-active {
  border-color: #409eff;
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.25);
}

.citation-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 13px;
}

.cite-index {
  font-weight: 600;
  color: #409eff;
}

.cite-file {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cite-score {
  color: #909399;
  font-size: 12px;
  font-family: Consolas, Monaco, monospace;
}

.citation-body {
  margin-top: 6px;
}

.cite-text {
  font-size: 13px;
  color: #303133;
  max-height: 160px;
  overflow: hidden;
}

.cite-text :deep(table) {
  margin: 6px 0;
  font-size: 12px;
}

.cite-text :deep(p) {
  margin: 4px 0;
}

.cite-image {
  max-width: 220px;
  max-height: 160px;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  cursor: zoom-in;
  margin-bottom: 6px;
  display: block;
}

.origin-body {
  max-height: 56vh;
  overflow-y: auto;
}

.origin-meta {
  color: #909399;
  font-size: 12px;
}
</style>
