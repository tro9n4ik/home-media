import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/admin/',
  build: { outDir: 'dist' },
  server: {
    proxy: {
      '/api': 'http://localhost:8142',
      '/plugins': 'http://localhost:8142',
    },
  },
})
