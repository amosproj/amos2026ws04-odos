import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppHeader } from "../components/AppHeader";
import { Icon } from "../components/Icon";
import { Logo } from "../components/Logo";
import { PdfViewer } from "../components/PdfViewer";
import { ProcessingStatus } from "../components/ProcessingStatus";
import { RecentDocuments, type DocumentProblem } from "../components/RecentDocuments";
import { DEFAULT_SPLIT, SplitDivider, splitVars } from "../components/SplitDivider";
import { StructureTree } from "../components/StructureTree";
import { TYPE_LABELS, firstPage, highlightsOf } from "../structure";
import type { DocElement } from "../types";
import type { DemoResult } from "./fixtures";
import { ProcessingError, nodeJson, openStoredDocument, pdfProblem, processPdf, releaseJob, type StoredDocument } from "./live";
import "./demo.css";


type Phase = { kind: "idle" } | { kind: "busy"; stage: string } | { kind: "done"; result: DemoResult; pdfUrl: string };
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
  const input = useRef<HTMLInputElement>(null);
  const running = useRef(false); // processing or opening; set synchronously: the disabled state only follows after the next render

  const pdfUrl = phase.kind === "done" ? phase.pdfUrl : null;
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
    setProblem(null);
    setPhase({ kind: "busy", stage: "uploading" });
    try {
      const result = await processPdf(file, (stage) => {
        setPhase({ kind: "busy", stage });
      });
      setPhase({ kind: "done", result, pdfUrl: URL.createObjectURL(file) });
    } catch (e) {
      setPhase({ kind: "idle" });
      setProblem({ kind: e instanceof ProcessingError ? e.kind : "failed", message: e instanceof Error ? e.message : String(e) });
      setRefreshKey((k) => k + 1);
    } finally {
      running.current = false;
    }
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
    if (phase.kind === "done" && phase.result.live) releaseJob(phase.result.live.jobId, phase.result.live.persistent);
    setPhase({ kind: "idle" });
    setFile(null);
    setProblem(null);
    setOpenProblem(null);
    if (input.current) input.current.value = "";
  };

  if (phase.kind === "done") return <ResultView result={phase.result} pdfUrl={phase.pdfUrl} onReset={reset} />;

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
            {phase.kind === "busy" && <ProcessingStatus stage={phase.stage} />}
          </div>
        </section>
        <RecentDocuments refreshKey={refreshKey} onOpen={(doc) => void open(doc)} openingId={opening} openError={openProblem} openDisabled={busy} />
      </div>
    </main>
  );
}

export function ResultView({ result, pdfUrl, onReset }: { result: DemoResult; pdfUrl: string; onReset: () => void }) {
  const { model } = result;
  const [tab, setTab] = useState<"structure" | "artifacts">("structure");
  const [selected, setSelected] = useState<string | null>(null);
  const [page, setPage] = useState(1);
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
        <Logo compact />
        <span className="docbar-sep" aria-hidden="true" />
        <h2 title={result.filename ? `${result.filename} · ${result.title}` : result.title}>{result.filename ?? result.title}</h2>
        <span className="demo-status ok">Completed</span>{/* a result is only ever shown for a completed document */}
        <span className="spacer" />
        <button className="btn" onClick={onReset}><Icon name="back" size={16} />Back to documents</button>
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
                <SourceDetail element={element} onGoToPage={setPage} />
              </div>
            )}
            {tab === "artifacts" && <Artifacts result={result} element={element} full={full} onFull={result.live ? setFull : undefined} />}
          </div>
        </section>
      </div>
    </main>
  );
}

function SourceDetail({ element: e, onGoToPage }: { element: DocElement | null; onGoToPage: (page: number) => void }) {
  if (!e) return <div className="detail empty"><Icon name="info" size={20} /><span>Select an element to highlight its source text in the PDF.</span></div>;
  return (
    <div className="detail">
      <h3>{TYPE_LABELS[e.type] ?? e.type} {e.marker ?? ""}</h3>
      {e.title && <p className="title">{e.title}</p>}
      <blockquote className="origtext">{e.original_text || <em>(no text)</em>}</blockquote>
      <dl className="kv">
        <dt>Pages</dt>
        <dd>{e.pages.length ? e.pages.map((p) => <button key={p} className="link" onClick={() => onGoToPage(p)}>p. {p}</button>) : "—"}</dd>
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


export function Artifacts({ result, element = null, full, onFull }: { result: DemoResult; element?: DocElement | null; full?: boolean; onFull?: (full: boolean) => void }) {
  const json = (!full && result.live && nodeJson(result.live, element)) || result.json;
  return (
    <div className="demo-artifacts">
      <section className="demo-artifact">
        <div className="demo-artifact-head">
          <h3>Custom Legal JSON</h3>
          {onFull && (
            <div className="demo-toggle" role="group" aria-label="JSON preview">
              {[false, true].map((f) => (
                <button key={String(f)} className="btn small" aria-pressed={!!full === f} onClick={() => onFull(f)}>{f ? "Full document" : "Selected element"}</button>
              ))}
            </div>
          )}
          <a className="btn small" href={result.download.href} download={result.download.name}>Download</a>
        </div>
        <pre className="preview demo-code" tabIndex={0}>{json.replace(/\n$/, "")}</pre>
      </section>
      
      {result.live && (
        <DoclingRaw
          key={result.live.jobId}
          jobId={result.live.jobId}
        />
      )}
    </div>
  );
}
