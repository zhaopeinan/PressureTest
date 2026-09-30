import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        // Keep SSE/event streams from being buffered by the dev proxy.
        timeout: 0,
        proxyTimeout: 0,
        configure: (proxy) => {
          proxy.on('proxyRes', (_proxyRes, req, res) => {
            const url = req.url || ''
            if (url.includes('/events')) {
              res.setHeader('Cache-Control', 'no-cache, no-transform')
              res.setHeader('X-Accel-Buffering', 'no')
              const flushable = res as typeof res & { flushHeaders?: () => void }
              flushable.flushHeaders?.()
            }
          })
        },
      },
    },
  },
})
