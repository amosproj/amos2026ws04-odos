import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeAll, describe, expect, it } from "vitest";
import { bboxToRect, highlightsOf } from "../structure";
import type { DocumentModel } from "../types";

// Generated from the partner's MBO PDF by `npm run demo:fixtures` and gitignored: skipped when not generated.
const DIR = resolve(__dirname, "../../public/demo/mbo");
const ID = "doc/teil-2/par-6/abs-1";

type Node = {
  id: string; type: string; germanType?: string; number?: string; marker?: string; title?: string; text?: string; pages?: number[]; children?: Node[];
};
const find = (n: Node): Node | undefined => (n.id === ID ? n : n.children?.map(find).find(Boolean));

describe.skipIf(!existsSync(DIR))("MBO § 6 (1) across pages 9 and 10", () => {
  // loaded in beforeAll, not while collecting: vitest runs a skipped suite's body too, and the files may not exist
  const read = (f: string) => readFileSync(resolve(DIR, f), "utf8");
  let model: DocumentModel;
  let json: Node;
  beforeAll(() => {
    model = JSON.parse(read("structure.json")) as DocumentModel;
    json = find(JSON.parse(read("teil-2.legal.json")) as Node)!;
  });

  it("is one Absatz text that runs on over the page break, with its Nummern kept apart", () => {
    expect(json.text).toMatch(/^1 Vor den Außenwänden von Gebäuden sind Abstandsflächen von oberirdischen Gebäuden freizuhalten\. 2 /);
    expect(json.text).toMatch(/4 Eine Abstandsfläche ist nicht erforderlich vor Außenwänden,$/);
    expect(json.children?.map((c) => c.id)).toEqual([`${ID}/nr-1`, `${ID}/nr-2`]);
    for (const c of json.children!) expect(json.text).not.toContain(c.text!.slice(0, 30));
  });

  it("carries the model's text and pages in the JSON; the model element keeps both source items", () => {
    const el = model.elements.find((e) => e.id === ID)!;
    expect(json.text).toBe(el.content_text);
    expect(json.pages).toEqual([9, 10]);
    expect(el.source_refs).toEqual(["#/texts/144", "#/texts/146"]);
    expect(el.provenance.map((p) => p.page_no)).toEqual([9, 10]);
  });

  it("highlights the text on both pages", () => {
    const el = model.elements.find((e) => e.id === ID)!;
    expect(el.children_ids).toEqual([`${ID}/nr-1`, `${ID}/nr-2`]);
    expect(model.elements.some((e) => e.id === `${ID}/txt-1`)).toBe(false);
    const { boxes } = highlightsOf(el);
    expect(boxes.map((b) => b.page_no)).toEqual([9, 10]);
    for (const b of boxes) {
      const r = bboxToRect(b.bbox!, 842, 1);
      expect(r.width).toBeGreaterThan(0);
      expect(r.height).toBeGreaterThan(0);
      expect(r.top).toBeGreaterThanOrEqual(0);
    }
  });
});

describe.skipIf(!existsSync(resolve(DIR, "teil-2.legal.json")))("MBO Legal JSON 2.0 excerpt (teil-2.legal.json)", () => {
  const read = (f: string) => readFileSync(resolve(DIR, f), "utf8");
  let root: Node;
  beforeAll(() => {
    root = JSON.parse(read("teil-2.legal.json")) as Node;
  });
  const ids = (n: Node): unknown => [n.id, ...(n.children ?? []).map(ids)];
  const byId = (n: Node, id: string): Node | undefined => (n.id === id ? n : n.children?.map((c) => byId(c, id)).find(Boolean));

  it("starts with Zweiter Teil and holds exactly § 6 with Absatz 1 (Nummer 1 and 2) and Absatz 2", () => {
    expect([root.type, root.germanType, root.marker, root.title]).toEqual(["part", "Teil", "Zweiter Teil", "Das Grundstück und seine Bebauung"]);
    expect(ids(root)).toEqual(["doc/teil-2", ["doc/teil-2/par-6", [ID, [`${ID}/nr-1`], [`${ID}/nr-2`]], ["doc/teil-2/par-6/abs-2"]]]);
    const par = byId(root, "doc/teil-2/par-6")!;
    expect([par.type, par.germanType, par.number, par.marker]).toEqual(["section", "Paragraph", "6", "§ 6"]);
    expect([1, 2].map((n) => byId(root, `${ID}/nr-${n}`)!).map((x) => [x.type, x.germanType, x.number, x.marker])).toEqual([
      ["number", "Nummer", "1", "1."], ["number", "Nummer", "2", "2."],
    ]);
  });

  it("keeps the whole Absatz 1 text from page 9 to page 10", () => {
    const abs = byId(root, ID)!;
    expect(abs.pages).toEqual([9, 10]);
    expect(abs.text).toMatch(/^1 Vor den Außenwänden von Gebäuden .* 4 Eine Abstandsfläche ist nicht erforderlich vor Außenwänden,$/);
  });

  it("is Legal JSON 2.0 without technical provenance", () => {
    expect(read("teil-2.legal.json")).not.toMatch(/sourceSpans|bbox|charStart|charEnd|bboxScope|itemRef|markerStyle|omittedChildren|nativeType/);
  });
});
