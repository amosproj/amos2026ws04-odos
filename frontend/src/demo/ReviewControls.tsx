import { useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "../components/Icon";
import { HttpError, getRuleHistory, postRuleReview, type RuleHistoryEvent, type RuleReviewEntry, type ReviewAction } from "./live";
import { applyFields, editableFields, parseField, pathKey, type EditField, type Path } from "./ruleEdit";
import type { RuleItem } from "./ruleResults";
import type { ReviewApi } from "./useRuleReviews";

export const REVIEW_UNAVAILABLE = "Review decisions cannot be saved right now.";
export const REVIEW_STALE = "The rules on this page are not the current extraction of this job: another extraction has replaced them since they were loaded. Review actions are disabled until the current results are loaded.";
export const REVIEW_UNIDENTIFIED = "These rules carry no extraction identifier (_generation.generatedAt), so a decision cannot be tied to them. Review actions are disabled; run a new extraction to review rules.";
export const REVIEW_NO_BACKEND = "Review decisions need the ODOS backend, which did not process this document.";
export const NAME_MISSING = "Enter your name next to “Reviewing as” first.";

const ACTION_LABEL: Record<ReviewAction, string> = { accept: "Accepted", reject: "Rejected", edit: "Edited", reset: "Edit reset" };
export const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "");
/** An extraction ID is the generation time of its rules.json: shown as a date when it reads as one. */
const extractionLabel = (id: string) => (Number.isNaN(Date.parse(id)) ? id : new Date(id).toLocaleString());

type Form = null | "reject" | "edit";
export type EditMode = "simple" | "json";

interface Options {
  jobId: string;
  rule: RuleItem;
  api: ReviewApi;
  reviewer: string;
  onEntry: (ruleId: string, entry: RuleReviewEntry) => void;
  onReload: () => Promise<void>;
  /** Called after an accepted or rejected decision was saved (the page may move on to the next rule). */
  onDecided?: (ruleId: string) => void;
  /** Called when the backend reported a conflict for this rule: the page keeps the rule in view so the reason stays readable. */
  onConflict?: (ruleId: string) => void;
}

/** The state of Human Review of one rule. Disabled unless the backend stores decisions for exactly the rules on screen; otherwise
 *  Accept, Reject (with a reason) and Adjust (validated by the backend) append events to the audit trail. Nothing is applied before
 *  the backend has answered, and the extracted record is never modified: an edit is stored beside it. */
export function useReviewActions({ jobId, rule, api, reviewer, onEntry, onReload, onDecided, onConflict }: Options) {
  const entry = api.kind === "ready" ? api.data.rules[rule.id] ?? null : null;
  const extractionId = api.kind === "ready" ? api.data.extractionId : null;
  const [form, setForm] = useState<Form>(null);
  const [rejectReason, setRejectReason] = useState(""); // separate from the edit's reason: one form's text never leaks into the other
  const [editReason, setEditReason] = useState("");
  const [draft, setDraft] = useState("");
  const [editMode, setEditMode] = useState<EditMode>("simple");
  const [values, setValues] = useState<Record<string, string | boolean>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sending = useRef(false); // set synchronously: a second click must not send a second event
  const name = reviewer.trim();
  const fields = useMemo(() => editableFields(rule.effective), [rule.effective]);

  // another rule, or other rules (a new extraction, a changed record): a clean form, so a draft written for one record is never sent for another
  const ruleHash = entry?.ruleSha256 ?? null;
  useEffect(() => { setForm(null); setRejectReason(""); setEditReason(""); setError(null); }, [rule.id]);
  useEffect(() => { setForm(null); setRejectReason(""); setEditReason(""); }, [extractionId, ruleHash]); // the reason a conflict was reported stays visible

  const send = async (action: ReviewAction, extra: { reason?: string; editedRule?: Record<string, unknown> } = {}) => {
    if (!entry || !extractionId || sending.current) return;
    if (!name) { setError(NAME_MISSING); return; }
    sending.current = true;
    setBusy(true);
    setError(null);
    try {
      const next = await postRuleReview(jobId, { ruleId: rule.id, extractionId, expectedRuleSha256: entry.ruleSha256, expectedLastEventId: entry.lastEventId, action, reviewer: name, ...extra });
      onEntry(rule.id, next);
      if (action === "accept" || action === "reject") onDecided?.(rule.id);
      setForm(null);
      setRejectReason("");
      setEditReason("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      if (e instanceof HttpError && e.status === 409) { onConflict?.(rule.id); await onReload(); } // the rules or this rule's review changed: show the current state
    } finally {
      sending.current = false;
      setBusy(false);
    }
  };

  /** Opens the editor: the simple form when the record has values it can change, else the JSON editor. */
  const openEdit = (mode: EditMode = fields.length ? "simple" : "json") => {
    setDraft(JSON.stringify(rule.effective, null, 2));
    setValues(Object.fromEntries(fields.map((f) => [pathKey(f.path), f.kind === "boolean" ? (f.value as boolean) : String(f.value)])));
    setEditMode(mode);
    setError(null);
    setForm("edit");
  };

  const saveEdit = () => {
    if (editMode === "json") {
      let parsed: unknown;
      try { parsed = JSON.parse(draft); } catch (e) { setError(`This is not valid JSON: ${e instanceof Error ? e.message : String(e)}`); return; }
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) { setError("The rule must be a JSON object."); return; }
      void send("edit", { editedRule: parsed as Record<string, unknown>, reason: editReason.trim() || undefined });
      return;
    }
    // the simple form: each changed value is written back to its own place with its own JSON type; nothing else of the record changes
    const changed = new Map<string, { path: Path; value: string | number | boolean }>();
    for (const f of fields) {
      const key = pathKey(f.path);
      const parsed = parseField(f, values[key] ?? (f.kind === "boolean" ? (f.value as boolean) : String(f.value)));
      if (!parsed.ok) { setError(parsed.error); return; }
      if (parsed.value !== f.value) changed.set(key, { path: f.path, value: parsed.value });
    }
    if (changed.size === 0) { setError("Nothing was changed."); return; }
    void send("edit", { editedRule: applyFields(rule.effective, changed), reason: editReason.trim() || undefined });
  };

  const setValue = (f: EditField, v: string | boolean) => setValues((cur) => ({ ...cur, [pathKey(f.path)]: v }));

  return { api, rule, jobId, entry, extractionId, form, setForm, rejectReason, setRejectReason, editReason, setEditReason, draft, setDraft,
           editMode, setEditMode, fields, values, setValue, busy, error, setError, send, openEdit, saveEdit };
}

export type ReviewState = ReturnType<typeof useReviewActions>;

/** One line about the rule's current decision; null while nothing is known. */
export function reviewStateLine(entry: RuleReviewEntry | null): string | null {
  if (!entry || entry.state === "pending") return entry?.edited ? "Edited · not reviewed yet" : null;
  const base = `${entry.state === "accepted" ? "Accepted" : "Rejected"} by ${entry.reviewer} · ${when(entry.at)}`;
  return entry.edited ? `${base} · edited` : base;
}

/** The events of the rule. Those of the extraction on screen decide its state; events of earlier extractions (a rule keeps its ID
 *  when it is extracted again) are history only and are listed apart, labelled as not applying to these rules. */
export function AuditTrail({ jobId, ruleId, extractionId, version }: { jobId: string; ruleId: string; extractionId: string | null; version: number }) {
  const key = `${jobId}\u001f${ruleId}`;
  const [loaded, setLoaded] = useState<{ key: string; events: RuleHistoryEvent[] } | null>(null);
  const [error, setError] = useState<{ key: string; message: string } | null>(null);
  useEffect(() => {
    let stale = false; // another rule was selected before the answer came: it is dropped
    getRuleHistory(jobId, ruleId).then(
      (events) => { if (!stale) { setLoaded({ key, events }); setError(null); } },
      (e) => { if (!stale) setError({ key, message: e instanceof Error ? e.message : String(e) }); },
    );
    return () => { stale = true; };
  }, [jobId, ruleId, key, version]);
  const events = loaded?.key === key ? loaded.events : null; // never the previous rule's events
  const failure = error?.key === key ? error.message : null;
  const current = events?.filter((ev) => ev.extractionId === extractionId) ?? [];
  const earlier = events?.filter((ev) => ev.extractionId !== extractionId) ?? [];
  return (
    <div className="rex-audit" aria-label="Audit trail">
      {!events && !failure && <p className="rex-note" role="status"><span className="spinner" aria-hidden="true" /> Loading the history…</p>}
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
    </div>
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
