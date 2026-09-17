<!-- [工单19] 人工智能NLP-Agent数字人项目-教育智能体-个性化学习推荐任务 —— 学习路径推荐（时间线） -->
<template>
  <div v-loading="loading" class="learn-page">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>学习路径推荐</span>
          <div>
            <el-tag v-if="!isStudent" size="small" type="success" effect="plain" style="margin-right: 8px">
              教师视角
            </el-tag>
            <el-button v-if="isTeacher" size="small" @click="drawerVisible = true">
              知识点治理
            </el-button>
            <el-button size="small" link type="primary" @click="load">刷新</el-button>
          </div>
        </div>
      </template>

      <el-alert
        v-if="!isStudent"
        type="info"
        :closable="false"
        show-icon
        title="学习路径按学生个人画像生成"
        description="教师账号没有个人作答数据，故此处没有路径。可用右下角「知识点治理」维护图谱与题库。"
        style="margin-bottom: 12px"
      />

      <el-alert
        type="success"
        :closable="false"
        show-icon
        :title="`推荐顺序共 ${items.length} 步，按「先修补前置、再学后继」排列`"
        description="标「起点」的是每条薄弱链上最该先动手的节点（可能不止一条链）；链上靠后的节点在理由里会写明要先补哪个前置。每个节点的右侧是它的三个出口：相关提问 / 学习资料 / 练习题。"
        v-if="items.length"
        style="margin-bottom: 12px"
      />

      <el-empty v-if="!items.length" :description="message || '暂无薄弱知识点'" />

      <el-timeline v-else>
        <el-timeline-item
          v-for="item in items"
          :key="item.kp_id"
          :timestamp="`第 ${item.order} 步`"
          placement="top"
          :type="item.is_entry ? 'danger' : 'primary'"
          :hollow="!item.is_entry"
        >
          <el-card shadow="hover" class="path-card">
            <div class="path-head">
              <el-tag v-if="item.is_entry" type="danger" effect="dark" size="small">
                起点
              </el-tag>
              <span class="path-name">{{ item.name }}</span>
              <el-progress
                :percentage="Math.round(item.mastery * 100)"
                :color="masteryColor(item.mastery)"
                :stroke-width="10"
                class="path-progress"
              />
              <el-button type="primary" size="small" @click="goPractice(item.kp_id)">
                去练习
              </el-button>
              <el-button size="small" @click="toggleRelated(item)">
                {{ expanded === item.kp_id ? '收起' : '相关学习' }}
              </el-button>
            </div>

            <!-- 可解释理由：工单要求"输出推荐顺序 + 可解释理由" -->
            <div class="path-reason">{{ item.reason }}</div>

            <el-collapse-transition>
              <div v-show="expanded === item.kp_id" class="path-related">
                <RelatedPanel :kp-id="item.kp_id" :kp-name="item.name" />
              </div>
            </el-collapse-transition>
          </el-card>
        </el-timeline-item>
      </el-timeline>
    </el-card>

    <KpTeacherDrawer v-model="drawerVisible" @changed="load" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import KpTeacherDrawer from '@/components/KpTeacherDrawer.vue'
import RelatedPanel from '@/components/RelatedPanel.vue'
import { getPath } from '@/api/learn'
import { authState } from '@/store/user'

const router = useRouter()
const loading = ref(false)
const items = ref([])
const message = ref('')
const expanded = ref(null)
const drawerVisible = ref(false)

const isStudent = computed(() => authState.user?.role === 'student')
const isTeacher = computed(() => authState.user?.role === 'teacher')
const masteryColor = (mastery) =>
  mastery >= 0.85 ? '#67c23a' : mastery >= 0.6 ? '#e6a23c' : '#f56c6c'

async function load() {
  if (!isStudent.value) return
  loading.value = true
  try {
    const data = await getPath()
    items.value = data.items || []
    message.value = data.message || ''
  } catch {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}

function toggleRelated(item) {
  expanded.value = expanded.value === item.kp_id ? null : item.kp_id
}

function goPractice(kpId) {
  router.push({ path: '/learn/practice', query: { kp_id: kpId } })
}

onMounted(load)
</script>

<style scoped>
.learn-page {
  padding-bottom: 24px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.path-card {
  border-left: 3px solid #409eff;
}

.path-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.path-name {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.path-progress {
  width: 180px;
}

.path-reason {
  margin-top: 8px;
  color: #606266;
  font-size: 13px;
  line-height: 1.6;
  background: #f7f9fc;
  border-radius: 4px;
  padding: 8px 10px;
}

.path-related {
  margin-top: 10px;
  border-top: 1px solid #ebeef5;
  padding-top: 8px;
}
</style>
