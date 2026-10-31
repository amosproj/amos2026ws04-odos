import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../api";
import { fmtBytes } from "../format";
import {
  DEFAULT_SORT, DeletionController, STATUS_FILTERS, VIEWS, filterDocuments, libraryMetrics, sortDocuments,
  type DeleteState, type SortDir, type SortKey, type StatusFilter, type View,
} from "../documentLibrary";
import type { DocumentStatus } from "../types";
import { DeleteDialog } from "./DeleteDialog";
import { DocumentTable, type MenuState } from "./DocumentTable";
import { Icon, type IconName } from "./Icon";
import { Toasts, type Toast } from "./Toasts";

const POLL_MS = 3000;
const TOAST_MS = 6000;

function Metric({ icon, label, value, tone }: { icon: IconName; label: string; value: number | string; tone?: string }) {
  return (
    <div className={`metric${tone ? ` ${tone}` : ""}`}>
      <span className="metric-icon" aria-hidden="true"><Icon name={icon} size={16} /></span>
      <span className="metric-value">{value}</span>
      <span className="metric-label">{label}</span>
    </div>
  );
}

export function DocumentHome({ view = "documents" }: { view?: View }) {
  const page = VIEWS.find((v) => v.view === view)!;
  const [docs, setDocs] = useState<DocumentStatus[] | null>(null); // null = not loaded yet
  const [loadError, setLoadError] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [drag, setDrag] = useState(false);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [sort, setSort] = useState(DEFAULT_SORT);
  const [menu, setMenu] = useState<MenuState | null>(null);
  const [del, setDel] = useState<DeleteState>({ phase: "idle" });
  const [toasts, setToasts] = useState<Toast[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const nextToast = useRef(1);

  const refresh = useCallback(async () => {
    try {
      setDocs(await api.listDocuments());
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof ApiError ? e.message : String(e));
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  // keep the table current while documents are being processed
  const active = docs?.some((d) => d.status === "queued" || d.status === "processing") ?? false;
  useEffect(() => {
    if (!active) return;
    const t = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(t);
  }, [active, refresh]);

  const toast = useCallback((kind: Toast["kind"], text: string) => {
    const id = nextToast.current++;
    setToasts((t) => [...t, { id, kind, text }]);
    if (kind === "success") window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), TOAST_MS);
  }, []);

  const deletion = useMemo(
    () => new DeletionController(api, setDel, (r) => {
      toast("success", `“${r.filename}” was permanently deleted (${r.removed.total_files} files, ${fmtBytes(r.removed.total_bytes)}).`);
      void refresh();
    }),
    [refresh, toast],
  );

  const upload = async (file: File | undefined) => {
    if (!file) return;
    setUploadError(null);
    setUploading(true);
    try {
      const doc = await api.upload(file);
      window.location.hash = `#/doc/${doc.id}`;
    } catch (e) {
      setUploadError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setUploading(false);
      if (input.current) input.current.value = "";
    }
  };

  const onSort = (key: SortKey) =>
    setSort((s) => (s.key === key ? { key, dir: (s.dir === "asc" ? "desc" : "asc") as SortDir } : { key, dir: key === "uploaded" ? "desc" : "asc" }));
  const onMenu = (doc: DocumentStatus, a: DOMRect | null) =>
    setMenu(a ? { doc, right: Math.max(8, window.innerWidth - a.right), top: a.bottom + 96 > window.innerHeight ? Math.max(8, a.top - 92) : a.bottom + 4 } : null);
  const open = (doc: DocumentStatus) => { window.location.hash = `#/doc/${doc.id}`; };

  const metrics = useMemo(() => libraryMetrics(docs ?? []), [docs]);
  const shown = useMemo(() => sortDocuments(filterDocuments(docs ?? [], { query, status, view }), sort.key, sort.dir), [docs, query, status, view, sort]);
  const inScope = useMemo(() => filterDocuments(docs ?? [], { query: "", status: "all", view }), [docs, view]);
  const filtered = query.trim() !== "" || status !== "all";

  return (
    <main
      className={`page library${drag ? " drag" : ""}`}
      onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setDrag(true); } }}
      onDragLeave={(e) => { if (e.currentTarget === e.target) setDrag(false); }}
      onDrop={(e) => { e.preventDefault(); setDrag(false); void upload(e.dataTransfer.files[0]); }}
    >
      <header className="page-head">
        <div>
          <h1>{page.title}</h1>
          <p className="muted">{page.description}</p>
        </div>
        <input ref={input} type="file" accept="application/pdf,.pdf" hidden onChange={(e) => void upload(e.target.files?.[0])} aria-label="Choose a PDF to upload" />
        <button className="btn primary" onClick={() => input.current?.click()} disabled={uploading}>
          {uploading ? <><span className="spinner" aria-hidden="true" /> Uploading…</> : <><Icon name="upload" size={16} /> Upload Document</>}
        </button>
      </header>

      {uploadError && <div className="alert error" role="alert"><Icon name="alert" size={15} /> {uploadError}</div>}

      {view === "documents" && (
        <section className="metrics" aria-label="Library summary" data-testid="metrics">
          <Metric icon="files" label="Total Documents" value={docs ? metrics.total : "—"} />
          <Metric icon="check" label="Completed" value={docs ? metrics.completed : "—"} tone="ok" />
          <Metric icon="clock" label="Processing / Pending" value={docs ? metrics.active : "—"} tone="warn" />
          {docs && metrics.failed > 0 && <Metric icon="alert" label="Failed" value={metrics.failed} tone="bad" />}
        </section>
      )}

      <section className="panel table-panel" aria-label="Documents">
        <div className="toolbar">
          <label className="search">
            <Icon name="search" size={15} />
            <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search by document name" aria-label="Search by document name" />
          </label>
          <label className="select">
            <span className="sr-only">Filter by status</span>
            <select value={status} onChange={(e) => setStatus(e.target.value as StatusFilter)} aria-label="Filter by status">
              {STATUS_FILTERS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
            </select>
          </label>
          <span className="spacer" />
          {docs && <span className="muted small" data-testid="result-count" aria-live="polite">{filtered ? `${shown.length} of ${inScope.length}` : `${inScope.length}`} {inScope.length === 1 ? "document" : "documents"}</span>}
        </div>

        {docs === null && !loadError && <p className="state" role="status"><span className="spinner" aria-hidden="true" /> Loading documents…</p>}
        {loadError && (
          <div className="state error" role="alert" data-testid="load-error">
            <Icon name="alert" size={18} />
            <div><strong>Documents could not be loaded.</strong><p className="muted">{loadError}</p></div>
            <button className="btn" onClick={() => void refresh()}>Retry</button>
          </div>
        )}
        {docs !== null && !loadError && shown.length === 0 && (
          <div className="state empty" data-testid="empty-state">
            <Icon name="files" size={22} />
            {filtered ? (
              <>
                <strong>No documents match your filters.</strong>
                <button className="btn small" onClick={() => { setQuery(""); setStatus("all"); }}>Clear filters</button>
              </>
            ) : view === "documents" ? (
              <>
                <strong>No documents yet.</strong>
                <p className="muted">Upload a PDF to extract its text and structure. PDFs are stored locally on this machine.</p>
                <button className="btn primary small" onClick={() => input.current?.click()}><Icon name="upload" size={14} /> Upload Document</button>
              </>
            ) : view === "processing" ? (
              <strong>No documents are queued, processing or failed.</strong>
            ) : (
              <>
                <strong>No document has a review yet.</strong>
                <p className="muted">A review starts when a processed document is opened for review.</p>
              </>
            )}
          </div>
        )}
        {docs !== null && !loadError && shown.length > 0 && (
          <DocumentTable docs={shown} view={view} sort={sort} onSort={onSort} menu={menu} onMenu={onMenu} onOpen={open}
            onDelete={(d) => { setMenu(null); void deletion.open(d); }} />
        )}
      </section>

      {drag && <div className="drop-hint" aria-hidden="true">Drop a PDF to upload</div>}
      <DeleteDialog state={del} onCancel={() => deletion.cancel()} onConfirm={() => void deletion.confirm()} />
      <Toasts toasts={toasts} onDismiss={(id) => setToasts((t) => t.filter((x) => x.id !== id))} />
    </main>
  );
}
