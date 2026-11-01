import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  base: "./", // a static site with no backend: it works under any sub-path
  build: { chunkSizeWarningLimit: 800 }, // one bundle: the app plus pdf.js (the pdf.js worker is a separate file)
  test: { environment: "node", include: ["src/**/*.test.{ts,tsx}"] },
});
