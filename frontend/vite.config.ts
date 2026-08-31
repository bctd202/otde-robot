import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': 'http://backend:8000', '/ws': { target: 'ws://backend:8000', ws: true } } },
  test: {
    setupFiles: ['./src/test/setup.ts'],
    environment: 'jsdom',
  },
});
