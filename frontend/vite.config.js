import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Frontend runs on :3000 (FRONTEND_URL in .env.example); the API/gateway is on :8000.
export default defineConfig({
  plugins: [react()],
  server: { port: 3000 },
  preview: { port: 3000 },
});
