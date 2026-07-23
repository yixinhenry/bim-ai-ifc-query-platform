import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vite";

const viewerDir = dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  base: "/",
  resolve: {
    dedupe: [
      "three",
      "@thatopen/components",
      "@thatopen/fragments",
      "camera-controls",
      "web-ifc",
    ],
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "es2022",
  },
  plugins: [
    {
      name: "copy-fragments-worker",
      closeBundle() {
        const output = resolve(viewerDir, "dist", "fragments-worker.mjs");
        mkdirSync(dirname(output), { recursive: true });
        copyFileSync(
          resolve(
            viewerDir,
            "node_modules",
            "@thatopen",
            "fragments",
            "dist",
            "Worker",
            "worker.mjs",
          ),
          output,
        );
      },
    },
  ],
});
