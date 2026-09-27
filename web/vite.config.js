import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// In dev, `npm run dev` serves the UI on :5173 and proxies /api to the
// FastAPI backend on :8000 (so no CORS).
//
// `npm run build` emits straight into the Python package (../service/web),
// which is where settings.frontend_dir points and what the wheel ships as
// package data. Building there rather than into a local dist/ and copying
// keeps one bundle in one place -- two copies drifted silently before.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
  build: {
    outDir: '../service/web',
    // Required by Vite to clear a directory outside its own root.
    emptyOutDir: true,
  },
})
