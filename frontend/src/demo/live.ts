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
  /** The backend keeps the job (database persistence, see Documentation/database-poc.md); absent from older backends. */
  persistent?: boolean;
}

/** What live mode keeps beside the DemoResult: the job (to delete it unless the backend keeps it) and the whole Legal
 *  JSON 2.0 document. */
export interface LiveData {
  jobId: string;
  persistent: boolean;
  legal: { title?: string | null; frontMatter: unknown[]; tableOfContents: unknown[]; structure: unknown[] };
}

/** A document of the backend's database as listed by GET /api/documents: metadata only. */
export interface StoredDocument {
  id: string;
  filename: string;
  status: Job["status"];
  created_at: string;
  /** The Legal JSON's documentType (e.g. "de_legislation"). Not part of GET /api/documents yet: shown when present. */
  document_type?: string | null;
}

/** User-facing wording for the stages the backend reports (Job.status / Job.stage) and the two the client adds itself
 *  ("uploading" before the job exists, "completed" once the backend has confirmed it and the results are loaded). */
export const STAGE_LABELS: Record<string, string> = {
  uploading: "Uploading document…",
  queued: "Waiting for processing to start…",
  processing: "Starting analysis…",
  extracting: "Analyzing document structure…",
  normalizing: "Preparing structured legal data…",
  completed: "Document processing complete. Opening results…",
};

export const stageLabel = (stage: string) => STAGE_LABELS[stage] ?? "Processing document…";

/** Why a job ended without a result: "unsupported" (the structure was not recognized) or "failed". */
export class ProcessingError extends Error {
  kind: "unsupported" | "failed";
  constructor(message: string, kind: "unsupported" | "failed") {
    super(message);
    this.name = "ProcessingError";
    this.kind = kind;
  }
}

/** An explanation when the file cannot be a PDF (the backend checks the content again), else null. */
export function pdfProblem(file: File): string | null {
  if (file.type !== "application/pdf" && !/\.pdf$/i.test(file.name)) return "Only PDF files can be processed. Please choose a .pdf file.";
  if (file.size === 0) return "This file is empty. Please choose another PDF.";
  return null;
}

const API = "/api";
const UNREACHABLE = "The ODOS backend is not reachable. Start it (see the README) and try again.";
export const pdfUrl = (job: string) => `${API}/jobs/${job}/pdf`;
export const fileUrl = (job: string, name: string, download = false) => `${API}/jobs/${job}/files/${name}${download ? "?download=true" : ""}`;

async function request(url: string, init?: RequestInit): Promise<Response> {
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
  return res;
}

const call = <T>(url: string, init?: RequestInit): Promise<T> => request(url, init).then((res) => res.json() as Promise<T>);

export const deleteJob = (id: string) => fetch(`${API}/jobs/${id}`, { method: "DELETE" }).catch(() => undefined);

/** Frees a job the frontend is done with; a job the backend keeps (database persistence) stays stored. */
export function releaseJob(id: string, persistent = false): void {
  if (!persistent) void deleteJob(id);
}

/** Deletes one stored document with its files. Resolves only when the backend confirms; throws the backend's
 *  explanation otherwise (e.g. while the document is still being processed). */
export async function deleteStoredDocument(id: string): Promise<void> {
  await request(`${API}/jobs/${id}`, { method: "DELETE" });
}

/** Loads a completed, stored document for the result view without processing anything: its job (which must be
 *  completed), the document model and Legal JSON, and the original PDF. Throws an Error that says what is missing. */
export async function openStoredDocument(id: string): Promise<{ result: DemoResult; pdf: Blob }> {
  const job = await call<Job>(`${API}/jobs/${id}`);
  if (job.status === "queued" || job.status === "processing") throw new Error("This document is still being processed.");
  if (job.status !== "completed") throw new Error(job.message ?? "This document has no result to open.");
  const [result, pdf] = await Promise.all([loadLiveResult(job), request(pdfUrl(id)).then((res) => res.blob())]);
  return { result, pdf };
}

/** The most recently stored documents, newest first; empty when the backend does not keep documents in its database. */
export const listDocuments = () => call<StoredDocument[]>(`${API}/documents`);

/** Uploads the PDF, polls its job until it ends and loads the results; `onStage` gets the current stage. The backend
 *  recognizes German or EU legislation itself. Throws an Error with the backend's explanation when the PDF is refused
 *  or the backend is unreachable, and a ProcessingError when its type is not recognised or processing fails. */
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
    releaseJob(job.id, job.persistent);
    throw new ProcessingError(job.message ?? "The PDF could not be processed.", job.status === "unsupported" ? "unsupported" : "failed");
  }
  onStage("completed"); // the backend has confirmed completion; only the result files are still being loaded
  return loadLiveResult(job);
}

async function loadLiveResult(job: Job): Promise<DemoResult> {
  const [model, legal] = await Promise.all([
    call<DocumentModel>(fileUrl(job.id, "document_model.json")),
    call<LiveData["legal"]>(fileUrl(job.id, "document.json")),
  ]);
  return {
    title: legal.title || model.metadata?.title || job.filename,
    filename: job.filename,
    model,
    json: toJsonText(forPresentation(legal)),
    download: { href: fileUrl(job.id, "document.json", true), name: `${job.filename.replace(/\.pdf$/i, "")}.legal.json` },
    live: { jobId: job.id, persistent: job.persistent ?? false, legal },
  };
}

/** The selected element's Legal JSON node with `nativeType` shown as `germanType`; null when the element is not a node
 *  of the document (the caller then shows the whole document). */
export function nodeJson(live: LiveData, element: DocElement | null): string | null {
  const node = element && findNode([live.legal.structure, live.legal.frontMatter, live.legal.tableOfContents], element.id);
  return node ? toJsonText(forPresentation(node)) : null;
}
