#!/usr/bin/env node
// Builds the local fixtures of the static demonstration (npm run demo:fixtures) from real ODOS pipeline outputs.
//
//   node scripts/build-demo-fixtures.mjs --eu <output dir of Regulation (EU) 2023/1230> --mbo <output dir of the MBO>
//
// Each directory is the output directory of `odos process` (see the root README) with document_model.json,
// document.json and extraction.json. Nothing is invented: the structure is the part of the document model the demo
// displays (with the provenance the PDF highlighting uses), and the Legal JSON excerpt is a Legal JSON 2.0 node cut out
// of document.json (see `legalExcerpt`; its ids, text and pages checked against the model). The PDFs are never copied;
// the demo matches the PDF the user picks against the SHA-256 recorded in extraction.json. The output (public/demo/) is
// gitignored because both documents are partner-supplied.
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { findNode, forPresentation, pick, toJsonText } from "../src/demo/excerpts.mjs";

const DOCS = [
  // `excerpt`: the Legal JSON shown and offered for download: `root` with only the path down to `nodes`, each with its subtree
  { key: "eu", id: "eu-2023-1230", title: "Regulation (EU) 2023/1230 (Machinery Regulation)",
    excerpt: { root: "doc/chp-2", nodes: ["doc/chp-2/art-10/para-1", "doc/chp-2/art-10/para-2"] } },
  { key: "mbo", id: "mbo", title: "Musterbauordnung (MBO)",
    excerpt: { root: "doc/teil-2", nodes: ["doc/teil-2/par-6/abs-1", "doc/teil-2/par-6/abs-2"] } },
];
// The only fields of the document model the demo reads (src/types.ts); everything else (Docling diagnostics, derived
// search text, the original file name, ...) stays out of the demo data.
const ELEMENT_FIELDS = ["id", "type", "region", "parent_id", "children_ids", "number", "marker", "title", "original_text", "content_text",
  "source_refs", "pages", "provenance", "uncertain", "uncertainty_reasons", "source_spans", "highlight_boxes"];
const TOC_FIELDS = ["id", "marker", "title", "target_id", "status", "evidence"];

const OUT = resolve(dirname(fileURLToPath(import.meta.url)), "../public/demo");

function args() {
  const a = process.argv.slice(2);
  const dirs = {};
  for (let i = 0; i < a.length; i += 2) {
    if (!a[i].startsWith("--") || !a[i + 1]) usage(`unexpected argument ${a[i]}`);
    dirs[a[i].slice(2)] = resolve(a[i + 1]);
  }
  for (const d of DOCS) if (!dirs[d.key]) usage(`missing --${d.key}`);
  return dirs;
}

function usage(msg) {
  console.error(`${msg}\nusage: node scripts/build-demo-fixtures.mjs ${DOCS.map((d) => `--${d.key} <pipeline output dir>`).join(" ")}`);
  process.exit(2);
}

const readJson = (p) => JSON.parse(readFileSync(p, "utf-8"));
const sha256 = (s) => createHash("sha256").update(s).digest("hex");

const norm = (s) => s.replace(/\u00ad/g, "").replace(/\s+/g, " ").trim();

/** Throws unless every node of the excerpt is a model element (the PDF highlighting finds its source there) with the
 *  model's marker, title, text and pages. */
function checkAgainstModel(key, node, byId) {
  const el = byId.get(node.id);
  if (!el) throw new Error(`${key}: ${node.id} of document.json is not an element of document_model.json`);
  for (const [k, v] of [["marker", el.marker], ["title", el.title], ["text", el.content_text]]) {
    if (node[k] != null && norm(node[k]) !== norm(v ?? "")) throw new Error(`${key}: ${node.id} ${k} differs between document.json and document_model.json`);
  }
  if (JSON.stringify(node.pages ?? []) !== JSON.stringify(el.pages)) throw new Error(`${key}: ${node.id} pages differ between document.json and document_model.json`);
  for (const c of node.children ?? []) checkAgainstModel(key, c, byId);
}

/** The Legal JSON 2.0 excerpt of `excerpt`: the root node of document.json with only the path down to each of
 *  `excerpt.nodes`, which keep their complete subtrees. Nodes are copied unchanged (all their fields, in their order);
 *  only children off that path are left out. */
function legalExcerpt(doc, legal) {
  const root = findNode(legal.structure, doc.excerpt.root);
  if (!root) throw new Error(`${doc.key}: ${doc.excerpt.root} is not in document.json`);
  for (const id of doc.excerpt.nodes) if (!findNode([root], id)) throw new Error(`${doc.key}: ${id} is not below ${doc.excerpt.root} in document.json`);
  const shown = new Set(doc.excerpt.nodes);
  const leadsTo = (n) => shown.has(n.id) || (n.children ?? []).some(leadsTo);
  const cut = (n) => {
    if (shown.has(n.id) || !n.children) return n;
    const { children, ...rest } = n;
    return { ...rest, children: children.filter(leadsTo).map(cut) };
  };
  return cut(root);
}

function build(doc, dir) {
  for (const f of ["document_model.json", "document.json", "extraction.json"]) {
    if (!existsSync(join(dir, f))) throw new Error(`${doc.key}: ${join(dir, f)} is missing`);
  }
  const extraction = readJson(join(dir, "extraction.json"));
  const model = readJson(join(dir, "document_model.json"));
  const legal = readJson(join(dir, "document.json"));
  if (legal.schemaVersion !== "2.0") throw new Error(`${doc.key}: document.json is Legal JSON ${legal.schemaVersion}; the demo shows 2.0 (run the pipeline again)`);

  const excerpt = legalExcerpt(doc, legal);
  checkAgainstModel(doc.key, excerpt, new Map(model.elements.map((e) => [e.id, e])));

  const structure = {
    ...(model.profile ? { profile: model.profile } : {}),
    source: { num_pages: model.source.num_pages },
    root_id: model.root_id,
    elements: model.elements.map((e) => pick(e, ELEMENT_FIELDS)),
    ...(model.toc_entries ? { toc_entries: model.toc_entries.map((t) => pick(t, TOC_FIELDS)) } : {}),
  };
  const files = {
    structure: `${doc.id}/structure.json`,
    json: `${doc.id}/${doc.excerpt.root.replace(/^doc\//, "").replace(/\//g, "_")}.legal.json`,
  };
  mkdirSync(join(OUT, doc.id), { recursive: true });
  writeFileSync(join(OUT, files.structure), JSON.stringify(structure));
  writeFileSync(join(OUT, files.json), toJsonText(forPresentation(excerpt)) + "\n");

  console.log(`${doc.key}: ${model.elements.length} elements, excerpt ${doc.excerpt.root}`);
  return {
    id: doc.id,
    title: doc.title,
    pdfSha256: extraction.pdf_sha256,
    pages: model.source.num_pages,
    profile: model.profile ?? "german_law",
    files,
    sources: {
      documentModelSha256: sha256(readFileSync(join(dir, "document_model.json"))),
      legalJsonSha256: sha256(readFileSync(join(dir, "document.json"))),
    },
  };
}

const dirs = args();
rmSync(OUT, { recursive: true, force: true });
const documents = DOCS.map((d) => build(d, dirs[d.key]));
writeFileSync(join(OUT, "manifest.json"), JSON.stringify({ documents }, null, 2) + "\n");
console.log(`wrote ${OUT}`);
