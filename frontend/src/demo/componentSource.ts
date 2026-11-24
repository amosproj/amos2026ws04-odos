// Where one part of a rule (a requirement, an exception, a definition, a target …) comes from. Rule JSON 2.0 records sources only
// for the rule as a whole, so a part's passage is established by verified text matching: the part's own wording (its
// `description`, or a definition's text) is compared with each passage the rule cites — the verified sentences of a cited
// element (see `checkSentence`), or the whole text of a cited element that has no sentences. A passage is used only when it
// clearly matches and no other passage comes close; otherwise there is no part-level source and the rule's own citation applies.
// The order of the parts is never used.
import { createContext } from "react";
import type { DocElement, DocumentModel } from "../types";
import { checkSentence, indexOf, type ModelIndex } from "./sourceMap";
import type { RuleItem } from "./ruleResults";
import { validPages } from "./ruleResults";

export interface ComponentSource {
  elementId: string;
  sentenceId: string | null;
  /** "§ 6 Abs. 1 Satz 3", built from the document's own structure. */
  citation: string;
  page: number | null;
  /** "exact": the matched passage is the element's whole text, so its highlight is exactly it. "element": the passage is one
   *  sentence of a longer element; the page has no sentence positions, so the whole element is highlighted. */
  precision: "exact" | "element";
  /** How much of the shorter text the other one contains (0–1). */
  score: number;
}

const MIN_TOKENS = 4;
/** Shared content words needed as evidence at all: a short phrase ("Es genügt eine Tiefe von 3 m.") fits several sentences. */
const MIN_SHARED = 5;
const MIN_SCORE = 0.6;
const MIN_MARGIN = 0.15;

/** Content words (four letters or more, so articles and short function words do not count) and every number, case-folded. */
export function tokens(text: string): Set<string> {
  return new Set((text.normalize("NFC").toLowerCase().match(/[\p{L}\p{N}]+(?:[.,]\d+)*/gu) ?? []).filter((w) => w.length >= 4 || /\d/.test(w)));
}

function overlap(a: Set<string>, b: Set<string>): number {
  if (a.size < MIN_TOKENS || b.size < MIN_TOKENS) return 0;
  let shared = 0;
  for (const w of a) if (b.has(w)) shared++;
  if (shared < MIN_SHARED) return 0;
  return Math.max(shared / a.size, shared / b.size);
}

const CITE: Record<string, (n: string) => string> = {
  paragraph: (n) => `§ ${n}`, article: (n) => `Art. ${n}`, absatz: (n) => `Abs. ${n}`, article_paragraph: (n) => `Abs. ${n}`,
  nummer: (n) => `Nr. ${n}`, buchstabe: (n) => `Buchst. ${n}`, point: (n) => `Buchst. ${n}`, anlage: (n) => `Anlage ${n}`,
};

/** The element's citation from its own ancestry, with the sentence after the paragraph level ("§ 6 Abs. 8 Satz 2"). */
export function citationOf(e: DocElement, ix: ModelIndex, sentence: string | null): string {
  const parts: string[] = [];
  for (let x: DocElement | undefined = e; x; x = x.parent_id ? ix.elements.get(x.parent_id) : undefined) {
    const f = CITE[x.type];
    if (f && x.number) parts.unshift(f(x.number));
  }
  if (sentence) {
    let after = -1;
    parts.forEach((p, i) => { if (/^(§|Art\.|Abs\.)/.test(p)) after = i; });
    parts.splice(after + 1 || parts.length, 0, `Satz ${sentence}`);
  }
  return parts.join(" ") || (e.marker ?? e.id);
}

interface Candidate { elementId: string; sentenceId: string | null; number: string | null; text: string; whole: boolean; words: Set<string> }

const candidatesCache = new WeakMap<RuleItem, Candidate[]>();
function candidates(rule: RuleItem, model: DocumentModel): Candidate[] {
  const hit = candidatesCache.get(rule);
  if (hit) return hit;
  const ix = indexOf(model);
  const out: Candidate[] = [];
  for (const elementId of new Set(rule.sources.map((s) => s.elementId))) {
    const e = ix.elements.get(elementId);
    if (!e) continue;
    const own = (model.sentences ?? []).filter((s) => s.unit_id === elementId || s.ranges?.some((r) => r.element_id === elementId));
    const checked = own.map((s) => checkSentence(s.id, elementId, ix)).filter((c) => c.ok);
    if (checked.length === 0) {
      out.push({ elementId, sentenceId: null, number: null, text: e.content_text, whole: true, words: tokens(e.content_text) });
      continue;
    }
    const chars = Array.from(e.content_text);
    for (const c of checked) {
      if (!c.ok || c.ranges.length === 0) continue;
      // a sentence may run over several elements (an intro and its numbered items): only its part in this element counts here
      const text = c.ranges.map(([a, b]) => chars.slice(a, b).join("")).join(" ");
      const whole = text.replace(/\s+/g, " ").trim() === e.content_text.replace(/\s+/g, " ").trim();
      out.push({ elementId, sentenceId: c.id, number: c.number, text, whole, words: tokens(text) });
    }
  }
  candidatesCache.set(rule, out);
  return out;
}

/** The passage a part of the rule comes from, or null when no cited passage clearly and uniquely matches its wording. */
export function matchComponent(text: string | null | undefined, rule: RuleItem, model: DocumentModel): ComponentSource | null {
  if (!text) return null;
  const words = tokens(text);
  if (words.size < MIN_TOKENS) return null;
  const scored = candidates(rule, model).map((c) => ({ c, score: overlap(words, c.words) })).sort((a, b) => b.score - a.score);
  const [best, second] = scored;
  if (!best || best.score < MIN_SCORE) return null;
  if (second && best.score - second.score < MIN_MARGIN && !(second.c.elementId === best.c.elementId && second.c.sentenceId === best.c.sentenceId)) return null;
  const ix = indexOf(model);
  const e = ix.elements.get(best.c.elementId)!;
  const pages = validPages(e.pages ?? [], model.source.num_pages);
  return {
    elementId: best.c.elementId, sentenceId: best.c.sentenceId, citation: citationOf(e, ix, best.c.number),
    page: pages[0] ?? null, precision: best.c.whole ? "exact" : "element", score: best.score,
  };
}

/** Elements whose whole text is one exception (or alternative) of the rule and nothing of its main requirement: those passages
 *  can be coloured as exceptions in the PDF. Only exact matches count; a sentence inside a longer element keeps the rule's colour. */
export function exceptionElements(rule: RuleItem, model: DocumentModel): Set<string> {
  const rec = rule.effective;
  const descs = (key: string) => (Array.isArray(rec[key]) ? (rec[key] as unknown[]) : [])
    .map((x) => (x && typeof x === "object" ? (x as Record<string, unknown>).description : null))
    .filter((d): d is string => typeof d === "string");
  const exact = (texts: string[]) => texts.map((t) => matchComponent(t, rule, model)).filter((m): m is ComponentSource => !!m && m.precision === "exact").map((m) => m.elementId);
  const main = new Set(exact(descs("requirements")));
  return new Set(exact(descs("exceptions")).filter((id) => !main.has(id)));
}

export interface ComponentNav {
  resolve: (text: string | null | undefined) => ComponentSource | null;
  go: (source: ComponentSource) => void;
  /** The part's passage the PDF is focused on, if any. */
  focused: ComponentSource | null;
}
export const ComponentNavContext = createContext<ComponentNav | null>(null);
