<!-- [工单19] 人工智能NLP-Agent数字人项目-教育智能体-个性化学习推荐任务 —— 知识点三出口面板 -->
<!--
  三出口 = 相关提问 / 学习资料 / 练习题（设计文档 2.2 场景三第 7 条）。
  该面板被**三个入口**复用：仪表盘今日任务、学习路径页每个节点、错题详情页侧栏。
  三处若各写一份，最先漂移的一定是「学习的下一步该往哪走」这个动作。
-->
<template>
  <div v-loading="loading" class="related-panel">
    <div class="related-head">
      <span class="related-title">
        <el-tag size="small" type="primary" effect="dark">知识点</el-tag>
        {{ kpName || '—' }} 的相关学习
      </span>
      <el-button link type="primary" size="small" @click="load">刷新</el-button>
    </div>

    <el-tabs v-model="activeTab" class="related-tabs">
      <!-- ① 相关提问 -->
      <el-tab-pane name="questions">
        <template #label>相关提问（{{ questions.length }}）</template>
        <el-empty v-if="!questions.length" description="你在助教里问过的相关问题会出现在这里" :image-size="60" />
        <div v-for="(item, index) in questions" :key="index" class="related-item">
          <el-tag v-if="item.source === 'own'" size="small" type="success" effect="plain">我的提问</el-tag>
          <el-tag v-else size="small" type="info" effect="plain">常见问题</el-tag>
          <span class="related-text">{{ item.question }}</span>
          <el-button
            v-if="item.conversation_id"
            link
            type="primary"
            size="small"
            @click="goConversation(item.conversation_id)"
          >
            回到对话
          </el-button>
          <el-button v-else link type="primary" size="small" @click="askAgain(item.question)">
            去提问
          </el-button>
        </div>
      </el-tab-pane>

      <!-- ② 学习资料（工单18 的公开检索结果，带引用） -->
      <el-tab-pane name="materials">
        <template #label>学习资料（{{ materials.length }}）</template>
        <el-empty v-if="!materials.length" description="知识库里暂无相关材料" :image-size="60" />
        <CitationList v-else :citations="materials" />
      </el-tab-pane>

      <!-- ③ 练习题 -->
      <el-tab-pane name="exercises">
        <template #label>练习题（{{ exercises.length }}）</template>
        <el-empty v-if="!exercises.length" description="该知识点下暂无题目" :image-size="60" />
        <div v-for="item in exercises" :key="item.question_id" class="related-item">
          <el-tag size="small" :type="difficultyTag(item.difficulty)" effect="plain">
            {{ item.difficulty }}
          </el-tag>
          <span class="related-text">{{ item.stem }}</span>
          <el-button link type="primary" size="small" @click="practice()">
            去做这类题
          </el-button>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import CitationList from '@/components/CitationList.vue'
import { getRelated } from '@/api/learn'

const props = defineProps({
  kpId: { type: Number, default: null },
  kpName: { type: String, default: '' },
})

const emit = defineEmits(['practice'])

const router = useRouter()
const loading = ref(false)
const activeTab = ref('questions')
const questions = ref([])
const materials = ref([])
const exercises = ref([])

const DIFF_TAGS = { 简单: 'success', 中等: 'warning', 困难: 'danger' }
const difficultyTag = (difficulty) => DIFF_TAGS[difficulty] ?? 'info'

async function load() {
  if (!props.kpId) return
  loading.value = true
  try {
    const data = await getRelated(props.kpId)
    questions.value = data.questions || []
    materials.value = data.materials || []
    exercises.value = data.exercises || []
  } catch {
    // 拦截器已提示；检索失败时三个列表保持为空即可，不影响其余页面
  } finally {
    loading.value = false
  }
}

function goConversation(conversationId) {
  router.push({ path: '/assistant/chat', query: { conversation: conversationId } })
}

// 跨用户聚合来的问题没有会话可跳，只能带问题文本去问答页预填、发起新的提问
function askAgain(question) {
  router.push({ path: '/assistant/chat', query: { q: question } })
}

// 练习页是按**知识点**取题的，不是按 question_id 取单题——所以这里只把 kp_id 带过去，
// 由练习页自己抽题。带 question_id 反而会让人以为"点了就只做这一道"。
function practice() {
  if (!props.kpId) {
    ElMessage.info('请到练习页选择该知识点')
    return
  }
  emit('practice', { kpId: props.kpId })
  router.push({ path: '/learn/practice', query: { kp_id: props.kpId } })
}

watch(() => props.kpId, load, { immediate: true })
</script>

<style scoped>
.related-panel {
  min-height: 120px;
}

.related-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.related-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.related-tabs {
  margin-top: 4px;
}

.related-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  border-bottom: 1px dashed #ebeef5;
  font-size: 13px;
}

.related-item:last-child {
  border-bottom: none;
}

.related-text {
  flex: 1;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
