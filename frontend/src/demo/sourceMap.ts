// Where in the document a rule comes from, as precisely as the document data proves. A rule's `source.elements[]` name an element
// and optionally a sentence; the document model holds the sentences as character ranges over element texts. Before a sentence is
// used its mapping is verified: the sentence exists, belongs to the element, every range lies inside the text it names and that
// text is the one the range was computed on (SHA-256). What the data does NOT hold is where a single sentence sits on the page:
// there are boxes for whole elements (and, for split items, exact lines without sentence offsets), never per sentence. So a cited
// sentence is highlighted exactly only when it is the element's entire text; otherwise the element's own highlight is the
// "fallback" and is named as such. No coordinate is estimated, interpolated or searched for.
import { highlightsOf, TYPE_LABELS } from "../structure";
import type { DocElement, DocumentModel, Provenance, Sentence } from "../types";
import { sha256Hex } from "../sha256";
import type { RuleItem } from "./ruleResults";
import { validPages } from "./ruleResults";

/** What a highlight means: the rule's classification (for the primary source) or the source's role. Never a review status. */
export type Tone = "definition" | "obligation" | "permission" | "prohibition" | "conditional" | "procedural" | "context" | "exception" | "condition";

export const TONE_LABEL: Record<Tone, string> = {
  definition: "Definition", obligation: "Obligation", permission: "Permission", prohibition: "Prohibition", conditional: "Conditional requirement",
  procedural: "Procedural requirement", context: "Related context", exception: "Exception / alternative", condition: "Condition",
};

const TYPE_TONE: Record<string, Tone> = {
  definition: "definition", obligation: "obligation", permission: "permission", prohibition: "prohibition",
  conditional_requirement: "conditional", procedural_requirement: "procedural",
};

/** The tone of one source of a rule: a definition source is a definition whatever the rule is; a context or cross-reference source
 *  is background; the primary source carries the rule's own classification (obligation when the record states none). */
export function toneOf(ruleType: string | null, role: string | undefined): Tone {
  if (role === "definition") return "definition";
  if (role === "context" || role === "cross_reference") return "context";
  return TYPE_TONE[ruleType ?? ""] ?? "obligation";
}

export interface ModelIndex {
  elements: Map<string, DocElement>;
  sentences: Map<string, Sentence>;
}
const indexes = new WeakMap<DocumentModel, ModelIndex>();
export function indexOf(model: DocumentModel): ModelIndex {
  let ix = indexes.get(model);
  if (!ix) {
    ix = { elements: new Map(model.elements.map((e) => [e.id, e])), sentences: new Map((model.sentences ?? []).map((s) => [s.id, s])) };
    indexes.set(model, ix);
  }
  return ix;
}

export type SentenceCheck =
  | { ok: true; id: string; number: string | null; /** the sentence's exact text, joined from its ranges */ text: string; /** its ranges inside this element */ ranges: Array<[number, number]> }
  | { ok: false; id: string; reason: string };

const cp = (text: string) => Array.from(text); // ranges count code points (Python str indices), not UTF-16 units

/** Verifies that `sentenceId` is a sentence of `elementId` whose ranges match the text they were computed on. */
export function checkSentence(sentenceId: string, elementId: string, ix: ModelIndex): SentenceCheck {
  const s = ix.sentences.get(sentenceId);
  if (!s) return { ok: false, id: sentenceId, reason: "The document data has no such sentence" };
  if (!s.ranges?.length) return { ok: false, id: sentenceId, reason: "The sentence has no text range" };
  if (s.unit_id !== elementId && !s.ranges.some((r) => r.element_id === elementId)) return { ok: false, id: sentenceId, reason: "The sentence does not belong to the cited element" };
  const parts: string[] = [];
  const own: Array<[number, number]> = [];
  for (const r of s.ranges) {
    const e = ix.elements.get(r.element_id);
    if (!e) return { ok: false, id: sentenceId, reason: "A text range names an element that is not in the document" };
    if (!Number.isInteger(r.start) || !Number.isInteger(r.end) || r.start < 0 || r.end <= r.start || r.end > cp(e.content_text).length) return { ok: false, id: sentenceId, reason: "A text range lies outside the element's text" };
    if (sha256Hex(e.content_text) !== r.text_sha256) return { ok: false, id: sentenceId, reason: "The element's text differs from the text the range was computed on" };
    parts.push(cp(e.content_text).slice(r.start, r.end).join(""));
    if (r.element_id === elementId) own.push([r.start, r.end]);
  }
  return { ok: true, id: sentenceId, number: s.number ?? null, text: parts.join(" "), ranges: own };
}

/** True when the ranges leave no visible text of the element uncovered (whitespace between them does not count). */
function coversElement(e: DocElement, ranges: Array<[number, number]>): boolean {
  const chars = cp(e.content_text);
  const covered = new Array<boolean>(chars.length).fill(false);
  for (const [a, b] of ranges) for (let i = a; i < b && i < chars.length; i++) covered[i] = true;
  return chars.every((c, i) => covered[i] || /\s/.test(c));
}

export type Precision =
  /** The highlight is exactly what the rule cites: the whole element, cited as a whole or through sentences that make up all of it. */
  | "element"
  /** The rule cites part of the element (a sentence), or its sentence reference could not be verified; the page positions of single
   *  sentences are not in the data, so the whole element is highlighted instead. `reason` says why. */
  | "fallback"
  /** The element is not in the opened document: nothing to draw. */
  | "missing";

export interface SourceHighlight {
  elementId: string;
  element: DocElement | null;
  role: string;
  tone: Tone;
  precision: Precision;
  reason: string | null;
  /** The verified sentences the rule cites in this element (exact text); empty when it cites the element as a whole. */
  sentences: Array<{ id: string; number: string | null; text: string }>;
  boxes: Provenance[];
  /** The boxes cover a whole Docling item that holds more than this element. */
  approximate: boolean;
  /** Pages of the passage: the rule's own page numbers when valid, else the element's. */
  pages: number[];
  /** First of them. */
  page: number | null;
  /** "Absatz (2)": what a person calls the element. */
  label: string;
  /** "Satz 2, Satz 3": the cited sentences, or "". */
  sentenceLabel: string;
}

const labelOf = (e: DocElement | null) => (e ? `${TYPE_LABELS[e.type] ?? e.type} ${e.marker ?? ""}`.trim() : "Unknown passage");
const sentenceNumber = (id: string, number: string | null) => (number ? `Satz ${number}` : id.split("/").pop() ?? id);

/** One entry per cited element, in the rule's order. */
export function planHighlights(rule: RuleItem, model: DocumentModel): SourceHighlight[] {
  const ix = indexOf(model);
  const order: string[] = [];
  const byElement = new Map<string, RuleItem["sources"]>();
  for (const s of rule.sources) {
    if (!byElement.has(s.elementId)) { byElement.set(s.elementId, []); order.push(s.elementId); }
    byElement.get(s.elementId)!.push(s);
  }
  return order.map((elementId): SourceHighlight => {
    const refs = byElement.get(elementId)!;
    const role = (refs.find((r) => (r.role ?? "primary") === "primary") ?? refs[0]).role ?? "primary";
    const tone = toneOf(rule.type, role);
    const e = ix.elements.get(elementId) ?? null;
    const own = validPages(refs.flatMap((r) => r.pdfPages), model.source.num_pages);
    const pages = own.length ? own : validPages(e?.pages ?? [], model.source.num_pages);
    const base = { elementId, element: e, role, tone, pages, page: pages[0] ?? null, label: labelOf(e) };
    if (!e) return { ...base, precision: "missing", reason: "The passage is not part of the opened document", sentences: [], boxes: [], approximate: false, sentenceLabel: "" };
    const geometry = highlightsOf(e);
    const ids = [...new Set(refs.map((r) => r.sentenceId).filter((x): x is string => !!x))];
    if (ids.length === 0) return { ...base, precision: "element", reason: null, sentences: [], boxes: geometry.boxes, approximate: geometry.approximate, sentenceLabel: "" };
    const checks = ids.map((id) => checkSentence(id, elementId, ix));
    const good = checks.filter((c): c is Extract<SentenceCheck, { ok: true }> => c.ok);
    const bad = checks.find((c) => !c.ok);
    const sentences = good.map((c) => ({ id: c.id, number: c.number, text: c.text }));
    const sentenceLabel = good.map((c) => sentenceNumber(c.id, c.number)).join(", ");
    if (bad && !bad.ok) return { ...base, precision: "fallback", reason: `${bad.reason}; the whole element is shown`, sentences, boxes: geometry.boxes, approximate: geometry.approximate, sentenceLabel };
    if (coversElement(e, good.flatMap((c) => c.ranges))) return { ...base, precision: "element", reason: null, sentences, boxes: geometry.boxes, approximate: geometry.approximate, sentenceLabel };
    return { ...base, precision: "fallback", reason: "Positions of single sentences are not in the document data; the whole element is shown", sentences, boxes: geometry.boxes, approximate: geometry.approximate, sentenceLabel };
  });
}
