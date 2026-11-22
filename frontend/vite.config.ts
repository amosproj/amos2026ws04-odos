import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { legalNotices } from "./legal-notices-plugin.ts";

// the ODOS backend (uvicorn odos.api:app), reached under /api from the dev server and the preview
const proxy = { "/api": process.env.ODOS_API_URL ?? "http://127.0.0.1:8000" };

export default defineConfig({
  plugins: [react(), legalNotices(process.env.ODOS_SBOM_PATH ?? fileURLToPath(new URL("../sbom.spdx.json", import.meta.url)), process.env.ODOS_NOTICES_PATH ?? fileURLToPath(new URL("./notices/notices.json", import.meta.url)))], // the Legal Notices page reads the repository SBOM
  base: "./", // relative paths: the prepared examples also work as a static site under any sub-path
  server: { proxy },
  preview: { proxy },
  build: { chunkSizeWarningLimit: 800 }, // one bundle: the app plus pdf.js (the pdf.js worker is a separate file)
  test: { environment: "node", include: ["src/**/*.test.{ts,tsx}"] },
});
