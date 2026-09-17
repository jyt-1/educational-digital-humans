<!-- [工单18] 人工智能NLP-Agent数字人项目-教育智能体-智能助教任务 —— 智能问答页（带引用流式问答） -->
<template>
  <div class="chat-layout">
    <!-- 会话列表 -->
    <aside class="chat-aside">
      <el-button type="primary" class="chat-new" :icon="Plus" @click="startNewChat">新对话</el-button>
      <div class="chat-conv-list">
        <div
          v-for="conv in conversations"
          :key="conv.id"
          class="chat-conv"
          :class="{ 'is-active': conv.id === conversationId }"
          @click="loadConversation(conv.id)"
        >
          <div class="chat-conv-title">{{ conv.title || '未命名会话' }}</div>
          <div class="chat-conv-meta">
            <span>{{ conv.message_count }} 条 · {{ formatTime(conv.created_at) }}</span>
            <el-icon class="chat-conv-del" @click.stop="handleDeleteConversation(conv)"><Delete /></el-icon>
          </div>
        </div>
        <el-empty v-if="!conversations.length" description="暂无历史会话" :image-size="60" />
      </div>
    </aside>

    <!-- 对话主体 -->
    <section class="chat-main">
      <div class="chat-toolbar">
        <el-select v-model="scope" size="small" style="width: 150px">
          <el-option label="全部（公共+私有）" value="all" />
          <el-option label="仅公共知识库" value="public" />
          <el-option label="仅我的私有库" value="private" />
        </el-select>
        <el-select v-model="rerankMode" size="small" style="width: 120px">
          <el-option label="重排跟随配置" value="auto" />
          <el-option label="强制重排" value="on" />
          <el-option label="关闭重排" value="off" />
        </el-select>
        <span class="chat-tip">答案中的 [n] 角标对应下方引用来源，点击可定位</span>
      </div>

      <div ref="scrollRef" class="chat-scroll">
        <div v-if="!messages.length" class="chat-welcome">
          <h3>智能助教</h3>
          <p>基于公共知识库与你的私有资料回答问题，答案附带引用来源。</p>
          <div class="chat-samples">
            <el-tag
              v-for="sample in samples"
              :key="sample"
              class="chat-sample"
              effect="plain"
              @click="input = sample"
            >
              {{ sample }}
            </el-tag>
          </div>
        </div>

        <div
          v-for="msg in messages"
          :key="msg.uid"
          class="chat-row"
          :class="msg.role === 'user' ? 'is-user' : 'is-assistant'"
        >
          <div class="chat-bubble">
            <div v-if="msg.role === 'user'" class="chat-text">{{ msg.content }}</div>
            <template v-else>
              <div
                class="rendered-md chat-md"
                :class="{ 'is-error': msg.failed }"
                @click="onAnswerClick($event, msg)"
                v-html="renderAnswer(msg)"
              />
              <span v-if="msg.streaming" class="chat-cursor">▍</span>
              <CitationList
                v-if="(msg.citations || []).length"
                :ref="(el) => setCiteRef(msg.uid, el)"
                :citations="msg.citations"
              />
            </template>
          </div>
        </div>
      </div>

      <div class="chat-input">
        <el-input
          v-model="input"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 5 }"
          resize="none"
          placeholder="输入问题，Enter 发送，Shift + Enter 换行"
          :disabled="streaming"
          @keydown.enter.exact.prevent="handleSend"
        />
        <div class="chat-actions">
          <el-button v-if="streaming" type="danger" plain @click="stopStreaming">停止生成</el-button>
          <el-button v-else type="primary" :icon="Promotion" :disabled="!input.trim()" @click="handleSend">
            发送
          </el-button>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Plus, Promotion } from '@element-plus/icons-vue'
import { marked } from 'marked'

import { chatStream, deleteConversation, getConversation, listConversations } from '@/api/assistant'
import CitationList from '@/components/CitationList.vue'

const route = useRoute()

const conversations = ref([])
const conversationId = ref(null)
const messages = ref([])
const input = ref('')
const scope = ref('all')
const rerankMode = ref('auto')
const streaming = ref(false)
const scrollRef = ref(null)

const samples = [
  '梯度下降的学习率过大会有什么后果？',
  '表格里 Adam 优化器适合什么场景？',
  '帮我总结反向传播的完整流程',
  '各知识点在期末考试中占多少分？',
]

let uidSeed = 0
let controller = null
const citeRefs = new Map()

function nextUid() {
  uidSeed += 1
  return `m${uidSeed}`
}

function setCiteRef(uid, el) {
  if (el) citeRefs.set(uid, el)
  else citeRefs.delete(uid)
}

function formatTime(value) {
  if (!value) return ''
  return String(value).replace('T', ' ').slice(5, 16)
}

// ---------------------------------------------------------------- 渲染

marked.setOptions({ breaks: true, gfm: true })

/** 把答案里的 [n] 角标变成可点击的上标；已是 markdown 链接的 [x](y) 不处理 */
function renderAnswer(msg) {
  if (!msg.content) return ''
  let html
  try {
    html = marked.parse(msg.content)
  } catch {
    html = msg.content
  }
  return html.replace(/\[(\d{1,2})\](?!\()/g, '<sup class="cite-badge" data-index="$1">[$1]</sup>')
}

function onAnswerClick(event, msg) {
  const badge = event.target.closest?.('.cite-badge')
  if (!badge) return
  const index = Number(badge.dataset.index)
  const list = citeRefs.get(msg.uid)
  list?.highlight?.(index)
}

async function scrollToBottom() {
  await nextTick()
  const el = scrollRef.value
  if (el) el.scrollTop = el.scrollHeight
}

// ---------------------------------------------------------------- 会话

async function loadConversations() {
  try {
    conversations.value = await listConversations()
  } catch {
    /* 拦截器已提示 */
  }
}

function startNewChat() {
  conversationId.value = null
  messages.value = []
  input.value = ''
}

async function loadConversation(id) {
  if (streaming.value) {
    ElMessage.warning('请先等待当前回答结束或点击停止生成')
    return
  }
  const detail = await getConversation(id)
  conversationId.value = detail.id
  messages.value = (detail.messages || []).map((item) => ({
    uid: nextUid(),
    role: item.role,
    content: item.content,
    citations: item.citations || [],
    streaming: false,
  }))
  scrollToBottom()
}

async function handleDeleteConversation(conv) {
  try {
    await ElMessageBox.confirm(`确认删除会话「${conv.title || '未命名会话'}」？`, '删除确认', {
      type: 'warning',
    })
  } catch {
    return
  }
  await deleteConversation(conv.id)
  if (conversationId.value === conv.id) startNewChat()
  await loadConversations()
}

// ---------------------------------------------------------------- 提问

function stopStreaming() {
  controller?.abort()
  streaming.value = false
}

async function handleSend() {
  const text = input.value.trim()
  if (!text || streaming.value) return

  messages.value.push({ uid: nextUid(), role: 'user', content: text, citations: [] })
  const answer = {
    uid: nextUid(),
    role: 'assistant',
    content: '',
    citations: [],
    streaming: true,
    failed: false,
  }
  messages.value.push(answer)
  input.value = ''
  streaming.value = true
  controller = new AbortController()
  await scrollToBottom()

  try {
    await chatStream(
      {
        question: text,
        conversation_id: conversationId.value,
        scope: scope.value,
        use_rerank: rerankMode.value === 'auto' ? null : rerankMode.value === 'on',
      },
      {
        signal: controller.signal,
        onEvent: (event, data) => {
          if (event === 'sources') {
            answer.citations = data.citations || []
          } else if (event === 'delta') {
            answer.content += data.text || ''
            scrollToBottom()
          } else if (event === 'done') {
            if (data.conversation_id) conversationId.value = data.conversation_id
            if (data.content) answer.content = data.content
            answer.citations = data.citations?.length ? data.citations : answer.citations
          } else if (event === 'error') {
            answer.failed = true
            answer.content += `\n\n> ⚠️ ${data.msg || '生成失败'}`
          }
        },
      },
    )
  } catch (error) {
    if (error?.name === 'AbortError') {
      answer.content += '\n\n> （已手动停止生成）'
    } else {
      answer.failed = true
      answer.content = answer.content || `> ⚠️ ${error.message || '请求失败'}`
    }
  } finally {
    streaming.value = false
    answer.streaming = false
    controller = null
    await loadConversations()
    scrollToBottom()
  }
}

// 「相关提问 / 相关学习」面板（错题详情页侧栏、仪表盘今日任务、学习路径每个节点）
// 跳到本页时带 ?q= 或 ?conversation=。不读这两个参数的话，点过去只会落在一个空会话上，
// 联动助教这条链路就是断的。
onMounted(async () => {
  await loadConversations()
  const presetConversation = Number(route.query.conversation)
  if (presetConversation) {
    await loadConversation(presetConversation)
  }
  const presetQuestion = String(route.query.q || '').trim()
  if (presetQuestion) {
    input.value = presetQuestion
    // 预填而不是直接发：学生可能想改一改再问，且自动发问会立刻消耗一次 LLM 调用
    ElMessage.info('已带入推荐问题，可直接发送或修改')
  }
})

onBeforeUnmount(() => {
  controller?.abort()
})
</script>

<style scoped>
.chat-layout {
  display: flex;
  gap: 16px;
  height: calc(100vh - 88px);
}

.chat-aside {
  width: 230px;
  flex-shrink: 0;
  background: #fff;
  border-radius: 6px;
  padding: 12px;
  display: flex;
  flex-direction: column;
}

.chat-new {
  width: 100%;
}

.chat-conv-list {
  flex: 1;
  overflow-y: auto;
  margin-top: 10px;
}

.chat-conv {
  padding: 8px 10px;
  border-radius: 4px;
  cursor: pointer;
  margin-bottom: 6px;
  border: 1px solid transparent;
}

.chat-conv:hover {
  background: #f5f7fa;
}

.chat-conv.is-active {
  background: #ecf5ff;
  border-color: #b3d8ff;
}

.chat-conv-title {
  font-size: 13px;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-conv-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  color: #a8abb2;
  margin-top: 4px;
}

.chat-conv-del:hover {
  color: #f56c6c;
}

.chat-main {
  flex: 1;
  min-width: 0;
  background: #fff;
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.chat-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-bottom: 1px solid #ebeef5;
}

.chat-tip {
  color: #a8abb2;
  font-size: 12px;
}

.chat-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  background: #f7f9fc;
}

.chat-welcome {
  text-align: center;
  color: #909399;
  padding-top: 60px;
}

.chat-welcome h3 {
  color: #303133;
  margin-bottom: 6px;
}

.chat-samples {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin-top: 14px;
}

.chat-sample {
  cursor: pointer;
}

.chat-row {
  display: flex;
  margin-bottom: 14px;
}

.chat-row.is-user {
  justify-content: flex-end;
}

.chat-row.is-assistant {
  justify-content: flex-start;
}

.chat-bubble {
  max-width: 78%;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 14px;
  line-height: 1.8;
}

.is-user .chat-bubble {
  background: #409eff;
  color: #fff;
}

.is-assistant .chat-bubble {
  background: #fff;
  border: 1px solid #ebeef5;
  width: 78%;
}

.chat-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.chat-md {
  word-break: break-word;
}

.chat-md.is-error {
  color: #f56c6c;
}

.chat-md :deep(.cite-badge) {
  color: #409eff;
  cursor: pointer;
  font-size: 12px;
  padding: 0 1px;
}

.chat-md :deep(.cite-badge:hover) {
  text-decoration: underline;
}

.chat-cursor {
  color: #409eff;
  animation: blink 1s step-start infinite;
}

@keyframes blink {
  50% {
    opacity: 0;
  }
}

.chat-input {
  border-top: 1px solid #ebeef5;
  padding: 10px 14px;
  display: flex;
  gap: 10px;
  align-items: flex-end;
}

.chat-actions {
  flex-shrink: 0;
}
</style>
