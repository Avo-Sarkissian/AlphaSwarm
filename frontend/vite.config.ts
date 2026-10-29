/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { answerBackendUnreachable } from './src/lib/backendUnreachable';

/** VITE_BASE is the public path; GitHub Pages serves the demo under /AlphaSwarm/. */
function resolveBase(raw: string | undefined): string {
  const base = raw === undefined || raw === '' ? '/' : raw;
  if (!base.startsWith('/') || !base.endsWith('/')) {
    throw new Error(`VITE_BASE must start and end with "/", got ${JSON.stringify(base)}`);
  }
  return base;
}

export default defineConfig({
  base: resolveBase(process.env.VITE_BASE),
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // A stopped backend answers 502 backend_unreachable instead of Vite's
        // empty 500, so the UI can say the backend is down.
        configure: (proxy) => proxy.on('error', answerBackendUnreachable),
      },
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
