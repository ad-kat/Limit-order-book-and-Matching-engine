import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const apiUrl = process.env.VITE_API_URL || 'http://localhost:8000'
  const wsUrl  = apiUrl.replace(/^http/, 'ws')

  return {
    plugins: [react()],
    server: {
      proxy: {
        '/ws':  { target: 'ws://localhost:8000',   ws: true },
        '/api': { target: 'http://localhost:8000', rewrite: p => p.replace(/^\/api/, '') }
      }
    },
    define: {
      __API_URL__: JSON.stringify(apiUrl),
      __WS_URL__:  JSON.stringify(wsUrl + '/ws'),
    }
  }
})
