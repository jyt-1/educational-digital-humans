<!-- [工单23] 人工智能NLP-Agent数字人项目-教育智能体-班级学情闭环 —— 教师学情看板 -->
<template>
  <div v-loading="loading" class="teach-page">
    <el-alert
      v-if="!isTeacher()"
      type="info"
      :closable="false"
      show-icon
      title="班级学情看板面向教师账号"
      description="当前登录账号是学生。你可以到「个性化学习」查看自己的画像与学习路径。"
    />

    <template v-else>
      <el-card shadow="never">
        <template #header>
          <div class="card-header">
            <span>我的班级</span>
            <div>
              <el-select
                v-model="currentClassId"
                placeholder="选择班级"
                style="width: 220px; margin-right: 8px"
                @change="loadInsight"
              >
                <el-option
                  v-for="item in classes"
                  :key="item.id"
                  :label="`${item.name}（${item.student_count} 人）`"
                  :value="item.id"
                />
              </el-select>
              <el-button size="small" @click="createVisible = true">新建班级</el-button>
              <el-button
                size="small"
                type="primary"
                :disabled="!currentClassId"
                @click="goGenerate"
              >
                按学情备课
              </el-button>
              <el-button size="small" link type="primary" @click="loadInsight">刷新</el-button>
            </div>
          </div>
        </template>

        <el-empty v-if="!classes.length" description="还没有班级。点右上角「新建班级」建一个。" />
        <div v-else-if="insight">
          <el-alert
            :type="coverageRate >= 0.5 ? 'success' : 'warning'"
            :closable="false"
            show-icon
            :title="`参与度：${insight.coverage.class_size} 人中 ${insight.coverage.covered_students} 人有作答或成绩记录（${percent(insight.coverage.rate)}）`"
            :description="coverageRate >= 0.5
              ? '覆盖率充足，下面的图形与排行可作备课依据。'
              : '覆盖率偏低，下面的数字只代表有记录的那部分学生，请谨慎据此备课。'"
            style="margin-bottom: 12px"
          />

          <el-row :gutter="16">
            <el-col :span="15">
              <el-card shadow="never">
                <template #header>
                  知识点 × 学生 掌握度
                  <span class="hint">（空白格 = 该生在此知识点上无作答记录，不是 0 分）</span>
                </template>
                <el-empty v-if="!heatmap.kps.length" description="本班暂无作答数据。" />
                <div v-else ref="heatEl" class="chart tall"></div>
              </el-card>
            </el-col>
            <el-col :span="9">
              <el-card shadow="never">
                <template #header>
                  学情卡预览
                  <span class="hint">（将喂给模型的内容）</span>
                </template>
                <pre v-if="insight.brief" class="brief">{{ insight.brief }}</pre>
                <el-empty v-else description="本班暂无作答数据，生成时不会注入学情。" :image-size="60" />
              </el-card>
            </el-col>
          </el-row>

          <el-row :gutter="16" style="margin-top: 16px">
            <el-col :span="12">
              <el-card shadow="never">
                <template #header>薄弱知识点排行（掌握度升序）</template>
                <el-empty v-if="!insight.weak_points.length" description="本班已采集到的知识点均已达标。" />
                <div v-else ref="barEl" class="chart"></div>
              </el-card>
            </el-col>
            <el-col :span="12">
              <el-card shadow="never">
                <template #header>
                  学生清单
                  <el-button size="small" link type="primary" @click="memberVisible = true">
                    管理成员
                  </el-button>
                </template>
                <el-table :data="students" size="small" max-height="380">
                  <el-table-column prop="display_name" label="姓名" width="110" />
                  <el-table-column prop="username" label="登录名" width="130" />
                  <el-table-column prop="kp_count" label="有数据知识点" width="115" />
                  <el-table-column label="薄弱" width="80">
                    <template #default="{ row }">
                      <el-tag v-if="row.weak_count" size="small" type="danger">{{ row.weak_count }}</el-tag>
                      <el-tag v-else size="small" type="success">0</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="操作">
                    <template #default="{ row }">
                      <el-button size="small" link type="danger" @click="removeOne(row)">移出</el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </el-card>
            </el-col>
          </el-row>
        </div>
      </el-card>

      <el-dialog v-model="createVisible" title="新建班级" width="440px">
        <el-form label-width="80px">
          <el-form-item label="班级名称">
            <el-input v-model="newClass.name" placeholder="如：人工智能2401班" />
          </el-form-item>
          <el-form-item label="课程名称">
            <el-input v-model="newClass.course_name" placeholder="如：人工智能导论" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="createVisible = false">取消</el-button>
          <el-button type="primary" @click="submitCreate">确定</el-button>
        </template>
      </el-dialog>

      <el-dialog v-model="memberVisible" title="管理成员（按登录名批量添加）" width="560px">
        <el-input
          v-model="memberInput"
          type="textarea"
          :rows="4"
          placeholder="每行一个登录名，也可用逗号或空格分隔"
        />
        <el-button type="primary" size="small" style="margin-top: 8px" @click="submitMembers">
          添加
        </el-button>
        <el-table v-if="memberRows.length" :data="memberRows" size="small" style="margin-top: 12px">
          <el-table-column prop="username" label="登录名" />
          <el-table-column label="结果" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.ok ? 'success' : 'danger'">
                {{ row.ok ? '已加入' : '失败' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="reason" label="说明" />
        </el-table>
      </el-dialog>
    </template>
  </div>
</template>

<script setup>
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'

import {
  addMembers,
  createClass,
  getInsight,
  listClasses,
  listStudents,
  removeMember,
} from '@/api/teach'
import { isTeacher } from '@/store/user'

const router = useRouter()

const loading = ref(false)
const classes = ref([])
const currentClassId = ref(null)
const insight = ref(null)
const students = ref([])
const heatEl = ref(null)
const barEl = ref(null)
let heatChart = null
let barChart = null

const createVisible = ref(false)
const newClass = ref({ name: '', course_name: '' })
const memberVisible = ref(false)
const memberInput = ref('')
const memberRows = ref([])

const coverageRate = computed(() => insight.value?.coverage?.rate ?? 0)
const heatmap = computed(() => insight.value?.heatmap || { kps: [], students: [], cells: [] })
const percent = (value) => `${Math.round((value || 0) * 100)}%`
const masteryColor = (mastery) =>
  mastery >= 0.85 ? '#67c23a' : mastery >= 0.6 ? '#e6a23c' : '#f56c6c'

async function loadClasses() {
  try {
    const data = await listClasses()
    classes.value = data.items || []
    if (!currentClassId.value && classes.value.length) {
      currentClassId.value = classes.value[0].id
    }
  } catch {
    /* 拦截器已提示 */
  }
}

async function loadInsight() {
  if (!currentClassId.value) {
    insight.value = null
    students.value = []
    return
  }
  loading.value = true
  try {
    const [insightData, studentData] = await Promise.all([
      getInsight(currentClassId.value, { top_n: 10 }),
      listStudents(currentClassId.value),
    ])
    insight.value = insightData
    students.value = studentData.items || []
    await nextTick()
    renderHeat()
    renderBar()
  } catch {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}

function renderHeat() {
  const grid = heatmap.value
  if (!heatEl.value || !grid.kps.length) return
  if (!heatChart) {
    heatChart = echarts.init(heatEl.value)
  }
  heatChart.setOption({
    tooltip: {
      position: 'top',
      formatter: (params) => {
        const [si, ki] = params.data
        return `${grid.students[si]}<br/>${grid.kps[ki]}：${percent(params.data[2])}`
      },
    },
    grid: { left: 120, right: 30, top: 20, bottom: 90 },
    // min 设 0 而 max 设 1，是为了让不同班级的图颜色可比；
    // 空白格（无数据）不会落在色带上，而是留白——与"掌握度 0"在视觉上分得开
    visualMap: {
      min: 0,
      max: 1,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      inRange: { color: ['#f56c6c', '#e6a23c', '#67c23a'] },
      text: ['掌握', '薄弱'],
    },
    xAxis: {
      type: 'category',
      data: grid.students,
      axisLabel: { rotate: 45, interval: 0, fontSize: 10 },
      splitArea: { show: true },
    },
    yAxis: { type: 'category', data: grid.kps, splitArea: { show: true } },
    series: [
      {
        type: 'heatmap',
        data: grid.cells,
        label: { show: false },
        emphasis: { itemStyle: { shadowBlur: 8, shadowColor: 'rgba(0,0,0,0.3)' } },
      },
    ],
  })
  heatChart.resize()
}

function renderBar() {
  const points = insight.value?.weak_points || []
  if (!barEl.value || !points.length) return
  if (!barChart) {
    barChart = echarts.init(barEl.value)
  }
  // 横向条形图：知识点名字长，横排比竖排好读；升序排让最薄弱的在最上面
  const ordered = [...points].reverse()
  barChart.setOption({
    tooltip: {
      formatter: (params) => {
        const item = ordered[params.dataIndex]
        return `${item.name}<br/>平均掌握度 ${percent(item.mastery)}<br/>覆盖 ${item.student_count}/${item.class_size} 人`
      },
    },
    grid: { left: 110, right: 70, top: 16, bottom: 24 },
    xAxis: { type: 'value', max: 1, axisLabel: { formatter: (v) => `${v * 100}%` } },
    yAxis: { type: 'category', data: ordered.map((item) => item.name) },
    series: [
      {
        type: 'bar',
        data: ordered.map((item) => ({
          value: Number(item.mastery.toFixed(4)),
          itemStyle: { color: masteryColor(item.mastery) },
        })),
        label: {
          show: true,
          position: 'right',
          formatter: (params) => {
            const item = ordered[params.dataIndex]
            return `${percent(item.mastery)}（${item.student_count}/${item.class_size}）`
          },
        },
      },
    ],
  })
  barChart.resize()
}

function goGenerate() {
  router.push({ name: 'lesson-generate', query: { class_id: currentClassId.value } })
}

async function submitCreate() {
  if (!newClass.value.name || !newClass.value.course_name) {
    ElMessage.warning('班级名称与课程名称都要填')
    return
  }
  try {
    const created = await createClass({ ...newClass.value })
    createVisible.value = false
    newClass.value = { name: '', course_name: '' }
    await loadClasses()
    currentClassId.value = created.id
    await loadInsight()
    ElMessage.success('班级已创建')
  } catch {
    /* 拦截器已提示 */
  }
}

async function submitMembers() {
  const usernames = memberInput.value
    .split(/[\s,，、]+/)
    .map((item) => item.trim())
    .filter(Boolean)
  if (!usernames.length) {
    ElMessage.warning('请先填写登录名')
    return
  }
  try {
    const data = await addMembers(currentClassId.value, usernames)
    memberRows.value = data.items || []
    ElMessage.success(`成功加入 ${data.added} 人，失败 ${data.failed} 人`)
    await Promise.all([loadClasses(), loadInsight()])
  } catch {
    /* 拦截器已提示 */
  }
}

async function removeOne(row) {
  try {
    await ElMessageBox.confirm(`确定把 ${row.display_name || row.username} 移出本班？`, '确认')
  } catch {
    return // 用户取消
  }
  try {
    await removeMember(currentClassId.value, row.student_id)
    await Promise.all([loadClasses(), loadInsight()])
  } catch {
    /* 拦截器已提示 */
  }
}

function handleResize() {
  heatChart?.resize()
  barChart?.resize()
}

onMounted(async () => {
  window.addEventListener('resize', handleResize)
  // `isTeacher()` 是 store 导出的普通函数（同 `Knowledge.vue` 的用法），不是 ref：
  // 模板里调用它是响应式的——它在渲染过程中读了 reactive 的 `authState.user`，
  // 依赖照样被收集。所以此处不需要 `.value`，也不需要再包一层 computed
  if (!isTeacher()) return
  await loadClasses()
  await loadInsight()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  heatChart?.dispose()
  barChart?.dispose()
  heatChart = null
  barChart = null
})
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.chart {
  height: 340px;
  width: 100%;
}
.chart.tall {
  height: 420px;
}
.brief {
  margin: 0;
  max-height: 420px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: 13px;
  line-height: 1.7;
  color: #303133;
}
.hint {
  color: #909399;
  font-size: 12px;
  font-weight: normal;
}
</style>
