#!/usr/bin/env node
/**
 * Offline consistency check of the repository's SPDX SBOM (no network, no Docker). Exit code 1 on any failure.
 *
 *   node scripts/check-sbom.mjs [--sbom FILE] [--json]
 *
 * Scope the SBOM claims (see notices/README.md): every package in frontend/package-lock.json, every pin in backend/requirements.lock (plus the two
 * documented packages the lock leaves out), the three Docker base images and the apt packages backend/Dockerfile installs. This check makes the SBOM
 * and those sources agree: names, versions, development/runtime scope, uniqueness and relationships. It does not validate against the SPDX schema
 * (use `pyspdxtools -i sbom.spdx.json`).
 */
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(fileURLToPath(new URL("..", import.meta.url)), "..");
/** Python packages the SBOM lists although requirements.lock does not pin them (setuptools: required by torch; websockets: an extra of docling). */
export const UNPINNED_PYTHON = ["setuptools", "websockets"];
const norm = (n) => n.toLowerCase().replace(/[-_.]+/g, "-");
const purlOf = (p) => p.externalRefs?.find((r) => r.referenceType === "purl")?.referenceLocator ?? "";
const typeOf = (p) => /^pkg:([^/]+)\//.exec(purlOf(p))?.[1] ?? "root";

/** @returns {{ failures: string[], counts: { packages: number, roots: number, components: number, relationships: number, byEcosystem: Record<string, number>, npm: object, pypi: object } }} */
export function checkSbom({ sbomPath = join(root, "sbom.spdx.json") } = {}) {
  const f = [];
  const s = JSON.parse(readFileSync(sbomPath, "utf8"));
  const pk = s.packages ?? [], rels = s.relationships ?? [];
  if (s.spdxVersion !== "SPDX-2.3") f.push(`spdxVersion is ${s.spdxVersion}, not SPDX-2.3`);
  if (s.dataLicense !== "CC0-1.0") f.push("dataLicense is not CC0-1.0");
  if (s.SPDXID !== "SPDXRef-DOCUMENT") f.push("document SPDXID is not SPDXRef-DOCUMENT");
  if (!s.creationInfo?.created || !s.creationInfo?.creators?.length) f.push("creationInfo is incomplete");

  // identities and relationships
  const ids = pk.map((p) => p.SPDXID);
  if (new Set(ids).size !== ids.length) f.push("duplicate SPDXID");
  const ident = pk.map((p) => `${typeOf(p)}|${norm(p.name)}|${p.versionInfo}`);
  for (const [k, n] of Object.entries(ident.reduce((m, k) => ({ ...m, [k]: (m[k] ?? 0) + 1 }), {}))) if (n > 1) f.push(`duplicate package ${k}`);
  const known = new Set([...ids, "SPDXRef-DOCUMENT"]);
  for (const r of rels) if (!known.has(r.spdxElementId) || !known.has(r.relatedSpdxElement)) f.push(`relationship to an unknown element: ${r.spdxElementId} ${r.relationshipType} ${r.relatedSpdxElement}`);
  const touched = new Set(rels.flatMap((r) => [r.spdxElementId, r.relatedSpdxElement]));
  for (const p of pk) if (!touched.has(p.SPDXID)) f.push(`${p.name} is in no relationship`);
  const roots = pk.filter((p) => p.primaryPackagePurpose === "APPLICATION");
  for (const r of roots) if (!rels.some((x) => x.spdxElementId === "SPDXRef-DOCUMENT" && x.relationshipType === "DESCRIBES" && x.relatedSpdxElement === r.SPDXID)) f.push(`${r.name} is not DESCRIBED by the document`);
  for (const p of pk) if (!p.licenseDeclared || !p.downloadLocation) f.push(`${p.name}: licenseDeclared or downloadLocation is missing`);

  // npm: exactly the packages of package-lock.json, scope from the lockfile
  const lock = JSON.parse(readFileSync(join(root, "frontend/package-lock.json"), "utf8")).packages;
  const npmLock = new Map();
  for (const [k, v] of Object.entries(lock)) if (k.startsWith("node_modules/") && v.version) npmLock.set(k.split("node_modules/").at(-1), v);
  const npm = pk.filter((p) => typeOf(p) === "npm");
  for (const [n, v] of npmLock) {
    const p = npm.find((x) => x.name === n);
    if (!p) { f.push(`npm ${n} ${v.version} is in package-lock.json but not in the SBOM`); continue; }
    if (p.versionInfo !== v.version) f.push(`npm ${n}: SBOM ${p.versionInfo}, lockfile ${v.version}`);
    const dev = /development dependency/.test(p.comment ?? "");
    if (!!v.dev !== dev) f.push(`npm ${n}: lockfile dev=${!!v.dev}, SBOM says ${dev ? "development" : "runtime"}`);
    if (!!v.optional !== /optional platform package/.test(p.comment ?? "")) f.push(`npm ${n}: optional marking differs from the lockfile (optional: ${!!v.optional})`);
  }
  for (const p of npm) if (!npmLock.has(p.name)) f.push(`npm ${p.name} is in the SBOM but not in package-lock.json`);

  // Python: every requirements.lock pin, plus the documented extras
  const pins = new Map();
  for (const l of readFileSync(join(root, "backend/requirements.lock"), "utf8").split("\n")) {
    const m = /^([A-Za-z0-9_.-]+)==(\S+)/.exec(l.trim());
    if (m) pins.set(norm(m[1]), m[2]);
  }
  const py = pk.filter((p) => typeOf(p) === "pypi");
  for (const [n, v] of pins) {
    const p = py.find((x) => norm(x.name) === n);
    if (!p) f.push(`python ${n} ${v} is in requirements.lock but not in the SBOM`);
    else if (p.versionInfo !== v) f.push(`python ${n}: SBOM ${p.versionInfo}, requirements.lock ${v}`);
  }
  for (const p of py) if (!pins.has(norm(p.name)) && !UNPINNED_PYTHON.includes(norm(p.name))) f.push(`python ${p.name} is in the SBOM but neither pinned nor a documented extra`);

  // Docker base images and apt packages named in the Dockerfiles / compose file
  const read = (p) => (existsSync(join(root, p)) ? readFileSync(join(root, p), "utf8") : "");
  const images = new Set([...[...read("backend/Dockerfile").matchAll(/^FROM (\S+)/gm), ...read("frontend/Dockerfile").matchAll(/^FROM (\S+)/gm), ...read("compose.yaml").matchAll(/^\s+image:\s*(postgres:\S+)/gm)].map((m) => m[1])]);
  const dockerSbom = new Set(pk.filter((p) => typeOf(p) === "docker").map((p) => `${p.name}:${p.versionInfo}`));
  for (const i of images) if (!dockerSbom.has(i)) f.push(`Docker image ${i} is used but not in the SBOM`);
  for (const i of dockerSbom) if (!images.has(i)) f.push(`Docker image ${i} is in the SBOM but no longer used`);
  const apt = new Set((/apt-get install[^\n]*?--no-install-recommends\s+([^&\n]+?)\s*&&/.exec(read("backend/Dockerfile"))?.[1] ?? "").split(/\s+/).filter(Boolean));
  const aptSbom = new Set(pk.filter((p) => typeOf(p) === "deb").map((p) => p.name));
  for (const a of apt) if (!aptSbom.has(a)) f.push(`apt package ${a} is installed by backend/Dockerfile but not in the SBOM`);
  for (const a of aptSbom) if (!apt.has(a)) f.push(`apt package ${a} is in the SBOM but backend/Dockerfile does not install it`);

  const by = {};
  for (const p of pk) { const t = typeOf(p); by[t] = (by[t] ?? 0) + 1; }
  const scope = (t) => { const l = pk.filter((p) => typeOf(p) === t); return { total: l.length, development: l.filter((p) => /development dependency/.test(p.comment ?? "")).length, optionalPlatform: l.filter((p) => /optional platform package/.test(p.comment ?? "")).length }; };
  return { failures: f, counts: { packages: pk.length, roots: roots.length, components: pk.length - roots.length, relationships: rels.length, byEcosystem: by, npm: scope("npm"), pypi: scope("pypi") } };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const i = process.argv.indexOf("--sbom");
  const { failures, counts } = checkSbom(i > 0 ? { sbomPath: process.argv[i + 1] } : {});
  if (process.argv.includes("--json")) console.log(JSON.stringify({ ok: !failures.length, failures, counts }, null, 1));
  else {
    console.log(`${counts.packages} packages (${counts.roots} roots + ${counts.components} components), ${counts.relationships} relationships`);
    console.log("by ecosystem:", JSON.stringify(counts.byEcosystem), "| npm:", JSON.stringify(counts.npm), "| python:", JSON.stringify(counts.pypi));
    console.log(failures.length ? `FAILED (${failures.length}):\n  ${failures.join("\n  ")}` : "OK: the SBOM agrees with the lockfiles, Dockerfiles and compose file");
  }
  process.exit(failures.length ? 1 : 0);
}
