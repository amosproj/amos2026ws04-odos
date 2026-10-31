import { useEffect, useState } from "react";
import { FIELD_LABELS, editableFields } from "../review";
import type { DocElement, EditableField, ReviewView } from "../types";

interface Props {
  element: DocElement;
  review: ReviewView;
  busy: boolean;
  onSave: (field: EditableField, value: string, note: string) => Promise<boolean>;
  onConfirm: (note: string) => Promise<boolean>;
  onNext: () => void;
}

/** Correct text, heading or marker of one element; confirm uncertain elements. Original Docling text stays visible. */
export function ReviewEditor({ element: e, review, busy, onSave, onConfirm, onNext }: Props) {
  const fields = editableFields(e);
  const [field, setField] = useState<EditableField | null>(fields[0] ?? null);
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  useEffect(() => {
    const f = editableFields(e)[0] ?? null;
    setField(f);
    setValue(f ? ((e as unknown as Record<string, string | null>)[f] ?? "") : "");
    setNote("");
  }, [e]);
  useEffect(() => {
    if (field) setValue((e as unknown as Record<string, string | null>)[field] ?? "");
  }, [field]); // eslint-disable-line react-hooks/exhaustive-deps

  const locked = review.state === "approved";
  const confirmed = review.confirmations.some((c) => c.element_id === e.id);
  const unresolved = review.unresolved_uncertain_ids.includes(e.id);
  const current = field ? (e as unknown as Record<string, string | null>)[field] ?? "" : "";
  const history = review.corrections.filter((c) => c.element_id === e.id);

  return (
    <div className="review-editor" data-testid="review-editor">
      <h4>Review</h4>
      {e.reviewed && (
        <div className="alert info" data-testid="corrected-notice">
          <strong>Corrected by a reviewer — not verbatim from the PDF.</strong>
          <ul className="diffs">
            {Object.entries(e.reviewed.fields).map(([f, v]) => (
              <li key={f}>
                {FIELD_LABELS[f as EditableField] ?? f}: <del>{v.original ?? "—"}</del> → <ins>{v.corrected}</ins>
              </li>
            ))}
          </ul>
        </div>
      )}
      {locked && <p className="muted">The document is approved. Reopen the review to make changes.</p>}
      {fields.length === 0 ? (
        <p className="muted">This element type cannot be edited. Structural editing (moving, adding or deleting elements) is not supported yet.</p>
      ) : (
        <form
          onSubmit={(ev) => {
            ev.preventDefault();
            if (field) void onSave(field, value, note).then((ok) => ok && setNote(""));
          }}
        >
          <div className="edit-row">
            <label>
              Field{" "}
              <select value={field ?? ""} onChange={(ev) => setField(ev.target.value as EditableField)} disabled={locked || busy}>
                {fields.map((f) => <option key={f} value={f}>{FIELD_LABELS[f]}</option>)}
              </select>
            </label>
          </div>
          {field === "content_text" ? (
            <textarea value={value} onChange={(ev) => setValue(ev.target.value)} rows={5} disabled={locked || busy} aria-label="Corrected text" />
          ) : (
            <input value={value} onChange={(ev) => setValue(ev.target.value)} disabled={locked || busy} aria-label={`Corrected ${field ?? ""}`} />
          )}
          <input value={note} onChange={(ev) => setNote(ev.target.value)} placeholder="Note for this correction (optional)" disabled={locked || busy} aria-label="Reviewer note" />
          <div className="edit-row">
            <button className="btn primary small" type="submit" disabled={locked || busy || value === current}>Save correction</button>
            <span className="muted small">Saves a new revision, regenerates the XML and validates it against the official XSD.</span>
          </div>
        </form>
      )}
      {e.uncertain && (
        <div className="edit-row">
          {confirmed ? (
            <span className="badge ok">checked</span>
          ) : (
            <button className="btn small" disabled={locked || busy || !unresolved} onClick={() => void onConfirm(note).then((ok) => ok && onNext())}>
              Confirm as checked &amp; next
            </button>
          )}
          <span className="muted small">Uncertain elements must be checked explicitly before approval.</span>
        </div>
      )}
      {history.length > 0 && (
        <details>
          <summary className="muted">Correction history ({history.length})</summary>
          <ul className="warnlist">
            {history.map((c) => (
              <li key={c.id}>
                <code>{c.id}</code> r{c.model_revision} {FIELD_LABELS[c.field]}: “{c.previous_value}” → “{c.corrected_value}” · {new Date(c.timestamp).toLocaleString()}
                {c.note ? ` · ${c.note}` : ""}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
