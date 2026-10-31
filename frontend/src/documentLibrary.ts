// Pure logic of the Document Library: routing, filtering, sorting, metrics and the delete-confirmation flow.
import { DOC_TYPE_LABELS } from "./classification";
import { REVIEW_STATE_LABELS } from "./review";
import type { DeleteResult, DeletionPreview, DocumentStatus, JobState } from "./types";

// ---- routes ------------------------------------------------------------------------------------------------------
export type View = "documents" | "processing" | "reviews";
export type Route = { kind: "view"; view: View } | { kind: "doc"; id: string };

export const VIEWS: { view: View; label: string; hash: string; title: string; description: string }[] = [
  { view: "documents", label: "Documents", hash: "#/", title: "Document Library", description: "Manage, process and validate regulatory and technical documents." },
  { view: "processing", label: "Processing", hash: "#/processing", title: "Processing", description: "Documents that are queued, being processed, or whose last processing run failed." },
  { view: "reviews", label: "Reviews", hash: "#/reviews", title: "Reviews", description: "Documents with a human review: unreviewed, in review, changes requested or approved." },
];

export function routeFromHash(hash: string): Route {
  const m = hash.match(/^#\/doc\/([0-9a-f-]{36})$/);
  if (m) return { kind: "doc", id: m[1] };
  const v = VIEWS.find((x) => x.hash === hash && x.view !== "documents");
  return { kind: "view", view: v ? v.view : "documents" };
}

// ---- labels and formatting -------------------------------------------------------------------------------------
export const STATUS_LABELS: Record<JobState, string> = {
  uploaded: "Uploaded", queued: "Queued", processing: "Processing", completed: "Completed", failed: "Failed",
};
export const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "All statuses" },
  ...(["uploaded", "queued", "processing", "completed", "failed"] as JobState[]).map((s) => ({ value: s, label: STATUS_LABELS[s] })),
];
export type StatusFilter = "all" | JobState;

export function statusLabel(d: DocumentStatus): string {
  return d.status === "completed" && d.outcome === "unsupported" ? "Unsupported" : STATUS_LABELS[d.status] ?? d.status;
}

/** Recognised document type, or null if the document has not been classified. */
export function docTypeLabel(d: DocumentStatus): string | null {
  return d.document_type ? DOC_TYPE_LABELS[d.document_type] ?? d.document_type : null;
}

export function reviewLabel(d: DocumentStatus): string | null {
  return d.review_state ? REVIEW_STATE_LABELS[d.review_state] ?? d.review_state : null;
}


// ---- filtering, sorting, metrics -------------------------------------------------------------------------------
export interface Filters { query: string; status: StatusFilter; view: View }

export function inView(d: DocumentStatus, view: View): boolean {
  if (view === "processing") return d.status === "queued" || d.status === "processing" || d.status === "failed";
  if (view === "reviews") return !!d.review_state;
  return true;
}

export function filterDocuments(docs: DocumentStatus[], f: Filters): DocumentStatus[] {
  const q = f.query.trim().toLowerCase();
  return docs.filter((d) => inView(d, f.view) && (f.status === "all" || d.status === f.status) && (!q || d.filename.toLowerCase().includes(q)));
}

export type SortKey = "uploaded" | "name" | "status";
export type SortDir = "asc" | "desc";
export const DEFAULT_SORT: { key: SortKey; dir: SortDir } = { key: "uploaded", dir: "desc" }; // most recently uploaded first

export function sortDocuments(docs: DocumentStatus[], key: SortKey, dir: SortDir): DocumentStatus[] {
  const sign = dir === "asc" ? 1 : -1;
  const val = (d: DocumentStatus) => (key === "name" ? d.filename.toLowerCase() : key === "status" ? STATUS_LABELS[d.status] : d.uploaded_at);
  return [...docs].sort((a, b) => sign * (val(a) < val(b) ? -1 : val(a) > val(b) ? 1 : 0) || sign * (a.uploaded_at < b.uploaded_at ? -1 : 1));
}

export interface Metrics { total: number; completed: number; active: number; failed: number }
/** Counted from the documents the API returned; nothing is hard-coded. active = uploaded, queued or processing. */
export function libraryMetrics(docs: DocumentStatus[]): Metrics {
  const n = (...s: JobState[]) => docs.filter((d) => s.includes(d.status)).length;
  return { total: docs.length, completed: n("completed"), active: n("uploaded", "queued", "processing"), failed: n("failed") };
}

// ---- deletion flow ---------------------------------------------------------------------------------------------
export type DeleteState =
  | { phase: "idle" }
  | { phase: "loading"; doc: DocumentStatus } // fetching what would be removed
  | { phase: "confirm"; doc: DocumentStatus; preview: DeletionPreview | null; error: string | null }
  | { phase: "deleting"; doc: DocumentStatus; preview: DeletionPreview };

export interface DeleteApi {
  deletionPreview: (id: string) => Promise<DeletionPreview>;
  deleteDocument: (id: string) => Promise<DeleteResult>;
}

/** Nothing is deleted unless confirm() is called on a loaded, deletable preview. cancel() never calls the API. */
export class DeletionController {
  state: DeleteState = { phase: "idle" };
  constructor(private api: DeleteApi, private onState: (s: DeleteState) => void, private onDeleted: (r: DeleteResult) => void, private onFailed: (msg: string) => void = () => undefined) {}

  private set(s: DeleteState) {
    this.state = s;
    this.onState(s);
  }

  async open(doc: DocumentStatus): Promise<void> {
    if (this.state.phase !== "idle") return;
    this.set({ phase: "loading", doc });
    try {
      this.set({ phase: "confirm", doc, preview: await this.api.deletionPreview(doc.id), error: null });
    } catch (e) {
      this.set({ phase: "confirm", doc, preview: null, error: message(e) });
    }
  }

  get canConfirm(): boolean {
    return this.state.phase === "confirm" && !!this.state.preview?.can_delete;
  }

  cancel(): void {
    if (this.state.phase === "deleting") return; // a running deletion cannot be cancelled
    this.set({ phase: "idle" });
  }

  async confirm(): Promise<boolean> {
    const s = this.state;
    if (s.phase !== "confirm" || !s.preview?.can_delete) return false;
    this.set({ phase: "deleting", doc: s.doc, preview: s.preview });
    try {
      const result = await this.api.deleteDocument(s.doc.id);
      this.set({ phase: "idle" });
      this.onDeleted(result);
      return true;
    } catch (e) {
      this.set({ phase: "confirm", doc: s.doc, preview: s.preview, error: message(e) });
      this.onFailed(message(e));
      return false;
    }
  }
}

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}
