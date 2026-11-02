import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "../components/Icon";
import { PdfViewer } from "../components/PdfViewer";
import { StructureTree } from "../components/StructureTree";
import { TYPE_LABELS, firstPage, highlightsOf } from "../structure";
import type { DocElement } from "../types";
import { fixtureUrl, loadManifest, loadResult, resolveUpload, type DemoDocument, type DemoResult } from "./fixtures";
import { PipelineView } from "./PipelineView";
import "./demo.css";

// Static proof of concept: no backend. "Process Document" looks the chosen PDF up among the prepared documents and
// shows their previously generated pipeline results; any other PDF is refused with an explanation.

type Phase = { kind: "idle" } | { kind: "checking" } | { kind: "done"; result: DemoResult; pdfUrl: string };

export default function DemoApp() {
  const [docs, setDocs] = useState<DemoDocument[] | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => { void loadManifest().then(setDocs); }, []);
  const pdfUrl = phase.kind === "done" ? phase.pdfUrl : null;
  useEffect(() => () => { if (pdfUrl) URL.revokeObjectURL(pdfUrl); }, [pdfUrl]);

  const choose = (f: File | undefined) => {
    setFile(f ?? null);
    setError(null);
  };

  const process = async () => {
    if (!file) return;
    setError(null);
    setPhase({ kind: "checking" });
    try {
      const doc = await resolveUpload(await file.arrayBuffer(), file.name, docs ?? (await loadManifest()));
      const result = await loadResult(doc);
      setPhase({ kind: "done", result, pdfUrl: URL.createObjectURL(file) });
    } catch (e) {
      setPhase({ kind: "idle" });
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const reset = () => {
    setPhase({ kind: "idle" });
    setFile(null);
    setError(null);
    if (input.current) input.current.value = "";
  };

  if (phase.kind === "done") return <ResultView result={phase.result} pdfUrl={phase.pdfUrl} onReset={reset} />;

  const busy = phase.kind === "checking";
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
          {busy ? <><span className="spinner" aria-hidden="true" /> Loading result…</> : "Process Document"}
        </button>
        {error && <div className="alert warn" role="alert">{error}</div>}
      </div>
    </main>
  );
}

export function ResultView({ result, pdfUrl, onReset }: { result: DemoResult; pdfUrl: string; onReset: () => void }) {
  const { doc, model } = result;
  const [tab, setTab] = useState<"structure" | "artifacts" | "pipeline">("structure");
  const [selected, setSelected] = useState<string | null>(null);
  const [page, setPage] = useState(1);
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
        <h2 title={doc.title}>{doc.title}</h2>
        <span className="chip" title="Loaded from previously generated pipeline output; nothing was processed in the browser">precomputed result</span>
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
            <button role="tab" aria-selected={tab === "pipeline"} className={tab === "pipeline" ? "active" : ""} onClick={() => setTab("pipeline")}>Processing details</button>
          </div>
          <div className="tabbody">
            {tab === "structure" && (
              <div className="structure">
                <StructureTree model={model} selectedId={selected} onSelect={select} />
                <SourceDetail element={element} onGoToPage={setPage} />
              </div>
            )}
            {tab === "artifacts" && <Artifacts result={result} />}
            {tab === "pipeline" && <PipelineView result={result} onSelect={(id) => { select(id); setTab("structure"); }} onOpenArtifacts={() => setTab("artifacts")} />}
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

/** The Legal JSON 2.0 excerpt, shown exactly as the downloaded file. */
export function Artifacts({ result }: { result: DemoResult }) {
  const file = result.doc.files.json;
  return (
    <div className="demo-artifacts">
      <section className="demo-artifact">
        <div className="demo-artifact-head">
          <h3>Custom Legal JSON</h3>
          <a className="btn small" href={fixtureUrl(file)} download={file.split("/").pop()}>Download</a>
        </div>
        <pre className="preview demo-code" tabIndex={0}>{result.json.replace(/\n$/, "")}</pre>
      </section>
    </div>
  );
}
