import { defineConfig } from 'vite';

// https://vite.dev/config/server-options#server-proxy
export default defineConfig({
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    // A Windows bind mount delivers no file events inside the dev container; poll there.
    watch: process.env.VISTO_VITE_POLL === '1' ? { usePolling: true, interval: 300 } : undefined,
    // The string shorthand implies changeOrigin: true. Keep the browser Host so the
    // backend's same-origin mutation guard sees matching Host and Origin.
    proxy: {
      '/api': { target: process.env.VISTO_API_URL ?? 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
});
