import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: `npm run dev` → http://127.0.0.1:5173 (API calls are proxied to the backend on :8420).
// Build: `npm run build` → dist/ (served by the backend at http://127.0.0.1:8420/).
export default defineConfig({
  base: "/",
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8420", changeOrigin: false },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
  },
});
