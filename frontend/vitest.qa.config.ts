/// <reference types="vitest/config" />
// Runs the QA suite in ../tests/frontend with the frontend's dependencies and test setup.
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const frontend = fileURLToPath(new URL(".", import.meta.url));
const repo = fileURLToPath(new URL("..", import.meta.url));

export default defineConfig({
  plugins: [react()],
  root: repo,
  server: { fs: { allow: [repo] } },
  resolve: {
    dedupe: ["react", "react-dom"],
    // tests/frontend has no node_modules of its own: resolve its bare imports from frontend/.
    alias: [
      {
        find: /^(react|react-dom|@testing-library\/[^/]+|@unovis\/ts|@fontsource-variable\/nunito-sans)(\/.*)?$/,
        replacement: frontend + "node_modules/$1$2",
      },
    ],
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["tests/frontend/**/*.test.{ts,tsx}"],
    setupFiles: [frontend + "src/test/setup.ts"],
    css: false,
    server: { deps: { moduleDirectories: ["node_modules", frontend + "node_modules"] } },
  },
});
