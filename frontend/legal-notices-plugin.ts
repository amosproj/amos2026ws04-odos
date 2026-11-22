import { existsSync, readFileSync } from "node:fs";
import type { Plugin } from "vite";
import { UNAVAILABLE, buildManifest, type NoticeStore } from "./src/legal/manifest.ts";
import { renderNotices } from "./src/legal/notices.ts";

const ID = "virtual:legal-notices";
export const NOTICES_FILE = "THIRD-PARTY-NOTICES.txt";

/**
 * Exposes the repository's sbom.spdx.json to the app as the virtual module "virtual:legal-notices" (a slim license manifest)
 * and publishes THIRD-PARTY-NOTICES.txt next to the app. Both are built from the files on every build and dev start, so
 * replacing the SBOM refreshes the Legal Notices page without edits. Notice texts come from the committed, verified store
 * (notices/notices.json, refreshed offline by scripts/collect-notices.mjs) and are only used for the exact name and version the
 * SBOM lists; missing and outdated notices are reported, never reused silently.
 * The SBOM lives outside frontend/ (the Dockerfile copies it in), so a build without it finds none and the page says so.
 */
export function legalNotices(sbomPath: string, storePath: string): Plugin {
  const load = (warn: (m: string) => void) => {
    if (!existsSync(sbomPath)) {
      warn(`SBOM not found at ${sbomPath}: the Legal Notices page will show no dependency licenses.`);
      return { manifest: UNAVAILABLE, store: null as NoticeStore | null };
    }
    const store: NoticeStore | null = existsSync(storePath) ? JSON.parse(readFileSync(storePath, "utf8")) : null;
    if (!store) warn(`Notice store not found at ${storePath}: no third-party license texts will be published.`);
    return { manifest: buildManifest(JSON.parse(readFileSync(sbomPath, "utf8")), store), store };
  };
  return {
    name: "odos-legal-notices",
    resolveId: (id) => (id === ID ? `\0${ID}` : null),
    load(id) {
      if (id !== `\0${ID}`) return null;
      this.addWatchFile(sbomPath);
      this.addWatchFile(storePath);
      try {
        const { manifest } = load((m) => this.warn(m));
        const missing = manifest.packages.filter((p) => !p.notice).length;
        if (manifest.available && (missing || manifest.staleNotices)) {
          this.warn(`Third-party notices: ${manifest.packages.length - missing} of ${manifest.packages.length} components have verified notice files, ${missing} are missing${manifest.staleNotices ? `, ${manifest.staleNotices} stored entries no longer match the SBOM (run scripts/collect-notices.mjs)` : ""}. They are listed in ${NOTICES_FILE}.`);
        }
        return `export default ${JSON.stringify(manifest)};`;
      } catch (e) {
        return this.error(`Cannot read the SBOM or the notice store: ${(e as Error).message}`);
      }
    },
    generateBundle() {
      const { manifest, store } = load(() => {});
      if (manifest.available) this.emitFile({ type: "asset", fileName: NOTICES_FILE, source: renderNotices(manifest, store) });
    },
    configureServer(server) {
      server.watcher.add([sbomPath, storePath]);
      server.watcher.on("change", (f) => {
        if (f !== sbomPath && f !== storePath) return;
        const mod = server.moduleGraph.getModuleById(`\0${ID}`);
        if (mod) server.moduleGraph.invalidateModule(mod);
        server.ws.send({ type: "full-reload" });
      });
      server.middlewares.use(`/${NOTICES_FILE}`, (_req, res) => {
        const { manifest, store } = load(() => {});
        res.setHeader("Content-Type", "text/plain; charset=utf-8");
        res.end(manifest.available ? renderNotices(manifest, store) : "The SBOM was not available, so no notices could be generated.\n");
      });
    },
  };
}
