import { AKN_HINT, TYPE_LABELS, hasPartialBox } from "../structure";
import type { DocElement, EditableField, ParserWarning, ReviewView } from "../types";
import { ReviewEditor } from "./ReviewEditor";

interface Props {
  element: DocElement | null;
  warnings: ParserWarning[];
  eId: string | null;
  onGoToPage: (page: number) => void;
  review?: ReviewView | null;
  reviewBusy?: boolean;
  onSave?: (field: EditableField, value: string, note: string) => Promise<boolean>;
  onConfirm?: (note: string) => Promise<boolean>;
  onNext?: () => void;
}

export function ElementDetail({ element: e, warnings, eId, onGoToPage, review, reviewBusy = false, onSave, onConfirm, onNext }: Props) {
  if (!e) return <div className="detail muted pad">Select an element in the structure to see its text and source.</div>;
  return (
    <div className="detail">
      <h3>
        {TYPE_LABELS[e.type] ?? e.type} {e.marker ?? ""}
        {e.uncertain && <span className="badge uncertain">uncertain</span>}
      </h3>
      {e.title && <p className="title">{e.title}</p>}
      {e.reviewed && e.content_text !== e.original_text && !e.title && (
        <>
          <p className="muted small">Reviewed text:</p>
          <blockquote className="origtext reviewed-text">{e.content_text}</blockquote>
        </>
      )}
      <p className="muted small">Original text from the PDF (Docling, unchanged):</p>
      <blockquote className="origtext">{e.original_text || <em>(no text)</em>}</blockquote>
      {e.table && (
        <table className="mini"><tbody>{e.table.rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody></table>
      )}
      {e.uncertain && (
        <div className="alert warn">
          <strong>Why uncertain:</strong> {e.uncertainty_reasons.join(", ")}. The parser kept this element at its document position instead of guessing.
        </div>
      )}
      {warnings.length > 0 && (
        <ul className="warnlist">
          {warnings.map((w, i) => <li key={i}><span className={`sev ${w.severity}`}>{w.severity}</span> <code>{w.code}</code> {w.message}</li>)}
        </ul>
      )}
      {hasPartialBox(e) && (
        <div className="alert info" data-testid="partial-box-notice">
          <strong>Approximate highlight.</strong> The source PDF item holds several paragraphs and Docling gives one box for
          all of it. The highlighted box may cover more than this element; the exact text range is characters{" "}
          {e.source_spans!.map((s) => `${s.start}–${s.end}`).join(", ")} of {e.source_spans![0].ref}.
        </div>
      )}
      {(e.highlight_boxes ?? []).length > 0 && (
        <p className="muted" data-testid="exact-box-notice">
          Exact highlight: {e.highlight_boxes!.length} line rectangle(s) proven from the PDF glyphs (characters{" "}
          {(e.source_spans ?? []).map((s) => `${s.start}–${s.end}`).join(", ")} of {(e.source_spans ?? [])[0]?.ref}).
        </p>
      )}
      {(e.hygiene_flags ?? []).length > 0 && (
        <p className="muted">Extraction notes: {(e.hygiene_flags ?? []).join(", ")}</p>
      )}
      {e.search_text && e.search_text !== e.original_text && (
        <details><summary className="muted">Normalised search text (derived)</summary><blockquote className="origtext">{e.search_text}</blockquote></details>
      )}
      {review && onSave && onConfirm && (
        <ReviewEditor element={e} review={review} busy={reviewBusy} onSave={onSave} onConfirm={onConfirm} onNext={onNext ?? (() => {})} />
      )}
      <h4>Source</h4>
      <dl className="kv">
        <dt>Pages</dt>
        <dd>{e.pages.length ? e.pages.map((p) => <button key={p} className="link" onClick={() => onGoToPage(p)}>p. {p}</button>) : "—"}</dd>
        <dt>Docling item</dt><dd><code>{e.source_refs.join(", ") || "—"}</code> {e.docling_label && <span className="muted">({e.docling_label})</span>}</dd>
        <dt>Bounding box</dt>
        <dd>
          {e.provenance.filter((p) => p.bbox).map((p, i) => (
            <div key={i}><code>p.{p.page_no}: l={p.bbox!.l.toFixed(1)} t={p.bbox!.t.toFixed(1)} r={p.bbox!.r.toFixed(1)} b={p.bbox!.b.toFixed(1)} ({p.bbox!.coord_origin})</code></div>
          ))}
          {!e.provenance.some((p) => p.bbox) && "—"}
        </dd>
        <dt>Model id</dt><dd><code>{e.id}</code></dd>
        {AKN_HINT[e.type] && <><dt>Akoma Ntoso</dt><dd><code>&lt;{AKN_HINT[e.type]}&gt;</code>{eId && <> · eId <code>{eId}</code></>}</dd></>}
      </dl>
    </div>
  );
}
