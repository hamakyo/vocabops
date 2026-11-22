import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const repoDataDir = resolve(__dirname, "../../data");

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@data": repoDataDir,
    },
  },
  server: {
    fs: {
      allow: [resolve(__dirname, "../..")],
    },
  },
});
