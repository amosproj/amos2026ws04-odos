import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "../components/Icon";
import { PdfViewer } from "../components/PdfViewer";
import { StructureTree } from "../components/StructureTree";
import { TYPE_LABELS, firstPage, fullText, highlightsOf } from "../structure";
import type { DocElement } from "../types";
import type { DemoResult } from "./fixtures";
import { STAGE_LABELS, nodeJson, processPdf, releaseJob } from "./live";
import "./demo.css";


type Phase = { kind: "idle" } | { kind: "busy"; stage: string } | { kind: "done"; result: DemoResult; pdfUrl: string };

export default function DemoApp() {
  const [file, setFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const pdfUrl = phase.kind === "done" ? phase.pdfUrl : null;
  useEffect(() => () => { if (pdfUrl) URL.revokeObjectURL(pdfUrl); }, [pdfUrl]);

  const choose = (f: File | undefined) => {
    setFile(f ?? null);
    setError(null);
  };

  const process = async () => {
    if (!file) return;
    setError(null);
    setPhase({ kind: "busy", stage: "checking" });
    try {
      const result = await processPdf(file, (stage) => {
        setPhase({ kind: "busy", stage });
      });
      setPhase({ kind: "done", result, pdfUrl: URL.createObjectURL(file) });
    } catch (e) {
      setPhase({ kind: "idle" });
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const reset = () => {
    if (phase.kind === "done" && phase.result.live) releaseJob(phase.result.live.jobId, phase.result.live.persistent);
    setPhase({ kind: "idle" });
    setFile(null);
    setError(null);
    if (input.current) input.current.value = "";
  };

  if (phase.kind === "done") return <ResultView result={phase.result} pdfUrl={phase.pdfUrl} onReset={reset} />;

  const busy = phase.kind === "busy";
  return (
    <main className="demo-upload">
      <div className="demo-card">
        <h1 className="demo-title">ODOS</h1>
        <label
          className={`demo-drop${file ? " has-file" : ""}`}
          onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) e.preventDefault(); }}
          onDrop={(e) => { e.preventDefault(); choose(e.dataTransfer.files[0]); }}
        >
          <input ref={input} type="file" accept="application/pdf,.pdf" className="sr-only" onChange={(e) => choose(e.target.files?.[0])} disabled={busy} />
          <Icon name="upload" size={20} />
          <span>{file ? file.name : "Choose a PDF or drop it here"}</span>
        </label>
        <button className="btn primary demo-process" onClick={() => void process()} disabled={!file || busy}>
          {phase.kind === "busy"
            ? <><span className="spinner" aria-hidden="true" /> {phase.stage === "checking" ? "Loading result…" : STAGE_LABELS[phase.stage] ?? "Processing…"}</>
            : "Process Document"}
        </button>
              {busy && (
        <p className="muted small demo-hint">
          Long documents take a few minutes (Docling extraction).
        </p>
      )}
        {error && <div className="alert warn" role="alert">{error}</div>}
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
        <span className="demo-brand">ODOS</span>
        <h2 title={result.title}>{result.title}</h2>
        <span className="spacer" />
        <button className="btn" onClick={onReset}>Choose another PDF</button>
      </div>
      <div className="split">
        <section className="pane left" aria-label="Original PDF">
          <PdfViewer url={pdfUrl} page={page} onPageChange={setPage} highlights={hl.boxes} approximate={hl.approximate} />
        </section>
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
  if (!e) return <div className="detail muted pad">Select an element to highlight its source text in the PDF.</div>;
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
