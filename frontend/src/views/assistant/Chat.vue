<!-- [工单22] 人工智能NLP-Agent数字人项目-教育智能体 —— 沉浸式数字人助教台
     布局：左 25% 控制区（会话列表 + 对话历史 + 检索设置）+ 右 75% 舞台区（数字人舞台 + 悬浮输入条 + 引用抽屉）
     后端 assistant/chat SSE 接口不变，仅视图层重构。 -->
<template>
  <div class="desk">
    <!-- ================= 左：控制区 25% ================= -->
    <aside class="desk-side">
      <div class="side-head">
        <div>
          <div class="side-title">智能助教</div>
          <div class="side-sub">基于知识库的答疑数字人</div>
        </div>
        <el-button size="small" type="primary" :icon="Plus" circle title="新对话" @click="startNewChat" />
      </div>

      <div class="side-convs">
        <div
          v-for="conv in conversations"
          :key="conv.id"
          class="side-conv"
          :class="{ 'is-active': conv.id === conversationId }"
          @click="loadConversation(conv.id)"
        >
          <div class="side-conv-title">{{ conv.title || '未命名会话' }}</div>
          <div class="side-conv-meta">
            <span>{{ conv.message_count }} 条 · {{ formatTime(conv.created_at) }}</span>
            <el-icon class="side-conv-del" @click.stop="handleDeleteConversation(conv)"><Delete /></el-icon>
          </div>
        </div>
        <div v-if="!conversations.length" class="side-empty">暂无历史会话</div>
      </div>

      <div ref="scrollRef" class="side-thread">
        <div v-if="!messages.length" class="thread-welcome">
          <p>向数字人老师提问，答案会同步朗读并附引用来源。</p>
          <div class="thread-samples">
            <el-tag
              v-for="sample in samples"
              :key="sample"
              class="thread-sample"
              effect="plain"
              size="small"
              @click="input = sample"
            >
              {{ sample }}
            </el-tag>
          </div>
        </div>

        <div
          v-for="msg in messages"
          :key="msg.uid"
          class="thread-row"
          :class="msg.role === 'user' ? 'is-user' : 'is-assistant'"
        >
          <div class="thread-bubble">
            <div v-if="msg.role === 'user'" class="thread-text">{{ msg.content }}</div>
            <template v-else>
              <div
                class="rendered-md thread-md"
                :class="{ 'is-error': msg.failed }"
                @click="onAnswerClick($event, msg)"
                v-html="renderAnswer(msg)"
              />
              <span v-if="msg.streaming" class="thread-cursor">▍</span>
              <button
                v-if="(msg.citations || []).length"
                class="thread-cites"
                @click="openCites(msg)"
              >
                引用来源 {{ msg.citations.length }} 篇
              </button>
            </template>
          </div>
        </div>
      </div>

      <div class="side-tools">
        <el-select v-model="scope" size="small" style="width: 100%">
          <el-option label="全部知识库（公共+私有）" value="all" />
          <el-option label="仅公共知识库" value="public" />
          <el-option label="仅我的私有库" value="private" />
        </el-select>
        <el-select v-model="rerankMode" size="small" style="width: 100%">
          <el-option label="重排跟随配置" value="auto" />
          <el-option label="强制重排" value="on" />
          <el-option label="关闭重排" value="off" />
        </el-select>
      </div>
    </aside>

    <!-- ================= 右：舞台区 75% ================= -->
    <section class="desk-stage">
      <AvatarSpotlight :thinking="streaming" :listening="listening" />

      <!-- 引用溯源抽屉（舞台右侧，折叠展示；点答案里的 [n] 会自动展开并高亮） -->
      <div class="stage-cites" :class="{ 'is-open': citesOpen }">
        <button class="cites-toggle" @click="citesOpen = !citesOpen">
          <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
            <path d="M4 2.5h6l2.5 2.5v8.5H4z" stroke="currentColor" stroke-width="1.3" />
            <line x1="6" y1="8" x2="10.5" y2="8" stroke="currentColor" stroke-width="1.3" />
            <line x1="6" y1="10.5" x2="10.5" y2="10.5" stroke="currentColor" stroke-width="1.3" />
          </svg>
          <span>引用来源</span>
          <em v-if="activeCitations.length">{{ activeCitations.length }}</em>
          <i class="cites-chevron"></i>
        </button>
        <transition name="cites-fade">
          <div v-show="citesOpen && activeCitations.length" class="cites-panel">
            <CitationList ref="activeCiteRef" :citations="activeCitations" />
          </div>
        </transition>
      </div>

      <!-- 悬浮输入条（不占主画面） -->
      <div class="stage-input">
        <el-input
          v-model="input"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 4 }"
          resize="none"
          :placeholder="inputPlaceholder"
          :disabled="streaming"
          class="stage-textarea"
          @keydown.enter.exact.prevent="handleSend"
        />
        <div class="stage-actions">
          <el-button
            class="chat-mic"
            :class="{ 'is-listening': listening }"
            :type="listening ? 'danger' : 'default'"
            :icon="Microphone"
            :disabled="streaming"
            circle
            title="语音提问"
            @click="toggleMic"
          />
          <el-button v-if="streaming" type="danger" plain circle :icon="VideoPause" title="停止生成" @click="stopStreaming" />
          <el-button
            v-else
            type="primary"
            :icon="Promotion"
            circle
            title="发送"
            :disabled="!input.trim()"
            @click="handleSend"
          />
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Microphone, Plus, Promotion, VideoPause } from '@element-plus/icons-vue'
import { marked } from 'marked'

import { chatStream, deleteConversation, getConversation, listConversations } from '@/api/assistant'
import { createAsr, isAsrSupported } from '@/audio/asr'
import AvatarSpotlight from '@/components/AvatarSpotlight.vue'
import CitationList from '@/components/CitationList.vue'
import { initAvatar, speech } from '@/store/avatar'

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

function nextUid() {
  uidSeed += 1
  return `m${uidSeed}`
}

function formatTime(value) {
  if (!value) return ''
  return String(value).replace('T', ' ').slice(5, 16)
}

// ---------------------------------------------------------------- 引用抽屉
const citesOpen = ref(false)
const activeCiteRef = ref(null)

/** 舞台抽屉展示「当前这轮」的引用：取最后一条带引用的助手消息 */
const activeCitations = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    const msg = messages.value[i]
    if (msg.role === 'assistant' && (msg.citations || []).length) return msg.citations
  }
  return []
})

function openCites() {
  citesOpen.value = true
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

async function onAnswerClick(event) {
  const badge = event.target.closest?.('.cite-badge')
  if (!badge) return
  const index = Number(badge.dataset.index)
  citesOpen.value = true // 点角标：先展开舞台里的引用抽屉，再高亮对应卡片
  await nextTick()
  activeCiteRef.value?.highlight?.(index)
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
  speech.stop() // 清掉上一轮可能还在念的尾句
  asr?.stop() // 收音中新建会话：停麦，否则中间结果会写进新会话的输入框
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
  speech.stop() // 切会话要把上一会话的声音掐掉，否则会边加载边念
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
  speech.stop()
}

async function handleSend() {
  const text = input.value.trim()
  if (!text || streaming.value) return
  asr?.stop() // 手动发送时顺手关麦，别让后续识别结果覆盖刚清空的输入框

  // ⚠️ 消息对象必须用 reactive 包一层再 push：后续流式写入（content/citations/streaming）
  // 都发生在「发送时捕获的引用」上，若引用指向原始对象，写入不过 Proxy、不触发更新——
  // 表现为引用抽屉与角标不刷新、答案要等下一个响应式信号才整块冒出来。
  messages.value.push(reactive({ uid: nextUid(), role: 'user', content: text, citations: [] }))
  const answer = reactive({
    uid: nextUid(),
    role: 'assistant',
    content: '',
    citations: [],
    streaming: true,
    failed: false,
  })
  messages.value.push(answer)
  input.value = ''
  streaming.value = true
  controller = new AbortController()
  // ★ warmup 必须在第一个 await 之前、用户手势的同步栈内调用，否则浏览器按
  // autoplay 策略挂起 AudioContext，后面一句也念不出来。
  speech.start()
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
            speech.feed(data.text || '') // 边生成边念：切句后就地合成，不等整篇写完
            scrollToBottom()
          } else if (event === 'done') {
            if (data.conversation_id) conversationId.value = data.conversation_id
            if (data.content) answer.content = data.content
            answer.citations = data.citations?.length ? data.citations : answer.citations
            // 本轮引用一出，抽屉的「引用来源 N」角标就有了内容，轻提示一下就够
            if (answer.citations.length) ElMessage.success({ message: `已检索到 ${answer.citations.length} 条引用，见舞台右侧`, duration: 2000 })
            speech.flush() // 把缓冲区里的尾句念完
          } else if (event === 'error') {
            answer.failed = true
            answer.content += `\n\n> ⚠️ ${data.msg || '生成失败'}`
            speech.stop()
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
    // ⚠️ 这里**不能**无条件 speech.stop()：流虽然结束了，最后几句往往还在念。
    // 照搬「finally 里统一清理」的直觉会直接把尾句掐掉。只有失败时才需要停。
    if (answer.failed) speech.stop()
    await loadConversations()
    scrollToBottom()
  }
}

// ---------------------------------------------------------------- 语音识别
//
// Web Speech API（Chrome / Edge 内置）。一次收一句：final 一到就自动发送，
// 匹配「提问 → 数字人回答」的课堂节奏；中间结果实时写入输入框，
// 学生能看见「我的话被听成了什么」。

const asrSupported = isAsrSupported()
const listening = ref(false)
let asr = null
let asrBaseText = '' // 开麦那一刻输入框里已有的文字，识别结果追加在其后

/** 输入框占位文案随聆听态切换，是语音功能可见性的第一触点 */
const inputPlaceholder = computed(() => {
  if (listening.value) return '正在聆听，请说出你的问题…'
  if (!asrSupported) return '输入问题，Enter 发送'
  return '输入问题，或点麦克风用语音提问'
})

function toggleMic() {
  if (listening.value) {
    asr?.stop() // 手动停：onEnd 的 gotFinal=false，不会触发自动发送
    return
  }
  if (!asrSupported) {
    ElMessage.warning('当前浏览器不支持语音识别，建议使用 Chrome 或 Edge')
    return
  }
  if (streaming.value) return

  asrBaseText = input.value.trim()
  asr = createAsr({
    onInterim: (text) => {
      input.value = asrBaseText ? `${asrBaseText} ${text}` : text
    },
    onFinal: (text) => {
      input.value = asrBaseText ? `${asrBaseText} ${text}` : text
    },
    onError: (_code, message) => {
      if (message) ElMessage.warning(message)
    },
    onStart: () => {
      listening.value = true
    },
    onEnd: (gotFinal) => {
      listening.value = false
      // 一句说完直接发：让「说 → 答」像真人课堂对话一样无缝衔接
      if (gotFinal && !streaming.value && input.value.trim()) handleSend()
    },
  })
  asr.start()
}

// 「相关提问 / 相关学习」面板（错题详情页侧栏、仪表盘今日任务、学习路径每个节点）
// 跳到本页时带 ?q= 或 ?conversation=。不读这两个参数的话，点过去只会落在一个空会话上，
// 联动助教这条链路就是断的。
onMounted(async () => {
  await loadConversations()
  initAvatar() // 不 await：语音配置晚一点到位不影响问答
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
  speech.stop() // 离开页面立刻静音，不留残留声音
  asr?.stop() // 麦克风也不能在离开页面后继续亮着
})
</script>

<style scoped>
/* ================= 总体：左 25% 控制区 + 右 75% 舞台区 ================= */
.desk {
  display: flex;
  gap: 14px;
  height: calc(100vh - 88px);
}

/* ---------------- 左：控制区 ---------------- */
.desk-side {
  width: 25%;
  min-width: 280px;
  max-width: 400px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-radius: 12px;
  overflow: hidden;
}

.side-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 14px 10px;
  border-bottom: 1px solid #f0f2f5;
}

.side-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}

.side-sub {
  margin-top: 2px;
  font-size: 11px;
  color: #a8abb2;
}

.side-convs {
  max-height: 26%;
  overflow-y: auto;
  padding: 8px 8px 4px;
  border-bottom: 1px solid #f0f2f5;
}

.side-conv {
  padding: 7px 9px;
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 4px;
  border: 1px solid transparent;
  transition: background 0.15s;
}

.side-conv:hover {
  background: #f5f7fa;
}

.side-conv.is-active {
  background: #ecf5ff;
  border-color: #b3d8ff;
}

.side-conv-title {
  font-size: 13px;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.side-conv-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  color: #a8abb2;
  margin-top: 3px;
}

.side-conv-del:hover {
  color: #f56c6c;
}

.side-empty {
  padding: 12px 4px;
  font-size: 12px;
  color: #c0c4cc;
  text-align: center;
}

.side-thread {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  background: #fafbfe;
}

.thread-welcome {
  font-size: 13px;
  color: #909399;
  line-height: 1.7;
}

.thread-samples {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.thread-sample {
  cursor: pointer;
}

.thread-row {
  display: flex;
  margin-bottom: 10px;
}

.thread-row.is-user {
  justify-content: flex-end;
}

.thread-bubble {
  max-width: 92%;
  border-radius: 10px;
  padding: 8px 12px;
  font-size: 13px;
  line-height: 1.7;
}

.is-user .thread-bubble {
  background: #409eff;
  color: #fff;
}

.is-assistant .thread-bubble {
  background: #fff;
  border: 1px solid #ebeef5;
  width: 92%;
}

.thread-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.thread-md {
  word-break: break-word;
}

.thread-md.is-error {
  color: #f56c6c;
}

.thread-md :deep(.cite-badge) {
  color: #409eff;
  cursor: pointer;
  font-size: 12px;
  padding: 0 1px;
}

.thread-md :deep(.cite-badge:hover) {
  text-decoration: underline;
}

.thread-cursor {
  color: #409eff;
  animation: blink 1s step-start infinite;
}

@keyframes blink {
  50% {
    opacity: 0;
  }
}

.thread-cites {
  display: inline-flex;
  align-items: center;
  margin-top: 8px;
  padding: 3px 10px;
  font-size: 12px;
  color: #5b52c4;
  background: #f2f0fd;
  border: 1px solid #e2defb;
  border-radius: 10px;
  cursor: pointer;
}

.thread-cites:hover {
  background: #e9e6fc;
}

.side-tools {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px 12px;
  border-top: 1px solid #f0f2f5;
}

/* ---------------- 右：舞台区 ---------------- */
.desk-stage {
  flex: 1;
  min-width: 0;
  position: relative;
}

/* 悬浮输入条 */
.stage-input {
  position: absolute;
  left: 50%;
  bottom: 18px;
  transform: translateX(-50%);
  width: min(700px, 86%);
  display: flex;
  align-items: flex-end;
  gap: 10px;
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.86);
  border: 1px solid rgba(255, 255, 255, 0.9);
  border-radius: 16px;
  backdrop-filter: blur(14px);
  box-shadow: 0 10px 30px rgba(89, 106, 168, 0.16);
  z-index: 4;
}

.stage-textarea {
  flex: 1;
}

.stage-textarea :deep(.el-textarea__inner) {
  background: transparent;
  box-shadow: none;
  border: none;
  padding: 4px 2px;
  font-size: 13px;
}

.stage-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  padding-bottom: 2px;
}

/* 聆听中：麦克风按钮呼吸光圈，与舞台胶囊的红色脉冲呼应 */
.chat-mic.is-listening {
  animation: mic-pulse 1.1s ease-in-out infinite;
}

@keyframes mic-pulse {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(245, 108, 108, 0.5);
  }
  50% {
    box-shadow: 0 0 0 7px rgba(245, 108, 108, 0);
  }
}

/* 引用溯源抽屉（舞台右侧，折叠） */
.stage-cites {
  position: absolute;
  right: 18px;
  bottom: 96px;
  width: 340px;
  max-width: 46%;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  z-index: 3;
}

.cites-toggle {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 7px 14px;
  font-size: 12px;
  color: #5a5f6b;
  background: rgba(255, 255, 255, 0.86);
  border: 1px solid rgba(255, 255, 255, 0.95);
  border-radius: 999px;
  backdrop-filter: blur(10px);
  box-shadow: 0 6px 18px rgba(89, 106, 168, 0.12);
  cursor: pointer;
}

.cites-toggle em {
  font-style: normal;
  padding: 0 6px;
  font-size: 11px;
  color: #fff;
  background: #7f77dd;
  border-radius: 8px;
}

.cites-chevron {
  width: 7px;
  height: 7px;
  border-right: 1.5px solid #909399;
  border-bottom: 1.5px solid #909399;
  transform: rotate(-135deg);
  transition: transform 0.2s;
  margin-top: 3px;
}

.stage-cites.is-open .cites-chevron {
  transform: rotate(45deg);
  margin-top: -3px;
}

.cites-panel {
  width: 100%;
  margin-top: 8px;
  max-height: 44vh;
  overflow-y: auto;
  padding: 12px;
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid rgba(255, 255, 255, 0.95);
  border-radius: 12px;
  backdrop-filter: blur(14px);
  box-shadow: 0 12px 32px rgba(89, 106, 168, 0.16);
}

.cites-fade-enter-active,
.cites-fade-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.cites-fade-enter-from,
.cites-fade-leave-to {
  opacity: 0;
  transform: translateY(6px);
}
</style>
