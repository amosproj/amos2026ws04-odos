import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The browser only ever talks to relative /api URLs; in development Vite forwards them to FastAPI.
const apiTarget = process.env.ODOS_API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": { target: apiTarget, changeOrigin: true } } },
  preview: { port: 4173, proxy: { "/api": { target: apiTarget, changeOrigin: true } } },
  test: { environment: "node", include: ["src/**/*.test.{ts,tsx}"] },
});
