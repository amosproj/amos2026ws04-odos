#!/usr/bin/env node
// Builds the local fixtures of the static demonstration (npm run demo:fixtures) from real ODOS pipeline outputs.
//
//   node scripts/build-demo-fixtures.mjs --eu <output dir of Regulation (EU) 2023/1230> --mbo <output dir of the MBO>
//
// Each directory is the output directory of `odos process` (see the root README) with
// document_model.json, document.json, document_akn.xml, akn_traceability.json and extraction.json. Nothing is
// invented: the structure is the part of the document model the demo displays, and the two artifact excerpts are the
// same provision cut out of document.json and document_akn.xml. The PDFs are never copied; the demo matches the PDF the
// user picks against the SHA-256 recorded in extraction.json. The output (public/demo/) is gitignored because both
// documents are partner-supplied.
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const DOCS = [
  { key: "eu", id: "eu-2023-1230", title: "Regulation (EU) 2023/1230 (Machinery Regulation)", example: "doc/chp-2/art-10/para-1" },
  // `preview`: the node of the Legal JSON whose complete subtree the demo shows as its preview (default: the example)
  { key: "mbo", id: "mbo", title: "Musterbauordnung (MBO)", example: "doc/teil-2/par-6", preview: "doc/teil-2/par-6/abs-1" },
];
// The only fields of the document model the demo reads (src/types.ts); everything else (Docling diagnostics, derived
// search text, the original file name, ...) stays out of the demo data.
const ELEMENT_FIELDS = ["id", "type", "region", "parent_id", "children_ids", "number", "marker", "title", "original_text", "content_text",
  "source_refs", "pages", "provenance", "uncertain", "uncertainty_reasons", "source_spans", "highlight_boxes"];
const TOC_FIELDS = ["id", "marker", "title", "target_id", "status", "evidence"];
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

/** The element with this eId, verbatim from the XML text (start tag to its matching end tag), dedented and carrying the
 *  root's namespace declarations so the excerpt parses on its own (as lxml serializes a sub-element). */
function xmlElement(xml, eId) {
  const start = xml.search(new RegExp(`<([A-Za-z][\\w.-]*)\\b[^>]*\\beId="${eId}"`));
  if (start < 0) throw new Error(`eId ${eId} not found in document_akn.xml`);
  const tag = /^<([A-Za-z][\w.-]*)/.exec(xml.slice(start))[1];
  const re = new RegExp(`<${tag}\\b[^>]*?(/?)>|</${tag}>`, "g");
  re.lastIndex = start;
  let depth = 0;
  for (let m; (m = re.exec(xml)); ) {
    if (m[0].startsWith("</")) depth--;
    else if (m[1] !== "/") depth++;
    if (depth > 0) continue;
    const indent = xml.slice(xml.lastIndexOf("\n", start) + 1, start);
    let text = xml.slice(start, re.lastIndex);
    if (/^[ \t]+$/.test(indent)) text = text.split(`\n${indent}`).join("\n");
    const ns = (/<akomaNtoso\b([^>]*)>/.exec(xml)?.[1].match(/\sxmlns(:\w+)?="[^"]*"/g) ?? []).join("");
    return { tag, text: `<?xml version='1.0' encoding='UTF-8'?>\n` + text.replace(`<${tag}`, `<${tag}${ns}`) };
  }
  throw new Error(`no end tag for ${tag} ${eId}`);
}

const norm = (s) => s.replace(/\u00ad/g, "").replace(/\s+/g, " ").trim();
const xmlText = (x) => norm(x.replace(/<[^>]+>/g, " ").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&amp;/g, "&"));
function jsonTexts(n, out = []) {
  for (const k of ["marker", "title", "text"]) if (typeof n[k] === "string" && n[k]) out.push(n[k]);
  for (const c of n.children ?? []) jsonTexts(c, out);
  return out;
}

function build(doc, dir) {
  for (const f of ["document_model.json", "document.json", "document_akn.xml", "akn_traceability.json", "extraction.json"]) {
    if (!existsSync(join(dir, f))) throw new Error(`${doc.key}: ${join(dir, f)} is missing`);
  }
  const extraction = readJson(join(dir, "extraction.json"));
  const model = readJson(join(dir, "document_model.json"));
  const legal = readJson(join(dir, "document.json"));
  const xmlRaw = readFileSync(join(dir, "document_akn.xml"), "utf-8");
  const trace = readJson(join(dir, "akn_traceability.json"));

  const byId = new Map(model.elements.map((e) => [e.id, e]));
  const el = byId.get(doc.example);
  if (!el) throw new Error(`${doc.key}: ${doc.example} is not in document_model.json`);
  const parent = el.parent_id ? byId.get(el.parent_id) : null;
  const label = [parent?.type === "article" ? parent.marker : null, el.marker, el.title].filter(Boolean).join(" ");

  const node = findNode(legal.structure, doc.example);
  if (!node) throw new Error(`${doc.key}: ${doc.example} is not in document.json`);
  if (doc.preview && !findNode([node], doc.preview)) throw new Error(`${doc.key}: ${doc.preview} is not below ${doc.example} in document.json`);
  const traced = trace.nodes.find((n) => n.model_id === doc.example);
  if (!traced?.eId) throw new Error(`${doc.key}: ${doc.example} has no eId in akn_traceability.json`);
  const xml = xmlElement(xmlRaw, traced.eId);

  // the two excerpts must carry the same text: every JSON marker/title/text occurs, in order, in the XML element
  const xt = xmlText(xml.text);
  let pos = 0;
  for (const t of jsonTexts(node)) {
    const at = xt.indexOf(norm(t), pos);
    if (at < 0) throw new Error(`${doc.key}: JSON text not found in the XML excerpt (in order): ${t.slice(0, 80)}`);
    pos = at + norm(t).length;
  }

  const structure = {
    ...(model.profile ? { profile: model.profile } : {}),
    source: { num_pages: model.source.num_pages },
    root_id: model.root_id,
    elements: model.elements.map((e) => pick(e, ELEMENT_FIELDS)),
    ...(model.toc_entries ? { toc_entries: model.toc_entries.map((t) => pick(t, TOC_FIELDS)) } : {}),
  };
  const base = doc.example.replace(/^doc\//, "").replace(/\//g, "_");
  const files = {
    structure: `${doc.id}/structure.json`,
    json: `${doc.id}/${base}.legal.json`,
    xml: `${doc.id}/${base}.akn.xml`,
  };
  mkdirSync(join(OUT, doc.id), { recursive: true });
  writeFileSync(join(OUT, files.structure), JSON.stringify(structure));
  writeFileSync(join(OUT, files.json), JSON.stringify(node, null, 2) + "\n");
  writeFileSync(join(OUT, files.xml), xml.text + "\n");

  console.log(`${doc.key}: ${model.elements.length} elements, example ${label} (${doc.example} = <${xml.tag} eId="${traced.eId}">)`);
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
      eId: traced.eId,
      aknElement: xml.tag,
      legalJsonSchemaVersion: legal.schemaVersion,
      ...(doc.preview ? { previewId: doc.preview } : {}),
    },
    sources: {
      documentModelSha256: sha256(readFileSync(join(dir, "document_model.json"))),
      legalJsonSha256: sha256(readFileSync(join(dir, "document.json"))),
      aknXmlSha256: sha256(xmlRaw),
    },
  };
}

const dirs = args();
rmSync(OUT, { recursive: true, force: true });
const documents = DOCS.map((d) => build(d, dirs[d.key]));
writeFileSync(join(OUT, "manifest.json"), JSON.stringify({ documents }, null, 2) + "\n");
console.log(`wrote ${OUT}`);
