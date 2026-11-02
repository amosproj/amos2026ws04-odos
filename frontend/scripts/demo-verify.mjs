#!/usr/bin/env node
// Verifies a demo setup against the committed reference (scripts/demo-reference.json) by SHA-256.
//
//   npm run demo:verify                                         # the fixtures in public/demo/
//   npm run demo:verify -- --mbo-pdf <MBO.pdf> --eu-pdf <eu_2023_1230.pdf>   # ... and your copies of the two PDFs
//   npm run demo:verify -- --write-reference                    # maintainers: record the current fixtures as the reference
//
// The reference holds only hashes (no document text), so it is safe to commit. It answers two different questions:
//   * PDFs: is this the exact file the prepared results belong to? (the demo itself also matches an uploaded PDF by this hash)
//   * fixtures: are the files in public/demo/ byte-identical to the ones the reference was recorded from?
// Docling is not byte-deterministic: re-running the pipeline can move a table or picture box by about 1e-5 points (observed
// here: 1 of 3 runs of the EU regulation). Such a file is reported as "equivalent" when its content is exactly the same after
// rounding all numbers to 0.01 pt (canonical SHA-256); text, structure and every other value must still match exactly. In
// manifest.json the `sources` hashes (of whole pipeline outputs, which carry that noise) are left out of the canonical form.
// A "DIFFERENT" file means this machine shows other data than the reference; it does not mean the demo is broken.
// Exit codes: 0 everything identical or equivalent, 1 a hash differs, 2 something is missing or the usage is wrong.
import { createHash } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
export const DEMO_DIR = resolve(HERE, "../public/demo");
export const REFERENCE = join(HERE, "demo-reference.json");

const sha256 = (data) => createHash("sha256").update(data).digest("hex");
export const sha256File = (p) => sha256(readFileSync(p));

/** SHA-256 of a JSON file with every number rounded to 0.01 (and, for the manifest, without the `sources` hashes);
 *  null for files that are not JSON. */
export function canonicalSha256(path) {
  if (!path.endsWith(".json")) return null;
  const isManifest = path.endsWith("manifest.json");
  const value = JSON.parse(readFileSync(path, "utf-8"), (k, v) => (isManifest && k === "sources" ? undefined : v));
  return sha256(JSON.stringify(value, (_k, v) => (typeof v === "number" ? Math.round(v * 100) / 100 : v)));
}

function parseArgs(argv) {
  const opts = { flags: new Set() };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--write-reference") opts.flags.add("write");
    else if (a === "--mbo-pdf" || a === "--eu-pdf" || a === "--dir") {
      if (!argv[i + 1]) fail(`${a} needs a value`);
      opts[a.slice(2)] = resolve(argv[++i]);
    } else fail(`unexpected argument ${a}`);
  }
  return opts;
}

function fail(msg) {
  console.error(`${msg}\nusage: node scripts/demo-verify.mjs [--mbo-pdf <pdf>] [--eu-pdf <pdf>] [--dir <demo dir>] [--write-reference]`);
  process.exit(2);
}

const PDF_OPTION = { mbo: "mbo-pdf", "eu-2023-1230": "eu-pdf" };

const fileEntry = (path) => ({ sha256: sha256File(path), ...(canonicalSha256(path) ? { canonicalSha256: canonicalSha256(path) } : {}) });

function writeReference(dir) {
  const manifest = JSON.parse(readFileSync(join(dir, "manifest.json"), "utf-8"));
  const previous = existsSync(REFERENCE) ? JSON.parse(readFileSync(REFERENCE, "utf-8")) : {};
  const documents = {};
  for (const d of manifest.documents) {
    documents[d.id] = { title: d.title, pdfSha256: d.pdfSha256, files: Object.fromEntries(Object.values(d.files).map((f) => [f, fileEntry(join(dir, f))])) };
  }
  const ref = {
    comment: "SHA-256 hashes only (no document text). Written by `npm run demo:verify -- --write-reference`; see the README.",
    retrievalDate: previous.retrievalDate ?? "2026-10-27",
    manifest: fileEntry(join(dir, "manifest.json")),
    documents,
  };
  writeFileSync(REFERENCE, JSON.stringify(ref, null, 2) + "\n");
  console.log(`wrote ${REFERENCE}`);
}

/** Returns { ok, differs, missing, equivalent, lines }. `pdfs` maps a document id to a PDF path (optional). */
export function verify(dir, pdfs = {}) {
  const ref = JSON.parse(readFileSync(REFERENCE, "utf-8"));
  const lines = [];
  const state = { differs: false, missing: false, equivalent: false };
  const checkPdf = (label, path, expected) => {
    if (!existsSync(path)) return void (lines.push(`  MISSING    ${label}`), (state.missing = true));
    const actual = sha256File(path);
    if (actual === expected) lines.push(`  identical  ${label}  ${actual.slice(0, 16)}…`);
    else {
      lines.push(`  DIFFERENT  ${label}\n               expected ${expected}\n               actual   ${actual}`);
      state.differs = true;
    }
  };
  const checkFile = (label, path, expected) => {
    if (!existsSync(path)) return void (lines.push(`  MISSING    ${label}`), (state.missing = true));
    const actual = sha256File(path);
    if (actual === expected.sha256) return void lines.push(`  identical  ${label}  ${actual.slice(0, 16)}…`);
    if (expected.canonicalSha256 && canonicalSha256(path) === expected.canonicalSha256) {
      lines.push(`  equivalent ${label}  (bytes differ, content equal after rounding numbers to 0.01)`);
      state.equivalent = true;
      return;
    }
    lines.push(`  DIFFERENT  ${label}\n               expected ${expected.sha256}\n               actual   ${actual}`);
    state.differs = true;
  };
  for (const [id, d] of Object.entries(ref.documents)) {
    lines.push(`${d.title}`);
    if (pdfs[id]) checkPdf(`PDF ${pdfs[id]}`, pdfs[id], d.pdfSha256);
    else lines.push(`  (PDF not checked: pass --${PDF_OPTION[id]} <file>)`);
    for (const [f, entry] of Object.entries(d.files)) checkFile(`fixture ${f}`, join(dir, f), entry);
  }
  lines.push("manifest");
  checkFile("fixture manifest.json", join(dir, "manifest.json"), ref.manifest);
  return { ok: !state.differs && !state.missing, ...state, lines };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const opts = parseArgs(process.argv.slice(2));
  const dir = opts.dir ?? DEMO_DIR;
  if (opts.flags.has("write")) {
    if (!existsSync(join(dir, "manifest.json"))) fail(`${dir}/manifest.json is missing: run npm run demo:setup first`);
    writeReference(dir);
  } else {
    const r = verify(dir, { mbo: opts["mbo-pdf"], "eu-2023-1230": opts["eu-pdf"] });
    console.log(r.lines.join("\n"));
    if (r.ok && !r.equivalent) console.log("\nAll checked files are byte-identical to the reference.");
    else if (r.ok) console.log("\nAll checked files match the reference; the ones marked equivalent differ only by Docling's float noise (< 0.01 pt in box coordinates).");
    else if (r.missing) console.log("\nSome files are missing: create them with npm run demo:setup (see the README).");
    else console.log("\nSome files differ from the reference: this machine shows other data than the reference setup (see the README).");
    process.exit(r.missing ? 2 : r.differs ? 1 : 0);
  }
}
