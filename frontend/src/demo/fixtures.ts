import type { DocumentModel } from "../types";

// Static demonstration: precomputed pipeline results for prepared documents (public/demo/, written by
// scripts/build-demo-fixtures.mjs). The PDFs are not part of the build; a PDF the user picks is matched by SHA-256.

export interface DemoDocument {
  id: string;
  title: string;
  pdfSha256: string;
  pages: number;
  profile: string;
  files: { structure: string; json: string; xml: string };
  example: { label: string; modelId: string; eId: string; aknElement: string; legalJsonSchemaVersion: string; previewId?: string };
  sources: { documentModelSha256: string; legalJsonSha256: string; aknXmlSha256: string };
}

export interface DemoResult {
  doc: DemoDocument;
  model: DocumentModel;
  json: string;
  xml: string;
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
  const [structure, json, xml] = await Promise.all([fetchText(doc.files.structure), fetchText(doc.files.json), fetchText(doc.files.xml)]);
  return { doc, model: JSON.parse(structure) as DocumentModel, json, xml };
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

/** The complete subtree of the node `id` of a Legal JSON excerpt, printed like the downloaded file (2-space indent,
 *  keys in their original order); null when the node is not in the excerpt. */
export function jsonSubtree(json: string, id: string): string | null {
  const find = (n: unknown): unknown => {
    if (!n || typeof n !== "object") return null;
    if ((n as { id?: unknown }).id === id) return n;
    for (const c of (n as { children?: unknown[] }).children ?? []) {
      const hit = find(c);
      if (hit) return hit;
    }
    return null;
  };
  try {
    const node = find(JSON.parse(json));
    return node ? JSON.stringify(node, null, 2) : null;
  } catch {
    return null;
  }
}

/** The first `maxLines` lines of an artifact excerpt and how many lines were left out. */
export function previewLines(text: string, maxLines: number): { text: string; hidden: number } {
  const lines = text.replace(/\n$/, "").split("\n");
  return { text: lines.slice(0, maxLines).join("\n"), hidden: Math.max(0, lines.length - maxLines) };
}
