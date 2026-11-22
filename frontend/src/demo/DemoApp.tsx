import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppHeader } from "../components/AppHeader";
import { Icon } from "../components/Icon";
import { Logo } from "../components/Logo";
import { PdfViewer } from "../components/PdfViewer";
import { ProcessingStatus } from "../components/ProcessingStatus";
import { StopConfirm } from "../components/StopConfirm";
import { RecentDocuments, type DocumentProblem } from "../components/RecentDocuments";
import { DEFAULT_SPLIT, SplitDivider, splitVars } from "../components/SplitDivider";
import { StructureTree } from "../components/StructureTree";
import { TYPE_LABELS, firstPage, fullText, highlightsOf } from "../structure";
import type { DocElement } from "../types";
import type { DemoResult } from "./fixtures";
import { cancelJob, fileUrl, getJob, ProcessingError, nodeJson, openStoredDocument, pdfProblem, processPdf, releaseJob, waitForJob, type StoredDocument } from "./live";
import { RuleExtractionView, type RulesNav } from "./RuleExtraction";
import "./demo.css";


/** `focusId`: a Legal JSON element the result view opens with selected and highlighted (from "Show in PDF" of a rule). */
type Phase = { kind: "idle" } | { kind: "busy"; stage: string; jobId?: string } | { kind: "stopping"; jobId?: string } | { kind: "done"; result: DemoResult; pdfUrl: string; focusId?: string } | { kind: "rules"; result: DemoResult; pdfUrl: string };

const SESSION = "odos.workspace";
type SessionView = "processing" | "document" | "rules";

function readSession(): { jobId: string; view: SessionView } | null {
  try {
    const raw = sessionStorage.getItem(SESSION);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { jobId?: string; view?: string };
    if (!parsed.jobId || (parsed.view !== "processing" && parsed.view !== "document" && parsed.view !== "rules")) return null;
    return { jobId: parsed.jobId, view: parsed.view };
  } catch {
    return null;
  }
}

function writeSession(jobId: string, view: SessionView) {
  try { sessionStorage.setItem(SESSION, JSON.stringify({ jobId, view })); } catch { /* private mode */ }
}

function forgetSession() {
  try { sessionStorage.removeItem(SESSION); } catch { /* private mode */ }
}
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
  const [notice, setNotice] = useState<string | null>(null);
  const [stopError, setStopError] = useState<string | null>(null);
  const [cancelDoc, setCancelDoc] = useState<StoredDocument | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const rulesNav = useRef<RulesNav | null>(null); // the reviewer's place on the Rule Extraction page while it is left for Document Review
  const running = useRef(false); // a document job until it ends; set synchronously so a second one cannot start
  const openingRef = useRef<string | null>(null);
  const processing = useRef<AbortController | null>(null);
  const dismissed = useRef(false); // the user left the processing view; late stage reports must not bring it back
  const resumed = useRef(false);

  const pdfUrl = phase.kind === "done" || phase.kind === "rules" ? phase.pdfUrl : null;
  useEffect(() => () => { if (pdfUrl) URL.revokeObjectURL(pdfUrl); }, [pdfUrl]);

  const choose = (f: File | undefined) => {
    if (running.current && !dismissed.current) return;
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

  const showDocument = (result: DemoResult, pdfUrl: string, view: "document" | "rules" = "document") => {
    if (result.live?.persistent) writeSession(result.live.jobId, view);
    else forgetSession();
    setPhase(view === "rules" ? { kind: "rules", result, pdfUrl } : { kind: "done", result, pdfUrl });
  };

  const process = async () => {
    if (!file || running.current || openingRef.current) return;
    running.current = true;
    dismissed.current = false;
    setProblem(null);
    setNotice(null);
    setStopError(null);
    const ctrl = new AbortController();
    processing.current = ctrl;
    setPhase({ kind: "busy", stage: "uploading" });
    try {
      const result = await processPdf(file, (stage) => {
        if (dismissed.current) return;
        setPhase((current) => current.kind === "stopping" ? current : { kind: "busy", stage, jobId: current.kind === "busy" ? current.jobId : undefined });
      }, {
        signal: ctrl.signal,
        onCancelError: (message) => setStopError(message),
        onJob: (job) => {
          writeSession(job.id, "processing");
          setPhase(dismissed.current ? { kind: "stopping", jobId: job.id } : { kind: "busy", stage: job.stage ?? job.status, jobId: job.id });
        },
      });
      dismissed.current = false;
      setStopError(null);
      showDocument(result, URL.createObjectURL(file));
    } catch (e) {
      dismissed.current = false;
      setStopError(null);
      if (e instanceof ProcessingError) {
        if (e.kind === "cancelled") {
          setNotice(null);
          if (readSession()?.view === "processing") forgetSession();
          setPhase((current) => current.kind === "done" || current.kind === "rules" ? current : { kind: "idle" });
        } else {
          forgetSession();
          setPhase({ kind: "idle" });
          setProblem({ kind: e.kind, message: e.message });
        }
      } else {
        forgetSession();
        setPhase({ kind: "idle" });
        setProblem({ kind: "failed", message: e instanceof Error ? e.message : String(e) });
      }
      setRefreshKey((k) => k + 1);
    } finally {
      processing.current = null;
      running.current = false;
    }
  };

  /** Returns the upload form to empty at once. The job is asked to stop, and a new one cannot start until that one has ended. */
  const acknowledgeStop = () => {
    dismissed.current = true;
    setFile(null);
    setNotice(null);
    setProblem(null);
    if (input.current) input.current.value = "";
    setPhase((current) => current.kind === "busy" ? { kind: "stopping", jobId: current.jobId } : current);
    processing.current?.abort();
  };

  const retryStop = async () => {
    const id = phase.kind === "stopping" ? phase.jobId : undefined;
    if (!id) return;
    setStopError(null);
    try {
      await cancelJob(id);
    } catch (e) {
      setStopError(e instanceof Error ? e.message : String(e));
    }
  };

  // A refresh drops the open page but not the job. Stored documents reopen; a job that is still running shows its real stage.
  useEffect(() => {
    const saved = readSession();
    if (!saved || resumed.current) return;
    resumed.current = true;
    let dead = false;
    void (async () => {
      running.current = true;
      try {
        const job = await getJob(saved.jobId);
        if (dead) return;
        if (job.status === "queued" || job.status === "processing") {
          const alreadyStopping = !!job.cancelRequested || job.stage === "cancelling";
          dismissed.current = alreadyStopping;
          if (alreadyStopping) setPhase({ kind: "stopping", jobId: job.id });
          else setPhase({ kind: "busy", stage: job.stage ?? job.status, jobId: job.id });
          const ctrl = new AbortController();
          processing.current = ctrl;
          const finished = await waitForJob(job, (stage) => { if (!dead && !dismissed.current) setPhase({ kind: "busy", stage, jobId: job.id }); }, ctrl.signal, (message) => { if (!dead) setStopError(message); });
          if (dead) return;
          if (finished.status === "completed" && finished.persistent) {
            const opened = await openStoredDocument(finished.id);
            if (!dead) showDocument(opened.result, URL.createObjectURL(opened.pdf), saved.view === "rules" ? "rules" : "document");
          } else if (finished.status === "cancelled" || (finished.status === "failed" && (finished.message ?? "").startsWith("Processing was cancelled"))) {
            dismissed.current = false;
            forgetSession();
            setStopError(null);
            setNotice(null);
            setPhase({ kind: "idle" });
          } else if (finished.status !== "completed") {
            forgetSession();
            setPhase({ kind: "idle" });
            setProblem({ kind: finished.status === "unsupported" ? "unsupported" : "failed", message: finished.message ?? "This document has no result to open." });
          } else {
            forgetSession();
            setPhase({ kind: "idle" });
          }
          return;
        }
        if (job.status === "cancelled" || (job.status === "failed" && (job.message ?? "").startsWith("Processing was cancelled"))) {
          forgetSession();
          setNotice(null);
          setPhase({ kind: "idle" });
          return;
        }
        if (job.status === "completed" && job.persistent && saved.view !== "processing") {
          const opened = await openStoredDocument(job.id);
          if (!dead) showDocument(opened.result, URL.createObjectURL(opened.pdf), saved.view === "rules" ? "rules" : "document");
          return;
        }
        forgetSession();
      } catch {
        if (!dead) forgetSession();
      } finally {
        processing.current = null;
        running.current = false;
      }
    })();
    return () => { dead = true; };
  }, []);

  /** Opens a stored document in the result view. Nothing is uploaded or processed: the backend serves what it stored.
   *  A cancel that is still settling does not block this: it is a different document. */
  const open = async (doc: StoredDocument) => {
    if (openingRef.current || (running.current && !dismissed.current)) return;
    openingRef.current = doc.id;
    setOpenProblem(null);
    setOpening(doc.id);
    try {
      const { result, pdf } = await openStoredDocument(doc.id);
      showDocument(result, URL.createObjectURL(pdf));
    } catch (e) {
      setOpenProblem({ id: doc.id, message: `${doc.filename} could not be opened. ${e instanceof Error ? e.message : String(e)}` });
    } finally {
      openingRef.current = null;
      setOpening(null);
    }
  };

  /** Back to the document list. `release` drops a finished in-memory job the way Back already did. A running extraction is never cancelled or deleted. */
  const goHome = (release: boolean) => {
    rulesNav.current = null;
    if (release && (phase.kind === "done" || phase.kind === "rules") && phase.result.live) releaseJob(phase.result.live.jobId, phase.result.live.persistent);
    dismissed.current = false;
    forgetSession();
    setPhase({ kind: "idle" });
    setFile(null);
    setProblem(null);
    setNotice(null);
    setStopError(null);
    setOpenProblem(null);
    setCancelDoc(null);
    if (input.current) input.current.value = "";
    setRefreshKey((k) => k + 1);
  };

  const reset = () => goHome(true);

  if (phase.kind === "done") {
    const { result, pdfUrl, focusId } = phase;
    return <ResultView result={result} pdfUrl={pdfUrl} initialSelectedId={focusId} onReset={reset} onHome={() => goHome(true)} onContinueToRules={() => { if (result.live?.persistent) writeSession(result.live.jobId, "rules"); setPhase({ kind: "rules", result, pdfUrl }); }} />;
  }
  if (phase.kind === "rules") {
    const { result, pdfUrl } = phase;
    // the rules of this job as the backend last stored them: kept on the result, so Document Review's Artifacts tab shows the same
    const rulesLoaded = (ruleJson: unknown) => setPhase((p) => (p.kind === "rules" && p.result.live ? { ...p, result: { ...p.result, live: { ...p.result.live, ruleJson } } } : p));
    return <RuleExtractionView result={result} onBack={() => { if (result.live?.persistent) writeSession(result.live.jobId, "document"); setPhase({ kind: "done", result, pdfUrl }); }}
                               onHome={() => goHome(false)}
                               onShowInPdf={(focusId) => { if (result.live?.persistent) writeSession(result.live.jobId, "document"); setPhase({ kind: "done", result, pdfUrl, focusId }); }} onRulesLoaded={rulesLoaded} nav={rulesNav} />;
  }

  const busy = phase.kind === "busy";
  const stopping = phase.kind === "stopping";
  const locked = busy || opening !== null; // one thing at a time: a run or opening a stored document. Stopping leaves the form usable.
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
            {notice && <div className="alert" role="status"><p>{notice}</p></div>}
            {stopError && (
              <div className="alert error" role="alert">
                <p>{stopError}</p>
                <button type="button" className="btn small" onClick={() => void retryStop()}>Try again</button>
              </div>
            )}
            {problem && (
              <div className="alert error" role="alert">
                <strong>{PROBLEM_TITLES[problem.kind]}</strong>
                <p>{problem.message}</p>
                {problem.kind === "failed" && file && <button type="button" className="btn small" onClick={() => void process()}>Try again</button>}
              </div>
            )}
            <button type="button" className="btn primary demo-process" onClick={() => void process()} disabled={!file || locked || stopping} aria-busy={busy}>
              {busy ? <><span className="spinner" aria-hidden="true" /> Processing…</> : "Process document"}
            </button>
            {phase.kind === "busy" && <ProcessingStatus stage={phase.stage} onCancel={acknowledgeStop} />}
          </div>
        </section>
        {cancelDoc && (
          <StopConfirm onKeep={() => setCancelDoc(null)} onStop={() => { const id = cancelDoc.id; setCancelDoc(null); void cancelJob(id).then(() => setRefreshKey((k) => k + 1), () => setRefreshKey((k) => k + 1)); }} />
        )}
        <RecentDocuments refreshKey={refreshKey} onOpen={(doc) => void open(doc)} openingId={opening} openError={openProblem} openDisabled={busy} onCancelDocument={busy ? undefined : setCancelDoc} />
      </div>
    </main>
  );
}

export function ResultView({ result, pdfUrl, initialSelectedId, onReset, onHome, onContinueToRules }: { result: DemoResult; pdfUrl: string; initialSelectedId?: string; onReset: () => void; onHome?: () => void; onContinueToRules?: () => void }) {
  const { model } = result;
  const [tab, setTab] = useState<"structure" | "artifacts">("structure");
  // opened from a rule's "Show in PDF": that element is selected (the PDF shows its page and highlights it)
  const initial = initialSelectedId ? model.elements.find((e) => e.id === initialSelectedId) : undefined;
  const [selected, setSelected] = useState<string | null>(initial?.id ?? null);
  const [page, setPage] = useState(firstPage(initial) ?? 1);
  const [full, setFull] = useState(false); // live Artifacts: the complete document instead of the selected element
  const [split, setSplit] = useState(DEFAULT_SPLIT); // the PDF panel's share of the width
  const splitRef = useRef<HTMLDivElement>(null);
  const element = useMemo(() => model.elements.find((e) => e.id === selected) ?? null, [model, selected]);
  const hl = highlightsOf(element);

  const select = useCallback((id: string) => {
    setSelected(id);
    const page = firstPage(model.elements.find((e) => e.id === id));
    if (page !== null) setPage(page);
  }, [model]);

  return (
    <main className="workspace demo-result">
      <div className="docbar">
        <button type="button" className="brand-link" onClick={onHome ?? onReset} aria-label="ODOS home"><Logo compact /></button>
        <span className="docbar-sep" aria-hidden="true" />
        <h2 title={result.filename ? `${result.filename} · ${result.title}` : result.title}>{result.filename ?? result.title}</h2>
        <span className="demo-status ok">Completed</span>{/* a result is only ever shown for a completed document */}
        <span className="spacer" />
        <button className="btn" onClick={onReset}><Icon name="back" size={16} />Back to documents</button>
        {onContinueToRules && <button className="btn primary" onClick={onContinueToRules}>Find Rules<Icon name="chevron-right" size={16} /></button>}
      </div>
      <div className="split" ref={splitRef} style={splitVars(split)}>
        <section className="pane left" aria-label="Original PDF">
          <PdfViewer url={pdfUrl} page={page} onPageChange={setPage} highlights={hl.boxes} approximate={hl.approximate} />
        </section>
        <SplitDivider containerRef={splitRef} value={split} onCommit={setSplit} />
        <section className="pane right" aria-label="Recognized legal structure">
          <div className="tabs" role="tablist">
            <button role="tab" aria-selected={tab === "structure"} className={tab === "structure" ? "active" : ""} onClick={() => setTab("structure")}>Legal structure</button>
            <button role="tab" aria-selected={tab === "artifacts"} className={tab === "artifacts" ? "active" : ""} onClick={() => setTab("artifacts")}>Artifacts</button>
          </div>
          <div className="tabbody">
            {tab === "structure" && (
              <div className="structure">
                <StructureTree model={model} selectedId={selected} onSelect={select} />
                <SourceDetail element={element} page={page} onGoToPage={setPage} />
              </div>
            )}
            {tab === "artifacts" && <Artifacts result={result} element={element} full={full} onFull={result.live ? setFull : undefined} />}
          </div>
        </section>
      </div>
    </main>
  );
}

export function SourceDetail({ element: e, page, onGoToPage }: { element: DocElement | null; page: number; onGoToPage: (page: number) => void }) {
  if (!e) return <div className="detail empty"><Icon name="info" size={20} /><span>Select an element to highlight its source text in the PDF.</span></div>;
  return (
    <div className="detail">
      <h3>{TYPE_LABELS[e.type] ?? e.type} {e.marker ?? ""}</h3>
      {e.title && <p className="title">{e.title}</p>}
      <blockquote className="origtext">{fullText(e) || <em>(no text)</em>}</blockquote>
      <dl className="kv">
        <dt>Pages</dt>
        <dd>{e.pages.length ? e.pages.map((p) => (
          <button key={p} className="link" onClick={() => onGoToPage(p)} aria-current={p === page ? "page" : undefined}
                  title={`Show page ${p} with the highlighted source text`}>p. {p}</button>
        )) : "—"}</dd>
        <dt>Source</dt><dd><code>{e.source_refs.join(", ") || "—"}</code></dd>
        <dt>Element id</dt><dd><code>{e.id}</code></dd>
      </dl>
    </div>
  );
}

function DoclingRaw({ jobId }: { jobId: string }) {
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
      <summary style={{ cursor: "pointer", padding: "12px" }}>
        Docling Raw JSON anzeigen / ausblenden
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
}) {
  const json = (!full && result.live && nodeJson(result.live, element)) || result.json;
  return (
    <div className="demo-artifacts">
      <div className="demo-artifact-tabs" role="group" aria-label="Artifact type">
        <button type="button" className="btn small" aria-pressed="true">Custom Legal JSON</button>
      </div>
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
        />
      )}
    </div>
  );
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
