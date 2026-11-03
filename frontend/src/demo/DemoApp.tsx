import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "../components/Icon";
import { PdfViewer } from "../components/PdfViewer";
import { StructureTree } from "../components/StructureTree";
import { TYPE_LABELS, firstPage, highlightsOf } from "../structure";
import type { DocElement } from "../types";
import { loadManifest, loadResult, resolveUpload, type DemoResult } from "./fixtures";
import { STAGE_LABELS, deleteJob, nodeJson, processPdf } from "./live";
import "./demo.css";

// "Process Document" sends the chosen PDF to the ODOS backend, which recognizes its type and runs the whole pipeline on
// it (src/demo/live.ts). Opening the page with ?example selects the prepared example mode instead: it looks the PDF up
// among the prepared documents and shows their previously generated results (src/demo/fixtures.ts); any other PDF is
// refused there with an explanation.

const EXAMPLE = new URLSearchParams(globalThis.location?.search).has("example");
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
      const result = EXAMPLE
        ? await loadResult(await resolveUpload(await file.arrayBuffer(), file.name, await loadManifest()))
        : await processPdf(file, (stage) => setPhase({ kind: "busy", stage }));
      setPhase({ kind: "done", result, pdfUrl: URL.createObjectURL(file) });
    } catch (e) {
      setPhase({ kind: "idle" });
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const reset = () => {
    if (phase.kind === "done" && phase.result.live) void deleteJob(phase.result.live.jobId); // its files are not kept
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
        {busy && !EXAMPLE && <p className="muted small demo-hint">Long documents take a few minutes (Docling extraction).</p>}
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
        {!result.live && <span className="chip" title="Loaded from previously generated pipeline output; nothing was processed in the browser">precomputed result</span>}
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
  if (!e) return <div className="detail muted pad">Select an element to highlight its source text in the PDF.</div>;
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

/** Prepared example: the Legal JSON 2.0 excerpt, shown exactly as the downloaded file. Live: a preview of the selected
 *  element or (`full`, switched with `onFull`) of the whole document, and the download of the complete document.json. */
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
    </div>
  );
}
