import type { ReactNode } from "react";
import { TYPE_LABELS } from "../structure";
import type { BoundingBox } from "../types";
import type { DemoResult, DoclingItem, PipelineDetails } from "./fixtures";

// "Processing details": how the previewed provision went through the offline pipeline. Everything shown is read from
// pipeline.json, the Legal JSON excerpt and the structure (cut from the pipeline outputs); the browser computes nothing.

const STAGES = ["Original PDF", "Docling output", "Legal parser → Document model", "Custom Legal JSON"];

// What the parser flags in the data mean (backend/src/odos/parsing/profiles/german_law/recognizer.py). Other flags are
// shown as they are.
const FLAG_NOTES: Record<string, string> = {
  page_break_continuation_merged_confirmed: "the text after the page break continues this unfinished Absatz and was joined to it",
};

const short = (t: string | undefined | null, n = 110) => {
  const s = (t ?? "").replace(/\s+/g, " ").trim();
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
};
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
const fmtBox = (b: BoundingBox | null | undefined) => (b ? `l ${b.l.toFixed(1)}, t ${b.t.toFixed(1)}, r ${b.r.toFixed(1)}, b ${b.b.toFixed(1)}` : "—");
const typeLabel = (t: string) => TYPE_LABELS[t] ?? t;
const codes = (xs: string[], sep = " ") => xs.map((x, i) => <span key={x}>{i ? sep : ""}<code>{x}</code></span>);

function Flags({ flags }: { flags?: string[] }) {
  if (!flags?.length) return <span className="muted">—</span>;
  return (
    <ul className="demo-flags">
      {flags.map((f) => (
        <li key={f}><code>{f}</code>{FLAG_NOTES[f] && <span className="muted"> {FLAG_NOTES[f]}</span>}</li>
      ))}
    </ul>
  );
}

function Step({ n, title, summary, children }: { n: number; title: string; summary: ReactNode; children: ReactNode }) {
  return (
    <details className="demo-step">
      <summary><span className="demo-step-n">{n}</span> <strong>{title}</strong> <span className="muted small">{summary}</span></summary>
      <div className="demo-step-body">{children}</div>
    </details>
  );
}

export function PipelineView({ result, onSelect, onOpenArtifacts }: { result: DemoResult; onSelect: (id: string) => void; onOpenArtifacts: () => void }) {
  const p = result.pipeline;
  return (
    <div className="demo-artifacts demo-pipeline">
      <ol className="demo-stages" aria-label="Processing stages">
        {STAGES.map((s) => <li key={s}>{s}</li>)}
      </ol>
      {p ? <Stages p={p} result={result} onSelect={onSelect} onOpenArtifacts={onOpenArtifacts} /> : (
        <div className="alert">Processing details are not part of this build. They are written by <code>npm run demo:fixtures</code> when the
          pipeline output directory contains <code>docling_raw.json</code>.</div>
      )}
    </div>
  );
}

function Stages({ p, result, onSelect, onOpenArtifacts }: { p: PipelineDetails; result: DemoResult; onSelect: (id: string) => void; onOpenArtifacts: () => void }) {
  const focus = p.elements.find((e) => e.id === p.focusId);
  const used = new Set(p.elements.flatMap((e) => e.source_refs));
  const depthOf = (id: string): number => {
    const e = p.elements.find((x) => x.id === id);
    return e?.parent_id && p.elements.some((x) => x.id === e.parent_id) ? depthOf(e.parent_id) + 1 : 0;
  };
  const joined = p.elements.filter((e) => e.source_refs.length > 1 && new Set(e.pages).size > 1);
  const docling = p.docling;
  return (
    <>
      <p className="muted small">
        Example: <strong className="demo-strong">{result.doc.example.label}</strong>
        {focus && focus.id !== result.doc.example.modelId && <>, <code>{focus.id}</code> with its children</>}.
      </p>

      <Step n={1} title="Docling output" summary={`${plural(docling.items.length, "extracted text item", "extracted text items")}${docling.itemsTotal ? ` (of ${docling.itemsTotal} in the document)` : ""}`}>
        <p className="muted small">
          Docling {docling.version ?? ""} turned the PDF into labelled text items with page and bounding box (PDF points, origin bottom left).
          Excerpt of <code>docling_raw.json</code>: the items this example uses and anything Docling placed between them.
        </p>
        <table className="demo-table">
          <thead><tr><th>Item</th><th>Label</th><th>Page</th><th>Bounding box</th><th>Extracted text</th></tr></thead>
          <tbody>
            {docling.items.map((t: DoclingItem) => (
              <tr key={t.self_ref} className={used.has(t.self_ref) ? "" : "demo-dim"}>
                <td><code>{t.self_ref}</code></td>
                <td>{t.label}{t.content_layer && t.content_layer !== "body" && <span className="muted"> ({t.content_layer})</span>}</td>
                <td>{(t.prov ?? []).map((v) => v.page_no).join(", ")}</td>
                <td className="small">{fmtBox(t.prov?.[0]?.bbox)}</td>
                <td>{short(t.orig ?? t.text)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <details className="demo-raw">
          <summary className="small">Raw Docling JSON of {docling.items.length === 1 ? "this item" : `these ${docling.items.length} items`}</summary>
          <pre className="preview demo-code" tabIndex={0}>{JSON.stringify(docling.items, null, 2)}</pre>
        </details>
      </Step>

      <Step n={2} title="Legal parser → Document model" summary={`${plural(p.elements.length, "recognized element", "recognized elements")} with parent/child links and source references`}>
        {joined.map((e) => (
          <p key={e.id} className="alert small">
            <code>{e.id}</code> runs over pages {e.pages.join("–")}: its text is joined from {codes(e.source_refs, " + ")}.
          </p>
        ))}
        <ul className="demo-model">
          {p.elements.map((e) => (
            <li key={e.id} style={{ marginLeft: depthOf(e.id) * 18 }}>
              <div className="demo-model-head">
                <span className="kind">{typeLabel(e.type)}</span> <strong>{[e.marker, e.title].filter(Boolean).join(" ")}</strong>
                <button className="link small" onClick={() => onSelect(e.id)}>Show in PDF</button>
              </div>
              <dl className="kv small">
                <dt>id</dt><dd><code>{e.id}</code></dd>
                <dt>parent_id</dt><dd><code>{e.parent_id ?? "—"}</code></dd>
                <dt>children_ids</dt><dd>{e.children_ids.length ? codes(e.children_ids) : "—"}</dd>
                <dt>source_refs</dt><dd>{codes(e.source_refs)} <span className="muted">(p. {e.pages.join(", ")})</span></dd>
                <dt>text</dt><dd>{short(e.content_text, 160) || "—"}</dd>
                {!!e.hygiene_flags?.length && <><dt>flags</dt><dd><Flags flags={e.hygiene_flags} /></dd></>}
              </dl>
            </li>
          ))}
        </ul>
        {p.warnings.length > 0 && <p className="muted small">Parser notes: {p.warnings.map((w) => `${w.code}: ${w.message}`).join("; ")}</p>}
      </Step>

      <Step n={3} title="Custom Legal JSON" summary="the exported hierarchy with numbering, text and pages">
        <LegalJson result={result} />
        <button className="link small" onClick={onOpenArtifacts}>Open the Custom Legal JSON preview and download</button>
      </Step>
    </>
  );
}

type JsonNode = { id?: string; type?: string; nativeType?: string; marker?: string; title?: string; text?: string; pages?: number[]; children?: JsonNode[] };
type Row = { node: JsonNode; parent: string | null; depth: number };

/** The nodes below `start` in document order, with the parent each one has in the nesting. */
function rowsOf(start: JsonNode, parent: string | null): Row[] {
  const rows: Row[] = [];
  const walk = (n: JsonNode, parent: string | null, depth: number) => {
    rows.push({ node: n, parent, depth });
    for (const c of n.children ?? []) walk(c, n.id ?? null, depth + 1);
  };
  walk(start, parent, 0);
  return rows;
}

function legalJsonRows(json: string): Row[] {
  try {
    return rowsOf(JSON.parse(json) as JsonNode, null);
  } catch {
    return [];
  }
}

// footnotes are listed beside the structure in Legal JSON, not as children
const NOT_CHILDREN = new Set(["footnote", "footnote_heading"]);

function LegalJson({ result }: { result: DemoResult }) {
  const rows = legalJsonRows(result.json);
  const byId = new Map(result.model.elements.map((e) => [e.id, e]));
  // the children the excerpt leaves out: the node's children in the document model that are not in the excerpt
  const omitted = (n: JsonNode) => {
    const all = (byId.get(n.id ?? "")?.children_ids ?? []).filter((c) => !NOT_CHILDREN.has(byId.get(c)?.type ?? ""));
    return all.length - (n.children?.length ?? 0);
  };
  return (
    <>
      <p className="muted small">
        The nodes of <code>{result.doc.files.json.split("/").pop()}</code>, an excerpt of <code>document.json</code> (the parent
        comes from the nesting; the format has no parent field). Each id is the id of the element in the document model.
      </p>
      <table className="demo-table">
        <thead><tr><th>id</th><th>type</th><th>parent</th><th>children</th><th>text</th><th>pages</th></tr></thead>
        <tbody>
          {rows.map(({ node, parent, depth }) => (
            <tr key={node.id}>
              <td style={{ paddingLeft: 8 + depth * 14 }}><code>{node.id}</code></td>
              <td>{node.type}{node.nativeType && <span className="muted"> ({node.nativeType})</span>}</td>
              <td>{parent ? <code>{parent}</code> : "—"}</td>
              <td>
                {(node.children ?? []).map((c) => c.id).join(", ") || "—"}
                {omitted(node) > 0 && <span className="muted"> (+{omitted(node)} not shown)</span>}
              </td>
              <td>{short([node.marker, node.title, node.text].filter(Boolean).join(" "), 90)}</td>
              <td>{(node.pages ?? []).join(", ") || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
