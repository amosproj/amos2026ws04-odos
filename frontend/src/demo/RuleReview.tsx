// The review page of the extracted rules, one rule at a time: a sidebar with the document and the review progress, and a card
// with the original text, ODOS's rule suggestion in plain language and three decisions. Everything technical (the Rule JSON,
// IDs, the history, how the result was produced, the list of all rules) is reachable but closed by default.
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Icon } from "../components/Icon";
import { JsonViewer } from "../components/JsonViewer";
import { TYPE_LABELS, fullText } from "../structure";
import type { DocElement } from "../types";
import { AuditTrail, NAME_MISSING, REVIEW_NO_BACKEND, REVIEW_STALE, REVIEW_UNAVAILABLE, REVIEW_UNIDENTIFIED, reviewStateLine, type ReviewState } from "./ReviewControls";
import { NUMERIC_OPERATORS, OPERATOR_LABEL, pathKey } from "./ruleEdit";
import { pagesLabel, reviewLabel, validPages, type Overview, type RuleItem, type RuleResults } from "./ruleResults";
import { readRule, type TextLine } from "./ruleText";
import type { ReviewApi } from "./useRuleReviews";

// ── sidebar ────────────────────────────────────────────────────────────────────────────────────────────────────────────

interface SidebarProps {
  filename: string;
  ov: Overview;
  api: ReviewApi;
  onOverview: () => void;
  exporting: boolean;
  onDownload: () => void;
  menu: ReactNode;
}

/** How far the review is: decisions of people only. A rule nobody decided is open, whether or not ODOS's checks flagged it. */
export function reviewProgress(ov: Overview, api: ReviewApi) {
  const decided = api.kind === "ready" ? ov.accepted + ov.rejected : api.kind === "stale" ? 0 : ov.reviewed + ov.approved;
  return { decided, total: ov.total, percent: ov.total ? Math.round((decided / ov.total) * 100) : 0 };
}

export function ReviewSidebar({ filename, ov, api, onOverview, exporting, onDownload, menu }: SidebarProps) {
  const { decided, total, percent } = reviewProgress(ov, api);
  const [why, setWhy] = useState(false);
  const ready = api.kind === "ready";
  const accepted = ready ? api.data.counts.accepted : 0;
  return (
    <aside className="rex-side" aria-label="Review progress">
      <div className="rex-side-doc">
        <Icon name="file" size={26} />
        <div>
          <p className="rex-side-name" title={filename}>{filename}</p>
          <p className="rex-side-count">{total} {total === 1 ? "rule" : "rules"} found</p>
        </div>
      </div>

      <ProgressRing percent={percent} label={`${decided} of ${total} rules reviewed`} />
      <p className="rex-side-sub">{decided} of {total} reviewed</p>

      <ul className="rex-side-list">
        <li className="rex-side-issues">
          <button type="button" className="rex-side-row warn" aria-expanded={why} onClick={() => setWhy((w) => !w)}>
            <Icon name="alert" size={22} />
            <span><strong>{ov.flagged}</strong> with potential issues</span>
          </button>
          {why && (
            <p className="rex-side-why">ODOS's automatic checks noticed something in these rules, for example a unit that is not in the original text. They are shown first. A rule without such a notice is not verified: every rule needs your review.</p>
          )}
        </li>
        <li><span className="rex-side-row"><span className="rex-side-dot" aria-hidden="true" /><span><strong>{ov.pending}</strong> waiting for review</span></span></li>
        {ready && ov.accepted > 0 && <li><span className="rex-side-row"><span className="rex-side-dot accepted" aria-hidden="true" /><span><strong>{ov.accepted}</strong> accepted</span></span></li>}
        {ready && ov.rejected > 0 && <li><span className="rex-side-row"><span className="rex-side-dot rejected" aria-hidden="true" /><span><strong>{ov.rejected}</strong> rejected</span></span></li>}
      </ul>

      <div className="rex-side-foot">
        <button type="button" className="btn rex-side-btn" onClick={onOverview}><Icon name="list" size={16} />All rules</button>
        {ready && (
          <button type="button" className="btn rex-side-btn" disabled={accepted === 0 || exporting} onClick={onDownload}
                  title={accepted > 0 ? "The accepted rules as Rule JSON 2.0 (status approved); rejected and open rules are not included" : "No rule has been accepted yet"}>
            <Icon name="download" size={16} />Download approved rules{accepted > 0 ? ` (${accepted})` : ""}
          </button>
        )}
        {menu}
      </div>
      <p className="rex-side-note">Every rule is a draft written by an AI model until a person has reviewed it.</p>
    </aside>
  );
}

function ProgressRing({ percent, label }: { percent: number; label: string }) {
  const r = 52, c = 2 * Math.PI * r;
  return (
    <div className="rex-ring" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-label={label}>
      <svg viewBox="0 0 120 120" aria-hidden="true">
        <circle className="rex-ring-track" cx="60" cy="60" r={r} />
        <circle className="rex-ring-value" cx="60" cy="60" r={r} strokeDasharray={`${Math.max(percent / 100 * c, 0.01)} ${c}`} transform="rotate(-90 60 60)" />
      </svg>
      <span className="rex-ring-text"><span className="rex-ring-pct">{percent} %</span><span className="rex-ring-label">reviewed</span></span>
    </div>
  );
}

// ── the review card ────────────────────────────────────────────────────────────────────────────────────────────────────

/** How a source reference of a rule reads: the document element it names (null when the opened document has none with that
 *  ID) and its pages. Pages come from the rule itself, else from the element; invalid ones are dropped, never guessed. */
function describeSource(s: RuleItem["sources"][number], elements: Map<string, DocElement>, numPages: number) {
  const e = elements.get(s.elementId) ?? null;
  const own = validPages(s.pdfPages, numPages);
  const pages = own.length ? own : e ? validPages(e.pages, numPages) : [];
  const name = e ? `${TYPE_LABELS[e.type] ?? e.type} ${e.marker ?? ""}`.trim() : "Unknown passage";
  return { s, e, pages, name, pagesText: pagesLabel(pages) };
}
type Ref = ReturnType<typeof describeSource>;

interface CardProps {
  rule: RuleItem;
  position: number;
  count: number;
  scope: string | null;
  onPrevious: () => void;
  onNext: () => void;
  elements: Map<string, DocElement>;
  numPages: number;
  onShowInPdf?: (elementId: string) => void;
  review: ReviewState;
  reviewer: string;
  onReviewer: (name: string) => void;
  advanced: ReactNode;
}

export function ReviewMain({ rule, position, count, scope, onPrevious, onNext, elements, numPages, onShowInPdf, review, reviewer, onReviewer, advanced }: CardProps) {
  return (
    <section className="rex-main" aria-label="Review rule">
      <header className="rex-main-head">
        <div>
          <h1 className="rex-main-title">Review Rule</h1>
          <p className="rex-main-sub">ODOS extracted this rule from the document. Please check whether it is correct.</p>
        </div>
        <nav className="rex-pager" aria-label="Rule navigation">
          <span className="rex-pager-pos" aria-live="polite">{position} of {count}{scope ? <small> · {scope}</small> : null}</span>
          <button type="button" className="rex-pager-btn" onClick={onPrevious} disabled={position <= 1} aria-label="Previous rule" title="Previous rule (←)"><Icon name="chevron-left" size={20} /></button>
          <button type="button" className="rex-pager-btn" onClick={onNext} disabled={position >= count} aria-label="Next rule" title="Next rule (→)"><Icon name="chevron-right" size={20} /></button>
        </nav>
      </header>

      <article className="rex-card" aria-label={rule.title}>
        <IssueNotice rule={rule} />
        <SourceSection rule={rule} elements={elements} numPages={numPages} onShowInPdf={onShowInPdf} />
        <SuggestionSection rule={rule} />
        <Decision review={review} reviewer={reviewer} onReviewer={onReviewer} />
        {advanced}
      </article>
    </section>
  );
}

function IssueNotice({ rule }: { rule: RuleItem }) {
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [rule.id]);
  if (rule.checkFlags.length === 0) return null;
  return (
    <div className="rex-issue">
      <button type="button" className="rex-issue-btn" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <Icon name="alert" size={16} />Potential issue — please look closely<span className="rex-issue-more">{open ? "Hide" : "Why?"}</span>
      </button>
      {open && <ul className="rex-issue-list" aria-label="Noticed by ODOS's automatic checks">{rule.checkFlags.map((f, i) => <li key={i}>{f}</li>)}</ul>}
    </div>
  );
}

function SourceSection({ rule, elements, numPages, onShowInPdf }: { rule: RuleItem; elements: Map<string, DocElement>; numPages: number; onShowInPdf?: (elementId: string) => void }) {
  const refs = useMemo(() => {
    const seen = new Set<string>();
    return rule.sources.filter((s) => (seen.has(s.elementId) ? false : (seen.add(s.elementId), true))).map((s) => describeSource(s, elements, numPages));
  }, [rule, elements, numPages]);
  const isPrimary = (r: Ref) => (r.s.role ?? "primary") === "primary";
  const main = refs.some(isPrimary) ? refs.filter(isPrimary) : refs.slice(0, 1);
  const related = refs.filter((r) => !main.includes(r));
  const target = main.find((r) => r.e) ?? null;
  const pages = pagesLabel(main.flatMap((r) => r.pages));
  return (
    <section className="rex-source" aria-labelledby={`rex-src-${rule.id}`}>
      <div className="rex-sec-head">
        <Icon name="book" size={24} />
        <h2 id={`rex-src-${rule.id}`}>Original text</h2>
        {rule.citation && <span className="rex-cite">{rule.citation}</span>}
      </div>
      <div className="rex-source-body">
        <div className="rex-quotes">
          {main.length === 0 && <p className="rex-muted">This rule names no passage of the document, so there is no original text to show.</p>}
          {main.map((r) => (
            <div key={r.s.elementId}>
              {main.length > 1 && <p className="rex-quote-label">{r.name}{r.pagesText ? ` · ${r.pagesText}` : ""}</p>}
              {r.e ? <blockquote className="rex-quote">{fullText(r.e) || <em>(no text)</em>}</blockquote>
                : <p className="rex-muted">The passage this rule names is not part of the opened document.</p>}
            </div>
          ))}
        </div>
        <div className="rex-source-action">
          <button type="button" className="btn rex-view-btn" disabled={!target || !onShowInPdf} onClick={() => target && onShowInPdf?.(target.s.elementId)}
                  title={target ? "Opens Document Review with this passage highlighted in the PDF" : "This passage is not part of the opened document"}>
            <Icon name="open" size={16} />View in document
          </button>
          {pages && <span className="rex-muted rex-pages">{pages}</span>}
        </div>
      </div>
      {related.length > 0 && (
        <details className="rex-related">
          <summary>Related passages ({related.length})</summary>
          <ul>
            {related.map((r) => (
              <li key={r.s.elementId}>
                <p className="rex-quote-label">{r.name}{r.s.role && r.s.role !== "primary" ? ` · ${ROLE_LABEL[r.s.role] ?? r.s.role}` : ""}{r.pagesText ? ` · ${r.pagesText}` : ""}</p>
                {r.e ? <blockquote className="rex-quote small">{fullText(r.e)}</blockquote> : <p className="rex-muted">Not part of the opened document.</p>}
                {r.e && onShowInPdf && <button type="button" className="btn small" onClick={() => onShowInPdf(r.s.elementId)} aria-label={`View ${r.name} in the document`}><Icon name="open" size={14} />View</button>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
const ROLE_LABEL: Record<string, string> = { definition: "definition", context: "context", cross_reference: "referenced" };

function Lines({ lines }: { lines: TextLine[] }) {
  return (
    <ul className="rex-lines">
      {lines.map((l, i) => (
        <li key={i} className={l.unclear ? "unclear" : undefined}>
          <span className="rex-line-text">{l.unclear && <span className="rex-unclear-tag">Unclear</span>}{l.text}</span>
          {l.note && <span className="rex-line-note">{l.note}</span>}
          {l.children && l.children.length > 0 && <Lines lines={l.children} />}
        </li>
      ))}
    </ul>
  );
}

function SuggestionSection({ rule }: { rule: RuleItem }) {
  const reading = useMemo(() => readRule(rule.effective), [rule.effective]);
  return (
    <section className="rex-suggest" aria-labelledby={`rex-sug-${rule.id}`}>
      <div className="rex-sec-head">
        <Icon name="sparkle" size={24} />
        <h2 id={`rex-sug-${rule.id}`}>ODOS rule suggestion</h2>
        <span className="rex-kind">{reading.kind}</span>
      </div>
      {rule.edited && <p className="rex-muted rex-edited-note"><Icon name="edit" size={14} />Adjusted by a reviewer. The original suggestion is kept under Advanced details.</p>}
      {reading.summary && <p className="rex-summary-text">{reading.summary}</p>}
      {reading.blocks.map((b) => (
        <div key={b.key} className="rex-block">
          <p className="rex-block-title">{b.title}</p>
          <Lines lines={b.lines} />
        </div>
      ))}
      {reading.gaps.length > 0 && (
        <div className="alert warn rex-gap" role="note">
          <Icon name="alert" size={14} />
          <span>Part of this rule cannot be shown in plain language, so the text above is not the complete rule. Check the complete rule under Advanced details → Rule JSON.</span>
        </div>
      )}
    </section>
  );
}

function Decision({ review, reviewer, onReviewer }: { review: ReviewState; reviewer: string; onReviewer: (name: string) => void }) {
  const { api, entry, busy, form, setForm, send, openEdit, setError, error, rule, jobId } = review;
  const ready = api.kind === "ready" && !!entry;
  const off = !ready || busy;
  const offTitle = api.kind === "stale" ? "The extraction has changed; reload the results" : api.kind === "loading" ? "Loading the review state" : !ready ? REVIEW_UNAVAILABLE : undefined;
  const state = reviewStateLine(entry);
  const nameMissing = error === NAME_MISSING;
  return (
    <section className="rex-decide" aria-label="Your decision">
      {state && <p className={`rex-decided ${entry?.state ?? ""}`} role="status">{entry?.state === "accepted" ? <Icon name="check" size={16} /> : entry?.state === "rejected" ? <Icon name="x" size={16} /> : <Icon name="edit" size={16} />}{state}</p>}
      {entry && entry.state !== "pending" && entry.reason && <p className="rex-muted rex-decided-reason">Reason: {entry.reason}</p>}
      <h2 className="rex-question">Is this rule suggestion correct?</h2>
      <div className="rex-choices" role="group" aria-label="Review actions">
        <button type="button" className="rex-choice yes" disabled={off || entry?.state === "accepted"} title={offTitle} onClick={() => void send("accept")}>
          <Icon name="check" size={28} /><span className="rex-choice-text"><span className="rex-choice-main">Yes, correct</span></span>
        </button>
        <button type="button" className="rex-choice" disabled={off} title={offTitle} aria-expanded={form === "edit"} onClick={() => (form === "edit" ? setForm(null) : openEdit())}>
          <Icon name="edit" size={24} /><span className="rex-choice-text"><span className="rex-choice-main">Adjust</span><span className="rex-choice-sub">Change the rule</span></span>
        </button>
        <button type="button" className="rex-choice no" disabled={off || entry?.state === "rejected"} title={offTitle} aria-expanded={form === "reject"} onClick={() => { setForm(form === "reject" ? null : "reject"); setError(null); }}>
          <Icon name="x" size={26} /><span className="rex-choice-text"><span className="rex-choice-main">No, incorrect</span><span className="rex-choice-sub">Reject the rule</span></span>
        </button>
      </div>

      {ready ? (
        <div className="rex-decide-foot">
          <label className={`rex-name${nameMissing ? " missing" : ""}`}>
            <span>Reviewing as</span>
            <input type="text" value={reviewer} maxLength={100} onChange={(e) => { onReviewer(e.target.value); if (nameMissing) setError(null); }} placeholder="Your name" autoComplete="name"
                   aria-invalid={nameMissing || undefined} title="Your name is saved with each decision. It is not checked by a login." aria-label="Reviewing as (your name, saved with each decision)" />
          </label>
          {entry!.edited && <button type="button" className="btn small" disabled={busy} onClick={() => void send("reset")}><Icon name="refresh" size={14} />Undo adjustment</button>}
        </div>
      ) : (
        <ReviewUnavailable api={api} rule={rule} hasJob={!!jobId} />
      )}

      {ready && form === "reject" && (
        <div className="rex-form">
          <label className="rex-field"><span>Why is this rule incorrect? (required)</span>
            <textarea rows={3} value={review.rejectReason} maxLength={2000} onChange={(e) => review.setRejectReason(e.target.value)} /></label>
          <div className="rex-actions">
            <button type="button" className="btn danger" disabled={busy || !review.rejectReason.trim()} onClick={() => void send("reject", { reason: review.rejectReason.trim() })}>Reject rule</button>
            <button type="button" className="btn" disabled={busy} onClick={() => setForm(null)}>Cancel</button>
          </div>
        </div>
      )}
      {ready && form === "edit" && <EditForm review={review} />}
      {error && <div className="alert error" role="alert">{error}</div>}
    </section>
  );
}

function ReviewUnavailable({ api, rule, hasJob }: { api: ReviewApi; rule: RuleItem; hasJob: boolean }) {
  if (api.kind === "loading") return <p className="rex-muted rex-center" role="status">Loading the review state…</p>;
  if (api.kind === "stale") return <div className="alert warn rex-stale" role="status"><Icon name="info" size={14} /><p>{api.unidentified ? REVIEW_UNIDENTIFIED : REVIEW_STALE}</p></div>;
  return (
    <p className="rex-muted rex-center"><Icon name="lock" size={14} />{hasJob ? REVIEW_UNAVAILABLE : REVIEW_NO_BACKEND} This rule stays “{reviewLabel(rule.reviewStatus)}”.{api.kind === "unavailable" && api.reason ? ` ${api.reason}` : ""}</p>
  );
}

function EditForm({ review }: { review: ReviewState }) {
  const { fields, values, setValue, editMode, draft, setDraft, busy, saveEdit, setForm, editReason, setEditReason, openEdit } = review;
  return (
    <div className="rex-form">
      <div className="rex-edit-head">
        <p className="rex-form-title">{editMode === "simple" ? "Adjust the values of this rule" : "Advanced editor (Rule JSON)"}</p>
        {fields.length > 0 && (
          <button type="button" className="btn small" onClick={() => (editMode === "simple" ? openEdit("json") : openEdit("simple"))}>
            {editMode === "simple" ? "Advanced editor" : "Simple editor"}
          </button>
        )}
      </div>
      {editMode === "simple" ? (
        <div className="rex-fields">
          {fields.map((f) => {
            const key = pathKey(f.path);
            const v = values[key];
            return (
              <label key={key} className="rex-field">
                <span>{f.label}{f.unit ? ` (${f.unit})` : ""}</span>
                {f.kind === "boolean" ? (
                  <select value={v === true ? "yes" : "no"} onChange={(e) => setValue(f, e.target.value === "yes")}><option value="yes">yes</option><option value="no">no</option></select>
                ) : f.kind === "operator" ? (
                  <select value={String(v)} onChange={(e) => setValue(f, e.target.value)}>{NUMERIC_OPERATORS.map((o) => <option key={o} value={o}>{OPERATOR_LABEL[o]}</option>)}</select>
                ) : f.kind === "longtext" ? (
                  <textarea rows={3} value={String(v ?? "")} onChange={(e) => setValue(f, e.target.value)} />
                ) : (
                  <input type="text" inputMode={f.kind === "text" ? undefined : "decimal"} value={String(v ?? "")} onChange={(e) => setValue(f, e.target.value)} />
                )}
              </label>
            );
          })}
          <p className="rex-muted rex-small">Conditions, exceptions and the structure of the rule are changed in the advanced editor.</p>
        </div>
      ) : (
        <>
          {fields.length === 0 && <p className="rex-muted rex-small">This rule has no values that can be changed in a simple form, so it is edited as Rule JSON.</p>}
          <label className="rex-field"><span>Rule JSON</span>
            <textarea className="rex-editor" rows={14} spellCheck={false} value={draft} onChange={(e) => setDraft(e.target.value)} aria-label="Edited Rule JSON" /></label>
        </>
      )}
      <label className="rex-field"><span>Reason for the change (optional)</span>
        <input type="text" value={editReason} maxLength={2000} onChange={(e) => setEditReason(e.target.value)} /></label>
      <p className="rex-muted rex-small"><Icon name="info" size={14} />The original suggestion is kept. The adjusted rule is checked against Rule JSON 2.0 by the server and then waits for review again.</p>
      <div className="rex-actions">
        <button type="button" className="btn primary" disabled={busy} onClick={saveEdit}>Save adjustment</button>
        <button type="button" className="btn" disabled={busy} onClick={() => setForm(null)}>Cancel</button>
      </div>
    </div>
  );
}

// ── advanced details ───────────────────────────────────────────────────────────────────────────────────────────────────

interface AdvancedProps {
  rule: RuleItem;
  results: RuleResults;
  ov: Overview;
  review: ReviewState;
  provisions: { total: number; withRules: number } | null;
  open: boolean;
  onOpen: (open: boolean) => void;
}

export function AdvancedDetails({ rule, results, ov, review, provisions, open, onOpen }: AdvancedProps) {
  const [jsonView, setJsonView] = useState<"effective" | "original">("effective");
  useEffect(() => setJsonView("effective"), [rule.id]);
  const { api, jobId, entry, extractionId } = review;
  const g = results.generation;
  const rows: Array<[string, ReactNode]> = [];
  if (g?.modelId) rows.push(["Model", <code key="m">{g.modelId}</code>]);
  if (g?.promptVersion) rows.push(["Prompt version", g.promptVersion]);
  if (g?.generatedAt) rows.push(["Generated", new Date(g.generatedAt).toLocaleString()]);
  if (g?.proposed !== undefined) rows.push(["Candidates proposed", g.proposed]);
  rows.push(["Refused by checks", ov.autoRejected]);
  if (g?.repaired !== undefined) rows.push(["Repaired by schema repair", g.repaired]);
  if (g?.coverage) rows.push(["Text units cited by a rule", `${g.coverage.sentencesCited} of ${g.coverage.sentences} (a count of cited text, not a measure of completeness)`]);
  if (provisions) rows.push(["Provisions with a rule", `${provisions.withRules} of ${provisions.total} (many provisions need no rule)`]);
  if (api.kind === "ready" && api.data.earlierExtractionEvents > 0) rows.push(["Events of earlier extractions", `${api.data.earlierExtractionEvents} (kept in the history, not applied to these rules)`]);

  return (
    <div className="rex-advanced">
      <button type="button" className="rex-adv-toggle" aria-expanded={open} onClick={() => onOpen(!open)}>
        <Icon name="chevron-right" size={14} />Advanced details
        <span className="rex-muted">Rule JSON, history, identifiers</span>
      </button>
      {open && (
        <div className="rex-adv-body">
          {rule.checkFlags.length > 0 && (
            <AdvSection title="Automatic checks">
              <ul className="rex-adv-list" aria-label="Flagged by ODOS checks">{rule.checkFlags.map((f, i) => <li key={i}>{f}</li>)}</ul>
              <p className="rex-muted rex-small">The checks cover form, units, numbers and sources. They do not compare meaning: an unflagged rule is not verified.</p>
            </AdvSection>
          )}
          {(rule.ambiguities.length > 0 || rule.notes.length > 0) && (
            <AdvSection title="Notes from the model">
              <ul className="rex-adv-list">{[...rule.ambiguities, ...rule.notes].map((f, i) => <li key={i}>{f}</li>)}</ul>
            </AdvSection>
          )}
          <AdvSection title="Rule JSON">
            {rule.edited && (
              <div className="rex-jsonview" role="group" aria-label="Which version of the rule to show">
                <button type="button" className="btn small" aria-pressed={jsonView === "effective"} onClick={() => setJsonView("effective")}>Adjusted (in force)</button>
                <button type="button" className="btn small" aria-pressed={jsonView === "original"} onClick={() => setJsonView("original")}>Extracted (original)</button>
              </div>
            )}
            <JsonViewer value={jsonView === "original" ? rule.rule : rule.effective} label={rule.edited ? (jsonView === "original" ? "Extracted Rule JSON" : "Edited Rule JSON") : "Rule JSON"} />
          </AdvSection>
          <AdvSection title="Review history">
            {api.kind === "ready" && jobId
              ? <AuditTrail jobId={jobId} ruleId={rule.id} extractionId={extractionId} version={entry?.lastEventId ?? 0} />
              : <p className="rex-muted rex-small">The history needs the review storage of the ODOS backend; it is not available for these rules right now.</p>}
          </AdvSection>
          <AdvSection title="Identifiers">
            <dl className="rex-tech-list">
              <div><dt>Rule ID</dt><dd><code>{rule.id}</code></dd></div>
              {rule.type && <div><dt>Type</dt><dd>{rule.type}</dd></div>}
              {rule.machineCheckable !== null && <div><dt>Machine-checkable (the model's assessment)</dt><dd>{rule.machineCheckable ? "yes" : "no"}</dd></div>}
              {rule.sources.length > 0 && <div><dt>Source elements</dt><dd>{rule.sources.map((s) => <code key={`${s.elementId}-${s.sentenceId ?? ""}`}>{s.elementId}{s.sentenceId ? ` · ${s.sentenceId}` : ""}</code>)}</dd></div>}
            </dl>
          </AdvSection>
          <AdvSection title="About this extraction">
            <dl className="rex-tech-list">{rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
            {api.kind === "ready" && <p className="rex-muted rex-small">Decisions are saved in the ODOS database with the reviewer's name and kept in an audit trail. The extracted rules are never changed.</p>}
            {ov.autoRejected > 0 && (
              <details className="rex-rejected">
                <summary>Candidates refused by automatic checks ({ov.autoRejected})</summary>
                <ul>{results.autoRejected.map((r, i) => <li key={`${r.id}-${i}`}><code>{r.id}</code>{r.reasons.map((reason, j) => <span key={j} className="rex-reason">{reason}</span>)}</li>)}</ul>
              </details>
            )}
          </AdvSection>
        </div>
      )}
    </div>
  );
}

function AdvSection({ title, children }: { title: string; children: ReactNode }) {
  return <section className="rex-adv-sec"><h3>{title}</h3>{children}</section>;
}

// ── small parts ────────────────────────────────────────────────────────────────────────────────────────────────────────

/** A modal panel (the overview of all rules, the help): closes on Escape and on the close button; focus moves into it and back. */
export function Dialog({ title, onClose, children, className = "" }: { title: string; onClose: () => void; children: ReactNode; className?: string }) {
  const panel = useRef<HTMLDivElement>(null);
  const id = useId();
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    panel.current?.querySelector<HTMLElement>("button, input, select, [tabindex]")?.focus();
    return () => before?.focus?.();
  }, []);
  return createPortal(
    <div className="rex-overlay" onPointerDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={`rex-dialog ${className}`} role="dialog" aria-modal="true" aria-labelledby={id} ref={panel}
           onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); onClose(); } }}>
        <div className="rex-dialog-head">
          <h2 id={id}>{title}</h2>
          <button type="button" className="rex-icon-btn" onClick={onClose} aria-label="Close"><Icon name="x" size={18} /></button>
        </div>
        {children}
      </div>
    </div>,
    document.body, // outside the page's animated container, so the overlay covers the whole window
  );
}

export function HelpContent() {
  return (
    <div className="rex-help">
      <ol>
        <li><strong>Read the original text.</strong> It is the passage of the document the rule was taken from. “View in document” shows it highlighted in the PDF.</li>
        <li><strong>Compare ODOS's suggestion.</strong> It states the rule with its exact values, units, conditions and exceptions.</li>
        <li><strong>Decide.</strong> “Yes, correct” accepts the rule, “Adjust” changes it, “No, incorrect” rejects it with a reason.</li>
      </ol>
      <p>Rules marked with a <strong>potential issue</strong> were noticed by ODOS's automatic checks and are shown first. Rules without that mark are not verified: every rule is a draft until a person has reviewed it.</p>
      <p>Your name is saved with each decision, and every decision is kept in the rule's history. Previous and next: the arrow buttons or the ← and → keys.</p>
    </div>
  );
}

/** The ⋯ menu: a button that opens a menu; closes on a click outside, on Escape (focus returns to the button) and after an item is
 *  used. Arrow keys move between the items. */
export function MoreMenu({ children }: { children: (close: () => void) => ReactNode }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const id = useId();
  const items = () => [...(root.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)') ?? [])];
  const close = (refocus = false) => { setOpen(false); if (refocus) trigger.current?.focus(); };

  useEffect(() => {
    if (!open) return;
    items()[0]?.focus();
    const away = (e: Event) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);

  return (
    <div className="rex-menu" ref={root}
         onKeyDown={(e) => {
           if (e.key === "Escape" && open) { e.preventDefault(); e.stopPropagation(); close(true); }
           else if (open && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
             e.preventDefault();
             const all = items();
             const at = all.indexOf(document.activeElement as HTMLButtonElement);
             all[(at + (e.key === "ArrowDown" ? 1 : all.length - 1)) % all.length]?.focus();
           } else if (open && e.key === "Tab") setOpen(false);
         }}>
      <button type="button" ref={trigger} className="btn rex-menu-btn" aria-haspopup="menu" aria-expanded={open} aria-controls={id} aria-label="More actions" title="More actions" onClick={() => setOpen((o) => !o)}>⋯</button>
      {open && <div className="rex-menu-list" id={id} role="menu" aria-label="More actions">{children(() => close(true))}</div>}
    </div>
  );
}
