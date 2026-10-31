import { useState } from "react";
import { api } from "../api";
import { FIELD_LABELS, REVIEW_STATE_LABELS, nextUnresolved, reviewBadge } from "../review";
import type { ReviewView } from "../types";

interface Props {
  docId: string;
  review: ReviewView;
  busy: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onDecide: (action: "approve" | "request-changes" | "reopen", note: string) => void;
}

export function ReviewPanel({ docId, review: r, busy, selectedId, onSelect, onDecide }: Props) {
  const [note, setNote] = useState("");
  const badge = reviewBadge(r);
  const v = r.validation;
  const next = nextUnresolved(r, selectedId);
  return (
    <div className="pad review-panel" data-testid="review-panel">
      <div className="cards">
        <div className={`card ${r.state === "approved" ? "ok" : ""}`}><b>{REVIEW_STATE_LABELS[r.state]}</b><span>review state</span></div>
        <div className="card"><b>r{r.model_revision}</b><span>model revision (review rev. {r.review_revision})</span></div>
        <div className="card"><b>{r.corrections.length}</b><span>corrections</span></div>
        <div className={`card ${r.unresolved_uncertain_ids.length ? "bad" : "ok"}`}><b>{r.unresolved_uncertain_ids.length}</b><span>uncertain not yet checked</span></div>
        {v && <div className={`card ${v.xsd_valid ? "ok" : "bad"}`}><b>{v.xsd_valid ? "valid" : "invalid"}</b><span>XSD (revision {v.model_revision})</span></div>}
      </div>
      <p className="muted">{badge.label}. Corrections are stored as versioned patches; the original PDF, Docling extraction and document model are unchanged.</p>

      <h4>Uncertain elements</h4>
      <p>
        {r.unresolved_uncertain_ids.length ? `${r.unresolved_uncertain_ids.length} of ${r.uncertain_element_ids.length} still need an explicit check.` : `All ${r.uncertain_element_ids.length} uncertain elements have been checked.`}{" "}
        {next && <button className="btn small" onClick={() => onSelect(next)}>Go to next unchecked</button>}
      </p>

      <h4>Validation of revision {r.model_revision}</h4>
      {v ? (
        <ul className="warnlist">
          <li>Akoma Ntoso generated: {v.generated ? "yes" : "no"}{v.xml_sha256 ? ` · sha256 ${v.xml_sha256.slice(0, 12)}…` : ""}</li>
          <li>Official OASIS XSD: {v.xsd_valid ? "valid" : `invalid (${v.xsd_errors.length} errors)`}</li>
          <li>XML text matches the reviewed model: {v.text_identical_to_reviewed_model ? "yes" : "no"}</li>
          <li>Corrected elements (reviewer text, not verbatim from the PDF): {v.corrected_elements.length}</li>
          {v.blocking_errors.map((b, i) => <li key={i} className="sev warning">{b}</li>)}
        </ul>
      ) : <p className="muted">Not validated.</p>}
      {v?.generated && (
        <p>
          <a className="btn small" href={api.revisionUrl(docId, r.model_revision, "xml")} download>Download XML r{r.model_revision}</a>{" "}
          <a className="btn small" href={api.revisionUrl(docId, r.model_revision, "traceability")} download>Traceability</a>{" "}
          <a className="btn small" href={api.revisionUrl(docId, r.model_revision, "validation")} download>XSD report</a>
        </p>
      )}
      {r.original_export_superseded && <p className="muted">The original export (revision 0) is superseded by the reviewed revision.</p>}

      <h4>Decision</h4>
      {r.state === "approved" && r.approval ? (
        <div className="alert info" data-testid="approved-notice">
          Approved model revision {r.approval.model_revision} on {new Date(r.approval.approved_at).toLocaleString()} ({r.approval.corrections} corrections, {r.approval.confirmed_uncertain} uncertain elements checked).
          {r.approval.note ? ` Note: ${r.approval.note}` : ""}
        </div>
      ) : null}
      {!r.can_approve && r.state !== "approved" && (
        <div className="alert warn" data-testid="approval-blockers"><strong>Approval blocked:</strong><ul className="warnlist">{r.approval_blockers.map((b, i) => <li key={i}>{b}</li>)}</ul></div>
      )}
      <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Decision note (optional)" aria-label="Decision note" disabled={busy} />
      <div className="edit-row">
        {r.state === "approved" ? (
          <button className="btn" disabled={busy} onClick={() => onDecide("reopen", note)}>Reopen review</button>
        ) : (
          <>
            <button className="btn primary" disabled={busy || !r.can_approve} onClick={() => onDecide("approve", note)} title={r.can_approve ? "" : r.approval_blockers.join(" ")}>Approve revision {r.model_revision}</button>
            <button className="btn" disabled={busy} onClick={() => onDecide("request-changes", note)}>Request changes</button>
          </>
        )}
      </div>

      <h4>Corrections ({r.corrections.length})</h4>
      <ul className="warnlist">
        {r.corrections.map((c) => (
          <li key={c.id}>
            <button className="link" onClick={() => onSelect(c.element_id)}>{c.element_id.split("/").slice(-3).join("/")}</button>{" "}
            {FIELD_LABELS[c.field]}: <del>{c.original_value}</del> → <ins>{c.corrected_value}</ins> <span className="muted">r{c.model_revision}{c.note ? ` · ${c.note}` : ""}</span>
          </li>
        ))}
        {!r.corrections.length && <li className="muted">None.</li>}
      </ul>
      <details><summary className="muted">History ({r.history.length})</summary>
        <ul className="warnlist">{r.history.map((h, i) => <li key={i}>{new Date(h.at).toLocaleString()} · {h.event}{h.detail ? ` · ${h.detail}` : ""}</li>)}</ul>
      </details>
    </div>
  );
}
