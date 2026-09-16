<!-- [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 题目结构化编辑器 -->
<template>
  <div>
    <el-collapse v-model="activeNames">
      <el-collapse-item
        v-for="(q, i) in items"
        :key="i"
        :name="String(i)"
      >
        <template #title>
          <div class="q-title">
            <span class="q-no">{{ i + 1 }}</span>
            <el-tag size="small">{{ q.qtype || '未设题型' }}</el-tag>
            <el-tag v-if="q.score" size="small" type="warning">{{ q.score }} 分</el-tag>
            <span class="q-stem-preview">{{ q.stem || '（题干为空）' }}</span>
          </div>
        </template>

        <el-form label-width="72px" size="small">
          <el-row :gutter="12">
            <el-col :span="10">
              <el-form-item label="题型">
                <el-select v-model="q.qtype" style="width: 100%" @change="touch">
                  <el-option v-for="t in QUESTION_TYPES" :key="t" :label="t" :value="t" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="7">
              <el-form-item label="分值">
                <el-input-number
                  v-model="q.score"
                  :min="0"
                  :max="100"
                  controls-position="right"
                  style="width: 100%"
                  @change="touch"
                />
              </el-form-item>
            </el-col>
            <el-col :span="7">
              <el-form-item label="知识点">
                <el-input v-model="q.knowledge_point" placeholder="用于工单19 组卷" @input="touch" />
              </el-form-item>
            </el-col>
          </el-row>

          <el-form-item label="题干">
            <el-input
              v-model="q.stem"
              type="textarea"
              :rows="3"
              placeholder="题干正文"
              @input="touch"
            />
          </el-form-item>

          <!-- 单选/多选/判断才有选项 -->
          <el-form-item v-if="hasOptions(q)" label="选项">
            <div style="width: 100%">
              <div v-for="(_, k) in q.options" :key="k" class="opt-row">
                <span class="opt-label">{{ optionLabel(k) }}</span>
                <el-input
                  v-model="q.options[k]"
                  :placeholder="`选项 ${optionLabel(k)}`"
                  @input="touch"
                />
                <el-button link type="danger" @click="removeOption(q, k)">删除</el-button>
              </div>
              <el-button link type="primary" @click="addOption(q)">＋ 添加选项</el-button>
            </div>
          </el-form-item>

          <el-form-item label="答案">
            <el-input v-model="q.answer" type="textarea" :rows="2" placeholder="参考答案" @input="touch" />
          </el-form-item>

          <el-form-item label="解析">
            <el-input
              v-model="q.analysis"
              type="textarea"
              :rows="3"
              placeholder="解题思路与易错点"
              @input="touch"
            />
          </el-form-item>

          <el-form-item>
            <el-button link type="danger" @click="removeQuestion(i)">删除本题</el-button>
          </el-form-item>
        </el-form>
      </el-collapse-item>
    </el-collapse>

    <el-empty v-if="!items.length" description="暂无题目，可点击下方按钮新增" :image-size="60" />
    <el-button style="margin-top: 8px" @click="addQuestion">＋ 新增一题</el-button>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  items: { type: Array, required: true },
})
const emit = defineEmits(['change'])

const QUESTION_TYPES = ['单选', '多选', '判断', '填空', '简答', '计算', '论述', '编程']

// 展开当前编辑的题目，默认收起避免长列表
const activeNames = ref([])

function optionLabel(index) {
  return String.fromCharCode(65 + index) // A/B/C/D…
}

function hasOptions(q) {
  return ['单选', '多选'].includes(q.qtype) || (q.options?.length ?? 0) > 0
}

function touch() {
  emit('change')
}

function addOption(q) {
  if (!Array.isArray(q.options)) q.options = []
  q.options.push('')
  touch()
}

function removeOption(q, index) {
  q.options.splice(index, 1)
  touch()
}

function addQuestion() {
  props.items.push({
    qtype: '单选',
    score: 5,
    stem: '',
    options: ['', '', '', ''],
    answer: '',
    analysis: '',
    knowledge_point: '',
  })
  activeNames.value = [String(props.items.length - 1)]
  emit('change')
}

function removeQuestion(index) {
  props.items.splice(index, 1)
  emit('change')
}
</script>

<style scoped>
.q-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding-right: 12px;
}

.q-no {
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  line-height: 22px;
  text-align: center;
  border-radius: 50%;
  background: #409eff;
  color: #fff;
  font-size: 12px;
}

.q-stem-preview {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #606266;
  font-size: 13px;
}

.opt-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.opt-label {
  width: 20px;
  flex-shrink: 0;
  color: #909399;
}
</style>
