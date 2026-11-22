#!/usr/bin/env node
/**
 * Maintainer tool (not part of the build): refreshes frontend/notices/notices.json, the store of verified license and copyright
 * evidence behind THIRD-PARTY-NOTICES.txt. Offline: it only reads directories you give it, never the network.
 * It rebuilds the store from ../sbom.spdx.json (override: ODOS_SBOM_PATH; output override: ODOS_STORE_PATH). Needs Node >= 22.18.
 * Every SBOM component gets an entry with one of three statuses:
 *   VERIFIED_FULL_TEXT      license/copyright files of the SAME name and version are stored, they contain the license text(s) the component
 *                           declares (checked against the text, see license-check.mjs) and, where the license requires it, a copyright notice
 *   VERIFIED_METADATA_ONLY  only metadata is verified (a declared license identifier, a repository reference) or the texts are incomplete
 *   UNRESOLVED              no evidence found
 * Only VERIFIED_FULL_TEXT counts as a notice. An identifier or a URL never does.
 *
 *   node scripts/collect-notices.mjs [--npm DIR]... [--python DIR]... [--debian DIR]... [--common-licenses DIR] [--standard DIR] [--extra DIR]...
 *     --evidence       the evidence folder written by notices/tools/evidence.py: replaces all the folder flags below (they can still be added)
 *     --npm            a node_modules directory (default: ./node_modules)
 *     --python         a directory of *.dist-info folders (a site-packages directory, or the dist-info folders copied out of an image)
 *     --debian         a directory of <package>/copyright, <package>/version (dpkg-query and /usr/share/doc in an image)
 *     --common-licenses the image's /usr/share/common-licenses: texts a copyright file refers to are attached to that package
 *     --standard       a directory with standard.json: [{ids:[SPDX id], name, path, source}], authoritative standard license texts (e.g. Debian's
 *                      common-licenses, the SPDX license list). They are attached - marked as standard texts - only where a component's declared
 *                      license text is missing from its own files; copyright attribution is never taken from them.
 *     --extra          a directory with extra.json: [{kind, name, version, evidence, files:[{name, path}], metadata?, reasons?}] for files obtained
 *                      elsewhere (an upstream release tag, a same-version source distribution). Every entry must name its evidence.
 *                      attach: true adds the files to the component's own evidence instead (role: "standard-license-text" marks standard texts);
 *                      waive: [{match, because}] removes an automatically found reason whose text contains `match` (the reason is kept as a note).
 */
import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { buildManifest } from "../src/legal/manifest.ts";
import { evaluate, hasAttribution } from "./license-check.mjs";

const FULL = "VERIFIED_FULL_TEXT", META = "VERIFIED_METADATA_ONLY", NONE = "UNRESOLVED";
const args = process.argv.slice(2);
const opt = (name) => args.flatMap((a, i) => (a === name ? [args[i + 1]] : []));
const ev = opt("--evidence")[0]; // the folder notices/tools/evidence.py writes
const dirs = (flag, sub) => (ev ? [...opt(flag), join(ev, sub)] : opt(flag));
const npmDirs = ev ? dirs("--npm", "npm") : opt("--npm").length ? opt("--npm") : ["node_modules"];
const root = fileURLToPath(new URL("..", import.meta.url));
const sbom = JSON.parse(readFileSync(process.env.ODOS_SBOM_PATH ?? join(root, "../sbom.spdx.json"), "utf8"));
const manifest = buildManifest(sbom);

const LICENSE_FILE = /^(licen[sc]e|copying|notice|unlicense|third[-_]?party[-_]?(licen[sc]es?|notices?))\d*([._-].*)?$/i;
const norm = (n) => n.toLowerCase().replace(/[-_.]+/g, "-");
const decoder = new TextDecoder("utf-8", { fatal: true });
const read = (f) => { try { return decoder.decode(readFileSync(f)); } catch { return null; } };
const json = (f) => JSON.parse(readFileSync(f, "utf8"));
// deep = a Python dist-info folder: everything under its licenses/ folder is a license file (PEP 639), plus license-named files elsewhere
const files = (dir, deep, root = dir) => readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
  const p = join(dir, e.name);
  return e.isDirectory() ? (deep ? files(p, true, root) : []) : LICENSE_FILE.test(e.name) || (deep && relative(root, p).split("/")[0] === "licenses") ? [p] : [];
});

// source index: "kind|normalised name" -> [{version, files:[{name, text}], evidence, metadata?, reasons?, copyrightFile?}]
const index = new Map();
const add = (kind, name, version, fs, evidence, more = {}) => {
  const list = fs.map((f) => ({ name: f.name, text: f.text })).filter((f) => f.text !== null);
  if (!list.length && !more.metadata) return;
  const k = `${kind}|${norm(name)}`;
  (index.get(k) ?? index.set(k, []).get(k)).push({ version, files: list, evidence, ...more });
};
for (const dir of npmDirs.filter(existsSync)) {
  const pkgs = readdirSync(dir).flatMap((d) => (d.startsWith("@") ? readdirSync(join(dir, d)).map((s) => `${d}/${s}`) : [d]));
  for (const name of pkgs) {
    const pj = join(dir, name, "package.json");
    if (!existsSync(pj)) continue;
    add("npm", name, json(pj).version, files(join(dir, name), false).map((f) => ({ name: relative(join(dir, name), f), text: read(f) })), "npm package contents");
  }
}
for (const dir of dirs("--python", "images/backend/site-packages").filter(existsSync)) {
  for (const d of readdirSync(dir).filter((x) => x.endsWith(".dist-info"))) {
    const meta = read(join(dir, d, "METADATA")) ?? "";
    const name = /^Name: (.+)$/m.exec(meta)?.[1]?.trim(), version = /^Version: (.+)$/m.exec(meta)?.[1]?.trim();
    if (name && version) add("Python", name, version, files(join(dir, d), true).map((f) => ({ name: relative(join(dir, d), f), text: read(f) })), "Python distribution metadata");
  }
}
const commonDir = dirs("--common-licenses", "common-licenses").find(existsSync);
for (const dir of dirs("--debian", "debian").filter(existsSync)) {
  for (const name of readdirSync(dir).filter((x) => statSync(join(dir, x)).isDirectory())) {
    const version = read(join(dir, name, "version"))?.trim();
    const text = read(join(dir, name, "copyright"));
    if (text === null) continue;
    const fs = [{ name: "copyright", text }], reasons = [];
    // texts the copyright file refers to but does not contain: the image's common-licenses, or files outside the package
    for (const ref of new Set([...text.matchAll(/\/usr\/share\/common-licenses\/([A-Za-z0-9._+-]+)/g)].map((m) => m[1].replace(/[.,;:)'"]+$/, "")))) {
      const t = commonDir && existsSync(join(commonDir, ref)) ? read(join(commonDir, ref)) : null;
      if (t !== null) fs.push({ name: `common-licenses/${ref}`, text: t });
      else reasons.push(`refers to /usr/share/common-licenses/${ref}, which is not available in the evidence`);
    }
    for (const ref of new Set([...text.matchAll(/(\/usr\/share\/(?!common-licenses)[A-Za-z0-9._+/-]*[A-Za-z0-9_+])/g)].map((m) => m[1]))) reasons.push(`refers to ${ref}, which is not part of the evidence`);
    if (/__AUTO_PERMISSIVE__/.test(text)) reasons.push('declares a placeholder license "__AUTO_PERMISSIVE__" for autogenerated files without stating a text');
    add("Debian package", name, version, fs, "Debian package copyright file and the common-licenses texts it refers to (same image)", { reasons });
  }
}
const standard = [];
for (const dir of dirs("--standard", "extra").filter(existsSync)) for (const s of json(join(dir, "standard.json"))) standard.push({ ...s, text: read(join(dir, s.path)) });
const standardFor = (id) => standard.find((s) => s.ids.some((x) => x.toLowerCase() === id.toLowerCase()) && s.text !== null);

const extras = [], attachments = [];
for (const dir of dirs("--extra", "extra").filter(existsSync)) {
  for (const e of json(join(dir, "extra.json"))) {
    if (!e.evidence) throw new Error(`extra entry ${e.name} has no evidence`);
    const e2 = { ...e, files: (e.files ?? []).map((f) => ({ name: f.name, text: read(join(dir, f.path)), role: e.role })) };
    if (e.attach) attachments.push(e2);
    else { extras.push(e2); add(e.kind, e.name, e.version, e2.files, e.evidence, { metadata: e.metadata, reasons: e.reasons }); }
  }
}

const store = { texts: {}, packages: {} };
const entries = [];
const STD = "standard-license-text";
for (const p of manifest.packages) {
  const cands = index.get(`${p.kind}|${norm(p.name)}`) ?? [];
  const ok = (c) => p.version === null || c.version === p.version || c.version.split("+")[0] === p.version;
  // several sources for the same exact version: prefer the one holding the most evidence files (e.g. a complete package tree over a filtered extract)
  const hit = cands.filter((c) => ok(c) && c.files.length).sort((x, y) => y.files.length - x.files.length)[0] ?? cands.find(ok);
  let entry;
  if (!hit) {
    entry = { status: NONE, files: [], evidence: "none", reasons: [p.kind === "Docker image" ? "composite base image: its operating-system packages are separate components and no single license applies" : "no source holds license files for this exact name and version"] };
  } else {
    let reasons = [...(hit.reasons ?? [])];
    const notes = [], evidence = [hit.evidence];
    const own = [...hit.files];
    for (const a of attachments.filter((a) => a.kind === p.kind && norm(a.name) === norm(p.name) && (a.version === p.version || a.version === hit.version))) {
      own.push(...a.files.filter((f) => f.text !== null));
      if (!a.role) evidence.push(`added: ${a.evidence}`); else evidence.push(`standard text: ${a.evidence}`);
      for (const w of a.waive ?? []) { const before = reasons.length; reasons = reasons.filter((r) => !r.includes(w.match)); if (reasons.length < before) notes.push(`waived: ${w.because}`); }
    }
    entry = { status: FULL, files: [], evidence: evidence.join("; ") };
    if (hit.metadata) entry.metadata = hit.metadata;
    if (p.version === null || hit.version !== p.version) entry.evidenceVersion = hit.version; // the SBOM pins no version, or the build carries a local tag (e.g. +cpu)
    const used = [...own];
    const textOf = (fs) => fs.map((f) => f.text).join("\n");
    let ev = p.license ? evaluate(p.license, textOf(used)) : null;
    // the declared license's text is missing from the component's own files: attach the authoritative standard text, marked as such
    if (p.license && ev?.satisfied === false) {
      const added = [];
      for (const id of ev.missing) {
        const s = standardFor(id.split(" WITH ")[0]);
        if (s && !used.some((f) => f.role === STD && f.name === s.name)) { used.push({ name: s.name, text: s.text, role: STD }); added.push(`${s.ids[0]} (${s.source})`); }
      }
      if (added.length) { entry.standardTexts = added; ev = evaluate(p.license, textOf(used)); }
    }
    const pkgFiles = used.filter((f) => f.role !== STD);
    entry.basis = pkgFiles.length ? "package-notice" : "standard-text-only";
    if (!used.length) entry.status = META;
    else {
      entry.check = { required: p.license, present: ev?.present ?? [], missing: ev?.missing ?? [], unverifiable: ev?.unverifiable ?? [], noticeRequired: ev?.noticeRequired ?? [], attribution: pkgFiles.length ? hasAttribution(pkgFiles) : false };
      if (ev?.satisfied === false) { entry.status = META; reasons.push(`no text found for the declared license ${ev.missing.join(", ")}`); }
      if (reasons.length) entry.status = META;
    }
    if (reasons.length) entry.reasons = reasons;
    if (notes.length) entry.notes = [...(hit.notes ?? []), ...notes];
    else if (hit.notes?.length) entry.notes = [...hit.notes];
    for (const f of [...used].sort((a, b) => a.name.localeCompare(b.name))) {
      const hash = createHash("sha256").update(f.text).digest("hex").slice(0, 16);
      store.texts[hash] = f.text;
      entry.files.push(f.role === STD ? { name: f.name, hash, role: STD } : { name: f.name, hash });
    }
  }
  store.packages[`${p.kind}|${p.name}|${p.version ?? ""}`] = entry;
  entries.push({ p, entry });
}
// Composite base images get no license of their own: their operating-system packages are separate components, and the image entry says how many of them are covered.
const KIND = { pypi: "Python", npm: "npm", docker: "Docker image", deb: "Debian package" };
const keyOf = (pk) => {
  const type = /^pkg:([^/]+)\//.exec(pk.externalRefs?.find((r) => r.referenceType === "purl")?.referenceLocator ?? "")?.[1];
  return `${KIND[type] ?? "Other"}|${pk.name}|${pk.versionInfo && pk.versionInfo !== "NOASSERTION" ? pk.versionInfo : ""}`;
};
const spdxById = new Map(sbom.packages.map((pk) => [pk.SPDXID, pk]));
for (const { p, entry } of entries.filter((e) => e.p.kind === "Docker image")) {
  const self = sbom.packages.find((pk) => keyOf(pk) === `${p.kind}|${p.name}|${p.version ?? ""}`);
  const kids = (sbom.relationships ?? []).filter((r) => r.spdxElementId === self?.SPDXID && r.relationshipType === "CONTAINS").map((r) => store.packages[keyOf(spdxById.get(r.relatedSpdxElement) ?? {})]);
  entry.composite = { contains: kids.length, fullText: kids.filter((k) => k?.status === FULL).length };
  entry.reasons = [kids.length ? `composite base image: no single license applies; it contains ${kids.length} components that are listed separately, ${entry.composite.fullText} of them with verified full text` : "composite base image: no single license applies, and the operating-system packages inside it are not listed in the SBOM"];
}
const sorted = (o) => Object.fromEntries(Object.entries(o).sort(([a], [b]) => a.localeCompare(b)));
store.texts = sorted(store.texts); store.packages = sorted(store.packages);
writeFileSync(process.env.ODOS_STORE_PATH ?? join(root, "notices/notices.json"), JSON.stringify(store, null, 1) + "\n");

const kinds = [...new Set(manifest.packages.map((p) => p.kind))];
const n = manifest.packages.length;
const count = (es, f) => es.filter(f).length;
console.log(`${n} components; ${Object.keys(store.texts).length} distinct texts`);
const ordinary = entries.filter((e) => e.p.kind !== "Docker image");
console.log(`ordinary components (without composite base images): full text ${count(ordinary, (e) => e.entry.status === FULL)}/${ordinary.length}, attribution ${count(ordinary, (e) => e.entry.check?.attribution === true)}/${ordinary.length}; composite base images: ${entries.length - ordinary.length}`);
console.log(`full-text coverage ${count(entries, (e) => e.entry.status === FULL)}/${n}   (of which standard texts only, no package-specific notice: ${count(entries, (e) => e.entry.status === FULL && e.entry.basis === "standard-text-only")})`);
console.log(`copyright attribution evidenced ${count(entries, (e) => e.entry.check?.attribution === true)}/${n}   (a copyright line in a package notice; standard texts never count)`);
for (const k of kinds) {
  const es = entries.filter((e) => e.p.kind === k);
  console.log(`  ${k.padEnd(15)} ${String(es.length).padStart(4)}  ${FULL}=${count(es, (e) => e.entry.status === FULL)}  ${META}=${count(es, (e) => e.entry.status === META)}  ${NONE}=${count(es, (e) => e.entry.status === NONE)}  attribution=${count(es, (e) => e.entry.check?.attribution === true)}`);
}
for (const { p } of entries.filter((e) => e.entry.status === FULL && e.entry.check && e.entry.check.attribution === false)) console.log(`  no-attribution: ${p.kind} ${p.name} ${p.version ?? ""} (${p.license ?? (p.mainLicense ? "multiple licenses" : "license not determined")})${entries.find((e) => e.p === p).entry.basis === "standard-text-only" ? " [standard text only]" : ""}`);
for (const { p, entry } of entries.filter((e) => e.entry.status !== FULL)) console.log(`  ${entry.status === META ? "metadata-only" : "unresolved"}: ${p.kind} ${p.name} ${p.version ?? ""} (${p.license ?? (p.mainLicense ? "multiple licenses" : "license not determined")}) - ${(entry.reasons ?? []).join("; ")}`);
