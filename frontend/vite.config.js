// [工单17] 人工智能NLP-Agent数字人项目-教育智能体-智能备课任务 —— Vite 配置
// 开发期把 /api 代理到后端 8000（CLAUDE.md 第 9 节），避免跨域配置。
// 前端不读 .env 里的后端密钥；如需前端变量用 import.meta.env.VITE_*。
import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    // main.js 全量引入 Element Plus，vendor-ui 约 1MB（gzip 333KB）。
    // 这是已知且可接受的：开发期图省事，后续如需优化改用 unplugin-vue-components 按需引入。
    chunkSizeWarningLimit: 1100,
    // Element Plus / ECharts 体积较大且很少变动，单独成块便于浏览器缓存
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-ui': ['element-plus'],
          'vendor-chart': ['echarts'],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // SSE 必须关闭代理层缓冲，否则流式会被攒成一坨再返回
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            if (proxyRes.headers['content-type']?.includes('text/event-stream')) {
              proxyRes.headers['x-accel-buffering'] = 'no'
            }
          })
        },
      },
    },
  },
})
