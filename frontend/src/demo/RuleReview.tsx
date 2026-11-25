// The Rule Validation page of the extracted rules, one rule at a time, in three panels: on the left the rule navigation (rule
// types, what the rules contain, review status, export), in the centre the selected rule in a structured, human-readable form
// with Accept / Edit / Reject, and on the right the document context (the original PDF and the Rule JSON record; RuleContext.tsx).
// Everything is read from the Rule JSON 2.0 record as stored: a section, a threshold or a check result is shown only when the
// record (or ODOS's own checks) states it.
import { createContext, useContext, useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Icon, type IconName } from "../components/Icon";
import type { DocElement } from "../types";
import { NAME_MISSING, NOT_ACCEPTABLE, REVIEW_NO_BACKEND, REVIEW_STALE, REVIEW_UNAVAILABLE, REVIEW_UNIDENTIFIED, reviewStateLine, type ReviewState } from "./ReviewControls";
import { RuleStatus } from "./RuleQueue";
import type { SourceHighlight } from "./sourceMap";
import { ComponentNavContext } from "./componentSource";
import { LONG_DEFINITION, parseDefinitionList, type DefItem } from "./definitionList";
import { NUMERIC_OPERATORS, OPERATOR_LABEL, pathKey } from "./ruleEdit";
import {
  FACETS, pagesLabel, reviewLabel, ruleFacets, typeCounts,
  type Overview, type ReviewFilter, type RuleCategory, type RuleItem,
} from "./ruleResults";
import { OPERATOR_SYMBOL, OPERATOR_WORDS, formulaParameters, mathName, type Formula, type MathToken } from "./ruleMath";
import { KIND_LABEL, readRule, type ReadableRule, type TextBlock, type TextLine, type Threshold } from "./ruleText";
import type { ReviewApi } from "./useRuleReviews";

// ── progress ───────────────────────────────────────────────────────────────────────────────────────────────────────────

/** How far the review is: decisions of people only. A rule nobody decided is open, whether or not ODOS's checks flagged it. */
export function reviewProgress(ov: Overview, api: ReviewApi) {
  const decided = api.kind === "ready" ? ov.accepted + ov.rejected : api.kind === "stale" ? 0 : ov.reviewed + ov.approved;
  return { decided, total: ov.total, percent: ov.total ? Math.round((decided / ov.total) * 100) : 0 };
}

// ── page header and footer ─────────────────────────────────────────────────────────────────────────────────────────────

export function ValidationHeader({ filename, numPages, total, decided, tally }: { filename: string; numPages: number; total: number; decided: number; tally?: { accepted: number; pending: number; rejected: number } | null }) {
  const pct = (n: number) => `${total ? (n / total) * 100 : 0}%`;
  return (
    <header className="rv-pagehead">
      <div className="rv-pagehead-title">
        <span className="rv-pagehead-icon"><Icon name="scale" size={34} /></span>
        <div>
          <h1 className="rv-h1">Rule Validation</h1>
          <p className="rv-lead">Review, validate and refine the extracted rules. Select a rule, check its source in the PDF and its Rule JSON, then accept, edit or reject it.</p>
        </div>
      </div>
      <div className="rv-doccard" aria-label="Document">
        <span className="rv-doccard-icon"><Icon name="file" size={22} /></span>
        <div className="rv-doccard-text">
          <p className="rv-doccard-name" title={filename}>{filename}</p>
          <p className="rv-doccard-meta">{numPages} {numPages === 1 ? "page" : "pages"} · {total} extracted {total === 1 ? "rule" : "rules"}</p>
        </div>
        <span className={`rv-pill${decided === total && total > 0 ? " done" : ""}`} title="Rules with a human decision (accepted or rejected)">
          <span className="rv-pill-dot" aria-hidden="true" />{decided} / {total} reviewed
        </span>
        {tally && (
          <div className="rv-tally" aria-label="Review progress by decision">
            <span className="rv-seg" aria-hidden="true"><span className="accepted" style={{ width: pct(tally.accepted) }} /><span className="rejected" style={{ width: pct(tally.rejected) }} /></span>
            <span className="rm accepted" title={`${tally.accepted} accepted`} aria-label={`${tally.accepted} accepted`}><Icon name="check" size={12} />{tally.accepted}</span>
            <span className="rm pending" title={`${tally.pending} pending`} aria-label={`${tally.pending} pending`}><Icon name="clock" size={12} />{tally.pending}</span>
            <span className="rm rejected" title={`${tally.rejected} rejected`} aria-label={`${tally.rejected} rejected`}><Icon name="x" size={12} />{tally.rejected}</span>
          </div>
        )}
      </div>
    </header>
  );
}

export function ValidationFooter({ decided, total, percent, onBack, onContinue }: { decided: number; total: number; percent: number; onBack: () => void; onContinue?: () => void }) {
  return (
    <footer className="rv-footer">
      <button type="button" className="btn" onClick={onBack}><Icon name="back" size={16} />Back to Document</button>
      <div className="rv-progress-wrap">
        <span className="rv-progress-text"><strong>{decided} / {total}</strong> rules reviewed</span>
        <div className="rv-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-label={`${decided} of ${total} rules reviewed`}>
          <span style={{ width: `${percent}%` }} />
        </div>
        <span className="rv-progress-pct">{percent} %</span>
      </div>
      {onContinue
        ? <button type="button" className="btn primary" onClick={onContinue}>Continue to Digital Twin Validation<Icon name="chevron-right" size={16} /></button>
        : <span />}
    </footer>
  );
}

// ── left panel: rule navigation ────────────────────────────────────────────────────────────────────────────────────────

const TYPE_ICON: Record<string, IconName> = {
  definition: "book", obligation: "check-square", prohibition: "ban", permission: "check", conditional_requirement: "branch", procedural_requirement: "list",
};
const TYPE_PLURAL: Record<string, string> = {
  definition: "Definitions", obligation: "Obligations", prohibition: "Prohibitions", permission: "Permissions",
  conditional_requirement: "Conditional requirements", procedural_requirement: "Procedural requirements",
};
const FACET_UI: Record<(typeof FACETS)[number], { label: string; icon: IconName; title: string }> = {
  conditions: { label: "With conditions", icon: "branch", title: "Rules whose applicability states conditions or scope exclusions" },
  exceptions: { label: "With exceptions", icon: "alert", title: "Rules that state at least one exception" },
  thresholds: { label: "Limits / thresholds", icon: "chart", title: "Rules with a numeric requirement (parameter, operator, value)" },
};
export const STATUS_LABEL: Record<ReviewFilter, string> = {
  all: "All statuses", pending: "Pending", accepted: "Accepted", rejected: "Rejected", edited: "Edited", flagged: "Potential issues", invalid: "Invalid Rule JSON", reviewed: "Reviewed (in file)",
};

interface SidebarProps {
  ov: Overview;
  api: ReviewApi;
  items: RuleItem[];
  category: RuleCategory;
  onCategory: (c: RuleCategory) => void;
  filters: ReviewFilter[];
  filter: ReviewFilter;
  onFilter: (f: ReviewFilter) => void;
  /** Rules of the chosen category with this status. */
  countOf: (f: ReviewFilter) => number;
  onOverview: () => void;
  search: string;
  onSearch: (q: string) => void;
  /** Rules left in the sequence by the current filters and search. */
  shown: number;
  exporting: boolean;
  onDownload: () => void;
  ruleDownload?: { href: string; name: string };
  menu: ReactNode;
}

export function ReviewSidebar({ ov, api, items, category, onCategory, filters, filter, onFilter, countOf, onOverview, search, onSearch, shown, exporting, onDownload, ruleDownload, menu }: SidebarProps) {
  const ready = api.kind === "ready";
  const accepted = ready ? api.data.counts.accepted : 0;
  const exportInfo = ready ? api.data.export : undefined;
  const types = useMemo(() => typeCounts(items), [items]);
  const facets = useMemo(() => {
    const all = items.map((r) => ruleFacets(r.effective));
    return FACETS.map((f) => ({ facet: f, count: all.filter((x) => x[f]).length })).filter((f) => f.count > 0);
  }, [items]);
  const cat = (key: RuleCategory, label: string, icon: IconName, count: number, title?: string) => (
    <li key={key}>
      <button type="button" className="rv-nav-row" aria-pressed={category === key} onClick={() => onCategory(key)} title={title}>
        <Icon name={icon} size={18} /><span className="rv-nav-label">{label}</span><span className="rv-count">{count}</span>
      </button>
    </li>
  );
  const STATUS_ICON: Record<ReviewFilter, IconName> = { all: "layers", pending: "clock", accepted: "check", rejected: "x", edited: "edit", flagged: "alert", invalid: "braces", reviewed: "check-square" };
  const statusRow = (f: ReviewFilter) => (
    <li key={f}>
      <button type="button" className={`rv-nav-row rv-status-row ${f}`} aria-pressed={filter === f} onClick={() => onFilter(f)}>
        <span className={`rm-dot ${f}`} aria-hidden="true"><Icon name={STATUS_ICON[f]} size={12} /></span>
        <span className="rv-nav-label">{STATUS_LABEL[f]}</span><span className="rv-count">{countOf(f)}</span>
      </button>
    </li>
  );
  return (
    <aside className="rex-side rv-side" aria-label="Rule navigation">
      <div className="rv-side-head">
        <Icon name="scale" size={20} />
        <h2>Rules ({ov.total})</h2>
        <button type="button" className="rex-icon-btn rv-list-btn" onClick={onOverview} title="Rule list: search, order and jump to any rule" aria-label="Rule list">
          <Icon name="list" size={18} />
        </button>
      </div>

      <label className="rex-search rv-find">
        <Icon name="search" size={14} />
        <input type="search" placeholder="Find a rule…" value={search} onChange={(e) => onSearch(e.target.value)} aria-label="Find a rule by title or citation" />
      </label>
      {search.trim() && <p className="rex-side-note" role="status">{shown} of {ov.total} rules match</p>}

      <div className="rv-status" role="group" aria-labelledby="rv-status-h">
        <h3 className="rv-side-h" id="rv-status-h">Review status</h3>
        <ul className="rv-nav">
          {filters.filter((f) => f !== "flagged" && f !== "invalid").map((f) => statusRow(f))}
        </ul>
        {filters.includes("flagged") && (
          <>
            <h3 className="rv-side-h" id="rv-checks-h">Automatic checks</h3>
            <ul className="rv-nav" aria-labelledby="rv-checks-h">{statusRow("flagged")}</ul>
          </>
        )}
        {filters.includes("invalid") && (
          <>
            <h3 className="rv-side-h" id="rv-valid-h">Rule JSON validity</h3>
            <ul className="rv-nav" aria-labelledby="rv-valid-h">{statusRow("invalid")}</ul>
          </>
        )}
        {ov.flagged > 0 && !filters.includes("flagged") && <p className="rex-side-note">{ov.flagged} with potential issues</p>}
      </div>

      <nav aria-label="Rule types">
        <details className="rv-group" open>
          <summary className="rv-side-h">Rule types</summary>
          <ul className="rv-nav">
            {cat("all", "All rules", "layers", ov.total)}
            {types.map(({ type, count }) => cat(`type:${type}`, TYPE_PLURAL[type] ?? KIND_LABEL[type] ?? type.replace(/_/g, " "), TYPE_ICON[type] ?? "file", count, `classification.type: ${type}`))}
          </ul>
        </details>
        {facets.length > 0 && (
          <details className="rv-group">
            <summary className="rv-side-h">Contains</summary>
            <ul className="rv-nav">
              {facets.map(({ facet, count }) => cat(`has:${facet}`, FACET_UI[facet].label, FACET_UI[facet].icon, count, FACET_UI[facet].title))}
            </ul>
          </details>
        )}
      </nav>

      <div className="rex-side-foot">
        {ready && (
          <button type="button" className="btn rex-side-btn" disabled={accepted === 0 || exporting} onClick={onDownload}
                  title={accepted > 0 ? "The accepted rules as Rule JSON 2.0 (status approved); rejected and open rules are not included" : "No rule has been accepted yet"}>
            <Icon name="download" size={16} />Download approved rules{accepted > 0 ? ` (${accepted})` : ""}
          </button>
        )}
        {ready && exportInfo && exportInfo.accepted > 0 && (
          exportInfo.blockedBy.length > 0
            ? <p className="rv-exportnote blocked" role="status"><Icon name="braces" size={14} /><span>Export blocked: {exportInfo.blockedBy.length} accepted {exportInfo.blockedBy.length === 1 ? "rule is" : "rules are"} not valid Rule JSON 2.0. <button type="button" className="link" onClick={() => onFilter("invalid")}>Show {exportInfo.blockedBy.length === 1 ? "it" : "them"}</button></span></p>
            : <p className="rv-exportnote ok" role="status"><Icon name="check" size={14} /><span>{exportInfo.accepted} accepted {exportInfo.accepted === 1 ? "rule is" : "rules are"} ready to export</span></p>
        )}
        {ruleDownload && <a className="btn rex-side-btn" href={ruleDownload.href} download={ruleDownload.name} title="The extracted rules.json as stored, without review decisions"><Icon name="download" size={16} />Download Rule JSON</a>}
        {menu}
      </div>
      <p className="rex-side-note">Every rule is a draft written by an AI model until a person has reviewed it.</p>
    </aside>
  );
}

// ── centre panel: the selected rule ────────────────────────────────────────────────────────────────────────────────────

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
  /** Shows a source passage in the PDF panel on this page. */
  onGoToSource?: (elementId: string) => void;
  /** The rule's cited passages, verified (sourceMap.ts). */
  highlights: SourceHighlight[];
  review: ReviewState;
  reviewer: string;
  onReviewer: (name: string) => void;
  /** Go on to the next pending rule after a decision (the same option as in the rule list). */
  advance?: boolean;
  onAdvance?: (on: boolean) => void;
}

export function ReviewMain({ rule, position, count, scope, onPrevious, onNext, onShowInPdf, onGoToSource, highlights, review, reviewer, onReviewer, advance, onAdvance }: CardProps) {
  const reading = useMemo(() => readRule(rule.effective), [rule.effective]);
  return (
    <section className="rex-main rv-center" aria-label="Review rule">
      <header className="rv-center-head">
        <nav className="rex-pager" aria-label="Rule navigation">
          <button type="button" className="rex-pager-btn" onClick={onPrevious} disabled={position <= 1} aria-label="Previous rule" title="Previous rule (←)"><Icon name="chevron-left" size={18} /></button>
          <button type="button" className="rex-pager-btn" onClick={onNext} disabled={position >= count} aria-label="Next rule" title="Next rule (→)"><Icon name="chevron-right" size={18} /></button>
          <span className="rex-pager-pos" aria-live="polite">Rule {position} of {count}{scope ? <small> · {scope}</small> : null}</span>
        </nav>
        <div className="rv-chips">
          <span className={`rex-kind${rule.type === "definition" ? " def" : ""}`} title={rule.type ? `classification.type: ${rule.type}` : undefined}>{reading.kind}</span>
          <SourceButtons highlights={highlights} onShowInPdf={onShowInPdf} onGoToSource={onGoToSource} />
        </div>
      </header>
      <div className="rv-title-row">
        <h2 className="rv-title">{rule.citation ? <span className="rex-cite">{rule.citation}</span> : <span className="rv-title-fallback">{rule.title}</span>}</h2>
        <RuleStatus rule={rule} />
      </div>
      <p className="rv-meta"><span>Rule ID</span><code className="rv-id">{rule.id}</code></p>

      <article className="rex-card" aria-label={rule.title}>
        <RuleContent rule={rule} reading={reading} />
        <CheckStatus rule={rule} />
        {review.issues && <InvalidNotice issues={review.issues} />}
        <Decision review={review} reviewer={reviewer} onReviewer={onReviewer} advance={advance} onAdvance={onAdvance} />
      </article>
    </section>
  );
}

/** The record is not valid Rule JSON 2.0: what is wrong, and the two ways out. Structural validity is its own fact, apart from the decision and
 *  from the automatic checks (which can say "no issues" for a record the schema refuses). */
function InvalidNotice({ issues }: { issues: string[] }) {
  return (
    <div className="rv-invalid" role="note" aria-label="Rule JSON validation">
      <Icon name="braces" size={18} />
      <div>
        <strong>Not valid Rule JSON 2.0: this rule cannot be accepted yet.</strong>
        <ul>{issues.map((i) => <li key={i}><code>{i}</code></li>)}</ul>
        <p>Correct it with <em>Edit</em> (advanced editor), or reject it if the passage is not an operative rule. The decision and the automatic checks are separate from this.</p>
      </div>
    </div>
  );
}

/** ODOS's automatic checks for the rule: their notices when they flagged something, else a plain statement that they flagged
 *  nothing. Never a claim that the rule is valid or correct: the checks do not compare meaning. */
function CheckStatus({ rule }: { rule: RuleItem }) {
  return (
    <>
      {rule.checkFlags.length > 0 ? <IssueNotice rule={rule} /> : (
        <p className="rv-check" role="note" title={CHECK_SCOPE}>
          <Icon name="check" size={16} />No issues flagged by automatic checks
          <span className="rv-check-info" aria-hidden="true"><Icon name="info" size={14} /></span>
          <span className="sr-only">. {CHECK_SCOPE}</span>
        </p>
      )}
      {rule.checkNotes.length > 0 && <CheckNotes rule={rule} />}
    </>
  );
}

/** Informational results of the automatic checks (not potential issues): shown neutrally, with the check's own wording on request. */
function CheckNotes({ rule }: { rule: RuleItem }) {
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [rule.id]);
  return (
    <div className="rv-checknote">
      <button type="button" className="rv-checknote-btn" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <Icon name="info" size={15} />Numbers appear only in the definition text, so automatic checks cannot verify them<span className="rex-issue-more">{open ? "Hide" : "Details"}</span>
      </button>
      {open && <ul className="rv-checknote-list" aria-label="Informational notes of ODOS's automatic checks">{rule.checkNotes.map((f, i) => <li key={i}>{f}</li>)}</ul>}
    </div>
  );
}
const CHECK_SCOPE = "ODOS's automatic checks look at form, units, numbers and sources. They do not verify legal meaning: please review the rule against its source.";

function IssueNotice({ rule }: { rule: RuleItem }) {
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [rule.id]);
  if (rule.checkFlags.length === 0) return null;
  return (
    <div className="rex-issue">
      <button type="button" className="rex-issue-btn" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <Icon name="alert" size={16} />{rule.checkFlags.length === 1 ? "1 issue" : `${rule.checkFlags.length} issues`} flagged by automatic checks — please look closely<span className="rex-issue-more">{open ? "Hide" : "Details"}</span>
      </button>
      {open && <ul className="rex-issue-list" aria-label="Noticed by ODOS's automatic checks">{rule.checkFlags.map((f, i) => <li key={i}>{f}</li>)}</ul>}
    </div>
  );
}

/** The rule's source as compact controls beside the citation: show the passage in the PDF panel, or open it in Document Review.
 *  How precisely the PDF highlight can show it is in the button's tooltip and the PDF legend; a cited passage that is not in the
 *  opened document is never hidden: it gets a visible warning chip. */
function SourceButtons({ highlights, onShowInPdf, onGoToSource }: { highlights: SourceHighlight[]; onShowInPdf?: (elementId: string) => void; onGoToSource?: (elementId: string) => void }) {
  const primary = highlights.filter((h) => h.role === "primary");
  const main = primary.length ? primary : highlights.slice(0, 1);
  const target = main.find((h) => h.element) ?? null;
  const missing = highlights.filter((h) => !h.element);
  const precision = main.filter((h) => h.element).map((h) => `${h.label}${h.sentenceLabel ? ` · ${h.sentenceLabel}` : ""}: ${h.precision === "element" ? "exact" : `whole element, not sentence-precise${h.reason ? ` (${h.reason})` : ""}`}`).join("\n");
  const pages = pagesLabel(main.flatMap((h) => h.pages));
  return (
    <>
      {onGoToSource && (
        <button type="button" className="rv-iconbtn rv-goto" disabled={!target} onClick={() => target && onGoToSource(target.elementId)}
                aria-label="Go to source" title={target ? `Go to source${pages ? ` (${pages})` : ""}\n${precision}` : "This passage is not part of the opened document"}>
          <Icon name="fit" size={16} />
        </button>
      )}
      <button type="button" className="rv-iconbtn rex-view-btn" disabled={!target || !onShowInPdf} onClick={() => target && onShowInPdf?.(target.elementId)}
              aria-label="View in document" title={target ? "View in document: opens Document Review with this passage highlighted" : "This passage is not part of the opened document"}>
        <Icon name="open" size={16} />
      </button>
      {(main.length === 0 || missing.length > 0) && (
        <span className="rv-srcwarn" role="note" title={main.length === 0 ? "This rule names no passage of the document." : missing.map((h) => `${h.label}: ${h.reason ?? "not part of the opened document"}`).join("\n")}>
          <Icon name="alert" size={14} />{main.length === 0 ? "No source" : `${missing.length} source${missing.length > 1 ? "s" : ""} not found`}
        </span>
      )}
    </>
  );
}
// ── the rule's content, adapted to what the record holds ──────────────────────────────────────────────────────────────

/** A fact in a formula: its short symbol or its name in words; the exact identifier is its tooltip and is in the legend. */
const Var = ({ id }: { id: string }) => {
  const n = mathName(id);
  return <span className={`rv-m-fact${n.symbol ? " sym" : ""}`} title={id}>{n.text}</span>;
};
const MathText = ({ tokens }: { tokens: MathToken[] }) => <>{tokens.map((t, i) => (t.kind === "fact" ? <Var key={i} id={t.text} /> : <span key={i} className={`rv-m-${t.kind}`}>{t.text}</span>))}</>;

/** The variables of a formula or bound: how each is written, its exact Rule JSON identifier and its unit. */
function VarLegend({ vars }: { vars: Array<{ id: string; unit?: string; note?: string }> }) {
  return (
    <dl className="rv-params" aria-label="Variables">
      {vars.map((v) => (
        <div key={v.id}><dt><Var id={v.id} /></dt><dd><code>{v.id}</code>{v.unit ? ` · in ${v.unit}` : ""}{v.note ? ` · ${v.note}` : ""}</dd></div>
      ))}
    </dl>
  );
}

/** A numeric requirement as a bound: the comparison written as mathematics, operator, value and unit exactly as stored. */
export function ThresholdTiles({ t }: { t: Threshold }) {
  const op = OPERATOR_SYMBOL[t.operator] ?? t.operator;
  return (
    <div className="rv-limit" role="group" aria-label={`Limit: ${t.fact} ${OPERATOR_WORDS[t.operator] ?? t.operator} ${String(t.value)}${t.unit ? ` ${t.unit}` : ""}`}>
      <p className="rv-eq" aria-hidden="true">
        <Var id={t.fact} /><span className="rv-m-rel" title={OPERATOR_LABEL[t.operator] ?? t.operator}>{op}</span>
        <span className="rv-m-num">{String(t.value)}</span>{t.unit && <span className="rv-m-unit">{"\u00a0"}{t.unit}</span>}
      </p>
      <VarLegend vars={[{ id: t.fact, unit: t.unit || undefined }]} />
    </div>
  );
}

/** A `formula` requirement as mathematics: fact ⟨relation⟩ expression, with the unit and a legend of its variables. `=` means
 *  the formula determines the fact; ≥ and ≤ are a minimum and a maximum. */
export function FormulaCard({ f }: { f: Formula }) {
  const params = formulaParameters(f);
  const op = OPERATOR_SYMBOL[f.operator];
  const spoken = `${f.fact} ${OPERATOR_WORDS[f.operator]} ${f.expression.tokens.map((t) => t.text).join("")}${f.unit ? `, in ${f.unit}` : ""}`;
  return (
    <figure className="rv-formula" aria-label={`Formula: ${spoken}`}>
      <p className="rv-eq" aria-hidden="true">
        <Var id={f.fact} /><span className="rv-m-rel" title={OPERATOR_WORDS[f.operator]}>{op}</span><MathText tokens={f.expression.tokens} />
        {f.unit && <span className="rv-m-unit rv-m-in">[{f.unit}]</span>}
      </p>
      <VarLegend vars={params.map((p) => ({ id: p.name, unit: p.unit, note: p.name === f.fact ? (f.operator === "==" ? "determined by this formula" : f.operator === "<=" || f.operator === "<" ? "bounded above" : "bounded below") : undefined }))} />
    </figure>
  );
}

/** The passage one part of the rule comes from, when its wording verifiably matches exactly one cited passage; nothing otherwise
 *  (the rule's citation in the header then applies). Clicking shows the passage in the PDF panel. */
const ParentCite = createContext<string | null>(null);
const citeKey = (s: { elementId: string; sentenceId: string | null }) => `${s.elementId}#${s.sentenceId ?? ""}`;
function PartCite({ text }: { text: string | null | undefined }) {
  const nav = useContext(ComponentNavContext);
  const parent = useContext(ParentCite);
  const src = nav?.resolve(text) ?? null;
  if (!nav || !src || citeKey(src) === parent) return null; // a part inside an exception that comes from the same passage: said once
  const how = src.precision === "exact" ? "The PDF highlight is exactly this passage." : "This is one sentence of a longer passage; the sentence's position on the page is not in the document data, so the whole passage is highlighted.";
  const active = nav.focused?.elementId === src.elementId && nav.focused?.sentenceId === src.sentenceId;
  return (
    <button type="button" className={`rv-pcite${src.precision === "element" ? " approx" : ""}`} aria-pressed={active} onClick={() => nav.go(src)}
            title={`Source of this part: ${src.citation} (matched by its wording). ${how} Click to show it in the PDF.`} aria-label={`Show source ${src.citation} in the PDF`}>
      {src.citation}
    </button>
  );
}

function ExceptionParts({ description, children }: { description: string; children: ReactNode }) {
  const nav = useContext(ComponentNavContext);
  const src = nav?.resolve(description) ?? null;
  return <ParentCite.Provider value={src ? citeKey(src) : null}>{children}</ParentCite.Provider>;
}

function Lines({ lines }: { lines: TextLine[] }) {
  return (
    <ul className="rex-lines">
      {lines.map((l, i) => (
        <li key={i} className={l.unclear ? "unclear" : undefined}>
          <span className="rex-line-text">{l.unclear && <span className="rex-unclear-tag">Unclear</span>}{l.text}</span>
          {l.note && <span className="rex-line-note">{l.note}<PartCite text={l.note} /></span>}
          {l.formula && <FormulaCard f={l.formula} />}
          {l.threshold && <ThresholdTiles t={l.threshold} />}
          {l.children && l.children.length > 0 && <Lines lines={l.children} />}
        </li>
      ))}
    </ul>
  );
}

type Tone = "main" | "def" | "cond" | "exc" | "plain";
const SECTION: Record<TextBlock["key"], { label: string; tone: Tone; icon: IconName }> = {
  definition: { label: "Definition", tone: "def", icon: "book" },
  requires: { label: "Main rule", tone: "main", icon: "target" },
  targets: { label: "Applies to", tone: "plain", icon: "cube" },
  actors: { label: "Who is involved", tone: "plain", icon: "users" },
  when: { label: "Conditions", tone: "cond", icon: "branch" },
  notWhen: { label: "Scope exclusions", tone: "cond", icon: "ban" },
  exceptions: { label: "Exceptions", tone: "exc", icon: "alert" },
  references: { label: "References", tone: "plain", icon: "link" },
};
/** The order of the sections: what the rule says first, then when it applies, then its exceptions. */
const SECTION_ORDER: TextBlock["key"][] = ["definition", "requires", "targets", "actors", "when", "notWhen", "exceptions", "references"];

function Section({ block, children }: { block: TextBlock; children: ReactNode }) {
  const ui = SECTION[block.key];
  const label = block.key === "exceptions" && block.lines.length === 1 ? "Exception" : ui.label;
  // the block's own title ("Applies when all of these are true", "Requirements (all must be met)") says how the parts combine,
  // exactly as the record's all / any does; it is shown only when it says more than the label
  const sub = block.title !== label && block.title !== "Requirement" && block.title !== "Definition" && !(block.key === "exceptions") ? block.title : null;
  return (
    <details className={`rv-sec ${ui.tone}`} open>
      <summary>
        <Icon name={ui.icon} size={18} />
        <span className="rv-sec-label">{label}</span>
        {sub && <span className="rv-sec-sub">{sub}</span>}
        {block.key === "exceptions" && block.lines.length > 1 && <span className="rv-count">{block.lines.length}</span>}
        <span className="rv-sec-chev" aria-hidden="true"><Icon name="chevron-down" size={16} /></span>
      </summary>
      <div className="rex-block rv-sec-body">{children}</div>
    </details>
  );
}

/** A definition's text: an explicit enumeration in it as separate items (cut only at the text's own markers), else the text as
 *  written. A long definition gets its own bounded scroll area. */
function DefinitionText({ text }: { text: string }) {
  const list = useMemo(() => parseDefinitionList(text), [text]);
  const long = text.length > LONG_DEFINITION;
  const body = list ? (
    <>
      {list.intro && <p className="rv-def-text rv-def-intro">{list.intro}</p>}
      <DefItems items={list.items} />
    </>
  ) : <p className="rv-def-text">{text}</p>;
  return long ? <div className="rv-def-scroll" tabIndex={0} role="region" aria-label="Definition text">{body}</div> : body;
}
function DefItems({ items, nested = false }: { items: DefItem[]; nested?: boolean }) {
  return (
    <ul className={nested ? "rv-def-list nested" : "rv-def-list"}>
      {items.map((it, i) => (
        <li key={i}>
          <span className="rv-def-marker">{it.marker}</span>
          <div className="rv-def-item">
            {it.text && <span>{it.text}</span>}
            {it.items && <DefItems items={it.items} nested />}
          </div>
        </li>
      ))}
    </ul>
  );
}

function RuleContent({ rule, reading }: { rule: RuleItem; reading: ReadableRule }) {
  const def = rule.effective.definition as Record<string, unknown> | undefined;
  const blocks = [...reading.blocks].sort((a, b) => SECTION_ORDER.indexOf(a.key) - SECTION_ORDER.indexOf(b.key));
  return (
    <section className="rex-suggest rv-content" aria-labelledby={`rex-sug-${rule.id}`}>
      <h3 className="sr-only" id={`rex-sug-${rule.id}`}>Rule content</h3>
      {/* the model's one-sentence summary only where the structured rule alone does not state the rule (nothing to read, or parts it cannot put into words) */}
      {reading.summary && (reading.gaps.length > 0 || !reading.blocks.some((b) => b.key === "requires" || b.key === "definition")) && (
        <p className="rex-summary-text rv-summary-line"><span className="rv-field-label">Summary</span>{reading.summary}</p>
      )}
      {rule.edited && <p className="rex-muted rex-edited-note"><Icon name="edit" size={14} />Edited by a reviewer. The extracted version is kept; compare both in the Rule JSON tab.</p>}
      {blocks.map((b) => (
        <Section key={b.key} block={b}>
          {b.key === "definition" && def && typeof def.term === "string" && typeof def.text === "string" ? (
            <>
              <div className="rv-def">
                <p className="rv-field-label">Term</p>
                <p className="rv-term">{def.term}</p>
                <p className="rv-field-label">Definition</p>
                <DefinitionText text={def.text} />
                <PartCite text={def.text} />
              </div>
              {b.lines[0]?.children && b.lines[0].children.length > 0 && <Lines lines={b.lines[0].children} />}
            </>
          ) : b.key === "exceptions" ? (
            <ol className="rv-exc-list">
              {b.lines.map((l, i) => (
                <li key={i} className={`rv-exc${l.unclear ? " unclear" : ""}`}>
                  <p className="rv-exc-head">{l.unclear && <span className="rex-unclear-tag">Unclear</span>}{l.tag && l.text.startsWith(`${l.tag}: `)
                    ? <><span className={`rv-exc-tag ${l.tag.toLowerCase().replace(/\s+/g, "-")}`}>{l.tag}</span>{l.text.slice(l.tag.length + 2)}<PartCite text={l.text.slice(l.tag.length + 2)} /></> : l.text}</p>
                  <ExceptionParts description={l.tag && l.text.startsWith(`${l.tag}: `) ? l.text.slice(l.tag.length + 2) : l.text}>
                    {l.formula && <FormulaCard f={l.formula} />}
                    {l.threshold && <ThresholdTiles t={l.threshold} />}
                    {l.children && l.children.length > 0 && <Lines lines={l.children} />}
                  </ExceptionParts>
                </li>
              ))}
            </ol>
          ) : (
            <Lines lines={b.lines} />
          )}
        </Section>
      ))}
      {reading.gaps.length > 0 && (
        <div className="alert warn rex-gap" role="note">
          <Icon name="alert" size={14} />
          <span>Part of this rule cannot be shown in plain language, so the text above is not the complete rule. Check the complete rule in the Rule JSON tab.</span>
        </div>
      )}
    </section>
  );
}

// ── decision ───────────────────────────────────────────────────────────────────────────────────────────────────────────

function Decision({ review, reviewer, onReviewer, advance, onAdvance }: { review: ReviewState; reviewer: string; onReviewer: (name: string) => void; advance?: boolean; onAdvance?: (on: boolean) => void }) {
  const { api, entry, busy, form, setForm, send, openEdit, setError, error, rule, jobId } = review;
  const ready = api.kind === "ready" && !!entry;
  const off = !ready || busy;
  const offTitle = api.kind === "stale" ? "The extraction has changed; reload the results" : api.kind === "loading" ? "Loading the review state" : !ready ? REVIEW_UNAVAILABLE : undefined;
  const state = reviewStateLine(entry);
  const nameMissing = error === NAME_MISSING;
  return (
    <section className="rex-decide" aria-label="Your decision">
      <div className="rv-actionbar">
      {state && <p className={`rex-decided ${entry?.state ?? ""}`} role="status">{entry?.state === "accepted" ? <Icon name="check" size={16} /> : entry?.state === "rejected" ? <Icon name="x" size={16} /> : <Icon name="edit" size={16} />}{state}</p>}
      {entry && entry.state !== "pending" && entry.reason && <p className="rex-muted rex-decided-reason">Reason: {entry.reason}</p>}
      <h2 className="sr-only">Is this rule correct?</h2>
      <div className="rex-choices" role="group" aria-label="Review actions">
        <button type="button" className="rex-choice yes" disabled={off || entry?.state === "accepted" || !!review.issues} title={review.issues ? NOT_ACCEPTABLE : offTitle ?? "The rule is correct"} onClick={() => void send("accept")}>
          <Icon name="check" size={18} /><span className="rex-choice-main">Accept</span>
        </button>
        <button type="button" className="rex-choice" disabled={off} title={offTitle ?? "Change the rule"} aria-expanded={form === "edit"} onClick={() => (form === "edit" ? setForm(null) : openEdit())}>
          <Icon name="edit" size={18} /><span className="rex-choice-main">Edit</span>
        </button>
        <button type="button" className="rex-choice no" disabled={off || entry?.state === "rejected"} title={offTitle ?? "The rule is incorrect (asks for a reason)"} aria-expanded={form === "reject"} onClick={() => { setForm(form === "reject" ? null : "reject"); setError(null); }}>
          <Icon name="trash" size={18} /><span className="rex-choice-main">Reject</span>
        </button>
      </div>

      {ready ? (
        <div className="rex-decide-foot">
          <label className={`rex-name${nameMissing ? " missing" : ""}`}>
            <span>Reviewing as</span>
            <input type="text" value={reviewer} maxLength={100} onChange={(e) => { onReviewer(e.target.value); if (nameMissing) setError(null); }} placeholder="Your name" autoComplete="name"
                   aria-invalid={nameMissing || undefined} title="Your name is saved with each decision. It is not checked by a login." aria-label="Reviewing as (your name, saved with each decision)" />
          </label>
          {entry!.edited && <button type="button" className="btn small" disabled={busy} onClick={() => void send("reset")} title="Back to the extracted rule; the edit stays in the history"><Icon name="refresh" size={14} />Reset edit</button>}
        </div>
      ) : (
        <ReviewUnavailable api={api} rule={rule} hasJob={!!jobId} />
      )}
      {ready && onAdvance && (
        <label className="rex-check rv-auto"><input type="checkbox" checked={!!advance} onChange={(e) => onAdvance(e.target.checked)} />Open the next pending rule after a decision</label>
      )}
      </div>

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
        <p className="rex-form-title">{editMode === "simple" ? "Edit the values of this rule" : "Advanced editor (Rule JSON)"}</p>
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
      <p className="rex-muted rex-small"><Icon name="info" size={14} />The extracted rule is kept. The edited rule is checked against Rule JSON 2.0 by the server and then waits for review again.</p>
      <div className="rex-actions">
        <button type="button" className="btn primary" disabled={busy} onClick={saveEdit}>Save edit</button>
        <button type="button" className="btn" disabled={busy} onClick={() => setForm(null)}>Cancel</button>
      </div>
    </div>
  );
}

// ── small parts ────────────────────────────────────────────────────────────────────────────────────────────────────────

/** A modal panel (the rule list, the help): closes on Escape and on the close button; focus moves into it and back. */
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
        <li><strong>Choose rules.</strong> The left panel filters by rule type, by what a rule contains and by review status; the list button opens every rule with search.</li>
        <li><strong>Check the rule against its source.</strong> “Go to source” shows the passage highlighted in the PDF on the right; the Rule JSON tab shows the complete record.</li>
        <li><strong>Decide.</strong> “Accept” accepts the rule, “Edit” changes it, “Reject” rejects it with a reason.</li>
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
