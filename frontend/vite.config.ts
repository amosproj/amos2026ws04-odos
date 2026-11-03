import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// the ODOS backend (uvicorn odos.api:app), reached under /api from the dev server and the preview
const proxy = { "/api": process.env.ODOS_API_URL ?? "http://127.0.0.1:8000" };

export default defineConfig({
  plugins: [react()],
  base: "./", // relative paths: the prepared examples also work as a static site under any sub-path
  server: { proxy },
  preview: { proxy },
  build: { chunkSizeWarningLimit: 800 }, // one bundle: the app plus pdf.js (the pdf.js worker is a separate file)
  test: { environment: "node", include: ["src/**/*.test.{ts,tsx}"] },
});
