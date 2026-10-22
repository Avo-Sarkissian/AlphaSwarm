/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/ws': { target: 'ws://localhost:8000', ws: true, changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
  },
  test: {
    // Pure tests run in node; hook and component tests opt into happy-dom with
    // a `// @vitest-environment happy-dom` first line.
    setupFiles: ['./src/__tests__/setup.ts'],
  },
});
