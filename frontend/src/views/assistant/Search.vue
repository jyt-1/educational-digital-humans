<!-- [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— 检索调试页（混合检索可视化） -->
<template>
  <div class="page-card">
    <h3 class="search-title">检索调试</h3>
    <p class="search-desc">
      向量召回（bge-m3）+ 关键词召回（BM25/jieba）融合排序（RRF），可叠加云端重排
      （bge-reranker-v2-m3）。用于验证「多模态内容可被检索到、可回显引用原文」。
    </p>

    <el-form :inline="true" class="search-form" @submit.prevent>
      <el-form-item label="问题" class="search-question">
        <el-input
          v-model="question"
          placeholder="例如：表格里 Adam 优化器适合什么场景？"
          clearable
          @keyup.enter="handleSearch"
        />
      </el-form-item>
      <el-form-item label="范围">
        <el-select v-model="scope" style="width: 150px">
          <el-option label="全部（公共+私有）" value="all" />
          <el-option label="仅公共知识库" value="public" />
          <el-option label="仅我的私有库" value="private" />
        </el-select>
      </el-form-item>
      <el-form-item label="Top K">
        <el-input-number v-model="topK" :min="1" :max="20" />
      </el-form-item>
      <el-form-item label="重排">
        <el-select v-model="rerankMode" style="width: 130px">
          <el-option label="跟随配置" value="auto" />
          <el-option label="强制开启" value="on" />
          <el-option label="强制关闭" value="off" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="loading" @click="handleSearch">检索</el-button>
      </el-form-item>
    </el-form>

    <div class="search-samples">
      <span class="search-samples-label">示例问题：</span>
      <el-tag
        v-for="sample in samples"
        :key="sample"
        class="search-sample"
        effect="plain"
        @click="useSample(sample)"
      >
        {{ sample }}
      </el-tag>
    </div>

    <el-alert
      v-if="searched && !results.length"
      type="warning"
      :closable="false"
      show-icon
      title="没有召回任何内容"
      description="请确认知识库中已有解析完成的文档（解析状态为「已完成」），或换一个更贴近资料原文的问法。"
    />

    <template v-if="results.length">
      <div class="search-meta">
        命中 {{ results.length }} 条 · 重排{{ rerankEnabled ? '已开启' : '未开启（RRF 融合排序）' }}
        · 召回通道 {{ channelSummary }}
      </div>
      <CitationList ref="citationRef" :citations="results" debug />
    </template>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { searchKb } from '@/api/kb'
import CitationList from '@/components/CitationList.vue'

const question = ref('')
const scope = ref('all')
const topK = ref(5)
const rerankMode = ref('auto')
const loading = ref(false)
const searched = ref(false)
const results = ref([])
const rerankEnabled = ref(false)
const citationRef = ref(null)

const samples = [
  '梯度下降的学习率过大会有什么后果？',
  '表格里 Adam 优化器适合什么场景？',
  '手写数字识别实验的关键步骤是什么？',
  '各知识点在期末考试中占多少分？',
]

const channelSummary = computed(() => {
  const channels = new Set()
  results.value.forEach((item) => (item.matched_by || []).forEach((name) => channels.add(name)))
  return channels.size ? [...channels].join(' + ') : '-'
})

function useSample(text) {
  question.value = text
  handleSearch()
}

async function handleSearch() {
  const text = question.value.trim()
  if (!text) {
    ElMessage.warning('请输入问题')
    return
  }
  loading.value = true
  try {
    const data = await searchKb({
      question: text,
      scope: scope.value,
      top_k: topK.value,
      use_rerank: rerankMode.value === 'auto' ? null : rerankMode.value === 'on',
    })
    results.value = data.citations || []
    rerankEnabled.value = Boolean(data.rerank_enabled)
    searched.value = true
  } catch {
    results.value = []
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.search-title {
  margin: 0 0 6px;
}

.search-desc {
  margin: 0 0 14px;
  color: #909399;
  font-size: 13px;
  line-height: 1.7;
  max-width: 900px;
}

.search-form {
  margin-bottom: 4px;
}

.search-question {
  width: 380px;
}

.search-question :deep(.el-input) {
  width: 100%;
}

.search-samples {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin: 4px 0 14px;
}

.search-samples-label {
  color: #909399;
  font-size: 12px;
}

.search-sample {
  cursor: pointer;
}

.search-meta {
  color: #606266;
  font-size: 13px;
  margin-bottom: 10px;
}
</style>
