import type { DocElement, DocumentModel } from "../types";
import { findNode, forPresentation, toJsonText } from "./excerpts.mjs";
import type { DemoResult } from "./fixtures";

// Live mode: the uploaded PDF is processed by the ODOS backend (backend/src/odos/api.py, reached under /api through
// the Vite proxy). The result view reads the job's document model and Legal JSON 2.0.

export interface Job {
  id: string;
  filename: string;
  status: "queued" | "processing" | "completed" | "unsupported" | "failed" | "cancelled";
  stage: string | null;
  message: string | null;
  /** Set while a running stage has been asked to stop. */
  cancelRequested?: boolean;
  /** The backend keeps the job (database persistence, see Documentation/database-poc.md); absent from older backends. */
  persistent?: boolean;
}

/** What live mode keeps beside the DemoResult: the job (to delete it unless the backend keeps it) and the whole Legal
 *  JSON 2.0 document. */
export interface LiveData {
  jobId: string;
  persistent: boolean;
  legal: { title?: string | null; frontMatter: unknown[]; tableOfContents: unknown[]; structure: unknown[] };
  llmInputV1?: unknown | null;
  llmInputV2?: unknown | null;
  llmInputReport?: { characters?: Record<string, number>; applicability?: { policy?: string | null; removed?: unknown[] } } | null;
  ruleJson: unknown | null;
  ruleDownload: { href: string; name: string };
}

/** A document of the backend's database as listed by GET /api/documents: metadata only. */
export interface StoredDocument {
  id: string;
  filename: string;
  status: Job["status"];
  stage?: string | null;
  /** Set when the database recorded one. A cancellation stored as failed begins with "Processing was cancelled". */
  message?: string | null;
  created_at: string;
  /** The Legal JSON's documentType (e.g. "de_legislation"). Not part of GET /api/documents yet: shown when present. */
  document_type?: string | null;
}

/** User-facing wording for the stages the backend reports (Job.status / Job.stage) and the two the client adds itself
 *  ("uploading" before the job exists, "completed" once the backend has confirmed it and the results are loaded). */
export const STAGE_LABELS: Record<string, string> = {
  uploading: "Uploading document",
  queued: "Waiting to start",
  processing: "Reading your document",
  extracting: "Reading your document",
  normalizing: "Preparing results",
  cancelling: "Stopping…",
  completed: "Ready",
};

export const stageLabel = (stage: string) => STAGE_LABELS[stage] ?? "Processing document";

/** The four document steps, in order. `current` is -1 when no step should be marked (for example while stopping). */
export const DOCUMENT_STEPS = ["Uploading document", "Reading your document", "Preparing results", "Ready"] as const;

export function documentStep(stage: string): number {
  if (stage === "cancelling") return -1;
  if (stage === "uploading" || stage === "queued") return 0;
  if (stage === "extracting" || stage === "processing") return 1;
  if (stage === "normalizing") return 2;
  if (stage === "completed") return 3;
  return -1;
}

/** Why a job ended without a result: "unsupported" (the structure was not recognized), "failed", or "cancelled". */
export class ProcessingError extends Error {
  kind: "unsupported" | "failed" | "cancelled";
  constructor(message: string, kind: "unsupported" | "failed" | "cancelled") {
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

/** A backend answer that was not OK; `status` lets the caller tell e.g. "already running" (409) from a real failure. */
export class HttpError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "HttpError";
    this.status = status;
  }
}

/** The backend could not be reached at all (as opposed to answering with an error). */
export class UnreachableError extends Error {
  constructor() {
    super(UNREACHABLE);
    this.name = "UnreachableError";
  }
}

async function request(url: string, init?: RequestInit): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    throw new UnreachableError();
  }
  if (!res.ok) {
    const detail = await res.json().then((b: { detail?: unknown }) => (typeof b.detail === "string" ? b.detail : null), () => null);
    throw new HttpError(detail ?? (res.status >= 500 ? UNREACHABLE : `The request failed (HTTP ${res.status}).`), res.status);
  }
  return res;
}

const call = <T>(url: string, init?: RequestInit): Promise<T> => request(url, init).then((res) => res.json() as Promise<T>);

/** Like `call`, but an optional artifact the backend does not have (404) resolves to null. */
async function callOptional<T>(url: string): Promise<T | null> {
  let res: Response;
  try {
    res = await fetch(url);
  } catch {
    throw new UnreachableError();
  }
  if (res.status === 404) return null;
  if (!res.ok) {
    const detail = await res.json().then((b: { detail?: unknown }) => (typeof b.detail === "string" ? b.detail : null), () => null);
    throw new HttpError(detail ?? (res.status >= 500 ? UNREACHABLE : `The request failed (HTTP ${res.status}).`), res.status);
  }
  return res.json() as Promise<T>;
}

export const deleteJob = (id: string) => fetch(`${API}/jobs/${id}`, { method: "DELETE" }).catch(() => undefined);

export const getJob = (id: string) => call<Job>(`${API}/jobs/${id}`);

/** Asks the backend to stop this document. A stage that has already started finishes, then its result is discarded. */
export const cancelJob = (id: string) => call<Job>(`${API}/jobs/${id}/cancel`, { method: "POST" });

/** Waits `ms`. An abort during this wait returns at once, so the first cancel is not stuck behind the poll interval.
 *  An abort that already happened does not skip later waits: the job is still polled until it has actually stopped. */
const sleep = (ms: number, signal?: AbortSignal) => new Promise<void>((resolve) => {
  const timer = setTimeout(() => { signal?.removeEventListener("abort", finish); resolve(); }, ms);
  const finish = () => { clearTimeout(timer); resolve(); };
  signal?.addEventListener("abort", finish, { once: true });
});

async function requestCancel(id: string): Promise<Job> {
  try {
    return await cancelJob(id);
  } catch (e) {
    if (e instanceof HttpError && e.status === 409) return getJob(id); // it already finished
    throw e;
  }
}

/** Polls until the job leaves queued/processing. When `signal` aborts, asks the backend to cancel and keeps polling
 *  until that cancellation is the stored status (or the job had already finished). Stage updates stop once a cancel
 *  was asked for, so a late poll cannot put the processing view back on screen. A failed cancel does not end the wait:
 *  the job may still be running, and `onCancelError` says so. */
export async function waitForJob(job: Job, onStage: (stage: string) => void, signal?: AbortSignal, onCancelError?: (message: string) => void): Promise<Job> {
  let stopping = false;
  while (job.status === "queued" || job.status === "processing") {
    if (signal?.aborted && !stopping) {
      stopping = true;
      try {
        job = await requestCancel(job.id);
      } catch (e) {
        onCancelError?.(e instanceof Error ? e.message : String(e));
      }
      if (job.status !== "queued" && job.status !== "processing") break;
      continue;
    }
    if (!stopping) onStage(job.stage ?? job.status);
    await sleep(1000, signal);
    try {
      job = await getJob(job.id);
    } catch (e) {
      if (!stopping && !signal?.aborted) throw e; // while a cancel is settling, a missed poll is retried, not reported as a failure
    }
  }
  return job;
}

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
export async function processPdf(file: File, onStage: (stage: string) => void, opts: { signal?: AbortSignal; onJob?: (job: Job) => void; onCancelError?: (message: string) => void } = {}): Promise<DemoResult> {
  onStage("uploading");
  const form = new FormData();
  form.append("file", file);
  let job = await call<Job>(`${API}/jobs`, { method: "POST", body: form });
  opts.onJob?.(job);
  job = await waitForJob(job, onStage, opts.signal, opts.onCancelError);
  if (job.status === "cancelled" || (job.status === "failed" && (job.message ?? "").startsWith("Processing was cancelled"))) {
    throw new ProcessingError(job.message ?? "Processing was cancelled.", "cancelled");
  }
  if (job.status !== "completed") {
    releaseJob(job.id, job.persistent);
    throw new ProcessingError(job.message ?? "The PDF could not be processed.", job.status === "unsupported" ? "unsupported" : "failed");
  }
  onStage("completed"); // the backend has confirmed completion; only the result files are still being loaded
  return loadLiveResult(job);
}

async function loadLiveResult(job: Job): Promise<DemoResult> {
  const [model, legal, ruleJson, llmInputV1, llmInputV2, llmInputReport] = await Promise.all([
    call<DocumentModel>(fileUrl(job.id, "document_model.json")),
    call<LiveData["legal"]>(fileUrl(job.id, "document.json")),
    callOptional<unknown>(fileUrl(job.id, "rules.json")),
    callOptional<unknown>(fileUrl(job.id, "llm_input_v1.json")),
    callOptional<unknown>(fileUrl(job.id, "llm_applicability_input_v2.json")),
    callOptional<LiveData["llmInputReport"]>(fileUrl(job.id, "llm_input_report.json")),
  ]);
  const stem = job.filename.replace(/\.pdf$/i, "");
  return {
    title: legal.title || model.metadata?.title || job.filename,
    filename: job.filename,
    model,
    json: toJsonText(forPresentation(legal)),
    download: { href: fileUrl(job.id, "document.json", true), name: `${stem}.legal.json` },
    live: {
      jobId: job.id,
      persistent: job.persistent ?? false,
      legal,
      ruleJson, llmInputV1, llmInputV2, llmInputReport,
      ruleDownload: { href: fileUrl(job.id, "rules.json", true), name: `${stem}.rules.json` },
    },
  };
}

// ── LLM rule extraction (Amazon Bedrock; POST/GET /api/jobs/{id}/rule-extraction, result = the job's rules.json) ──────

/** The backend's RuleExtraction (backend/src/odos/rule_extraction_jobs.py). Only `status` is guaranteed; the rest is
 *  what the backend reports for the run and is shown as given. */
export interface RuleExtractionStatus {
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  scope?: string[] | "document";
  requestedAt?: string;
  startedAt?: string | null;
  finishedAt?: string | null;
  /** preparing, then finding (the model request), then checking. Absent on older backends. */
  stage?: "preparing" | "finding" | "checking" | null;
  cancelRequested?: boolean;
  /** True once a model request was sent. Cancelling after that may still cost money. */
  externalRequestStarted?: boolean;
  /** Present only when the backend actually counts sections. This build does not: extraction is one request. */
  progress?: { completed?: number; total?: number } | null;
  message?: string | null;
  errorCode?: string | null;
  errorDetail?: Record<string, unknown>;
  modelId?: string | null;
  promptVersion?: string | null;
  counts?: Record<string, number>;
  rulesFile?: string | null;
}

export const RULE_STEPS = ["Preparing document", "Finding rules", "Checking results", "Ready for review"] as const;

/** Which rule step is current. -1 means stopping: no step is claimed as finished or in progress. */
export function ruleStep(status: RuleExtractionStatus): number {
  if (status.cancelRequested && (status.status === "queued" || status.status === "running")) return -1;
  if (status.stage === "checking") return 2;
  if (status.stage === "finding" || (status.status === "running" && status.stage !== "preparing")) return 1;
  if (status.status === "completed") return 3;
  return 0;
}

/** A real section count, or null. Never invents one. */
export function sectionProgress(status: RuleExtractionStatus): string | null {
  const completed = status.progress?.completed;
  const total = status.progress?.total;
  if (!Number.isInteger(completed) || !Number.isInteger(total) || total == null || completed == null) return null;
  if (total < 1 || completed < 0 || completed > total) return null;
  return `${completed} of ${total} sections`;
}

const EXTRACTION_ERRORS: Record<string, string> = {
  not_configured: "Finding rules is not available right now.",
  bedrock_auth: "Finding rules could not sign in. Try again later.",
  bedrock_throttled: "The language service is busy. Try again later.",
  bedrock_timeout: "The language service did not answer in time.",
  bedrock_unavailable: "The language service is not available.",
  too_large: "This document is too long to process in one pass.",
  bedrock_request: "The language service rejected the request.",
  model_response: "No usable answer came back. Nothing was saved.",
  output_truncated: "The answer was too long to use. Nothing was saved.",
  malformed_output: "The answer could not be read. Nothing was saved.",
  invalid_scope: "The selected part of the document could not be used.",
  interrupted: "Finding rules was interrupted. You can try again.",
  internal: "Finding rules failed.",
  bedrock_error: "Finding rules failed.",
};

/** Plain wording for a failed extraction. The code stays available separately for the advanced details. */
export function friendlyExtractionMessage(message?: string | null, code?: string | null): string {
  if (code && code !== "cancelled" && EXTRACTION_ERRORS[code]) return EXTRACTION_ERRORS[code];
  const text = message?.trim() || "Finding rules failed.";
  return text.replace(/Amazon Bedrock/g, "the language service");
}

export const extractionActive = (s: RuleExtractionStatus | null | undefined) => s?.status === "queued" || s?.status === "running";

const ruleExtractionUrl = (job: string) => `${API}/jobs/${job}/rule-extraction`;

/** Starts a rule extraction of the whole document (a paid Amazon Bedrock call; the backend refuses a second one while one
 *  is queued or running with 409). Resolves with the queued status at once; the extraction runs on the server. */
export const startRuleExtraction = (jobId: string) => call<RuleExtractionStatus>(ruleExtractionUrl(jobId), { method: "POST" });

/** Asks the backend to stop this job's rule extraction. Does not affect any other job. */
export const cancelRuleExtraction = (jobId: string) => call<RuleExtractionStatus>(`${ruleExtractionUrl(jobId)}/cancel`, { method: "POST" });

/** The latest extraction of the job; null when none was ever started. */
export const getRuleExtraction = (jobId: string) => callOptional<RuleExtractionStatus>(ruleExtractionUrl(jobId));

/** The job's stored `rules.json`; null when it has none. Reading it never starts an extraction. */
export const loadRules = (jobId: string) => callOptional<unknown>(fileUrl(jobId, "rules.json"));

/** Why waiting for an extraction stopped without a final status. The extraction itself keeps running on the server. */
export class ExtractionWaitError extends Error {
  kind: "timeout" | "connection";
  constructor(kind: "timeout" | "connection", message: string) {
    super(message);
    this.name = "ExtractionWaitError";
    this.kind = kind;
  }
}

export const EXTRACTION_POLL_MS = 2000;
/** Longest wait of one watch: the backend allows up to 10 minutes per Bedrock attempt (and retries), so a long run is normal. */
export const EXTRACTION_TIMEOUT_MS = 30 * 60 * 1000;
const POLL_FAILURES = 3; // consecutive unreachable answers before the watch gives up (the extraction goes on)

/** Polls the extraction until it is completed or failed and returns that final status. `onStatus` gets every status seen.
 *  Throws ExtractionWaitError when `timeoutMs` passes or the backend stays unreachable; resolves with the last status
 *  and never throws when `signal` is aborted (the caller left the page). */
export async function watchRuleExtraction(jobId: string, onStatus: (s: RuleExtractionStatus) => void, opts: { signal?: AbortSignal; intervalMs?: number; timeoutMs?: number } = {}): Promise<RuleExtractionStatus | null> {
  const { signal, intervalMs = EXTRACTION_POLL_MS, timeoutMs = EXTRACTION_TIMEOUT_MS } = opts;
  const deadline = Date.now() + timeoutMs;
  let failures = 0;
  let last: RuleExtractionStatus | null = null;
  for (;;) {
    if (signal?.aborted) return last;
    try {
      const status = await getRuleExtraction(jobId);
      failures = 0;
      if (!status) throw new HttpError("No rule extraction was started for this job.", 404);
      if (signal?.aborted) return last;
      last = status;
      onStatus(status);
      if (!extractionActive(status)) return status;
    } catch (e) {
      if (!(e instanceof UnreachableError || (e instanceof HttpError && e.status >= 500))) throw e; // a restarting backend is a pause, not an answer
      if (++failures >= POLL_FAILURES) throw new ExtractionWaitError("connection", "The connection to the ODOS backend was lost. The extraction may still be running on the server.");
    }
    if (Date.now() >= deadline) throw new ExtractionWaitError("timeout", "The extraction is taking longer than expected. It may still be running on the server.");
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

// ── human review of the extracted rules (GET/POST /api/jobs/{id}/rule-reviews; decisions are events in PostgreSQL) ───────

export type HumanState = "pending" | "accepted" | "rejected";
export type ReviewAction = "accept" | "reject" | "edit" | "reset";

/** The review state of one rule: the decision, whether its content was edited, and the edited record. The extracted
 *  record in `rules.json` never changes; `effectiveRule` is the reviewer's edit (null = the original is in force). */
export interface RuleReviewEntry {
  ruleSha256: string;
  state: HumanState;
  edited: boolean;
  /** Advisory result of ODOS's automated checks, not a decision. Only "flagged" and "unverified" exist so far. */
  verification: "flagged" | "unverified";
  lastEventId: number;
  reviewer: string | null;
  reason: string | null;
  at: string | null;
  effectiveRule: Record<string, unknown> | null;
}

export interface RuleReviews {
  extractionId: string;
  criteriaVersion: number;
  counts: { pending: number; accepted: number; rejected: number; edited: number };
  rules: Record<string, RuleReviewEntry>;
  /** Decisions of other extractions of this document: kept as history, never applied to these rules. */
  earlierExtractionEvents: number;
}

export interface RuleHistoryEvent {
  id: number;
  extractionId: string;
  action: ReviewAction;
  decision: HumanState;
  reviewer: string;
  reason: string | null;
  at: string;
  edited: boolean;
  ruleSha256: string;
}

export interface ReviewRequest {
  ruleId: string;
  extractionId: string;
  expectedRuleSha256: string;
  expectedLastEventId: number;
  action: ReviewAction;
  reviewer: string;
  reason?: string;
  editedRule?: Record<string, unknown>;
}

const reviewsUrl = (job: string) => `${API}/jobs/${job}/rule-reviews`;

export const getRuleReviews = (jobId: string) => call<RuleReviews>(reviewsUrl(jobId));

/** Appends one review event; resolves with the rule's new entry. Throws an HttpError whose message is the backend's
 *  explanation (409: the rule or the rules changed meanwhile, 422: invalid edit or request, 503: storage unavailable). */
export const postRuleReview = (jobId: string, body: ReviewRequest) =>
  call<RuleReviewEntry>(reviewsUrl(jobId), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const getRuleHistory = (jobId: string, ruleId: string) => call<RuleHistoryEvent[]>(`${reviewsUrl(jobId)}/history?ruleId=${encodeURIComponent(ruleId)}`);

/** The accepted rules as Rule JSON 2.0 (`review.status: approved`); rejected and pending rules are not in it. */
export const approvedExportUrl = (jobId: string) => `${reviewsUrl(jobId)}/approved-export?download=true`;

/** The file name the backend proposes (`Content-Disposition`), or null. */
function dispositionName(header: string | null): string | null {
  const star = header?.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if (star) { try { return decodeURIComponent(star); } catch { /* fall through to the plain form */ } }
  return header?.match(/filename="?([^";]+)"?/i)?.[1] ?? null;
}

/** Fetches the approved export and saves it as a file. A failed request (409, 503, backend down) throws with the backend's
 *  explanation and saves nothing: an error answer is never written to disk as if it were an approved-rules file. */
export async function downloadApprovedRules(jobId: string): Promise<void> {
  const res = await request(approvedExportUrl(jobId));
  const blob = await res.blob();
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = dispositionName(res.headers.get("Content-Disposition")) ?? "approved.rules.json";
  document.body.append(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(href), 1000);
}

/** Accept an array of individual Rule JSON records, a `{ rules }` collection, or a single record. */
export function ruleEntries(data: unknown): Record<string, unknown>[] {
  if (Array.isArray(data)) return data.filter(isRuleRecord);
  if (!data || typeof data !== "object") return [];
  const record = data as Record<string, unknown>;
  if (Array.isArray(record.rules)) return record.rules.filter(isRuleRecord);
  return isRuleRecord(record) ? [record] : [];
}

/** A Rule JSON record (backend/schemas/rule-json/rule.schema.json) declares schemaVersion 2.0 and lists its source
 *  elements in `source.elements`. */
function isRuleRecord(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return record.schemaVersion === "2.0" && typeof record.id === "string" && !!sourceElements(record);
}

function sourceElements(rule: Record<string, unknown>): unknown[] | undefined {
  const source = rule.source;
  const elements = source && typeof source === "object" ? (source as Record<string, unknown>).elements : undefined;
  return Array.isArray(elements) ? elements : undefined;
}

/** Rule records map to any Legal JSON element through the stable element IDs in their `source.elements`. */
export function rulesForElement(data: unknown, elementId: string | null): Record<string, unknown>[] {
  if (!elementId) return [];
  return ruleEntries(data).filter((rule) => (sourceElements(rule) ?? []).some((element) =>
    !!element && typeof element === "object" && (element as Record<string, unknown>).elementId === elementId,
  ));
}

/** The selected element's Legal JSON node with `nativeType` shown as `germanType`; null when the element is not a node
 *  of the document (the caller then shows the whole document). */
export function nodeJson(live: LiveData, element: DocElement | null): string | null {
  const node = element && findNode([live.legal.structure, live.legal.frontMatter, live.legal.tableOfContents], element.id);
  return node ? toJsonText(forPresentation(node)) : null;
}
