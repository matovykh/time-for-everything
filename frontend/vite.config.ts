/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The production build is served by FastAPI on the same origin as /api/v1.
// In development Vite proxies /api to the backend so auth cookies stay same-origin.
const backend = process.env.VITE_BACKEND_ORIGIN ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  base: "/",
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": { target: backend, changeOrigin: false, xfwd: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false, // no source maps in the production bundle (QA)
    chunkSizeWarningLimit: 1200,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
