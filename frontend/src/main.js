// [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— 应用入口
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { createApp } from 'vue'

import App from '@/App.vue'
import router from '@/router'

import 'element-plus/dist/index.css'
import '@/styles/main.css'

const app = createApp(App)
app.use(router)
app.use(ElementPlus, { locale: zhCn })
app.mount('#app')
