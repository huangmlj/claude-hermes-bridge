import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd())

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      proxy: {
        '/api': env.VITE_BACKEND_URL || 'http://localhost:8765',
        '/discussions': env.VITE_BACKEND_URL || 'http://localhost:8765',
        '/current.json': env.VITE_BACKEND_URL || 'http://localhost:8765',
      }
    }
  }
})
