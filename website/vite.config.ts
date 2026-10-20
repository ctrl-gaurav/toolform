import { resolve } from "node:path";

/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base: "./" so the built bundle works from any static host, including a
// project subpath on GitHub Pages.
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: { port: 5173, open: false },
  // The parity tests read the evidence JSON from public/ with node:fs.
  test: { environment: "node", include: ["src/**/*.test.ts"] },
  build: {
    outDir: "dist",
    sourcemap: false,
    rollupOptions: {
      input: { main: resolve(__dirname, "index.html") },
      output: {
        // Charting is most of the bundle and changes rarely. Splitting it out
        // means a text edit does not invalidate the whole cache.
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          charts: ["recharts"],
        },
      },
    },
  },
});
