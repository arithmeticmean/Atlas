import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// In dev, `npm run dev` serves the UI on :5173 and proxies /api to the
// FastAPI backend on :8000 (so no CORS). In prod, `npm run build` emits
// dist/, which FastAPI serves itself (settings.frontend_dir -> ../web/dist).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
  build: {
    outDir: 'dist',
  },
})
