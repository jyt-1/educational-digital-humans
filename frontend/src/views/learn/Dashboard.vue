<!-- [工单19] 人工智能NLP-Agent数字人项目-教育智能体-个性化学习推荐任务 —— 学习仪表盘（掌握度雷达图） -->
<template>
  <div v-loading="loading" class="learn-page">
    <el-alert
      v-if="!isStudent"
      type="info"
      :closable="false"
      show-icon
      title="当前是教师账号"
      description="画像、练习与错题本按用户隔离，只能查看本人的数据。教师可到「学习路径」页打开知识点治理抽屉。"
      style="margin-bottom: 16px"
    />

    <template v-else>
      <!-- 概览 -->
      <el-row :gutter="16">
        <el-col :span="6">
          <el-card shadow="never" class="stat-card">
            <div class="stat-value">{{ profile.kp_count || 0 }}</div>
            <div class="stat-label">已评估知识点</div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="never" class="stat-card">
            <div class="stat-value">{{ percent(profile.average_mastery) }}</div>
            <div class="stat-label">平均掌握度</div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="never" class="stat-card">
            <div class="stat-value warn">{{ profile.weak_count || 0 }}</div>
            <div class="stat-label">薄弱知识点</div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="never" class="stat-card">
            <div class="stat-value">{{ mistakes.length }}</div>
            <div class="stat-label">待复习错题</div>
          </el-card>
        </el-col>
      </el-row>

      <el-row :gutter="16" style="margin-top: 16px">
        <!-- 雷达图 -->
        <el-col :span="14">
          <el-card shadow="never">
            <template #header>
              <div class="card-header">
                <span>掌握度雷达图</span>
                <span class="card-tip">
                  达标线 {{ percent(profile.weak_threshold) }}，低于它的知识点会进入学习路径
                </span>
              </div>
            </template>
            <el-empty
              v-if="!profileItems.length"
              description="还没有数据。做一次练习或导入历史成绩后，这里会画出你的掌握度。"
            />
            <div v-else ref="chartEl" class="radar"></div>
          </el-card>
        </el-col>

        <!-- 今日任务：三出口之一 -->
        <el-col :span="10">
          <el-card shadow="never">
            <template #header>
              <div class="card-header">
                <span>今日任务</span>
                <el-button
                  v-if="todayTask"
                  link
                  type="primary"
                  size="small"
                  @click="goPractice(todayTask.kp_id)"
                >
                  开始练习
                </el-button>
              </div>
            </template>
            <el-empty
              v-if="!todayTask"
              :description="pathMessage || '暂无薄弱知识点，先去练习页做几道题吧'"
            />
            <template v-else>
              <div class="today-head">
                <el-tag type="danger" effect="dark" size="small">最该补</el-tag>
                <span class="today-name">{{ todayTask.name }}</span>
                <span class="today-mastery">掌握度 {{ percent(todayTask.mastery) }}</span>
              </div>
              <p class="today-reason">{{ todayTask.reason }}</p>
              <el-divider style="margin: 10px 0" />
              <RelatedPanel :kp-id="todayTask.kp_id" :kp-name="todayTask.name" />
            </template>
          </el-card>
        </el-col>
      </el-row>

      <!-- 掌握度明细 -->
      <el-card shadow="never" style="margin-top: 16px">
        <template #header>
          <div class="card-header">
            <span>知识点掌握度明细</span>
            <el-button link type="primary" size="small" @click="load">刷新</el-button>
          </div>
        </template>
        <el-empty v-if="!profileItems.length" description="暂无数据" :image-size="70" />
        <el-table v-else :data="sortedItems" size="small" max-height="360">
          <el-table-column prop="name" label="知识点" min-width="180" />
          <el-table-column label="掌握度" width="220">
            <template #default="{ row }">
              <el-progress
                :percentage="Math.round(row.mastery * 100)"
                :color="masteryColor(row.mastery)"
                :stroke-width="12"
              />
            </template>
          </el-table-column>
          <el-table-column prop="attempt_count" label="作答次数" width="100" />
          <el-table-column prop="import_count" label="导入成绩" width="100" />
          <el-table-column label="操作" width="200">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="goPractice(row.kp_id)">练习</el-button>
              <el-button link type="primary" size="small" @click="goRelated(row)">相关学习</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <ScoreImportCard style="margin-top: 16px" @imported="load" />
    </template>

    <el-dialog v-model="relatedVisible" :title="`${relatedKp.name} 的相关学习`" width="720px">
      <RelatedPanel :kp-id="relatedKp.kp_id" :kp-name="relatedKp.name" />
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'

import RelatedPanel from '@/components/RelatedPanel.vue'
import ScoreImportCard from '@/views/learn/ScoreImportCard.vue'
import { getPath, getProfile, listMistakes } from '@/api/learn'
import { authState } from '@/store/user'

const router = useRouter()
const loading = ref(false)
const profile = ref({})
const profileItems = ref([])
const pathItems = ref([])
const pathMessage = ref('')
const mistakes = ref([])

const chartEl = ref(null)
let chart = null

const relatedVisible = ref(false)
const relatedKp = ref({ kp_id: null, name: '' })

const isStudent = computed(() => authState.user?.role === 'student')
const percent = (value) => `${((value || 0) * 100).toFixed(0)}%`
const masteryColor = (mastery) =>
  mastery >= 0.85 ? '#67c23a' : mastery >= 0.6 ? '#e6a23c' : '#f56c6c'

// 路径里排在最前的就是"最该补"的那个（后端已按上游优先排好序）
const todayTask = computed(() => pathItems.value[0] || null)

const sortedItems = computed(() =>
  [...profileItems.value].sort((a, b) => b.mastery - a.mastery),
)

async function load() {
  if (!isStudent.value) return
  loading.value = true
  try {
    const [profileData, pathData, mistakeData] = await Promise.all([
      getProfile(),
      getPath({ limit: 10 }),
      listMistakes(),
    ])
    profile.value = profileData
    profileItems.value = profileData.items || []
    pathItems.value = pathData.items || []
    pathMessage.value = pathData.message || ''
    mistakes.value = mistakeData.items || []
    await nextTick()
    renderChart()
  } catch {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}

function renderChart() {
  if (!chartEl.value || !profileItems.value.length) return
  if (!chart) {
    chart = echarts.init(chartEl.value)
  }
  // 雷达图轴数不宜过多：>12 条就分不清了，按掌握度升序取最该关注的 12 个
  const top = [...profileItems.value]
    .sort((a, b) => a.mastery - b.mastery)
    .slice(0, 12)
  chart.setOption({
    tooltip: {},
    radar: {
      indicator: top.map((item) => ({ name: item.name, max: 1 })),
      radius: '68%',
      axisName: { color: '#606266', fontSize: 12 },
      splitArea: { areaStyle: { color: ['#ffffff', '#f7f9fc'] } },
    },
    series: [
      {
        type: 'radar',
        data: [
          {
            value: top.map((item) => Number(item.mastery.toFixed(4))),
            name: '掌握度',
            areaStyle: { color: 'rgba(64, 158, 255, 0.25)' },
            lineStyle: { color: '#409eff', width: 2 },
            itemStyle: { color: '#409eff' },
          },
        ],
      },
    ],
  })
  chart.resize()
}

function goPractice(kpId) {
  router.push({ path: '/learn/practice', query: { kp_id: kpId } })
}

function goRelated(row) {
  relatedKp.value = { kp_id: row.kp_id, name: row.name }
  relatedVisible.value = true
}

function handleResize() {
  chart?.resize()
}

onMounted(() => {
  load()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  chart?.dispose()
  chart = null
})

watch(isStudent, load)
</script>

<style scoped>
.learn-page {
  padding-bottom: 24px;
}

.stat-card {
  text-align: center;
}

.stat-value {
  font-size: 28px;
  font-weight: 600;
  color: #409eff;
  line-height: 1.2;
}

.stat-value.warn {
  color: #f56c6c;
}

.stat-label {
  color: #909399;
  font-size: 13px;
  margin-top: 4px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-tip {
  color: #909399;
  font-size: 12px;
  font-weight: 400;
}

.radar {
  height: 380px;
  width: 100%;
}

.today-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.today-name {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.today-mastery {
  color: #f56c6c;
  font-size: 13px;
}

.today-reason {
  color: #606266;
  font-size: 13px;
  margin: 8px 0 0;
  line-height: 1.6;
}
</style>
