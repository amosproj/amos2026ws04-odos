import { describe, expect, it } from "vitest";
import { sha256Hex } from "../sha256";
import type { DocumentModel } from "../types";
import { exceptionElements, matchComponent } from "./componentSource";
import { toRuleItem } from "./ruleResults";

const ABS = "Vor den Außenwänden von Gebäuden sind Abstandsflächen freizuhalten. Satz 1 gilt nicht für Antennen im Außenbereich mit einer Höhe bis 50 m.";
const S1 = ABS.indexOf("Satz 1 gilt");
const NR1 = "Außenwände, die in einem Winkel von mehr als 75 Grad zueinander stehen,";
const NR2 = "Gebäude und andere bauliche Anlagen, die in den Abstandsflächen zulässig sind.";
const el = (id: string, type: string, number: string | null, parent: string | null, text: string) =>
  ({ id, type, number, marker: number, parent_id: parent, children_ids: [], content_text: text, original_text: text, pages: [10], region: "body" });
const range = (element_id: string, text: string, start: number, end: number) => ({ element_id, start, end, text_sha256: sha256Hex(text) });
const model = {
  source: { num_pages: 20 },
  elements: [el("p", "paragraph", "6", null, ""), el("p/a1", "absatz", "1", "p", ABS), el("p/a3", "absatz", "3", "p", "Abstandsflächen dürfen sich nicht überdecken; dies gilt nicht für"),
    el("p/a3/n1", "nummer", "1", "p/a3", NR1), el("p/a3/n2", "nummer", "2", "p/a3", NR2)],
  sentences: [
    { id: "p/a1/s1", unit_id: "p/a1", number: "1", ranges: [range("p/a1", ABS, 0, S1 - 1)], method: "t" },
    { id: "p/a1/s2", unit_id: "p/a1", number: "2", ranges: [range("p/a1", ABS, S1, Array.from(ABS).length)], method: "t" },
  ],
} as unknown as DocumentModel;
const rule = (elements: unknown[], extra: Record<string, unknown> = {}) =>
  toRuleItem({ schemaVersion: "2.0", id: "r", source: { elements }, classification: { type: "obligation" }, review: { status: "draft" }, ...extra });

describe("component sources", () => {
  it("finds the sentence a part's wording comes from, and says the highlight is element-level", () => {
    const r = rule([{ elementId: "p/a1", sentenceId: "p/a1/s1" }]);
    expect(matchComponent("Satz 1 gilt nicht für Antennen im Außenbereich mit einer Höhe von höchstens 50 m.", r, model))
      .toMatchObject({ citation: "§ 6 Abs. 1 Satz 2", precision: "element", page: 10 });
  });

  it("maps an exception to the numbered item it quotes, exactly", () => {
    const r = rule([{ elementId: "p/a3" }, { elementId: "p/a3/n1" }, { elementId: "p/a3/n2" }],
      { requirements: [{ kind: "boolean", fact: "x", value: true, description: "Abstandsflächen dürfen sich nicht überdecken." }],
        exceptions: [{ kind: "exception", description: "Das Verbot gilt nicht für Außenwände, die in einem Winkel von mehr als 75 Grad zueinander stehen." }] });
    expect(matchComponent("Das Verbot gilt nicht für Außenwände, die in einem Winkel von mehr als 75 Grad zueinander stehen.", r, model))
      .toMatchObject({ citation: "§ 6 Abs. 3 Nr. 1", precision: "exact" });
    expect([...exceptionElements(r, model)]).toEqual(["p/a3/n1"]);
  });

  it("gives no source when the wording is too short, unrelated or matches two passages alike", () => {
    const r = rule([{ elementId: "p/a3/n1" }, { elementId: "p/a3/n2" }]);
    expect(matchComponent("Abstandsflächen von Gebäuden", r, model)).toBeNull();
    expect(matchComponent("Es genügen Außenwände von mehr als 75 Grad.", r, model)).toBeNull(); // four shared words are not evidence enough
    expect(matchComponent("Brandwände müssen feuerbeständig sein und aus nichtbrennbaren Baustoffen bestehen.", r, model)).toBeNull();
    const twice = rule([{ elementId: "p/a3/n1" }, { elementId: "p/a3/n1" }]);
    expect(matchComponent(NR1, twice, model)?.citation).toBe("§ 6 Abs. 3 Nr. 1"); // the same passage twice is not ambiguous
  });

  it("never looks beyond the passages the rule cites", () => {
    expect(matchComponent(NR2, rule([{ elementId: "p/a3/n1" }]), model)).toBeNull();
  });
});
