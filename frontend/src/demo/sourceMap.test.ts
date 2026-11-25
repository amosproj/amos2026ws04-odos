// Sentence-to-element mapping, verification and the precision a highlight can honestly claim.
import { describe, expect, it } from "vitest";
import { sha256Hex } from "../sha256";
import { box, el, modelOf } from "../testing";
import type { Sentence } from "../types";
import { markOf, marksByElement } from "./reviewMarks";
import { toRuleItem } from "./ruleResults";
import { checkSentence, indexOf, planHighlights, toneOf } from "./sourceMap";

const TEXT1 = "Erster Satz. Zweiter Satz mit 3 m."; // two sentences
const TEXT2 = "Nur ein Satz.";
const range = (element_id: string, start: number, end: number, text: string) => ({ element_id, start, end, text_sha256: sha256Hex(text) });
const model = (sentences: Sentence[]) => modelOf([
  el("doc", "document", null, ["doc/p1"], { region: "document" }),
  el("doc/p1", "paragraph", "doc", ["doc/p1/a1", "doc/p1/a2"], { marker: "§ 1", pages: [1] }),
  el("doc/p1/a1", "absatz", "doc/p1", [], { marker: "(1)", content_text: TEXT1, original_text: `(1) ${TEXT1}`, pages: [2], provenance: [box(2, 60, 700, 500, 660)] }),
  el("doc/p1/a2", "absatz", "doc/p1", [], { marker: "(2)", content_text: TEXT2, original_text: `(2) ${TEXT2}`, pages: [3], provenance: [box(3, 60, 700, 500, 680)] }),
], { source: { num_pages: 5 }, sentences });
const S1: Sentence = { id: "doc/p1/a1/satz-1", unit_id: "doc/p1/a1", number: "1", ranges: [range("doc/p1/a1", 0, 12, TEXT1)] };
const S2: Sentence = { id: "doc/p1/a1/satz-2", unit_id: "doc/p1/a1", number: "2", ranges: [range("doc/p1/a1", 13, 34, TEXT1)] };
const WHOLE: Sentence = { id: "doc/p1/a2/satz-1", unit_id: "doc/p1/a2", number: "1", ranges: [range("doc/p1/a2", 0, 13, TEXT2)] };
const M = model([S1, S2, WHOLE]);

const rule = (id: string, type: string, elements: unknown[]) => toRuleItem({
  schemaVersion: "2.0", id, source: { citation: "§ 1", elements }, classification: { type, summary: id }, review: { status: "draft" },
});

describe("sha256Hex", () => {
  it("matches the standard vectors, including multi-byte text and block boundaries", () => {
    expect(sha256Hex("abc")).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    expect(sha256Hex("")).toBe("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    expect(sha256Hex("a".repeat(56))).toBe("b35439a4ac6f0948b6d6f9e3c6af0f5f590ce20f1bde7090ef7970686ec6738a"); // padding spills into a second block
    expect(sha256Hex("Außenwände § 6")).toBe("4cdebcfe46b455b11abba2dbc15aa19910f15faefea347fcdb12b721057ab853");
  });
});

describe("checkSentence", () => {
  const ix = indexOf(M);
  it("returns the exact text of a verified sentence", () => {
    const r = checkSentence(S2.id, "doc/p1/a1", ix);
    expect(r).toMatchObject({ ok: true, number: "2", text: "Zweiter Satz mit 3 m." });
  });
  it("refuses unknown sentences, sentences of another element, out-of-range offsets and texts that changed", () => {
    expect(checkSentence("doc/p1/a1/satz-9", "doc/p1/a1", ix)).toMatchObject({ ok: false, reason: expect.stringContaining("no such sentence") });
    expect(checkSentence(S1.id, "doc/p1/a2", ix)).toMatchObject({ ok: false, reason: expect.stringContaining("does not belong") });
    const outside = indexOf(model([{ ...S1, ranges: [range("doc/p1/a1", 0, 400, TEXT1)] }]));
    expect(checkSentence(S1.id, "doc/p1/a1", outside)).toMatchObject({ ok: false, reason: expect.stringContaining("outside") });
    const changed = indexOf(model([{ ...S1, ranges: [{ ...S1.ranges[0], text_sha256: sha256Hex("anderer Text") }] }]));
    expect(checkSentence(S1.id, "doc/p1/a1", changed)).toMatchObject({ ok: false, reason: expect.stringContaining("differs") });
    const ghost = indexOf(model([{ ...S1, ranges: [range("doc/none", 0, 3, "abc")] }]));
    expect(checkSentence(S1.id, "doc/p1/a1", ghost)).toMatchObject({ ok: false });
  });
  it("counts code points, as the document data does", () => {
    const emoji = "𝔸 Satz"; // one astral character: 2 UTF-16 units, 1 code point
    const m = modelOf([el("d", "document", null, ["d/x"], { region: "document" }), el("d/x", "absatz", "d", [], { content_text: emoji })],
      { sentences: [{ id: "d/x/satz-1", unit_id: "d/x", ranges: [range("d/x", 2, 6, emoji)] }] });
    expect(checkSentence("d/x/satz-1", "d/x", indexOf(m))).toMatchObject({ ok: true, text: "Satz" });
  });
});

describe("planHighlights", () => {
  it("highlights a cited element exactly when the rule cites it without a sentence", () => {
    const [h] = planHighlights(rule("r", "obligation", [{ elementId: "doc/p1/a1", role: "primary", pdfPages: [2] }]), M);
    expect(h).toMatchObject({ precision: "element", reason: null, sentences: [], page: 2, pages: [2], tone: "obligation", label: "Absatz (1)" });
    expect(h.boxes).toHaveLength(1);
  });

  it("never claims sentence precision for one sentence of several: whole element, named as a fallback", () => {
    const [h] = planHighlights(rule("r", "obligation", [{ elementId: "doc/p1/a1", sentenceId: S2.id, role: "primary" }]), M);
    expect(h.precision).toBe("fallback");
    expect(h.reason).toContain("Positions of single sentences are not in the document data");
    expect(h.sentences).toEqual([{ id: S2.id, number: "2", text: "Zweiter Satz mit 3 m." }]); // what is cited is still known exactly
    expect(h.sentenceLabel).toBe("Satz 2");
    expect(h.boxes).toHaveLength(1); // the element's own geometry, nothing narrower
  });

  it("is exact when the cited sentence is the element's entire text, or when all its sentences are cited", () => {
    expect(planHighlights(rule("r", "obligation", [{ elementId: "doc/p1/a2", sentenceId: WHOLE.id }]), M)[0].precision).toBe("element");
    const both = planHighlights(rule("r", "obligation", [{ elementId: "doc/p1/a1", sentenceId: S1.id }, { elementId: "doc/p1/a1", sentenceId: S2.id }]), M);
    expect(both).toHaveLength(1); // one entry per element
    expect(both[0]).toMatchObject({ precision: "element", sentenceLabel: "Satz 1, Satz 2" });
  });

  it("handles several elements on several pages, each with its own role, tone and precision", () => {
    const plan = planHighlights(rule("r", "permission", [
      { elementId: "doc/p1/a1", sentenceId: S1.id, role: "primary" }, { elementId: "doc/p1/a2", role: "definition" }, { elementId: "doc/p1", role: "cross_reference" },
    ]), M);
    expect(plan.map((h) => [h.elementId, h.tone, h.precision, h.page])).toEqual([
      ["doc/p1/a1", "permission", "fallback", 2], ["doc/p1/a2", "definition", "element", 3], ["doc/p1", "context", "element", 1],
    ]);
  });

  it("falls back, with the reason, when the sentence reference cannot be verified", () => {
    const [h] = planHighlights(rule("r", "obligation", [{ elementId: "doc/p1/a1", sentenceId: "doc/p1/a1/satz-7" }]), M);
    expect(h).toMatchObject({ precision: "fallback", sentences: [] });
    expect(h.reason).toContain("no such sentence");
  });

  it("falls back when the document data has no sentences at all", () => {
    const bare = modelOf(M.elements, { source: { num_pages: 5 } });
    const [h] = planHighlights(rule("r", "obligation", [{ elementId: "doc/p1/a1", sentenceId: S1.id }]), bare);
    expect(h.precision).toBe("fallback");
  });

  it("draws nothing for a passage that is not in the document, and drops page numbers that cannot exist", () => {
    const [gone, odd] = planHighlights(rule("r", "obligation", [{ elementId: "doc/none", pdfPages: [2] }, { elementId: "doc/p1/a1", pdfPages: [0, 99, 2.5] }]), M);
    expect(gone).toMatchObject({ precision: "missing", boxes: [], element: null });
    expect(odd.pages).toEqual([2]); // the element's own page, nothing invented
  });

  it("draws no coordinates for an element without geometry", () => {
    const m = modelOf([el("d", "document", null, ["d/x"], { region: "document" }), el("d/x", "absatz", "d", [], { pages: [1], provenance: [] })], { source: { num_pages: 1 } });
    expect(planHighlights(rule("r", "obligation", [{ elementId: "d/x" }]), m)[0].boxes).toEqual([]);
  });
});

describe("tones follow the record, never keywords", () => {
  it("maps classification and source role", () => {
    expect(toneOf("definition", "primary")).toBe("definition");
    expect(toneOf("obligation", undefined)).toBe("obligation");
    expect(toneOf("prohibition", "primary")).toBe("prohibition");
    expect(toneOf("conditional_requirement", "primary")).toBe("conditional");
    expect(toneOf("obligation", "definition")).toBe("definition");
    expect(toneOf("obligation", "cross_reference")).toBe("context");
    expect(toneOf(null, "primary")).toBe("obligation");
  });
});

describe("marksByElement", () => {
  const elements = new Map(M.elements.map((e) => [e.id, e]));
  const withState = (id: string, state: "accepted" | "pending" | "rejected", edited: boolean, sentenceId?: string) =>
    ({ ...rule(id, "obligation", [{ elementId: "doc/p1/a1", sentenceId }]), human: state, edited });

  it("keeps rules that share a sentence apart, each with its own state", () => {
    const a = withState("a", "accepted", false, S1.id), b = withState("b", "rejected", true, S1.id), c = withState("c", "pending", false, S1.id);
    const m = marksByElement([a, b, c], elements).get("doc/p1/a1")!;
    expect(m.rules.map((r) => [r.rule.id, r.mark.state, r.mark.edited])).toEqual([["a", "accepted", false], ["b", "rejected", true], ["c", "pending", false]]);
    expect(m.own).toEqual({ accepted: 1, pending: 1, rejected: 1, edited: 1, invalid: 0 });
  });

  it("counts an edited and accepted rule as accepted (edited is an extra attribute)", () => {
    expect(markOf(withState("a", "accepted", true))).toEqual({ state: "accepted", edited: true, invalid: false });
  });

  it("rolls the counts up to the containing elements, separately from their own", () => {
    const marks = marksByElement([withState("a", "accepted", false)], elements);
    expect(marks.get("doc/p1")!.own).toEqual({ accepted: 0, pending: 0, rejected: 0, edited: 0, invalid: 0 });
    expect(marks.get("doc/p1")!.below.accepted).toBe(1);
    expect(marks.get("doc")!.below.accepted).toBe(1);
  });

  it("shows nothing for rules without a persisted decision, and ignores elements that are not in the document", () => {
    const undecided = rule("u", "obligation", [{ elementId: "doc/p1/a1" }]); // human: null, no review storage
    expect(markOf(undecided)).toBeNull();
    const ghost = { ...rule("g", "obligation", [{ elementId: "doc/none" }]), human: "accepted" as const };
    expect(marksByElement([undecided, ghost], elements).size).toBe(0);
  });
});
