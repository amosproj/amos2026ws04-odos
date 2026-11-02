#!/usr/bin/env node
// Builds the local fixtures of the static demonstration (npm run demo:fixtures) from real ODOS pipeline outputs.
//
//   node scripts/build-demo-fixtures.mjs --eu <output dir of Regulation (EU) 2023/1230> --mbo <output dir of the MBO>
//
// Each directory is the output directory of `odos process` (see the root README) with document_model.json,
// document.json and extraction.json (docling_raw.json and validation_report.json are used when present). Nothing is
// invented: the structure is the part of the document model the demo displays (with the provenance the PDF highlighting
// uses), the Legal JSON excerpt is a Legal JSON 2.0 node cut out of document.json (see `legalExcerpt`; its ids, text and
// pages checked against the model), and pipeline.json ("Processing details") holds, verbatim, the Docling items behind
// the previewed provision and the model elements and page furniture they became. The PDFs are never copied; the demo matches the PDF the user picks against the SHA-256 recorded in
// extraction.json. The output (public/demo/) is gitignored because both
// documents are partner-supplied.
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const DOCS = [
  // `preview`: the element whose stages "Processing details" shows (default: the example)
  // `excerpt`: the Legal JSON shown and offered for download: `root` with only the path down to `nodes`, each with its subtree
  { key: "eu", id: "eu-2023-1230", title: "Regulation (EU) 2023/1230 (Machinery Regulation)", example: "doc/chp-2/art-10/para-1",
    excerpt: { root: "doc/chp-2", nodes: ["doc/chp-2/art-10/para-1", "doc/chp-2/art-10/para-2"] } },
  { key: "mbo", id: "mbo", title: "Musterbauordnung (MBO)", example: "doc/teil-2/par-6", preview: "doc/teil-2/par-6/abs-1",
    excerpt: { root: "doc/teil-2", nodes: ["doc/teil-2/par-6/abs-1", "doc/teil-2/par-6/abs-2"] } },
];
// The only fields of the document model the demo reads (src/types.ts); everything else (Docling diagnostics, derived
// search text, the original file name, ...) stays out of the demo data.
const ELEMENT_FIELDS = ["id", "type", "region", "parent_id", "children_ids", "number", "marker", "title", "original_text", "content_text",
  "source_refs", "pages", "provenance", "uncertain", "uncertainty_reasons", "source_spans", "highlight_boxes"];
const TOC_FIELDS = ["id", "marker", "title", "target_id", "status", "evidence"];
// pipeline.json: the model fields that show how the Docling items were normalized and parsed
const PIPELINE_FIELDS = ["id", "type", "region", "parent_id", "children_ids", "number", "marker", "title", "original_text", "content_text",
  "docling_label", "source_refs", "pages", "provenance", "source_spans", "hygiene_flags", "uncertain", "uncertainty_reasons"];
const MAX_DOCLING_ITEMS = 12; // the Docling items between the first and last one used, if no more than this
const pick = (o, keys) => Object.fromEntries(keys.filter((k) => o[k] !== undefined).map((k) => [k, o[k]]));

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

function findNode(node, id) {
  if (Array.isArray(node)) {
    for (const n of node) {
      const hit = findNode(n, id);
      if (hit) return hit;
    }
    return null;
  }
  if (!node || typeof node !== "object") return null;
  if (node.id === id) return node;
  return findNode(node.children ?? [], id);
}

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

// Presentation names of the demo file (temporary, for the stakeholder presentation): only the key is renamed, in place;
// values, order, ids and hierarchy stay. The Legal JSON schema and document.json keep `nativeType`.
const PRESENTATION_NAMES = { nativeType: "germanType" };

function forPresentation(node) {
  return Object.fromEntries(Object.entries(node).map(([k, v]) =>
    [PRESENTATION_NAMES[k] ?? k, k === "children" ? v.map(forPresentation) : v]));
}

/** The pipeline stages behind the previewed provision, cut verbatim from the pipeline outputs (null without docling_raw.json). */
function pipelineDetails(doc, dir, model, byId) {
  if (!existsSync(join(dir, "docling_raw.json"))) return null;
  const raw = readJson(join(dir, "docling_raw.json"));
  const focus = doc.preview ?? doc.example;
  // the example element and the path down to the previewed node, then the previewed node with all its descendants
  const ids = [];
  for (let id = focus; id && id !== doc.example; id = byId.get(id)?.parent_id) ids.unshift(id);
  if (focus !== doc.example) ids.unshift(doc.example);
  const below = (id) => [id, ...byId.get(id).children_ids.flatMap(below)];
  const elements = [...new Set([...ids, ...below(focus)])].map((id) => pick(byId.get(id), PIPELINE_FIELDS));

  // the Docling text items they come from, plus anything Docling put between them (e.g. a page footer at a page break)
  const index = (ref) => Number(/^#\/texts\/(\d+)$/.exec(ref)?.[1] ?? NaN);
  const used = [...new Set(elements.flatMap((e) => e.source_refs))].map(index).filter(Number.isFinite).sort((a, b) => a - b);
  if (!used.length) return null;
  const [lo, hi] = [used[0], used[used.length - 1]];
  const range = hi - lo + 1 <= MAX_DOCLING_ITEMS ? Array.from({ length: hi - lo + 1 }, (_, i) => lo + i) : used;
  const items = range.map((i) => raw.texts[i]).filter(Boolean);
  const pages = [...new Set(items.flatMap((t) => (t.prov ?? []).map((p) => p.page_no)))].sort((a, b) => a - b);

  const inScope = new Set(elements.map((e) => e.id));
  const report = existsSync(join(dir, "validation_report.json")) ? readJson(join(dir, "validation_report.json")) : null;
  return {
    focusId: focus,
    docling: {
      version: model.source.docling_version ?? raw.version,
      itemsTotal: report?.docling_items_total ?? null,
      itemsInModel: report?.docling_items_in_model ?? null,
      pageSizes: Object.fromEntries(pages.map((p) => [p, raw.pages?.[p]?.size ?? null])),
      items,
    },
    elements,
    warnings: (model.warnings ?? []).filter((w) => inScope.has(w.element_id)),
  };
}

function build(doc, dir) {
  for (const f of ["document_model.json", "document.json", "extraction.json"]) {
    if (!existsSync(join(dir, f))) throw new Error(`${doc.key}: ${join(dir, f)} is missing`);
  }
  const extraction = readJson(join(dir, "extraction.json"));
  const model = readJson(join(dir, "document_model.json"));
  const legal = readJson(join(dir, "document.json"));
  if (legal.schemaVersion !== "2.0") throw new Error(`${doc.key}: document.json is Legal JSON ${legal.schemaVersion}; the demo shows 2.0 (run the pipeline again)`);

  const byId = new Map(model.elements.map((e) => [e.id, e]));
  const el = byId.get(doc.example);
  if (!el) throw new Error(`${doc.key}: ${doc.example} is not in document_model.json`);
  const parent = el.parent_id ? byId.get(el.parent_id) : null;
  const label = [parent?.type === "article" ? parent.marker : null, el.marker, el.title].filter(Boolean).join(" ");

  const node = findNode(legal.structure, doc.example);
  if (!node) throw new Error(`${doc.key}: ${doc.example} is not in document.json`);
  if (doc.preview && !findNode([node], doc.preview)) throw new Error(`${doc.key}: ${doc.preview} is not below ${doc.example} in document.json`);
  const excerpt = legalExcerpt(doc, legal);
  if (!findNode([excerpt], doc.example)) throw new Error(`${doc.key}: ${doc.example} is not in the excerpt below ${doc.excerpt.root}`);
  checkAgainstModel(doc.key, excerpt, byId);

  const structure = {
    ...(model.profile ? { profile: model.profile } : {}),
    source: { num_pages: model.source.num_pages },
    root_id: model.root_id,
    elements: model.elements.map((e) => pick(e, ELEMENT_FIELDS)),
    ...(model.toc_entries ? { toc_entries: model.toc_entries.map((t) => pick(t, TOC_FIELDS)) } : {}),
  };
  const pipeline = pipelineDetails(doc, dir, model, byId);
  const files = {
    structure: `${doc.id}/structure.json`,
    json: `${doc.id}/${doc.excerpt.root.replace(/^doc\//, "").replace(/\//g, "_")}.legal.json`,
    ...(pipeline ? { pipeline: `${doc.id}/pipeline.json` } : {}),
  };
  mkdirSync(join(OUT, doc.id), { recursive: true });
  writeFileSync(join(OUT, files.structure), JSON.stringify(structure));
  // page lists on one line ("pages": [9, 10]), the rest as JSON.stringify writes it
  const excerptText = JSON.stringify(forPresentation(excerpt), null, 2).replace(/\[\s+(\d+(?:,\s+\d+)*)\s+\]/g, (_m, ns) => `[${ns.split(/,\s+/).join(", ")}]`);
  writeFileSync(join(OUT, files.json), excerptText + "\n");
  if (pipeline) writeFileSync(join(OUT, files.pipeline), JSON.stringify(pipeline, null, 2) + "\n");
  else console.log(`${doc.key}: no docling_raw.json, so no processing details (pipeline.json)`);

  console.log(`${doc.key}: ${model.elements.length} elements, example ${label} (${doc.example})`);
  return {
    id: doc.id,
    title: doc.title,
    pdfSha256: extraction.pdf_sha256,
    pages: model.source.num_pages,
    profile: model.profile ?? "german_law",
    files,
    example: {
      label,
      modelId: doc.example,
      legalJsonSchemaVersion: legal.schemaVersion,
    },
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
