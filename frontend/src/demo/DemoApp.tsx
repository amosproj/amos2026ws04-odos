import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { AppHeader } from "../components/AppHeader";
import { Icon } from "../components/Icon";
import { BrandButton } from "../components/BrandButton";
import { PdfViewer } from "../components/PdfViewer";
import { ProcessingStatus } from "../components/ProcessingStatus";
import { RecentDocuments, type DocumentProblem } from "../components/RecentDocuments";
import { DEFAULT_ROW_SPLIT, DEFAULT_SPLIT, RowDivider, SplitDivider, splitVars } from "../components/SplitDivider";
import { StructureTree } from "../components/StructureTree";
import { TYPE_LABELS, firstPage, fullText, highlightsOf, legalReference } from "../structure";
import type { DocElement } from "../types";
import type { DemoResult } from "./fixtures";
import { fileUrl, ProcessingCancelled, ProcessingError, nodeJson, openStoredDocument, pdfProblem, processPdf, releaseJob, ruleEntries, rulesForElement, type StoredDocument } from "./live";
import { RuleExtractionView, type RulesNav } from "./RuleExtraction";
import { DigitalTwinValidation } from "./DigitalTwinValidation";
import { applyReview, toRuleResults } from "./ruleResults";
import { STATE_LABEL, marksByElement, type ElementMarks } from "./reviewMarks";
import { toneOf } from "./sourceMap";
import { useReviewerName, useRuleReviews, type ReviewApi } from "./useRuleReviews";
import { NOT_ACCEPTABLE, useReviewActions } from "./ReviewControls";
import type { RuleReviewEntry } from "./live";
import type { RuleItem } from "./ruleResults";
import "./demo.css";


/** `focusId`: a Legal JSON element the result view opens with selected and highlighted (from "Show in PDF" of a rule). */
type Phase = { kind: "idle" } | { kind: "busy"; stage: string } | { kind: "done"; result: DemoResult; pdfUrl: string; focusId?: string } | { kind: "rules"; result: DemoResult; pdfUrl: string } | { kind: "validation"; result: DemoResult; pdfUrl: string };
/** What went wrong: the file cannot be used ("invalid"), its structure was not recognized, or the upload/processing failed. */
type Problem = { kind: "invalid" | "unsupported" | "failed"; message: string };

const PROBLEM_TITLES: Record<Problem["kind"], string> = {
  invalid: "This file can't be processed",
  unsupported: "Document type not recognized",
  failed: "Processing failed",
};

const formatSize = (bytes: number) => (bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`);

export default function DemoApp() {
  const [file, setFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [problem, setProblem] = useState<Problem | null>(null);
  const [dragging, setDragging] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0); // reloads the recent documents after a run ended without a result
  const [opening, setOpening] = useState<string | null>(null); // the stored document being opened
  const [openProblem, setOpenProblem] = useState<DocumentProblem | null>(null);
  const [confirmStopDoc, setConfirmStopDoc] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const rulesNav = useRef<RulesNav | null>(null); // the reviewer's place on the Rule Extraction page while it is left for Document Review
  const running = useRef(false); // processing or opening; set synchronously: the disabled state only follows after the next render
  const processAbort = useRef<AbortController | null>(null);

  const pdfUrl = phase.kind === "done" || phase.kind === "rules" || phase.kind === "validation" ? phase.pdfUrl : null;
  useEffect(() => () => { if (pdfUrl) URL.revokeObjectURL(pdfUrl); }, [pdfUrl]);

  const choose = (f: File | undefined) => {
    if (running.current) return;
    setProblem(null);
    if (!f) {
      setFile(null);
      return;
    }
    const invalid = pdfProblem(f);
    if (invalid) {
      setFile(null);
      setProblem({ kind: "invalid", message: invalid });
      if (input.current) input.current.value = "";
      return;
    }
    setFile(f);
  };

  const process = async () => {
    if (!file || running.current) return;
    running.current = true;
    const abort = new AbortController();
    processAbort.current = abort;
    setProblem(null);
    setPhase({ kind: "busy", stage: "uploading" });
    try {
      const result = await processPdf(file, (stage) => {
        if (processAbort.current !== abort) return; // abandoned by confirm-cancel
        setPhase({ kind: "busy", stage });
      }, abort.signal);
      if (processAbort.current !== abort) {
        // finished before the cancellation took effect: nobody will open it, so the temporary job is released
        if (result.live) releaseJob(result.live.jobId, result.live.persistent);
        setRefreshKey((k) => k + 1);
        return;
      }
      setPhase({ kind: "done", result, pdfUrl: URL.createObjectURL(file) });
    } catch (e) {
      if (processAbort.current !== abort) {
        // abandoned: the user confirmed cancel and the UI is already idle; refresh the library
        // once the backend has settled the cancellation (this catch runs ~1-2 s after confirm)
        setRefreshKey((k) => k + 1);
        return;
      }
      setPhase({ kind: "idle" });
      if (!(e instanceof ProcessingCancelled)) {
        setProblem({ kind: e instanceof ProcessingError ? e.kind : "failed", message: e instanceof Error ? e.message : String(e) });
        setRefreshKey((k) => k + 1);
      }
    } finally {
      if (processAbort.current === abort) {
        running.current = false;
        processAbort.current = null;
      }
      setConfirmStopDoc(false);
    }
  };

  /** Confirm document processing cancellation: immediately return to idle; let processPdf settle in the background. */
  const confirmCancelDoc = () => {
    const abort = processAbort.current;
    abort?.abort();
    processAbort.current = null; // detach: process()'s catch/finally will not touch state
    running.current = false;     // allow a new process to start immediately
    setConfirmStopDoc(false);
    setPhase({ kind: "idle" });
    setRefreshKey((k) => k + 1); // best-effort early refresh; a second refresh fires when processPdf settles
  };

  /** Opens a stored document in the result view. Nothing is uploaded or processed: the backend serves what it stored. */
  const open = async (doc: StoredDocument) => {
    if (running.current) return;
    running.current = true;
    setOpenProblem(null);
    setOpening(doc.id);
    try {
      const { result, pdf } = await openStoredDocument(doc.id);
      setPhase({ kind: "done", result, pdfUrl: URL.createObjectURL(pdf) });
    } catch (e) {
      setOpenProblem({ id: doc.id, message: `${doc.filename} could not be opened. ${e instanceof Error ? e.message : String(e)}` });
    } finally {
      running.current = false;
      setOpening(null);
    }
  };

  const reset = () => {
    rulesNav.current = null;
    if ((phase.kind === "done" || phase.kind === "rules" || phase.kind === "validation") && phase.result.live) releaseJob(phase.result.live.jobId, phase.result.live.persistent);
    setPhase({ kind: "idle" });
    setFile(null);
    setProblem(null);
    setOpenProblem(null);
    if (input.current) input.current.value = "";
  };

  if (phase.kind === "done") {
    const { result, pdfUrl, focusId } = phase;
    // "Open rule": Rule Validation with that rule selected (the reviewer's earlier filters are replaced, so the rule is certainly in view)
    const openRule = (ruleId: string) => {
      if (result.live) rulesNav.current = { jobId: result.live.jobId, filter: "all", search: "", selectedId: ruleId, category: "all", pageScroll: 0 };
      setPhase({ kind: "rules", result, pdfUrl });
    };
    return <ResultView result={result} pdfUrl={pdfUrl} initialSelectedId={focusId} onReset={reset} onContinueToRules={() => setPhase({ kind: "rules", result, pdfUrl })} onOpenRule={openRule} />;
  }
  if (phase.kind === "validation") {
    const { result, pdfUrl } = phase;
    return <DigitalTwinValidation documentName={result.filename ?? result.title} ruleSourceName={result.live?.ruleDownload.name}
                                  onBack={() => setPhase({ kind: "rules", result, pdfUrl })} />;
  }
  if (phase.kind === "rules") {
    const { result, pdfUrl } = phase;
    // Keep the stored rules on the result so reopening Rule Extraction reuses them without a new model call.
    const rulesLoaded = (ruleJson: unknown) => setPhase((p) => (p.kind === "rules" && p.result.live ? { ...p, result: { ...p.result, live: { ...p.result.live, ruleJson } } } : p));
    return <RuleExtractionView result={result} pdfUrl={pdfUrl} onBack={() => setPhase({ kind: "done", result, pdfUrl })} onHome={reset}
                               onShowInPdf={(focusId) => setPhase({ kind: "done", result, pdfUrl, focusId })} onRulesLoaded={rulesLoaded} nav={rulesNav}
                               onContinueToValidation={() => setPhase({ kind: "validation", result, pdfUrl })} />;
  }

  const busy = phase.kind === "busy";
  const locked = busy || opening !== null; // one thing at a time: a run or opening a stored document
  return (
    <main className="home" id="top">
      <AppHeader />
      <div className="shell">
        <section id="upload" className="home-upload" aria-labelledby="upload-heading">
          <div className="home-intro">
            <p className="eyebrow"><i aria-hidden="true" />Document workspace</p>
            <h1 id="upload-heading" className="home-title">Your documents</h1>
            <p className="muted home-lead">Upload, process and review German and EU legal documents.</p>
          </div>
          <div className="home-uploadpanel">
            <label
              className={`demo-drop${file ? " has-file" : ""}${dragging ? " dragging" : ""}${locked ? " disabled" : ""}`}
              onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); if (!locked) setDragging(true); } }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                const dropped = e.dataTransfer.files[0];
                if (dropped) choose(dropped);
              }}
            >
              <input ref={input} type="file" accept="application/pdf,.pdf" className="sr-only" onChange={(e) => choose(e.target.files?.[0])} disabled={locked} />
              <Icon name="upload" size={22} />
              <span className="demo-drop-title">{file ? file.name : "Choose a PDF or drop it here"}</span>
              <span className="demo-drop-hint">{file ? `${formatSize(file.size)} · Select a different file` : "PDF files only"}</span>
            </label>
            {problem && (
              <div className="alert error" role="alert">
                <strong>{PROBLEM_TITLES[problem.kind]}</strong>
                <p>{problem.message}</p>
                {problem.kind === "failed" && file && <button type="button" className="btn small" onClick={() => void process()}>Try again</button>}
              </div>
            )}
            <button type="button" className="btn primary demo-process" onClick={() => void process()} disabled={!file || locked} aria-busy={busy}>
              {busy ? <><span className="spinner" aria-hidden="true" /> Processing…</> : "Process document"}
            </button>
            {phase.kind === "busy" && (
              <>
                <ProcessingStatus stage={phase.stage} />
                {phase.stage !== "cancelling" && (
                  <button type="button" className="btn small" onClick={() => setConfirmStopDoc(true)}>
                    Stop processing
                  </button>
                )}
              </>
            )}
            {confirmStopDoc && (
              <div role="alertdialog" aria-modal="true" aria-labelledby="stop-doc-title" className="cancel-confirm">
                <strong id="stop-doc-title">Stop document processing?</strong>
                <p>The pipeline will finish its current stage, then stop. No result will be saved. Any previous result for this document is unaffected.</p>
                <div className="cancel-confirm-actions">
                  <button type="button" className="btn danger" onClick={confirmCancelDoc}>Stop processing</button>
                  <button type="button" className="btn" onClick={() => setConfirmStopDoc(false)}>Keep running</button>
                </div>
              </div>
            )}
          </div>
        </section>
        <RecentDocuments refreshKey={refreshKey} onOpen={(doc) => void open(doc)} openingId={opening} openError={openProblem} openDisabled={busy} />
      </div>
    </main>
  );
}

export function ResultView({ result, pdfUrl, initialSelectedId, onReset, onContinueToRules, onOpenRule }: { result: DemoResult; pdfUrl: string; initialSelectedId?: string; onReset: () => void; onContinueToRules?: () => void; onOpenRule?: (ruleId: string) => void }) {
  const { model } = result;
  const [tab, setTab] = useState<"structure" | "artifacts">("structure");
  // opened from a rule's "Show in PDF": that element is selected (the PDF shows its page and highlights it)
  const initial = initialSelectedId ? model.elements.find((e) => e.id === initialSelectedId) : undefined;
  const [selected, setSelected] = useState<string | null>(initial?.id ?? null);
  const [page, setPage] = useState(firstPage(initial) ?? 1);
  const [full, setFull] = useState(false); // live Artifacts: the complete document instead of the selected element
  const [split, setSplit] = useState(DEFAULT_SPLIT); // the PDF panel's share of the width
  const splitRef = useRef<HTMLDivElement>(null);
  const [rowSplit, setRowSplit] = useState(DEFAULT_ROW_SPLIT); // the tree's share of the panel; kept while other elements are selected
  const structureRef = useRef<HTMLDivElement>(null);
  const [anim, setAnim] = useState(false); // the panel animates only while the details open or close, never while the divider is dragged
  const detailsOpen = selected !== null;
  useEffect(() => { setAnim(true); const t = setTimeout(() => setAnim(false), 320); return () => clearTimeout(t); }, [detailsOpen]);
  const element = useMemo(() => model.elements.find((e) => e.id === selected) ?? null, [model, selected]);
  // the persisted review decisions of the document's rules (loaded again whenever the document is opened); nothing without review storage
  const ruleResults = useMemo(() => toRuleResults(result.live?.ruleJson ?? null), [result.live?.ruleJson]);
  const reviewJob = result.live && ruleResults && ruleResults.items.length ? result.live.jobId : undefined;
  const { api: reviewApi, reload: reloadReviews, setEntry } = useRuleReviews(reviewJob, ruleResults?.generation?.generatedAt ?? null);
  const [reviewer, setReviewer] = useReviewerName();
  const review: RuleReview | undefined = reviewJob ? { jobId: reviewJob, api: reviewApi, reviewer, setReviewer, onEntry: setEntry, onReload: reloadReviews } : undefined;
  const elementsById = useMemo(() => new Map(model.elements.map((e) => [e.id, e])), [model]);
  const marks = useMemo(() => (ruleResults && reviewApi.kind === "ready"
    ? marksByElement(ruleResults.items.map((r) => applyReview(r, reviewApi.data.rules[r.id])), elementsById) : undefined), [ruleResults, reviewApi, elementsById]);
  const elementMarks = element ? marks?.get(element.id) : undefined;
  const hl = highlightsOf(element);
  // one rule on the element: its meaning (fill) and review state (outline); several rules: the plain highlight, each rule listed beside
  const single = elementMarks?.rules.length === 1 ? elementMarks.rules[0] : null;
  const groups = useMemo(() => (single && hl.boxes.length ? [{ boxes: hl.boxes, approximate: hl.approximate, tone: toneOf(single.rule.type, single.role),
    status: single.role === "primary" || single.role === "definition" ? single.mark.state : undefined, edited: single.mark.edited }] : undefined), [single, hl.boxes, hl.approximate]);

  const select = useCallback((id: string) => {
    setSelected(id);
    const page = firstPage(model.elements.find((e) => e.id === id));
    if (page !== null) setPage(page);
  }, [model]);

  return (
    <main className="workspace demo-result">
      <div className="docbar">
        <BrandButton onClick={onReset} />
        <span className="docbar-sep" aria-hidden="true" />
        <h2 title={result.filename ? `${result.filename} · ${result.title}` : result.title}>{result.filename ?? result.title}</h2>
        <span className="demo-status ok">Completed</span>{/* a result is only ever shown for a completed document */}
        <span className="spacer" />
        <button className="btn" onClick={onReset}><Icon name="back" size={16} />Back to documents</button>
        {onContinueToRules && <button className="btn primary" onClick={onContinueToRules}>Continue to Rule Extraction<Icon name="chevron-right" size={16} /></button>}
      </div>
      <div className="split" ref={splitRef} style={splitVars(split)}>
        <section className="pane left" aria-label="Original PDF">
          <PdfViewer url={pdfUrl} page={page} onPageChange={setPage} highlights={hl.boxes} approximate={hl.approximate} groups={groups} />
        </section>
        <SplitDivider containerRef={splitRef} value={split} onCommit={setSplit} />
        <section className="pane right" aria-label="Recognized legal structure">
          <div className="tabs" role="tablist">
            <button role="tab" aria-selected={tab === "structure"} className={tab === "structure" ? "active" : ""} onClick={() => setTab("structure")}>Legal structure</button>
            <button role="tab" aria-selected={tab === "artifacts"} className={tab === "artifacts" ? "active" : ""} onClick={() => setTab("artifacts")}>Artifacts</button>
          </div>
          <div className="tabbody">
            {tab === "structure" && (
              <div className={`structure${element ? " open" : ""}${anim ? " anim" : ""}`} ref={structureRef} style={{ "--tree": `${(rowSplit * 1000).toFixed(0)}fr`, "--det": `${((1 - rowSplit) * 1000).toFixed(0)}fr` } as React.CSSProperties}>
                <StructureTree model={model} selectedId={selected} onSelect={select} marks={marks} />
                <RowDivider containerRef={structureRef} value={rowSplit} onChange={setRowSplit} />
                {element
                  ? <SourceDetail element={element} elements={elementsById} page={page} onGoToPage={setPage} marks={elementMarks} onOpenRule={onOpenRule} review={review} onClose={() => setSelected(null)} />
                  : <div className="detail-hint"><Icon name="info" size={16} /><span>Select an element to highlight its source text in the PDF.</span></div>}
              </div>
            )}
            {tab === "artifacts" && <Artifacts result={result} element={element} full={full} onFull={result.live ? setFull : undefined} />}
          </div>
        </section>
      </div>
    </main>
  );
}

/** What the rule rows need to save a decision: the same review state and actions Rule Validation uses (one source of truth). */
export interface RuleReview {
  jobId: string; api: ReviewApi; reviewer: string; setReviewer: (name: string) => void;
  onEntry: (ruleId: string, entry: RuleReviewEntry) => void; onReload: () => Promise<void>;
}

/** One extracted rule of the selected element as a card: type, state, a four-line preview of its text, and the review actions. A decision
 *  can be changed later: only the button of the current state is disabled. Nothing changes on screen until the backend has answered. */
function RuleRow({ rule, mark, sentenceIds, index, review, onOpenRule }: { rule: RuleItem; mark: { state: "accepted" | "pending" | "rejected"; edited: boolean }; sentenceIds: string[]; index: number; review?: RuleReview; onOpenRule?: (ruleId: string) => void }) {
  const r = useReviewActions({ jobId: review?.jobId ?? "", rule, api: review?.api ?? { kind: "unavailable", reason: null }, reviewer: review?.reviewer ?? "", onEntry: review?.onEntry ?? (() => {}), onReload: review?.onReload ?? (async () => {}) });
  const [full, setFull] = useState(false);
  const [overflows, setOverflows] = useState(false);
  const text = useRef<HTMLParagraphElement>(null);
  // "Show full text" only when the preview really cuts the text (measured, so it follows the panel's width)
  useLayoutEffect(() => {
    const el = text.current;
    if (!el || full) return;
    const check = () => setOverflows(el.scrollHeight > el.clientHeight + 1);
    check();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(check);
    ro.observe(el);
    return () => ro.disconnect();
  }, [full, rule.title]);
  const can = !!review && !!r.entry && !r.busy;
  const icon = mark.state === "accepted" ? "check" : mark.state === "rejected" ? "x" : "clock";
  const kind = rule.type ? rule.type.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()) : null;
  return (
    <li className={`elrule ${mark.state}`} data-state={mark.state}>
      <div className="elrule-head">
        <span className="elrule-no">Rule {String(index + 1).padStart(2, "0")}{kind ? <> · <span className="elrule-kind">{kind}</span></> : null}</span>
        <span className="elrule-chips">
          <span className={`rm-chip ${mark.state}`}><Icon name={icon} size={12} />{STATE_LABEL[mark.state]}</span>
          {mark.edited && <span className="rm-chip edited"><Icon name="edit" size={12} />Edited</span>}
          {r.issues && <span className="rm-chip invalid" title="The record is not valid Rule JSON 2.0"><Icon name="braces" size={12} />Invalid Rule JSON</span>}
        </span>
      </div>
      <p ref={text} className={`elrules-title${full ? "" : " clamp"}`}>{rule.title}</p>
      {(overflows || full) && <button type="button" className="elrule-more" aria-expanded={full} onClick={() => setFull(!full)}>{full ? "Show less" : "Show full text"}</button>}
      {r.issues && (
        <div className="elrule-invalid" role="note">
          <ul>{r.issues.map((i) => <li key={i}>{i}</li>)}</ul>
          <p>It cannot be accepted until it is valid: correct it in Rule Validation (Edit), or reject it if the passage is not a rule.</p>
        </div>
      )}
      {sentenceIds.length > 0 && <p className="elrule-src"><Icon name="link" size={12} />Source: {sentenceIds.map((id) => `Satz ${id.split("/").pop()?.replace(/^satz-/, "") ?? id}`).join(", ")}</p>}
      {review && (
        <div className="elrule-actions">
          <button type="button" className="rv-act accept" disabled={!can || mark.state === "accepted" || !!r.issues} aria-busy={r.busy || undefined} title={r.issues ? NOT_ACCEPTABLE : undefined}
                  onClick={() => void r.send("accept")} aria-label={`Accept rule ${rule.id}`}><Icon name="check" size={16} />Accept</button>
          <button type="button" className="rv-act reject" disabled={!can || mark.state === "rejected"} aria-expanded={r.form === "reject"}
                  onClick={() => r.setForm(r.form === "reject" ? null : "reject")} aria-label={`Reject rule ${rule.id}`}><Icon name="x" size={16} />Reject</button>
        </div>
      )}
      {r.form === "reject" && (
        <form className="elrule-reject" onSubmit={(ev) => { ev.preventDefault(); if (r.rejectReason.trim()) void r.send("reject", { reason: r.rejectReason.trim() }); }}>
          <textarea autoFocus value={r.rejectReason} onChange={(ev) => r.setRejectReason(ev.target.value)} rows={2} placeholder="Why is this rule incorrect? (required)" aria-label={`Reason for rejecting ${rule.id}`} />
          <span><button type="submit" className="btn small reject" disabled={!can || !r.rejectReason.trim()}>Reject rule</button>
          <button type="button" className="btn small" onClick={() => r.setForm(null)}>Cancel</button></span>
        </form>
      )}
      {r.error && <p className="elrule-error" role="alert">{r.error}</p>}
      {onOpenRule && (
        <button type="button" className="elrule-open" onClick={() => onOpenRule(rule.id)} aria-label={`Open rule ${rule.id} in Rule Validation`} title="Opens Rule Validation: conditions, exceptions and source references">
          <Icon name="file" size={15} />View full rule details<Icon name="chevron-right" size={14} />
        </button>
      )}
    </li>
  );
}

/** Copies the complete original text of the selected element. */
function CopyText({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return <button type="button" className="srctext-copy" onClick={() => { void navigator.clipboard?.writeText(text).then(() => setCopied(true), () => {}); }}>{copied ? "Copied" : "Copy text"}</button>;
}

export function SourceDetail({ element: e, elements, page, onGoToPage, marks, onOpenRule, review, onClose }: { onClose?: () => void; element: DocElement | null; elements?: Map<string, DocElement>; page: number; onGoToPage: (page: number) => void; marks?: ElementMarks; onOpenRule?: (ruleId: string) => void; review?: RuleReview }) {
  if (!e) return <div className="detail empty"><Icon name="info" size={20} /><span>Select an element to highlight its source text in the PDF.</span></div>;
  const reference = elements ? legalReference(e, elements) : `${TYPE_LABELS[e.type] ?? e.type} ${e.marker ?? ""}`.trim();
  const text = fullText(e);
  return (
    <div className="detail" key={e.id}>{/* keyed: another element starts at the top of the details */}
      <div className="detail-head">
        <h3>{reference}</h3>
        <span className="detail-pages">{e.pages.length ? e.pages.map((p) => (
          <button key={p} className="link" onClick={() => onGoToPage(p)} aria-current={p === page ? "page" : undefined}
                  title={`Show page ${p} with the highlighted source text`}><Icon name="file" size={13} />Page {p}</button>
        )) : null}</span>
        {onClose && <button type="button" className="detail-close" onClick={onClose} aria-label="Close details" title="Close details"><Icon name="x" size={16} /></button>}
      </div>
      {e.title && <p className="title">{e.title}</p>}
      <details className="srctext">
        <summary><span className="detail-label">Original source text</span><small>Highlighted in the PDF</small></summary>
        <blockquote className="origtext">{text || <em>(no text)</em>}</blockquote>
        {text && <CopyText key={e.id} text={text} />}
      </details>
      <details className="techref">
        <summary>Technical details</summary>
        <dl className="kv">
          <dt>Source</dt><dd><code>{e.source_refs.join(", ") || "—"}</code></dd>
          <dt>Element id</dt><dd><code>{e.id}</code></dd>
        </dl>
      </details>
      {marks && marks.rules.length > 0 && (
        <section className="elrules" aria-label="Extracted rules linked to this element">
          <div className="elrules-head">
            <h4>Extracted rules</h4>
            <span className="elrules-count">{marks.rules.length} rule{marks.rules.length === 1 ? "" : "s"}</span>
            {review && (
              <label className="elrules-name">Reviewer
                <input value={review.reviewer} onChange={(ev) => review.setReviewer(ev.target.value)} placeholder="Your name" maxLength={100} aria-label="Reviewing as (your name, saved with each decision)" title="Saved with each decision; not a login." />
              </label>
            )}
          </div>
          <p className="elrules-hint">AI-extracted rules linked to this legal text. Review them before use.</p>
          <ul>
            {marks.rules.map(({ rule, mark, sentenceIds }, i) => <RuleRow key={rule.id} rule={rule} mark={mark} sentenceIds={sentenceIds} index={i} review={review} onOpenRule={onOpenRule} />)}
          </ul>
        </section>
      )}
    </div>
  );
}

function DoclingRaw({ jobId, filename }: { jobId: string; filename: string }) {
  const [json, setJson] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    if (json || loading) return;

    setLoading(true);
    setError("");

    try {
      const response = await fetch(
        `/api/jobs/${jobId}/files/docling_raw.json`
      );

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();
      setJson(JSON.stringify(data, null, 2));
    } catch {
      setError("Docling-Ausgabe konnte nicht geladen werden.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <details
      className="demo-artifact"
      onToggle={(event) => {
        if (event.currentTarget.open) {
          void load();
        }
      }}
    >
      <summary style={{ cursor: "pointer", padding: "10px 12px" }}>
        <span style={{ display: "inline-flex", width: "calc(100% - 20px)", justifyContent: "space-between", alignItems: "center", gap: "12px", verticalAlign: "middle" }}>
          <h3 style={{ display: "inline", fontSize: "14px", margin: 0 }}>Docling Raw JSON</h3>
          <a className="btn small" href={fileUrl(jobId, "docling_raw.json", true)}
             download={`${filename.replace(/\.pdf$/i, "")}.docling-raw.json`}
             onClick={event => event.stopPropagation()}>Download</a>
        </span>
      </summary>

      {loading && <p>Wird geladen …</p>}

      {error && (
        <p>
          {error}{" "}
          <button type="button" onClick={() => void load()}>
            Erneut versuchen
          </button>
        </p>
      )}

      {json && (
        <pre
          className="preview demo-code"
          tabIndex={0}
          style={{ maxHeight: "500px", overflow: "auto" }}
        >
          {json}
        </pre>
      )}
    </details>
  );
}


export function Artifacts({ result, element = null, full, onFull }: {
  result: DemoResult;
  element?: DocElement | null;
  full?: boolean;
  onFull?: (full: boolean) => void;
  artifactView?: "legal" | "rule";
  onArtifactViewChange?: (artifact: "legal" | "rule") => void;
}) {
  const json = (!full && result.live && nodeJson(result.live, element)) || result.json;
  return (
    <div className="demo-artifacts">
      <section className="demo-artifact">
        <div className="demo-artifact-head">
          <h3>Custom Legal JSON</h3>
          {onFull && (
            <div className="demo-toggle" role="group" aria-label="Custom Legal JSON preview">
              {[false, true].map((f) => (
                <button key={String(f)} className="btn small" aria-pressed={!!full === f} onClick={() => onFull(f)}>{f ? "Full document" : "Selected element"}</button>
              ))}
            </div>
          )}
          <a className="btn small" href={result.download.href} download={result.download.name}>Download</a>

        </div>
        <pre className="preview demo-code" tabIndex={0}>{json.replace(/\n$/, "")}</pre>
      </section>
      
      {result.live && <LlmInputViews result={result} />}
      {result.live && (
        <DoclingRaw
          key={result.live.jobId}
          jobId={result.live.jobId}
          filename={result.filename ?? result.title}
        />
      )}
    </div>
  );
}

export function ArtifactSwitch({ selected, onChange }: { selected: "legal" | "rule"; onChange: (artifact: "legal" | "rule") => void }) {
  return (
    <div className="demo-artifact-tabs" role="group" aria-label="Artifact type">
      <button type="button" className="btn small" aria-pressed={selected === "legal"} onClick={() => onChange("legal")}>Custom Legal JSON</button>
      <button type="button" className="btn small" aria-pressed={selected === "rule"} onClick={() => onChange("rule")}>Rule JSON</button>
    </div>
  );
}

export function RuleJsonPreview({ result, element, full }: { result: DemoResult; element: DocElement | null; full: boolean }) {
  const availableRules = ruleEntries(result.live?.ruleJson);
  const visibleRules = full ? availableRules : rulesForElement(result.live?.ruleJson, element?.id ?? null);
  if (!visibleRules.length) {
    const message = !availableRules.length || full
      ? "No Rule JSON available for this document."
      : element
        ? "No Rule JSON available for this element."
        : "Select an element to view associated Rule JSON.";
    return <p className="demo-artifact-empty" role="status">{message}</p>;
  }
  return <pre className="preview demo-code" tabIndex={0}>{JSON.stringify(visibleRules, null, 2)}</pre>;
}


export function LlmInputViews({ result }: { result: DemoResult }) {
  const live = result.live;
  if (!live) return null;
  const stem = (result.filename ?? result.title).replace(/\.pdf$/i, "");
  const variants = [
    { key: "v1", title: "Reduced LLM input JSON V1", file: "llm_input_v1.json", suffix: "llm-input-v1", data: live.llmInputV1 },
    { key: "v2", title: "LLM applicability input JSON V2", file: "llm_applicability_input_v2.json", suffix: "llm-applicability-input-v2", data: live.llmInputV2 },
  ];
  return <>
    {variants.map(v => <details className="demo-artifact" key={v.key}>
      <summary style={{ cursor: "pointer", padding: "10px 12px" }}>
        <span style={{ display: "inline-flex", width: "calc(100% - 20px)", justifyContent: "space-between", alignItems: "center", gap: "12px", verticalAlign: "middle" }}>
          <h3 style={{ display: "inline", fontSize: "14px", margin: 0 }}>{v.title}</h3>
          {v.data != null && <a className="btn small" href={fileUrl(live.jobId, v.file, true)} download={`${stem}.${v.suffix}.json`} onClick={event => event.stopPropagation()}>Download</a>}
        </span>
      </summary>
      {v.data == null ? <p>This input view is not available. Reprocess the document with the updated backend.</p>
        : <pre className="preview demo-code" tabIndex={0}>{JSON.stringify(v.data, null, 2)}</pre>}
    </details>)}
  </>;
}
