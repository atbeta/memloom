import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8789',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://127.0.0.1:8789',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: '../memloom/admin/static',
    emptyOutDir: true,
    sourcemap: true,
  },
})
