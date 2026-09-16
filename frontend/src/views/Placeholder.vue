<!-- [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 后续工单占位页 -->
<template>
  <el-empty :description="description" />
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const description = computed(
  () => `${route.meta.title}（${route.meta.ticket}）将在对应工单中实现`,
)
</script>
