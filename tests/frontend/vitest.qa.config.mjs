// QA-owned Vitest config: runs tests/frontend/*.qa.test.tsx with the FRONTEND's own dependencies
// and setup (no install, no edits to frontend/). Run from frontend/:
//   npx vitest run --config ../tests/frontend/vitest.qa.config.mjs
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "../..");
const fe = path.join(repo, "frontend");
const nm = path.join(fe, "node_modules");
const { default: react } = await import(path.join(nm, "@vitejs/plugin-react/dist/index.js"));

export default {
  root: fe,
  plugins: [react()],
  resolve: {
    alias: [
      { find: /^(react|react-dom|@testing-library\/[\w-]+|@unovis\/[\w-]+|@fontsource-variable\/[\w-]+)(\/.*)?$/,
        replacement: `${nm}/$1$2` },
    ],
  },
  server: { fs: { allow: [repo] } },
  test: {
    environment: "jsdom",
    globals: true,
    css: false,
    include: [path.join(here, "**/*.qa.test.{ts,tsx}")],
    setupFiles: [path.join(fe, "src/test/setup.ts")],
  },
};
