import { useState } from "react";
import { classificationView, evidenceRows } from "../classification";
import type { Classification } from "../types";

interface Props {
  classification: Classification;
  onGoToPage: (page: number) => void;
  onRefresh?: () => void;
}

/** Detected document type with its evidence. The suggestion can be accepted or overridden in the mode picker. */
export function ClassificationPanel({ classification: c, onGoToPage, onRefresh }: Props) {
  const [open, setOpen] = useState(c.confidence_band !== "high");
  const v = classificationView(c);
  const rows = evidenceRows(c);
  return (
    <section className={`classification alert ${v.tone === "ok" ? "info" : v.tone}`} data-testid="classification" aria-label="Document classification">
      <div className="cls-head">
        <strong data-testid="classification-headline">{v.headline}</strong>
        <span className={`band band-${c.confidence_band}`} title={c.confidence_note}>{c.confidence_band}</span>
        <span className="spacer" />
        <button className="link" onClick={() => setOpen((o) => !o)}>{open ? "Hide evidence" : `Show evidence (${rows.length})`}</button>
        {onRefresh && <button className="link" onClick={onRefresh} title="Re-run the classification (uses the Docling output if it exists)">Re-check</button>}
      </div>
      <p className="cls-detail" data-testid="classification-detail">{v.detail}</p>
      {c.warnings.length > 0 && (
        <ul className="warnlist cls-warn">{c.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
      )}
      {open && (
        <div>
          <ul className="evidence">
            {rows.map((r) => (
              <li key={r.key}>
                <span className="w">+{r.weight}</span> {r.text}{" "}
                {r.page != null && <button className="link" onClick={() => onGoToPage(r.page!)}>p. {r.page}</button>}
              </li>
            ))}
            {rows.length === 0 && <li className="muted">No evidence found.</li>}
          </ul>
          <p className="muted small">
            {c.confidence_note} Read from: {c.input.source === "docling" ? "the Docling extraction" : "the PDF text layer"}, {c.input.pages_scanned}/{c.input.pages_total} pages.
          </p>
        </div>
      )}
    </section>
  );
}
