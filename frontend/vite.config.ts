import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
// VITE_API_URL — set this in Vercel environment variables to your Railway backend URL.
// e.g. https://apex-store-intelligence.railway.app
export default defineConfig({
  plugins: [react()],
  define: {
    // Expose the env var to the browser bundle
    __API_URL__: JSON.stringify(process.env.VITE_API_URL || 'http://localhost:8000'),
  },
  server: {
    proxy: {
      // During local dev, proxy API calls to the local FastAPI server
      '/api': {
        target: process.env.VITE_API_URL || 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
