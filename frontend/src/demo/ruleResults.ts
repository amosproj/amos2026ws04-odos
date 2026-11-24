// What the Rule Extraction page shows of a job's `rules.json` (written by the backend's Bedrock extraction): the Rule JSON
// 2.0 records exactly as stored, plus the facts the page may state about them. Nothing here invents a field, a score or a
// review decision: a value the file does not hold is absent from the result.
import type { DocElement } from "../types";
import { ruleEntries, type HumanState, type RuleReviewEntry } from "./live";

/** Prefix of the review ambiguities the backend's own quality checks add to a rule (backend/src/odos/llm/rule_checks.py). */
export const CHECK_FLAG_PREFIX = "ODOS check: ";

export interface SourceElementRef {
  elementId: string;
  sentenceId?: string;
  role?: string;
  pdfPages: number[];
}

export interface RuleItem {
  id: string;
  /** `classification.summary`; the id when the record has none. */
  title: string;
  citation: string | null;
  type: string | null;
  /** The record, unchanged. */
  rule: Record<string, unknown>;
  sources: SourceElementRef[];
  /** `review.status` of the record: "draft", "reviewed" or "approved" (Rule JSON schema). */
  reviewStatus: string;
  machineCheckable: boolean | null;
  /** Review ambiguities written by the backend's automated checks (prefix removed). */
  checkFlags: string[];
  /** Automated-check results that are informational for this rule, not potential issues: for a definition, a number that appears
   *  only in its descriptive text (a definition describes; it need not restate its numbers as conditions). Kept as written. */
  checkNotes: string[];
  /** The other review ambiguities, as the model wrote them. */
  ambiguities: string[];
  notes: string[];
  /** The reviewer's decision when the backend stores decisions; null when it does not (then `reviewStatus` is all there is). */
  human: HumanState | null;
  /** A reviewer edited the content. `rule` stays the extracted record; `effective` is what is in force. */
  edited: boolean;
  effective: Record<string, unknown>;
  entry: RuleReviewEntry | null;
}

/** A candidate the backend's automated checks refused. Not a human decision, and not part of the rule list. */
export interface AutoRejected {
  id: string;
  reasons: string[];
}

export interface RuleResults {
  items: RuleItem[];
  /** Records of the file that are not Rule JSON 2.0 and are therefore not shown. */
  skipped: number;
  autoRejected: AutoRejected[];
  generation: RuleGeneration | null;
}

/** What `_generation` of the stored file states; every field is optional because older files lack some of them. */
export interface RuleGeneration {
  modelId?: string;
  promptVersion?: string;
  generatedAt?: string;
  /** Candidates the model proposed (accepted ones plus those the checks refused). */
  proposed?: number;
  /** Records whose form the backend repaired along the schema (each repair is listed in the rule's review notes). */
  repaired?: number;
  /** How much of the document's normative text some rule cites as its primary source (counts, not a quality measure). */
  coverage?: { sentences: number; sentencesCited: number; elements: number; elementsCited: number };
}

const record = (v: unknown): Record<string, unknown> | null => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null);
const strings = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
const str = (v: unknown): string | undefined => (typeof v === "string" && v ? v : undefined);

function sourcesOf(rule: Record<string, unknown>): SourceElementRef[] {
  const elements = record(rule.source)?.elements;
  if (!Array.isArray(elements)) return [];
  return elements.flatMap((e) => {
    const r = record(e);
    const elementId = str(r?.elementId);
    if (!r || !elementId) return [];
    return [{
      elementId, sentenceId: str(r.sentenceId), role: str(r.role),
      pdfPages: Array.isArray(r.pdfPages) ? r.pdfPages.filter((p): p is number => typeof p === "number") : [],
    }];
  });
}

/** The backend's two quantity checks ("a threshold only in a description cannot be checked" / "express it as a predicate or
 *  requirement"): they report numbers of the text that the record's logic does not contain. */
const DESCRIPTIVE_NUMBER = [/a threshold only in a description cannot be checked\.?$/, /which the record's conditions and requirements do not contain; express it as a predicate or requirement\.?$/];

/** Splits the automated checks of a rule into potential issues and informational notes. Only for definitions, and only the
 *  "number only in descriptive text" result becomes a note; every other check (sources, units, values, form) stays an issue. */
export function splitChecks(flags: string[], type: string | null): { checkFlags: string[]; checkNotes: string[] } {
  if (type !== "definition") return { checkFlags: flags, checkNotes: [] };
  const descriptive = (f: string) => DESCRIPTIVE_NUMBER.some((re) => re.test(f.trim()));
  return { checkFlags: flags.filter((f) => !descriptive(f)), checkNotes: flags.filter(descriptive) };
}

export function toRuleItem(rule: Record<string, unknown>): RuleItem {
  const review = record(rule.review) ?? {};
  const classification = record(rule.classification);
  const ambiguities = strings(review.ambiguities);
  return {
    id: String(rule.id),
    title: str(classification?.summary) ?? String(rule.id),
    citation: str(record(rule.source)?.citation) ?? null,
    type: str(classification?.type) ?? null,
    rule,
    sources: sourcesOf(rule),
    reviewStatus: str(review.status) ?? "draft",
    machineCheckable: typeof review.machineCheckable === "boolean" ? review.machineCheckable : null,
    ...splitChecks(ambiguities.filter((a) => a.startsWith(CHECK_FLAG_PREFIX)).map((a) => a.slice(CHECK_FLAG_PREFIX.length)), str(classification?.type) ?? null),
    ambiguities: ambiguities.filter((a) => !a.startsWith(CHECK_FLAG_PREFIX)),
    notes: strings(review.notes),
    human: null, edited: false, effective: rule, entry: null,
  };
}

/** The item with the reviewer's state of the backend applied. The extracted record (`rule`) and the source references stay
 *  as extracted; the review notes and flags are those of the record in force (an edit recomputes ODOS's notes). */
export function applyReview(item: RuleItem, entry: RuleReviewEntry | undefined): RuleItem {
  if (!entry) return item;
  const effective = entry.effectiveRule ?? item.rule;
  const now = toRuleItem(effective);
  return { ...item, title: now.title, machineCheckable: now.machineCheckable, checkFlags: now.checkFlags, checkNotes: now.checkNotes, ambiguities: now.ambiguities,
           notes: now.notes, human: entry.state, edited: entry.edited, effective, entry };
}

/** The stored `rules.json` (`{ _generation, rules }`, or a bare array of records) as the page shows it. Null when there is
 *  no such file. */
export function toRuleResults(data: unknown): RuleResults | null {
  if (data === null || data === undefined) return null;
  const items = ruleEntries(data).map(toRuleItem);
  const file = record(data);
  const raw = Array.isArray(data) ? data.length : Array.isArray(file?.rules) ? file.rules.length : items.length;
  const gen = record(file?._generation);
  const counts = record(gen?.counts);
  const rejected = Array.isArray(gen?.rulesRejected) ? gen.rulesRejected : [];
  const proposed = typeof counts?.proposed === "number" ? counts.proposed : typeof gen?.rulesProposed === "number" ? gen.rulesProposed : undefined;
  return {
    items,
    skipped: Math.max(0, raw - items.length),
    autoRejected: rejected.flatMap((r) => { const x = record(r); return x ? [{ id: str(x.id) ?? "(no id)", reasons: strings(x.reasons) }] : []; }),
    generation: gen ? {
      modelId: str(gen.modelId), promptVersion: str(gen.promptVersion), generatedAt: str(gen.generatedAt), proposed,
      repaired: typeof counts?.repaired === "number" ? counts.repaired : Array.isArray(gen.schemaRepairs) ? gen.schemaRepairs.length : undefined,
      coverage: coverageOf(gen.coverage),
    } : null,
  };
}

function coverageOf(value: unknown): RuleGeneration["coverage"] {
  const c = record(value);
  const n = (k: string) => (typeof c?.[k] === "number" && Number.isFinite(c[k]) ? (c[k] as number) : null);
  const [sentences, sentencesCited, elements, elementsCited] = [n("sentences"), n("sentencesCited"), n("elements"), n("elementsCited")];
  if (sentences === null || sentencesCited === null || elements === null || elementsCited === null) return undefined;
  return { sentences, sentencesCited, elements, elementsCited };
}

/** The pages of a source reference that can be real pages of a document with `numPages` pages (whole numbers from 1);
 *  anything else is dropped, never repaired or guessed. */
export const validPages = (pages: number[], numPages: number): number[] => pages.filter((p) => Number.isInteger(p) && p >= 1 && p <= numPages);

/** "p. 9", "p. 9–10", "pp. 3, 7": the page numbers as a person reads them; empty when there are none. */
export function pagesLabel(pages: number[]): string {
  const p = [...new Set(pages)].sort((a, b) => a - b);
  if (!p.length) return "";
  if (p.length === 1) return `p. ${p[0]}`;
  return p.every((x, i) => i === 0 || x === p[i - 1] + 1) ? `p. ${p[0]}–${p[p.length - 1]}` : `pp. ${p.join(", ")}`;
}

/** `_generation.generatedAt` of a stored `rules.json`: tells two extractions apart. */
export const generatedAt = (data: unknown): string | null => str(record(record(data)?._generation)?.generatedAt) ?? null;

/** "edited" is an attribute, not a state: an edited rule keeps its decision (accepted, rejected or pending). */
export type ReviewFilter = "all" | "pending" | "accepted" | "rejected" | "flagged" | "reviewed" | "edited";

/** Pending / reviewed as stored: the reviewer's decision when the backend keeps decisions, else the status in the file. */
export const isPending = (r: RuleItem) => (r.human ? r.human === "pending" : r.reviewStatus === "draft");
export const isReviewed = (r: RuleItem) => !r.human && (r.reviewStatus === "reviewed" || r.reviewStatus === "approved");

export const REVIEW_LABEL: Record<string, string> = { draft: "Pending Review", reviewed: "Reviewed", approved: "Approved" };
export const reviewLabel = (status: string) => REVIEW_LABEL[status] ?? status;

export function matchesFilter(r: RuleItem, f: ReviewFilter): boolean {
  return f === "all" || (f === "pending" && isPending(r)) || (f === "accepted" && r.human === "accepted") || (f === "rejected" && r.human === "rejected")
    || (f === "flagged" && r.checkFlags.length > 0) || (f === "reviewed" && isReviewed(r)) || (f === "edited" && r.edited);
}

// ── rule categories: the record's own type, and what its structure contains ──────────────────────────────────────────

/** What the record in force contains. Read from the Rule JSON 2.0 structure only; a rule has a part only when the record states it.
 *  `conditions`: the rule's own applicability conditions or scope exclusions (an exception's condition belongs to the exception).
 *  `thresholds`: a numeric requirement anywhere in the record (requirements, requirement expression, exceptions, definition). */
export interface RuleFacets { exceptions: boolean; conditions: boolean; thresholds: boolean }

function hasNumeric(v: unknown): boolean {
  const x = record(v);
  if (Array.isArray(v)) return v.some(hasNumeric);
  if (!x) return false;
  if (x.kind === "numeric") return true;
  return hasNumeric(x.requirement) || hasNumeric(x.requirements) || hasNumeric(x.meaning);
}

export function ruleFacets(rule: Record<string, unknown>): RuleFacets {
  const app = record(rule.applicability);
  const exceptions = Array.isArray(rule.exceptions) ? rule.exceptions : [];
  return {
    exceptions: exceptions.length > 0,
    conditions: (app?.conditions !== undefined && app.conditions !== null) || (Array.isArray(app?.scopeExclusions) && app.scopeExclusions.length > 0),
    thresholds: hasNumeric(rule.requirements) || hasNumeric(rule.requirementExpression) || hasNumeric(record(rule.definition)?.meaning)
      || exceptions.some((e) => hasNumeric(record(e)?.requirements)),
  };
}

/** "all", a classification type ("type:obligation") or a structural facet ("has:exceptions"). */
export type RuleCategory = string;
export const FACETS = ["conditions", "exceptions", "thresholds"] as const;

export function matchesCategory(r: RuleItem, c: RuleCategory): boolean {
  if (c === "all") return true;
  if (c.startsWith("type:")) return (r.type ?? "") === c.slice(5);
  if (c.startsWith("has:")) return ruleFacets(r.effective)[c.slice(4) as keyof RuleFacets] === true;
  return true;
}

/** The classification types that occur in `items`, in the schema's order, with their counts. Types that do not occur are left out. */
export const TYPE_ORDER = ["definition", "obligation", "prohibition", "permission", "conditional_requirement", "procedural_requirement"];
export function typeCounts(items: RuleItem[]): Array<{ type: string; count: number }> {
  const counts = new Map<string, number>();
  for (const r of items) if (r.type) counts.set(r.type, (counts.get(r.type) ?? 0) + 1);
  const rank = (t: string) => { const i = TYPE_ORDER.indexOf(t); return i < 0 ? TYPE_ORDER.length : i; };
  return [...counts].sort((a, b) => rank(a[0]) - rank(b[0]) || a[0].localeCompare(b[0])).map(([type, count]) => ({ type, count }));
}

/** Search over what a person reads of a rule: id, summary, citation and type. */
export function matchesSearch(r: RuleItem, query: string): boolean {
  const q = query.trim().toLowerCase();
  return !q || [r.id, r.title, r.citation ?? "", r.type ?? ""].some((t) => t.toLowerCase().includes(q));
}

export interface Overview {
  total: number;
  pending: number;
  reviewed: number;
  approved: number;
  /** Decisions of reviewers (zero while the backend keeps none). */
  accepted: number;
  rejected: number;
  edited: number;
  flagged: number;
  autoRejected: number;
}

export function overviewOf(results: RuleResults): Overview {
  const { items } = results;
  return {
    total: items.length,
    pending: items.filter(isPending).length,
    reviewed: items.filter((r) => !r.human && r.reviewStatus === "reviewed").length,
    approved: items.filter((r) => !r.human && r.reviewStatus === "approved").length,
    accepted: items.filter((r) => r.human === "accepted").length,
    rejected: items.filter((r) => r.human === "rejected").length,
    edited: items.filter((r) => r.edited).length,
    flagged: items.filter((r) => r.checkFlags.length > 0).length,
    autoRejected: results.autoRejected.length,
  };
}

// ── provisions: how the review queue groups and names rules, for any document type ─────────────────────────────────────

/** Element types that are a *provision* of a document: the unit a reader cites (a section sign in German law, an article in EU
 *  law). The queue groups rules by the nearest of these around their source. Another document type (for example a technical
 *  standard's clause) is supported by adding its element type here; a rule whose sources lie in none of them is listed under
 *  "Other provisions". Nothing else in the page depends on the document type. */
export const PROVISION_TYPES: ReadonlySet<string> = new Set(["paragraph", "article"]);

export interface Provision {
  id: string;
  /** "§ 6 · Abstandsflächen, Abstände", "Artikel 4 · Verfügbarkeit …": marker and title as the document prints them. */
  label: string;
}

export const provisionLabel = (e: DocElement): string => [e.marker, e.title].filter(Boolean).join(" · ") || e.id;

/** The provision a rule belongs to: that of its primary source element (else of any source element); null when its sources lie in
 *  none or are not part of the opened document. */
export function provisionOf(item: RuleItem, elements: Map<string, DocElement>): Provision | null {
  const sources = [...item.sources].sort((a, b) => Number((b.role ?? "primary") === "primary") - Number((a.role ?? "primary") === "primary"));
  for (const s of sources) {
    for (let e = elements.get(s.elementId); e; e = e.parent_id ? elements.get(e.parent_id) : undefined) {
      if (PROVISION_TYPES.has(e.type)) return { id: e.id, label: provisionLabel(e) };
    }
  }
  return null;
}

export type QueueOrder = "flagged" | "document";

/** The queue in the order the reviewer works it. "flagged": rules with a check flag first (they ask for a closer look), the
 *  rest in document order. "document": as extracted, which follows the document. Both are stable and drop nothing. A rule
 *  without a flag is not thereby verified; the order only says where attention goes first. */
export function queueOrder<T extends RuleItem>(items: T[], order: QueueOrder): T[] {
  return order === "document" ? items : [...items.filter((r) => r.checkFlags.length > 0), ...items.filter((r) => r.checkFlags.length === 0)];
}

/** How many of the document's provisions have at least one rule, or null when the opened document has no provisions of a known
 *  type. A count of where rules exist, not a measure of completeness: many provisions need no rule. */
export function provisionCoverage(elements: Map<string, DocElement>, items: RuleItem[]): { total: number; withRules: number } | null {
  const all = [...elements.values()].filter((e) => PROVISION_TYPES.has(e.type));
  if (all.length === 0) return null;
  const used = new Set(items.map((r) => provisionOf(r, elements)?.id).filter((id): id is string => !!id));
  return { total: all.length, withRules: used.size };
}
