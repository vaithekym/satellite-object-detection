import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const backend = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // MapLibre (~1 MB) is lazy-loaded on the map page only; that chunk is expected to be large.
  build: { chunkSizeWarningLimit: 1200 },
  server: {
    // Same-origin requests in development; FastAPI runs on :8000.
    proxy: { "/api": backend, "/health": backend },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});
