import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api";
import { MODE_LABELS, modeChoiceNote } from "../classification";
import { aknStatus } from "../exports";
import { nextUnresolved, reviewBadge } from "../review";
import { highlightsOf, warningsByElement } from "../structure";
import type { Classification, DocumentModel, DocumentStatus, EditableField, ProcessingMode, ReviewView, TraceNode } from "../types";
import { Akn4euPanel } from "./Akn4euPanel";
import { Icon } from "./Icon";
import { ArtifactsPanel } from "./ArtifactsPanel";
import { ClassificationPanel } from "./ClassificationPanel";
import { ElementDetail } from "./ElementDetail";
import { MetadataPanel } from "./MetadataPanel";
import { PdfViewer } from "./PdfViewer";
import { ReviewPanel } from "./ReviewPanel";
import { StructureTree } from "./StructureTree";
import { WarningsPanel } from "./WarningsPanel";

type Tab = "structure" | "review" | "document" | "warnings" | "artifacts" | "akn4eu";
const STAGES: Record<string, string> = {
  queued: "Waiting in the queue…",
  starting: "Starting…",
  extracting: "Extracting text and layout with Docling (this can take a minute)…",
  normalizing: "Reconstructing the legal hierarchy…",
  generating_akn: "Generating and validating Akoma Ntoso XML…",
};
const MODES: { value: ProcessingMode; title: string; text: string }[] = [
  { value: "german_law", title: "German law (prototype)", text: "Docling + § / Absatz parser + Akoma Ntoso. Tuned to the BDSG; only for German statutes." },
  { value: "eu_legislation", title: "EU legislation (prototype)", text: "Docling + EU parser + Akoma Ntoso (validated against the OASIS XSD). Tested on Regulation (EU) 2023/1230." },
  { value: "extract_only", title: "Extract only", text: "Docling text extraction. No legal interpretation, no XML." },
];

export function Workspace({ id }: { id: string }) {
  const [doc, setDoc] = useState<DocumentStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<ProcessingMode>("german_law");
  const [model, setModel] = useState<DocumentModel | null>(null);
  const [review, setReview] = useState<ReviewView | null>(null);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [structError, setStructError] = useState<string | null>(null);
  const [eIds, setEIds] = useState<Map<string, string>>(new Map());
  const [selected, setSelected] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [tab, setTab] = useState<Tab>("structure");

  // Preselect the mode the document was last processed with, otherwise the classifier's suggestion.
  const [classification, setClassification] = useState<Classification | null>(null);
  const [classError, setClassError] = useState<string | null>(null);
  const loadClassification = useCallback((refresh = false) => {
    api.classification(id, refresh).then(
      (c) => { setClassification(c); setClassError(null); },
      (e: ApiError) => setClassError(e.message),
    );
  }, [id]);
  useEffect(() => { loadClassification(); }, [loadClassification]);
  const firstMode = doc?.mode ?? null;
  useEffect(() => { if (firstMode) setMode(firstMode); }, [firstMode]);
  const suggested = classification?.suggested_processing_mode ?? null;
  useEffect(() => { if (!firstMode && suggested) setMode(suggested); }, [firstMode, suggested]);

  // Poll while the job is queued/processing.
  useEffect(() => {
    let dead = false;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const s = await api.status(id);
        if (dead) return;
        setDoc(s);
        setError(null);
        if (s.status === "queued" || s.status === "processing") timer = window.setTimeout(tick, 1000);
      } catch (e) {
        if (dead) return;
        setError(e instanceof ApiError ? e.message : String(e));
        timer = window.setTimeout(tick, 3000); // keep trying: the API may be restarting
      }
    };
    void tick();
    return () => { dead = true; window.clearTimeout(timer); };
  }, [id, doc?.status === "queued" || doc?.status === "processing" ? "busy" : doc?.finished_at]);

  const hasModel = doc?.artifacts.some((a) => a.type === "document_model") ?? false;
  const hasTrace = doc?.artifacts.find((a) => a.type === "akn_traceability");
  useEffect(() => {
    setModel(null);
    setStructError(null);
    if (!doc || doc.status !== "completed" || !hasModel) return;
    // the review model is the original model plus reviewer corrections; fall back to the original structure
    api.review(id).then(
      (r) => { setReview(r); return api.reviewModel(id).then(setModel); },
      () => api.structure(id).then(setModel),
    ).catch((e: ApiError) => setStructError(e.message));
  }, [id, doc?.finished_at, hasModel]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setEIds(new Map());
    if (!hasTrace) return;
    api.artifactText(hasTrace.url).then((t) => {
      const nodes = (JSON.parse(t) as { nodes: TraceNode[] }).nodes;
      setEIds(new Map(nodes.filter((n) => n.eId).map((n) => [n.model_id, n.eId!])));
    }, () => undefined);
  }, [hasTrace?.url]); // eslint-disable-line react-hooks/exhaustive-deps

  const start = useCallback(async () => {
    setError(null);
    setModel(null);
    setSelected(null);
    try {
      setDoc(await api.process(id, mode));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, [id, mode]);

  const wmap = useMemo(() => (model ? warningsByElement(model.warnings) : new Map()), [model]);
  const warningIds = useMemo(() => new Set<string>(wmap.keys()), [wmap]);
  const element = useMemo(() => model?.elements.find((e) => e.id === selected) ?? null, [model, selected]);

  const afterReview = useCallback(async (p: Promise<ReviewView>): Promise<boolean> => {
    setReviewBusy(true);
    setReviewError(null);
    try {
      const r = await p;
      setReview(r);
      setModel(await api.reviewModel(id));
      return true;
    } catch (e) {
      const err = e as ApiError;
      setReviewError(err.code === "stale_revision" ? `${err.message} The latest review state has been loaded.` : err.message);
      if (err.code === "stale_revision") {
        setReview(await api.review(id));
        setModel(await api.reviewModel(id));
      }
      return false;
    } finally {
      setReviewBusy(false);
    }
  }, [id]);

  const saveCorrection = (field: EditableField, value: string, note: string) =>
    review && selected ? afterReview(api.correct(id, { base_revision: review.review_revision, element_id: selected, field, value, note: note || undefined })) : Promise.resolve(false);
  const confirmElement = (note: string) =>
    review && selected ? afterReview(api.confirm(id, { base_revision: review.review_revision, element_id: selected, note: note || undefined })) : Promise.resolve(false);
  const decide = (action: "approve" | "request-changes" | "reopen", note: string) =>
    review ? void afterReview(api.decide(id, action, { base_revision: review.review_revision, note: note || undefined })) : undefined;

  const select = useCallback((elId: string) => {
    setSelected(elId);
    const el = model?.elements.find((e) => e.id === elId);
    if (el?.pages.length) setPage(el.pages[0]);
  }, [model]);

  if (!doc) return <main className="home">{error ? <div className="alert error">{error}</div> : <p className="muted">Loading…</p>}</main>;

  const busy = doc.status === "queued" || doc.status === "processing";
  const euDone = doc.mode === "eu_legislation" && doc.status === "completed" && doc.outcome === "completed" && hasModel;
  const needsStart = doc.status === "uploaded" || doc.status === "failed" || doc.status === "completed";

  return (
    <main className="workspace">
      <div className="docbar">
        <a href="#/" className="back" title="Back to the Document Library"><Icon name="back" size={15} /> Documents</a>
        <h2 title={doc.filename}>{doc.filename}</h2>
        <span className={`chip ${doc.status}`}>{doc.status}{doc.outcome === "unsupported" ? " · unsupported" : ""}</span>
        {review && <span className={`chip review-${reviewBadge(review).tone}`} data-testid="review-badge">{reviewBadge(review).label}</span>}
        <span className="spacer" />
        {needsStart && (
          <div className="startbox">
            <select value={mode} onChange={(e) => setMode(e.target.value as ProcessingMode)} aria-label="Processing mode" disabled={busy}>
              {MODES.map((m) => <option key={m.value} value={m.value}>{m.title}{m.value === suggested ? " — suggested" : ""}</option>)}
            </select>
            <button className="btn primary" onClick={() => void start()} disabled={busy}>
              {doc.status === "uploaded" ? `Process: ${MODE_LABELS[mode]}` : "Process again"}
            </button>
          </div>
        )}
      </div>
      {classification && <ClassificationPanel classification={classification} onGoToPage={setPage} onRefresh={() => loadClassification(true)} />}
      {classError && <div className="alert warn" role="status">Classification unavailable: {classError}</div>}
      {needsStart && <p className="muted modehint">{MODES.find((m) => m.value === mode)!.text}</p>}
      {needsStart && modeChoiceNote(classification, mode) && <p className="muted modehint" data-testid="override-note">{modeChoiceNote(classification, mode)}</p>}

      {error && <div className="alert error" role="alert">{error}</div>}
      {busy && (
        <div className="alert info" role="status">
          <span className="spinner" aria-hidden="true" /> {STAGES[doc.stage ?? doc.status] ?? doc.stage ?? "Processing…"}
        </div>
      )}
      {doc.routing?.manual_override && doc.status !== "uploaded" && (
        <div className="alert warn" role="status" data-testid="routing-note"><strong>Manual mode choice.</strong> {doc.routing.warnings.join(" ")}</div>
      )}
      {doc.status === "failed" && <div className="alert error" role="alert"><strong>Processing failed.</strong> {doc.error}</div>}
      {doc.status === "completed" && doc.outcome === "unsupported" && (
        <div className="alert warn" role="status"><strong>Unsupported document type.</strong> {doc.message}</div>
      )}
      {doc.status === "completed" && doc.outcome === "completed" && doc.message && doc.mode !== "eu_legislation" && <div className="alert info">{doc.message}</div>}
      {doc.mode === "eu_legislation" && doc.status === "completed" && doc.outcome === "completed" && (
        <AknStatus summary={doc.summary} onOpen={() => setTab("artifacts")} />
      )}
      {reviewError && <div className="alert error" role="alert" data-testid="review-error">{reviewError}</div>}
      {structError && <div className="alert error">{structError}</div>}

      <div className="split">
        <section className="pane left" aria-label="Original PDF">
          <PdfViewer url={api.originalUrl(id)} page={page} onPageChange={setPage} highlights={highlightsOf(element).boxes} approximate={highlightsOf(element).approximate} />
        </section>
        <section className="pane right" aria-label="Extracted document">
          <div className="tabs" role="tablist">
            {(["structure", ...(review ? ["review"] : []), "document", "warnings", "artifacts", ...(euDone ? ["akn4eu"] : [])] as Tab[]).map((t) => (
              <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
                {t === "structure" ? "Structure" : t === "review" ? `Review${review ? ` (${review.unresolved_uncertain_ids.length} open)` : ""}` : t === "document" ? "Document" : t === "warnings" ? `Warnings${model ? ` (${model.warnings.length})` : ""}` : t === "akn4eu" ? "AKN4EU export" : `Artifacts (${doc.artifacts.length})`}
              </button>
            ))}
          </div>
          <div className="tabbody">
            {tab === "structure" && (
              model ? (
                <div className="structure">
                  <StructureTree model={model} selectedId={selected} onSelect={select} warningIds={warningIds} editedIds={new Set(review?.corrected_element_ids ?? [])} />
                  <ElementDetail element={element} warnings={element ? wmap.get(element.id) ?? [] : []} eId={element ? eIds.get(element.id) ?? null : null} onGoToPage={setPage}
                    review={review} reviewBusy={reviewBusy} onSave={saveCorrection} onConfirm={confirmElement}
                    onNext={() => { if (review) { const n = nextUnresolved({ ...review, unresolved_uncertain_ids: review.unresolved_uncertain_ids.filter((x) => x !== selected) }, selected); if (n) select(n); } }} />
                </div>
              ) : (
                <p className="muted pad">
                  {busy ? "The structure appears here when processing completes."
                    : doc.status === "uploaded" ? "Choose a processing mode and press “Process document”."
                    : doc.outcome === "unsupported" ? "No legal structure is offered for this document (see the notice above)."
                    : doc.mode === "extract_only" ? "Extract-only mode produces no structure. Open the Artifacts tab for the Markdown and Docling JSON."
                    : "No structure available."}
                </p>
              )
            )}
            {tab === "review" && review && (
              <ReviewPanel docId={id} review={review} busy={reviewBusy} selectedId={selected} onSelect={(i) => { select(i); setTab("structure"); }} onDecide={decide} />
            )}
            {tab === "document" && (model ? <MetadataPanel model={model} onSelect={(i) => { select(i); setTab("structure"); }} /> : <p className="muted pad">Metadata appears after processing.</p>)}
            {tab === "warnings" && (model ? <WarningsPanel model={model} summary={doc.summary} onSelect={(i) => { select(i); setTab("structure"); }} /> : <p className="muted pad">Warnings appear after processing.</p>)}
            {tab === "artifacts" && <ArtifactsPanel key={doc.finished_at ?? "none"} artifacts={doc.artifacts} />}
            {tab === "akn4eu" && euDone && <Akn4euPanel key={doc.finished_at ?? "none"} docId={id} />}
          </div>
        </section>
      </div>
    </main>
  );
}

function AknStatus({ summary, onOpen }: { summary: Record<string, unknown>; onOpen: () => void }) {
  const st = aknStatus(summary);
  return (
    <div className={`alert ${st.kind}`} role="status" data-testid="eu-akn-status">
      <strong>{st.title}</strong> {st.text}{" "}
      {st.kind !== "warn" || summary.akn_generated ? <button className="link" onClick={onOpen}>Open XML and reports</button> : null}
    </div>
  );
}
