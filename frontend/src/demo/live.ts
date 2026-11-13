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
  ruleJson: unknown | null;
  ruleDownload: { href: string; name: string };
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

async function callOptional<T>(url: string): Promise<T | null> {
  let res: Response;
  try {
    res = await fetch(url);
  } catch {
    throw new Error(UNREACHABLE);
  }
  if (res.status === 404) return null;
  if (!res.ok) {
    const detail = await res.json().then((b: { detail?: unknown }) => (typeof b.detail === "string" ? b.detail : null), () => null);
    throw new Error(detail ?? (res.status >= 500 ? UNREACHABLE : `The request failed (HTTP ${res.status}).`));
  }
  return res.json() as Promise<T>;
}

export const deleteJob = (id: string) => fetch(`${API}/jobs/${id}`, { method: "DELETE" }).catch(() => undefined);

/** Frees a job the frontend is done with; a job the backend keeps (database persistence) stays stored. */
export function releaseJob(id: string, persistent = false): void {
  if (!persistent) void deleteJob(id);
}

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
    releaseJob(job.id, job.persistent);
    throw new Error(job.message ?? "The PDF could not be processed.");
  }
  return loadLiveResult(job);
}

async function loadLiveResult(job: Job): Promise<DemoResult> {
  const [model, legal, ruleJson] = await Promise.all([
    call<DocumentModel>(fileUrl(job.id, "document_model.json")),
    call<LiveData["legal"]>(fileUrl(job.id, "document.json")),
    callOptional<unknown>(fileUrl(job.id, "rules.json")),
  ]);
  const stem = job.filename.replace(/\.pdf$/i, "");
  return {
    title: legal.title || model.metadata?.title || job.filename,
    model,
    json: toJsonText(forPresentation(legal)),
    download: { href: fileUrl(job.id, "document.json", true), name: `${stem}.legal.json` },
    live: {
      jobId: job.id,
      persistent: job.persistent ?? false,
      legal,
      ruleJson,
      ruleDownload: { href: fileUrl(job.id, "rules.json", true), name: `${stem}.rules.json` },
    },
  };
}

/** Accept an array of individual Rule JSON records, a `{ rules }` collection, or a single record. */
export function ruleEntries(data: unknown): Record<string, unknown>[] {
  if (Array.isArray(data)) return data.filter(isRuleRecord);
  if (!data || typeof data !== "object") return [];
  const record = data as Record<string, unknown>;
  if (Array.isArray(record.rules)) return record.rules.filter(isRuleRecord);
  return isRuleRecord(record) ? [record] : [];
}

function isRuleRecord(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return typeof record.id === "string" && typeof record.type === "string" && Array.isArray(record.source);
}

/** Rule records map to any Legal JSON element through their stable source element IDs. */
export function rulesForElement(data: unknown, elementId: string | null): Record<string, unknown>[] {
  if (!elementId) return [];
  return ruleEntries(data).filter((rule) => {
    const sources = rule.source;
    return Array.isArray(sources) && sources.some((source) =>
      !!source && typeof source === "object" && (source as Record<string, unknown>).elementId === elementId,
    );
  });
}

/** The selected element's Legal JSON node with `nativeType` shown as `germanType`; null when the element is not a node
 *  of the document (the caller then shows the whole document). */
export function nodeJson(live: LiveData, element: DocElement | null): string | null {
  const node = element && findNode([live.legal.structure, live.legal.frontMatter, live.legal.tableOfContents], element.id);
  return node ? toJsonText(forPresentation(node)) : null;
}
