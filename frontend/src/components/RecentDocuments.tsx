import { useCallback, useEffect, useRef, useState, type RefObject, type Ref } from "react";
import { deleteStoredDocument, listDocuments, type StoredDocument } from "../demo/live";
import { Icon } from "./Icon";

export type DocumentsState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; documents: StoredDocument[] };

/** A problem with one document (opening or deleting it), shown at that document. */
export interface DocumentProblem { id: string; message: string }

const STATUS: Record<StoredDocument["status"], { label: string; tone: "ok" | "busy" | "warn" | "danger" }> = {
  completed: { label: "Completed", tone: "ok" },
  processing: { label: "Processing", tone: "busy" },
  queued: { label: "Queued", tone: "busy" },
  unsupported: { label: "Not recognized", tone: "warn" },
  failed: { label: "Failed", tone: "danger" },
};

/** Only a completed document has a result to open; the backend refuses to delete one that is still being processed. */
export const canOpen = (doc: StoredDocument) => doc.status === "completed";
export const canDelete = (doc: StoredDocument) => doc.status !== "queued" && doc.status !== "processing";

const TYPE_LABELS: Record<string, string> = {
  de_legislation: "German law",
  eu_regulation: "EU regulation",
  eu_directive: "EU directive",
  eu_decision: "EU decision",
  eu_legislation: "EU legislation",
  technical_standard: "Technical standard",
};
const typeLabel = (type: string | null | undefined) => (type ? TYPE_LABELS[type] ?? type.replace(/_/g, " ") : "—");

/** Where a document stands among uploads that share its file name. */
export type UploadRank = "latest" | "earlier";
const RANK_LABELS: Record<UploadRank, string> = { latest: "Latest upload", earlier: "Earlier upload" };

/** Marks documents that share an identical file name: the newest upload of each such name is "latest", the others are
 *  "earlier". Documents with a unique name get no entry. It only compares upload times (created_at); the content of the
 *  documents is not compared. Equal times are ordered by id (the greater id counts as newer), so the result never depends
 *  on the order of the list. Compute it from the whole list, not from a filtered one. */
export function uploadRanks(documents: StoredDocument[]): Map<string, UploadRank> {
  const groups = new Map<string, StoredDocument[]>();
  for (const doc of documents) groups.set(doc.filename, [...(groups.get(doc.filename) ?? []), doc]);
  const newerFirst = (a: StoredDocument, b: StoredDocument) => {
    const byTime = (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0);
    if (byTime) return byTime;
    if (a.created_at !== b.created_at) return a.created_at < b.created_at ? 1 : -1; // finer than a millisecond
    return a.id < b.id ? 1 : a.id > b.id ? -1 : 0;
  };
  const ranks = new Map<string, UploadRank>();
  for (const group of groups.values()) {
    if (group.length < 2) continue;
    [...group].sort(newerFirst).forEach((doc, i) => ranks.set(doc.id, i === 0 ? "latest" : "earlier"));
  }
  return ranks;
}

const formatDate = (iso: string) => {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
};

const messageOf = (e: unknown) => (e instanceof Error ? e.message : String(e));

interface Props {
  /** Reloads the list when it changes. */
  refreshKey?: number;
  onOpen: (doc: StoredDocument) => void;
  /** The document being opened right now, if any. */
  openingId?: string | null;
  openError?: DocumentProblem | null;
  /** Opening is not possible right now (a PDF is being processed or another document is opening). */
  openDisabled?: boolean;
}

/** The documents the backend keeps in its database (metadata only): open a completed one, delete any finished one.
 *  Loads them on mount and whenever `refreshKey` changes. */
export function RecentDocuments({ refreshKey = 0, onOpen, openingId = null, openError = null, openDisabled = false }: Props) {
  const [state, setState] = useState<DocumentsState>({ kind: "loading" });
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<DocumentProblem | null>(null);
  const [query, setQuery] = useState("");
  const latest = useRef(0); // the newest list request: older answers are ignored
  const deleting = useRef(false); // set synchronously, so that a second click cannot start a second deletion
  const heading = useRef<HTMLHeadingElement>(null);
  const triggers = useRef(new Map<string, HTMLButtonElement | null>()); // each document's Delete button
  const [returnFocusTo, setReturnFocusTo] = useState<string | null>(null);

  // cancelling the confirmation removes the button that had the focus: it goes back to the Delete button that opened it
  useEffect(() => {
    if (returnFocusTo && confirmId === null) {
      triggers.current.get(returnFocusTo)?.focus();
      setReturnFocusTo(null);
    }
  }, [returnFocusTo, confirmId]);

  const load = useCallback((silent = false) => {
    const request = ++latest.current;
    if (!silent) setState({ kind: "loading" });
    listDocuments().then(
      (documents) => {
        if (request !== latest.current) return;
        setState(Array.isArray(documents)
          ? { kind: "ready", documents }
          : { kind: "error", message: "The document list could not be read." });
      },
      (e: unknown) => { if (request === latest.current && !silent) setState({ kind: "error", message: messageOf(e) }); },
    );
  }, []);

  useEffect(() => {
    load();
    return () => { latest.current++; };
  }, [refreshKey, load]);

  const confirmDelete = async (doc: StoredDocument) => {
    if (deleting.current) return;
    deleting.current = true;
    setDeleteError(null);
    setDeletingId(doc.id);
    try {
      await deleteStoredDocument(doc.id);
      // removed from the list only now that the backend has confirmed it
      setState((s) => (s.kind === "ready" ? { kind: "ready", documents: s.documents.filter((d) => d.id !== doc.id) } : s));
      setConfirmId(null);
      heading.current?.focus(); // the button that had the focus is gone
      load(true); // and the list is read again from the database
    } catch (e) {
      setDeleteError({ id: doc.id, message: messageOf(e) });
    } finally {
      deleting.current = false;
      setDeletingId(null);
    }
  };

  return (
    <RecentDocumentsView
      state={state}
      onRefresh={() => load()}
      onOpen={onOpen}
      openingId={openingId}
      openError={openError}
      openDisabled={openDisabled}
      confirmId={confirmId}
      deletingId={deletingId}
      deleteError={deleteError}
      onAskDelete={(doc) => { setDeleteError(null); setConfirmId(doc.id); }}
      onCancelDelete={() => { setDeleteError(null); setReturnFocusTo(confirmId); setConfirmId(null); }}
      onConfirmDelete={(doc) => void confirmDelete(doc)}
      headingRef={heading}
      triggerRefs={triggers}
      query={query}
      onQueryChange={setQuery}
    />
  );
}

interface ViewProps {
  state: DocumentsState;
  onRefresh: () => void;
  onOpen?: (doc: StoredDocument) => void;
  openingId?: string | null;
  openError?: DocumentProblem | null;
  openDisabled?: boolean;
  confirmId?: string | null;
  deletingId?: string | null;
  deleteError?: DocumentProblem | null;
  onAskDelete?: (doc: StoredDocument) => void;
  onCancelDelete?: () => void;
  onConfirmDelete?: (doc: StoredDocument) => void;
  headingRef?: Ref<HTMLHeadingElement>;
  triggerRefs?: RefObject<Map<string, HTMLButtonElement | null>>;
  /** Filters the listed documents by file name; without `onQueryChange` there is no search field. */
  query?: string;
  onQueryChange?: (query: string) => void;
}

export function RecentDocumentsView({
  state, onRefresh, onOpen, openingId = null, openError = null, openDisabled = false,
  confirmId = null, deletingId = null, deleteError = null, onAskDelete, onCancelDelete, onConfirmDelete, headingRef, triggerRefs, query = "", onQueryChange,
}: ViewProps) {
  const loading = state.kind === "loading";
  const idle = openingId === null && deletingId === null;
  // the type column appears once the API provides document types
  const showType = state.kind === "ready" && state.documents.some((d) => d.document_type);
  const needle = query.trim().toLowerCase();
  const ranks = state.kind === "ready" ? uploadRanks(state.documents) : new Map<string, UploadRank>(); // before the search filter
  const shown = state.kind === "ready" ? state.documents.filter((d) => d.filename.toLowerCase().includes(needle)) : [];
  const searchable = state.kind === "ready" && state.documents.length > 0 && onQueryChange !== undefined;
  return (
    <section id="library" className="library demo-recent" aria-labelledby="recent-heading" aria-busy={loading}>
      <div className="demo-section-head">
        <h2 id="recent-heading" className="demo-section-title" ref={headingRef} tabIndex={-1}>Document library</h2>
        <div className="demo-tools">
          {searchable && (
            <label className="demo-search">
              <Icon name="search" size={18} />
              <input type="search" value={query} onChange={(e) => onQueryChange(e.target.value)} placeholder="Search documents…" aria-label="Search documents" />
            </label>
          )}
          <button type="button" className="demo-toolbtn" onClick={onRefresh} disabled={loading || !idle} aria-label="Refresh" title="Refresh the list"><Icon name="refresh" size={18} /></button>
        </div>
      </div>
      {loading && <p className="muted demo-empty" role="status">Loading documents…</p>}
      {state.kind === "error" && (
        <div className="alert error" role="alert">
          <p>{state.message}</p>
          <button type="button" className="btn small" onClick={onRefresh}>Try again</button>
        </div>
      )}
      {state.kind === "ready" && state.documents.length === 0 && (
        <p className="muted demo-empty">No documents yet. Upload a PDF above and it will appear here.</p>
      )}
      {state.kind === "ready" && state.documents.length > 0 && shown.length === 0 && (
        <p className="muted demo-empty">No documents match “{query.trim()}”.</p>
      )}
      {state.kind === "ready" && shown.length > 0 && (
        <>
        <div className={`demo-listhead${showType ? " has-type" : ""}`} aria-hidden="true">
          <span>Name</span>{showType && <span>Type</span>}<span>Status</span><span>Uploaded</span><span />
        </div>
        <ul className={`demo-doclist${showType ? " has-type" : ""}`}>
          {shown.map((doc) => {
            const status = STATUS[doc.status] ?? { label: doc.status, tone: "busy" as const };
            const created = formatDate(doc.created_at);
            const rank = ranks.get(doc.id);
            // identical file names: the accessible names and the confirmation say which upload is meant
            const which = rank ? ` (${RANK_LABELS[rank].toLowerCase()}${created ? `, ${created}` : ""})` : "";
            const name = (
              <span className="demo-doctext">
                {canOpen(doc) && onOpen ? <span className="demo-docname">{doc.filename}</span> : <span className="demo-docname plain" title={doc.filename}>{doc.filename}</span>}
                {rank && <span className={`demo-dup ${rank}`}>{RANK_LABELS[rank]}</span>}
              </span>
            );
            const opening = openingId === doc.id;
            const confirming = confirmId === doc.id;
            const deleting = deletingId === doc.id;
            const problem = openError?.id === doc.id ? openError.message : null;
            return (
              <li key={doc.id} className="demo-docitem">
                <div className="demo-docrow">
                  {canOpen(doc) && onOpen ? (
                    <button type="button" className="demo-doclink" onClick={() => onOpen(doc)} disabled={openDisabled || !idle} aria-label={`Open ${doc.filename}${which}`} title="Open the saved result">
                      <Icon name="file" size={24} />
                      {name}
                      {opening && <span className="spinner" aria-hidden="true" />}
                    </button>
                  ) : (
                    <span className="demo-doclabel"><Icon name="file" size={24} />{name}</span>
                  )}
                  {showType && <span className="demo-type">{typeLabel(doc.document_type)}</span>}
                  <span className={`demo-status ${status.tone}`}>{opening ? "Opening…" : status.label}</span>
                  {created ? <time className="muted demo-docdate" dateTime={doc.created_at}>{created}</time> : <span />}
                  <div className="demo-actions">
                    {canOpen(doc) && onOpen && <span className="demo-openicon" aria-hidden="true"><Icon name="open" size={19} /></span>}
                    {canDelete(doc) && onAskDelete && (
                      <button type="button" className="demo-iconbtn" ref={(el) => { triggerRefs?.current.set(doc.id, el); }} onClick={() => onAskDelete(doc)} disabled={!idle || confirming} aria-label={`Delete ${doc.filename}${which}`} title="Delete">
                        <Icon name="trash" size={19} />
                      </button>
                    )}
                  </div>
                </div>
                {problem && <div className="alert error" role="alert"><p>{problem}</p></div>}
                {confirming && onConfirmDelete && onCancelDelete && (
                  <div className="demo-confirm" role="group" aria-label={`Delete ${doc.filename}${which}?`} onKeyDown={(e) => { if (e.key === "Escape" && !deleting) onCancelDelete(); }}>
                    <p>Delete <strong className="demo-docname-inline">{doc.filename}</strong>{which}? The stored PDF and its extracted data are removed permanently. This cannot be undone.</p>
                    {deleteError?.id === doc.id && <div className="alert error" role="alert"><p>{deleteError.message}</p></div>}
                    <div className="demo-confirm-actions">
                      <button type="button" className="btn small danger" onClick={() => onConfirmDelete(doc)} disabled={deleting} aria-busy={deleting}>
                        {deleting ? <><span className="spinner" aria-hidden="true" /> Deleting…</> : "Delete document"}
                      </button>
                      <button type="button" className="btn small" onClick={onCancelDelete} disabled={deleting} autoFocus>Cancel</button>
                    </div>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
        </>
      )}
    </section>
  );
}
