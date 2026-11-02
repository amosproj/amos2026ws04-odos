#!/usr/bin/env node
// Creates the local demo fixtures (public/demo/) from your own copies of the two PDFs with the offline ODOS pipeline.
//
//   npm run demo:setup -- --mbo-pdf <MusterBauVerordnung.pdf> --eu-pdf <eu_2023_1230.pdf> [--odos <odos executable>]
//
// 1. checks that both PDFs are the exact files the demo is prepared for (SHA-256, scripts/demo-reference.json);
// 2. runs `odos process` on both (Docling extraction, parsing, Legal JSON) into .demo-work/ (git-ignored);
// 3. builds public/demo/ from those outputs (scripts/build-demo-fixtures.mjs);
// 4. compares the fixtures with the reference hashes and says whether they are identical, equivalent (Docling float noise) or different.
// The odos executable is --odos, else $ODOS_BIN, else ../backend/.venv/bin/odos, else `odos` on the PATH.
// Exit codes: 0 fixtures identical or equivalent to the reference, 1 built but different, 2 a PDF, the pipeline or the usage failed.
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { DEMO_DIR, REFERENCE, sha256File, verify } from "./demo-verify.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const FRONTEND = resolve(HERE, "..");
const WORK = join(FRONTEND, ".demo-work");

const DOCS = [
  { key: "mbo", id: "mbo", option: "mbo-pdf", mode: "german_law", name: "Musterbauordnung (MBO)" },
  { key: "eu", id: "eu-2023-1230", option: "eu-pdf", mode: "eu_legislation", name: "Regulation (EU) 2023/1230" },
];

function usage(msg) {
  console.error(`${msg}\nusage: npm run demo:setup -- --mbo-pdf <MBO PDF> --eu-pdf <EU 2023/1230 PDF> [--odos <odos executable>]`);
  process.exit(2);
}

const opts = {};
const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i += 2) {
  if (!argv[i].startsWith("--") || !argv[i + 1]) usage(`unexpected argument ${argv[i]}`);
  opts[argv[i].slice(2)] = argv[i + 1];
}
for (const d of DOCS) if (!opts[d.option]) usage(`missing --${d.option}`);

const ref = JSON.parse(readFileSync(REFERENCE, "utf-8"));

// 1. the PDFs
console.log("1/4 checking the PDFs");
for (const d of DOCS) {
  const pdf = resolve(opts[d.option]);
  if (!existsSync(pdf)) usage(`${pdf} does not exist`);
  const actual = sha256File(pdf);
  const expected = ref.documents[d.id].pdfSha256;
  if (actual !== expected) {
    console.error(`${d.name}: ${pdf}\n  is not the PDF this demo is prepared for.\n  expected SHA-256 ${expected}\n  actual   SHA-256 ${actual}`);
    process.exit(2);
  }
  console.log(`  identical  ${d.name}  ${actual.slice(0, 16)}…`);
  opts[d.option] = pdf;
}

// 2. the offline pipeline
const venvOdos = resolve(FRONTEND, "../backend/.venv/bin/odos");
const odos = opts.odos ?? process.env.ODOS_BIN ?? (existsSync(venvOdos) ? venvOdos : "odos");
console.log(`2/4 running the offline pipeline with ${odos} (the first run downloads Docling models)`);
mkdirSync(WORK, { recursive: true });
for (const d of DOCS) {
  const out = join(WORK, d.key);
  console.log(`  ${d.name} -> ${out}`);
  const r = spawnSync(odos, ["process", opts[d.option], "-o", out, "--mode", d.mode], { stdio: "inherit" });
  if (r.error) {
    console.error(`cannot run ${odos}: ${r.error.message}\nInstall the backend first (see the README) or pass --odos <path to the odos executable>.`);
    process.exit(2);
  }
  if (r.status !== 0) {
    console.error(`odos process failed for ${d.name} (exit ${r.status})`);
    process.exit(2);
  }
}

// 3. the fixtures
console.log("3/4 building public/demo/");
const build = spawnSync(process.execPath, [join(HERE, "build-demo-fixtures.mjs"), "--mbo", join(WORK, "mbo"), "--eu", join(WORK, "eu")], { stdio: "inherit" });
if (build.status !== 0) {
  console.error("building the fixtures failed");
  process.exit(2);
}

// 4. compare with the reference
console.log("4/4 comparing with the reference hashes");
const result = verify(DEMO_DIR);
console.log(result.lines.join("\n"));
if (result.ok) {
  console.log(
    result.equivalent
      ? "\nThe demo fixtures match the reference; files marked equivalent differ only by Docling's float noise (< 0.01 pt in box coordinates), " +
          "so the demo shows the same structure, text and highlights. Start the demo with: npm run dev"
      : "\nThe demo fixtures are byte-identical to the reference. Start the demo with: npm run dev",
  );
  process.exit(0);
}
console.log(
  "\nThe fixtures were built, but they do NOT match the reference: the pipeline output on this machine differs " +
    "(other Docling/torch versions or other content). The demo works, but may not show exactly the same data.\n" +
    "To use the reference data, get the exact public/demo/ folder from the person who recorded it (if the documents' licence allows it) " +
    "and check it with: npm run demo:verify",
);
process.exit(1);
