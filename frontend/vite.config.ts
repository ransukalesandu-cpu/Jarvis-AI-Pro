import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

// The bundle is loaded from file:// inside QWebEngineView, so every URL must be relative.
export default defineConfig({
  base: './',
  plugins: [react()],
  build: {
    outDir: fileURLToPath(new URL('../jarvis/webui/dist', import.meta.url)),
    emptyOutDir: true,
    target: 'chrome110',
    chunkSizeWarningLimit: 900,
    rollupOptions: { output: { manualChunks: (id: string) => (id.includes('node_modules/three') ? 'three' : id.includes('node_modules/react') ? 'react' : undefined) } },
  },
  test: { environment: 'jsdom', include: ['src/**/*.test.ts?(x)'] },
});
