import type { DocumentModel, Provenance, SourceSpan } from "../types";

// Static demonstration: precomputed pipeline results for prepared documents (public/demo/, written by
// scripts/build-demo-fixtures.mjs). The PDFs are not part of the build; a PDF the user picks is matched by SHA-256.

export interface DemoDocument {
  id: string;
  title: string;
  pdfSha256: string;
  pages: number;
  profile: string;
  files: { structure: string; json: string; pipeline?: string };
  example: { label: string; modelId: string; legalJsonSchemaVersion: string };
  sources: { documentModelSha256: string; legalJsonSha256: string };
}

export interface DemoResult {
  doc: DemoDocument;
  model: DocumentModel;
  json: string; // the Legal JSON 2.0 excerpt, shown and offered for download as it is
  pipeline?: PipelineDetails | null; // absent from builds made before pipeline.json existed
}

/** A Docling text item, verbatim from docling_raw.json. */
export interface DoclingItem {
  self_ref: string;
  label: string;
  content_layer?: string;
  prov?: Provenance[];
  orig?: string;
  text?: string;
  marker?: string;
  [key: string]: unknown;
}

/** pipeline.json (scripts/build-demo-fixtures.mjs): the stages behind the previewed provision, cut from the outputs. */
export interface PipelineDetails {
  focusId: string;
  docling: {
    version: string | null;
    itemsTotal: number | null;
    itemsInModel: number | null;
    pageSizes: Record<string, { width: number; height: number } | null>;
    items: DoclingItem[];
  };
  elements: {
    id: string; type: string; region: string; parent_id: string | null; children_ids: string[]; number: string | null;
    marker: string | null; title: string | null; original_text: string; content_text: string; docling_label?: string;
    source_refs: string[]; pages: number[]; provenance: Provenance[]; source_spans?: SourceSpan[]; hygiene_flags?: string[];
  }[];
  warnings: { code: string; severity: string; message: string; element_id: string | null }[];
}

export const fixtureUrl = (path: string) => `${import.meta.env.BASE_URL}demo/${path}`;

async function fetchText(path: string): Promise<string> {
  const res = await fetch(fixtureUrl(path));
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.text();
}

/** The prepared documents of this build; empty when the build has no fixtures (a static host may answer a missing
 *  file with index.html, so anything that is not the manifest counts as missing). */
export async function loadManifest(): Promise<DemoDocument[]> {
  try {
    const m = JSON.parse(await fetchText("manifest.json")) as { documents?: DemoDocument[] };
    return Array.isArray(m.documents) ? m.documents : [];
  } catch {
    return [];
  }
}

export async function loadResult(doc: DemoDocument): Promise<DemoResult> {
  const [structure, json, pipeline] = await Promise.all([fetchText(doc.files.structure), fetchText(doc.files.json), loadPipeline(doc.files.pipeline)]);
  return { doc, model: JSON.parse(structure) as DocumentModel, json, pipeline };
}

/** The optional processing details; null when the build has none or the file cannot be read (the rest still works). */
async function loadPipeline(path: string | undefined): Promise<PipelineDetails | null> {
  if (!path) return null;
  try {
    const p = JSON.parse(await fetchText(path)) as PipelineDetails;
    return Array.isArray(p.docling?.items) && Array.isArray(p.elements) ? p : null;
  } catch {
    return null;
  }
}

export async function sha256Hex(data: ArrayBuffer): Promise<string> {
  if (!globalThis.crypto?.subtle) throw new Error("This browser cannot compute file checksums here (the page needs HTTPS or localhost).");
  const digest = await globalThis.crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

export const isPdf = (data: ArrayBuffer) => new TextDecoder().decode(new Uint8Array(data, 0, Math.min(5, data.byteLength))) === "%PDF-";

export function matchDocument(docs: DemoDocument[], sha256: string): DemoDocument | null {
  return docs.find((d) => d.pdfSha256.toLowerCase() === sha256.toLowerCase()) ?? null;
}

/** Looks the chosen PDF up among the prepared documents. Throws an Error whose message explains why a file is refused:
 *  not a PDF at all, no prepared documents in this build, or a PDF that is not one of the prepared documents. */
export async function resolveUpload(data: ArrayBuffer, fileName: string, available: DemoDocument[]): Promise<DemoDocument> {
  if (!isPdf(data)) throw new Error(`“${fileName}” is not a PDF file.`);
  if (!available.length) throw new Error("This build contains no prepared demonstration documents. Create them with npm run demo:fixtures and build again.");
  const doc = matchDocument(available, await sha256Hex(data));
  if (!doc) {
    throw new Error(
      `“${fileName}” is not one of the prepared demonstration documents. This static prototype does not process PDFs: ` +
      `it only shows previously generated ODOS results for ${available.map((d) => d.title).join(" and ")}, and recognises ` +
      "them by the exact file. Processing other documents needs the ODOS backend.",
    );
  }
  return doc;
}
