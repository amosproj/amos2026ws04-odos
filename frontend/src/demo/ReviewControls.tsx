import { useEffect, useRef, useState } from "react";
import { Icon } from "../components/Icon";
import { HttpError, getRuleHistory, postRuleReview, type RuleHistoryEvent, type RuleReviewEntry, type ReviewAction } from "./live";
import { reviewLabel, type RuleItem } from "./ruleResults";
import type { ReviewApi } from "./useRuleReviews";

export const REVIEW_UNAVAILABLE = "Review decisions cannot be saved right now.";
export const REVIEW_STALE = "The rules on this page are not the current extraction of this job: another extraction has replaced them since they were loaded. Review actions are disabled until the current results are loaded.";
export const REVIEW_UNIDENTIFIED = "These rules carry no extraction identifier (_generation.generatedAt), so a decision cannot be tied to them. Review actions are disabled; run a new extraction to review rules.";
export const REVIEW_NO_BACKEND = "Review decisions need the ODOS backend, which did not process this document.";

const ACTION_LABEL: Record<ReviewAction, string> = { accept: "Accepted", reject: "Rejected", edit: "Edited", reset: "Edit reset" };
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "");
/** An extraction ID is the generation time of its rules.json: shown as a date when it reads as one. */
const extractionLabel = (id: string) => (Number.isNaN(Date.parse(id)) ? id : new Date(id).toLocaleString());

interface Props {
  jobId: string;
  rule: RuleItem;
  api: ReviewApi;
  reviewer: string;
  onReviewer: (name: string) => void;
  onEntry: (ruleId: string, entry: RuleReviewEntry) => void;
  onReload: () => Promise<void>;
}

type Form = null | "reject" | "edit";

/** Human Review of one rule. Disabled with an explanation unless the backend stores decisions; otherwise Accept, Reject
 *  (with a reason) and Edit JSON (validated by the backend) append events to the audit trail. Nothing is applied before the
 *  backend has answered, and the extracted record is never modified: an edit is stored beside it. */
export function ReviewControls({ jobId, rule, api, reviewer, onReviewer, onEntry, onReload }: Props) {
  const entry = api.kind === "ready" ? api.data.rules[rule.id] ?? null : null;
  const extractionId = api.kind === "ready" ? api.data.extractionId : null;
  const [form, setForm] = useState<Form>(null);
  const [rejectReason, setRejectReason] = useState(""); // separate from the edit's reason: one form's text never leaks into the other
  const [editReason, setEditReason] = useState("");
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sending = useRef(false); // set synchronously: a second click must not send a second event
  const name = reviewer.trim();

  // another rule, or other rules (a new extraction, a changed record): a clean form, so a draft written for one record is never sent for another
  const ruleHash = entry?.ruleSha256 ?? null;
  useEffect(() => { setForm(null); setRejectReason(""); setEditReason(""); setError(null); }, [rule.id]);
  useEffect(() => { setForm(null); setRejectReason(""); setEditReason(""); }, [extractionId, ruleHash]); // the reason a conflict was reported stays visible

  const send = async (action: ReviewAction, extra: { reason?: string; editedRule?: Record<string, unknown> } = {}) => {
    if (!entry || !extractionId || sending.current) return;
    if (!name) { setError("Enter your reviewer name first."); return; }
    sending.current = true;
    setBusy(true);
    setError(null);
    try {
      const next = await postRuleReview(jobId, { ruleId: rule.id, extractionId, expectedRuleSha256: entry.ruleSha256, expectedLastEventId: entry.lastEventId, action, reviewer: name, ...extra });
      onEntry(rule.id, next);
      setForm(null);
      setRejectReason("");
      setEditReason("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      if (e instanceof HttpError && e.status === 409) await onReload(); // the rules or this rule's review changed: show the current state
    } finally {
      sending.current = false;
      setBusy(false);
    }
  };

  const openEdit = () => { setDraft(JSON.stringify(rule.effective, null, 2)); setError(null); setForm("edit"); };
  const saveEdit = () => {
    let parsed: unknown;
    try { parsed = JSON.parse(draft); } catch (e) { setError(`This is not valid JSON: ${e instanceof Error ? e.message : String(e)}`); return; }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) { setError("The rule must be a JSON object."); return; }
    void send("edit", { editedRule: parsed as Record<string, unknown>, reason: editReason.trim() || undefined });
  };

  if (api.kind !== "ready" || !entry) {
    // never a usable control here: whatever the reason, the buttons stay disabled and the page says why
    const why = api.kind === "loading" ? "Loading the review state…" : api.kind === "stale" ? (api.unidentified ? REVIEW_UNIDENTIFIED : REVIEW_STALE) : "";
    const detail = api.kind === "unavailable" ? api.reason : null;
    const title = api.kind === "stale" ? "The extraction has changed; reload the results" : api.kind === "loading" ? "Loading the review state" : REVIEW_UNAVAILABLE;
    return (
      <>
        <div className="rex-detail-actions" role="group" aria-label="Human review">
          <button type="button" className="btn primary" disabled title={title}><Icon name="check" size={14} />Accept Rule</button>
          <button type="button" className="btn danger-outline" disabled title={title}>Reject</button>
          <button type="button" className="btn" disabled title={title}><Icon name="edit" size={14} />Edit JSON</button>
        </div>
        {api.kind === "stale" && <div className="alert warn rex-stale" role="status"><Icon name="info" size={14} /><p>{why}</p></div>}
        {api.kind === "loading" && <p className="rex-note" role="status"><Icon name="info" size={14} />{why}</p>}
        {api.kind === "unavailable" && (
          <p className="rex-note"><Icon name="lock" size={14} />{jobId ? REVIEW_UNAVAILABLE : REVIEW_NO_BACKEND} This rule stays “{reviewLabel(rule.reviewStatus)}”.{detail ? ` ${detail}` : ""}</p>
        )}
      </>
    );
  }

  const decided = entry.state !== "pending";
  return (
    <section className="rex-review" aria-label="Human review">
      <div className="rex-review-head">
        <p className="rex-card-title">Human review</p>
        <p className="rex-review-state" role="status">
          {entry.state === "pending" ? "Pending review" : `${entry.state === "accepted" ? "Accepted" : "Rejected"} by ${entry.reviewer} · ${when(entry.at)}`}
          {entry.edited && " · edited"}
        </p>
      </div>
      {decided && entry.reason && <p className="rex-note">Reason: {entry.reason}</p>}

      <label className="rex-field">
        <span>Reviewer name <small>(self-declared, not authenticated)</small></span>
        <input type="text" value={reviewer} maxLength={100} onChange={(e) => onReviewer(e.target.value)} placeholder="Your name" autoComplete="name" />
      </label>

      <div className="rex-detail-actions" role="group" aria-label="Review actions">
        <button type="button" className="btn primary" disabled={busy || entry.state === "accepted"} onClick={() => void send("accept")}><Icon name="check" size={14} />Accept Rule</button>
        <button type="button" className="btn danger-outline" disabled={busy || entry.state === "rejected"} aria-expanded={form === "reject"} onClick={() => { setForm(form === "reject" ? null : "reject"); setError(null); }}>Reject</button>
        <button type="button" className="btn" disabled={busy} aria-expanded={form === "edit"} onClick={() => (form === "edit" ? setForm(null) : openEdit())}><Icon name="edit" size={14} />Edit JSON</button>
        {entry.edited && <button type="button" className="btn" disabled={busy} onClick={() => void send("reset")}><Icon name="refresh" size={14} />Reset edit</button>}
      </div>

      {form === "reject" && (
        <div className="rex-form">
          <label className="rex-field"><span>Reason for rejecting (required)</span>
            <textarea rows={3} value={rejectReason} maxLength={2000} onChange={(e) => setRejectReason(e.target.value)} /></label>
          <div className="rex-actions">
            <button type="button" className="btn danger-outline" disabled={busy || !rejectReason.trim()} onClick={() => void send("reject", { reason: rejectReason.trim() })}>Confirm rejection</button>
            <button type="button" className="btn" disabled={busy} onClick={() => setForm(null)}>Cancel</button>
          </div>
        </div>
      )}
      {form === "edit" && (
        <div className="rex-form">
          <label className="rex-field"><span>Edited Rule JSON</span>
            <textarea className="rex-editor" rows={14} spellCheck={false} value={draft} onChange={(e) => setDraft(e.target.value)} aria-label="Edited Rule JSON" /></label>
          <label className="rex-field"><span>Reason for the change (optional)</span>
            <input type="text" value={editReason} maxLength={2000} onChange={(e) => setEditReason(e.target.value)} /></label>
          <p className="rex-note"><Icon name="info" size={14} />The extracted rule is kept as it is. <code>id</code>, <code>source</code>, <code>schemaVersion</code> and the review status cannot be changed; the edit is validated as Rule JSON 2.0 and returns the rule to “Pending review”.</p>
          <div className="rex-actions">
            <button type="button" className="btn primary" disabled={busy} onClick={saveEdit}>Save edit</button>
            <button type="button" className="btn" disabled={busy} onClick={() => setForm(null)}>Cancel</button>
          </div>
        </div>
      )}
      {error && <div className="alert error" role="alert">{error}</div>}
      <AuditTrail jobId={jobId} ruleId={rule.id} extractionId={extractionId} version={entry.lastEventId} />
    </section>
  );
}

/** The events of the rule. Those of the extraction on screen decide its state; events of earlier extractions (a rule keeps its ID
 *  when it is extracted again) are history only and are listed apart, labelled as not applying to these rules. */
function AuditTrail({ jobId, ruleId, extractionId, version }: { jobId: string; ruleId: string; extractionId: string | null; version: number }) {
  const [open, setOpen] = useState(false);
  const key = `${jobId}\u001f${ruleId}`;
  const [loaded, setLoaded] = useState<{ key: string; events: RuleHistoryEvent[] } | null>(null);
  const [error, setError] = useState<{ key: string; message: string } | null>(null);
  useEffect(() => {
    if (!open) { setLoaded(null); setError(null); return; }
    let stale = false; // another rule was selected (or the panel closed) before the answer came: it is dropped
    getRuleHistory(jobId, ruleId).then(
      (events) => { if (!stale) { setLoaded({ key, events }); setError(null); } },
      (e) => { if (!stale) setError({ key, message: e instanceof Error ? e.message : String(e) }); },
    );
    return () => { stale = true; };
  }, [open, jobId, ruleId, key, version]);
  const events = loaded?.key === key ? loaded.events : null; // never the previous rule's events
  const failure = error?.key === key ? error.message : null;
  const current = events?.filter((ev) => ev.extractionId === extractionId) ?? [];
  const earlier = events?.filter((ev) => ev.extractionId !== extractionId) ?? [];
  return (
    <details className="rex-audit" onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>Audit trail</summary>
      {failure && <p className="rex-note">{failure}</p>}
      {!failure && events && current.length === 0 && <p className="rex-note">No review events yet for these rules.</p>}
      {current.length > 0 && (
        <ol className="rex-audit-list" aria-label="Events of this extraction">
          {current.map((ev) => <AuditEvent key={ev.id} ev={ev} />)}
        </ol>
      )}
      {earlier.length > 0 && (
        <>
          <p className="rex-audit-earlier-h"><Icon name="info" size={14} />Earlier extractions: history only, not applied to these rules</p>
          <ol className="rex-audit-list rex-audit-earlier" aria-label="Events of earlier extractions (history only)">
            {earlier.map((ev) => <AuditEvent key={ev.id} ev={ev} earlier />)}
          </ol>
        </>
      )}
    </details>
  );
}

function AuditEvent({ ev, earlier = false }: { ev: RuleHistoryEvent; earlier?: boolean }) {
  return (
    <li className={earlier ? "earlier" : undefined}>
      <span className="rex-audit-when">{when(ev.at)}</span>
      <span>
        <strong>{ACTION_LABEL[ev.action]}</strong> by {ev.reviewer}{ev.reason ? ` — ${ev.reason}` : ""}
        {earlier && <span className="rex-audit-tag" title={`Extraction of ${extractionLabel(ev.extractionId)}`}>earlier extraction · {extractionLabel(ev.extractionId)}</span>}
      </span>
    </li>
  );
}
