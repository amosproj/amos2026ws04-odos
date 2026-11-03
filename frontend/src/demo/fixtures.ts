import type { DocumentModel } from "../types";
import type { LiveData } from "./live";

// Prepared examples: precomputed pipeline results for prepared documents (public/demo/, written by
// scripts/build-demo-fixtures.mjs), shown only when the user picks the example mode. The PDFs are not part of the
// build; the PDF the user picks is matched by SHA-256.

export interface DemoDocument {
  id: string;
  title: string;
  pdfSha256: string;
  files: { structure: string; json: string };
}

/** What the result view shows, from the backend (`live`) or from the prepared fixtures. */
export interface DemoResult {
  title: string;
  model: DocumentModel;
  json: string; // the Legal JSON preview: the prepared excerpt as the downloaded file, or the live document (presentation names)
  download: { href: string; name: string }; // the complete document (live) or the excerpt (prepared), as generated
  live?: LiveData; // set when the ODOS backend processed the PDF (src/demo/live.ts)
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
  const [structure, json] = await Promise.all([fetchText(doc.files.structure), fetchText(doc.files.json)]);
  return { title: doc.title, model: JSON.parse(structure) as DocumentModel, json, download: { href: fixtureUrl(doc.files.json), name: doc.files.json.split("/").pop()! } };
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
      `“${fileName}” is not one of the prepared demonstration documents. The prepared example mode does not process PDFs: ` +
      `it only shows previously generated ODOS results for ${available.map((d) => d.title).join(" and ")}, and recognises ` +
      "them by the exact file. To process this PDF, open ODOS without ?example.",
    );
  }
  return doc;
}
