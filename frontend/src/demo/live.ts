import type { DocElement, DocumentModel } from "../types";
import { findNode, forPresentation, toJsonText } from "./excerpts.mjs";
import type { DemoResult } from "./fixtures";

// Live mode: the uploaded PDF is processed by the ODOS backend (backend/src/odos/api.py, reached under /api through
// the Vite proxy). The result view reads the job's document model and Legal JSON 2.0.

export interface Job {
  id: string;
  filename: string;
  status: "queued" | "processing" | "completed" | "unsupported" | "failed";
  stage: string | null;
  message: string | null;
}

/** What live mode keeps beside the DemoResult: the job (to delete it) and the whole Legal JSON 2.0 document. */
export interface LiveData {
  jobId: string;
  legal: { title?: string | null; frontMatter: unknown[]; tableOfContents: unknown[]; structure: unknown[] };
}

export const STAGE_LABELS: Record<string, string> = {
  uploading: "Uploading…",
  queued: "Waiting for the processor…",
  processing: "Processing…",
  extracting: "Extracting the PDF with Docling…",
  normalizing: "Recognizing the legal structure…",
};

const API = "/api";
const UNREACHABLE = "The ODOS backend is not reachable. Start it (see the README) and try again.";
export const fileUrl = (job: string, name: string, download = false) => `${API}/jobs/${job}/files/${name}${download ? "?download=true" : ""}`;

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    throw new Error(UNREACHABLE);
  }
  if (!res.ok) {
    const detail = await res.json().then((b: { detail?: unknown }) => (typeof b.detail === "string" ? b.detail : null), () => null);
    throw new Error(detail ?? (res.status >= 500 ? UNREACHABLE : `The request failed (HTTP ${res.status}).`));
  }
  return res.json() as Promise<T>;
}

export const deleteJob = (id: string) => fetch(`${API}/jobs/${id}`, { method: "DELETE" }).catch(() => undefined);

/** Uploads the PDF, polls its job until it ends and loads the results; `onStage` gets the current stage. The backend
 *  recognizes German or EU legislation itself. Throws an Error with the backend's explanation when the PDF is refused,
 *  its type is not recognised or processing fails. */
export async function processPdf(file: File, onStage: (stage: string) => void): Promise<DemoResult> {
  onStage("uploading");
  const form = new FormData();
  form.append("file", file);
  let job = await call<Job>(`${API}/jobs`, { method: "POST", body: form });
  while (job.status === "queued" || job.status === "processing") {
    onStage(job.stage ?? job.status);
    await new Promise((r) => setTimeout(r, 1000));
    job = await call<Job>(`${API}/jobs/${job.id}`);
  }
  if (job.status !== "completed") {
    void deleteJob(job.id);
    throw new Error(job.message ?? "The PDF could not be processed.");
  }
  return loadLiveResult(job);
}

async function loadLiveResult(job: Job): Promise<DemoResult> {
  const [model, legal] = await Promise.all([
    call<DocumentModel>(fileUrl(job.id, "document_model.json")),
    call<LiveData["legal"]>(fileUrl(job.id, "document.json")),
  ]);
  return {
    title: legal.title || model.metadata?.title || job.filename,
    model,
    json: toJsonText(forPresentation(legal)),
    download: { href: fileUrl(job.id, "document.json", true), name: `${job.filename.replace(/\.pdf$/i, "")}.legal.json` },
    live: { jobId: job.id, legal },
  };
}

/** The selected element's Legal JSON node with `nativeType` shown as `germanType`; null when the element is not a node
 *  of the document (the caller then shows the whole document). */
export function nodeJson(live: LiveData, element: DocElement | null): string | null {
  const node = element && findNode([live.legal.structure, live.legal.frontMatter, live.legal.tableOfContents], element.id);
  return node ? toJsonText(forPresentation(node)) : null;
}
