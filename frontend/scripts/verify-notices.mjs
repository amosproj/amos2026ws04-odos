#!/usr/bin/env node
/**
 * Offline integrity check of the third-party notice store - needs only a checkout (no network, no Docker). Exit code 1 on any failure.
 *
 *   node scripts/verify-notices.mjs [--sbom FILE] [--store FILE] [--lock FILE] [--json]
 *
 * It checks that (1) every SBOM component has exactly one store entry and the store holds no stale entry, (2) every stored text hashes to its key and
 * nothing is unused, (3) a VERIFIED_FULL_TEXT entry really holds the license text(s) its component declares (the same checker the collector uses),
 * (4) every entry that is not full text says why, (5) standard texts are labelled, (6) no private path or secret pattern is stored, and (7) the provenance
 * register lists a verified checksum for every download. It prints the coverage metrics, which the README quotes.
 */
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { buildManifest, noticeKey } from "../src/legal/manifest.ts";
import { evaluate } from "./license-check.mjs";

const root = fileURLToPath(new URL("..", import.meta.url));

/** Run all checks; returns { failures, metrics }. */
export function verify({ sbomPath = join(root, "../sbom.spdx.json"), storePath = join(root, "notices/notices.json"), lockPath = join(root, "notices/sources.lock.json") } = {}) {
const store = JSON.parse(readFileSync(storePath, "utf8"));
const manifest = buildManifest(JSON.parse(readFileSync(sbomPath, "utf8")), store);
const failures = [];
const fail = (m) => failures.push(m);

const keys = new Set(manifest.packages.map(noticeKey));
for (const k of keys) if (!store.packages[k]) fail(`no store entry for ${k}`);
for (const k of Object.keys(store.packages)) if (!keys.has(k)) fail(`stale store entry ${k} (no such SBOM component)`);

const used = new Set();
for (const [h, t] of Object.entries(store.texts)) if (createHash("sha256").update(t).digest("hex").slice(0, 16) !== h) fail(`text ${h} does not hash to its key`);
const PRIVATE = /\/Users\/|\/private\/tmp|\/tmp\/claude|AKIA[0-9A-Z]{12}|BEGIN [A-Z ]*PRIVATE KEY|ghp_[A-Za-z0-9]{20}|sk-[A-Za-z0-9_-]{20}/;
for (const [k, e] of Object.entries(store.packages)) {
  for (const f of e.files) {
    used.add(f.hash);
    if (!(f.hash in store.texts)) fail(`${k}: file ${f.name} refers to a missing text`);
  }
  if (!e.evidence) fail(`${k}: no evidence statement`);
  if (PRIVATE.test(JSON.stringify(e))) fail(`${k}: a private path or secret pattern in the entry`);
  const p = manifest.packages.find((x) => noticeKey(x) === k);
  const status = e.status ?? "VERIFIED_FULL_TEXT";
  if (status === "VERIFIED_FULL_TEXT") {
    if (!e.files.length) fail(`${k}: full text without files`);
    const ev = p?.license ? evaluate(p.license, e.files.map((f) => store.texts[f.hash] ?? "").join("\n")) : null;
    if (ev?.satisfied === false) fail(`${k}: the stored files hold no text for the declared license ${ev.missing.join(", ")}`);
    if (e.basis === "standard-text-only" && !e.files.every((f) => f.role === "standard-license-text")) fail(`${k}: standard-text-only entry holds a package file`);
    if (e.reasons?.length) fail(`${k}: full text but open reasons: ${e.reasons.join("; ")}`);
  } else if (!e.reasons?.length) fail(`${k}: ${status} without a reason`);
  if (e.files.some((f) => f.role === "standard-license-text") && !e.evidence.includes("standard text") && !e.standardTexts?.length && !e.evidence.includes("common-licenses")) fail(`${k}: a standard text without a statement where it comes from`);
}
for (const h of Object.keys(store.texts)) if (!used.has(h)) fail(`text ${h} is not used by any entry`);
for (const t of Object.values(store.texts)) if (PRIVATE.test(t)) fail("a stored text contains a private path or secret pattern");

let downloads = 0;
if (existsSync(lockPath)) {
  const lock = JSON.parse(readFileSync(lockPath, "utf8"));
  for (const [u, d] of Object.entries(lock.downloads ?? {})) { downloads++; if (d.verified === false) fail(`provenance: the checksum of ${u} did not verify`); }
} else fail(`no provenance register at ${lockPath}`);

const entries = manifest.packages.map((p) => store.packages[noticeKey(p)]).filter(Boolean);
const ordinary = manifest.packages.filter((p) => p.kind !== "Docker image");
const st = (p) => store.packages[noticeKey(p)];
const m = {
  components: manifest.packages.length,
  fullText: entries.filter((e) => (e.status ?? "VERIFIED_FULL_TEXT") === "VERIFIED_FULL_TEXT").length,
  metadataOnly: entries.filter((e) => e.status === "VERIFIED_METADATA_ONLY").length,
  unresolved: entries.filter((e) => e.status === "UNRESOLVED").length,
  ordinaryFullText: ordinary.filter((p) => (st(p)?.status ?? "VERIFIED_FULL_TEXT") === "VERIFIED_FULL_TEXT").length,
  ordinary: ordinary.length,
  standardTextOnly: entries.filter((e) => e.basis === "standard-text-only").length,
  attribution: entries.filter((e) => e.check?.attribution === true).length,
  distinctTexts: Object.keys(store.texts).length,
  downloadsInRegister: downloads,
};
return { failures, metrics: m };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const args = process.argv.slice(2);
  const opt = (n, d) => (args.includes(n) ? args[args.indexOf(n) + 1] : d);
  const o = { sbomPath: opt("--sbom", undefined), storePath: opt("--store", undefined), lockPath: opt("--lock", undefined) };
  const { failures, metrics: m } = verify(Object.fromEntries(Object.entries(o).filter(([, v]) => v)));
  if (args.includes("--json")) console.log(JSON.stringify({ ok: !failures.length, failures, metrics: m }, null, 1));
  else {
    console.log(`components ${m.components} | full text ${m.fullText} (ordinary components ${m.ordinaryFullText}/${m.ordinary}) | metadata only ${m.metadataOnly} | unresolved ${m.unresolved}`);
    console.log(`standard text only ${m.standardTextOnly} | copyright attribution evidenced ${m.attribution}/${m.components} | distinct texts ${m.distinctTexts} | downloads in the register ${m.downloadsInRegister}`);
    console.log(failures.length ? `FAILED (${failures.length}):\n  ${failures.join("\n  ")}` : "OK: store, SBOM and provenance register are consistent");
  }
  process.exit(failures.length ? 1 : 0);
}
