import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// 构建产物直接输出到 static/，base=/static/，与后端 StaticFiles mount 完全对齐。
// emptyOutDir=false 保留 static/ 下后端依赖的 favicon.ico / icon.png / generated/ 等资源。
export default defineConfig({
  plugins: [vue()],
  base: '/static/',
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    outDir: '../static',
    emptyOutDir: false,
    assetsDir: 'assets',
    sourcemap: false,
  },
  server: {
    host: '0.0.0.0',
    allowedHosts: true,
    port: 5173,
    // 开发模式：API 请求转发到后端（需 python server.py 已在 8765 运行）
    proxy: {
      '/api': {
        target: 'http://localhost:8765',
        changeOrigin: true,
      },
    },
  },
})
