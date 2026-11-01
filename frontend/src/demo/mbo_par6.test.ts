import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { bboxToRect, highlightsOf } from "../structure";
import type { DocumentModel } from "../types";
import { jsonSubtree, type DemoDocument } from "./fixtures";

// Generated from the partner's MBO PDF by `npm run demo:fixtures` and gitignored: skipped when not generated.
const DIR = resolve(__dirname, "../../public/demo/mbo");
const ID = "doc/teil-2/par-6/abs-1";

type Node = { id: string; text?: string; children?: Node[]; source?: { pages: number[]; sourceSpans: { itemRef: string; page: number }[] } };
const find = (n: Node): Node | undefined => (n.id === ID ? n : n.children?.map(find).find(Boolean));

describe.skipIf(!existsSync(DIR))("MBO § 6 (1) across pages 9 and 10", () => {
  const read = (f: string) => readFileSync(resolve(DIR, f), "utf8");
  const model = JSON.parse(read("structure.json")) as DocumentModel;
  const json = find(JSON.parse(read("teil-2_par-6.legal.json")) as Node)!;
  const xml = read("teil-2_par-6.akn.xml");
  const intro = xml.match(/<intro eId="part_2__art_6__para_1__intro">([\s\S]*?)<\/intro>/)![1];
  const ps = [...intro.matchAll(/<p [^>]*odos:src="([^"]*)"[^>]*>([^<]*)<\/p>/g)];

  it("is one Absatz text that runs on over the page break, with its Nummern kept apart", () => {
    expect(json.text).toMatch(/^1 Vor den Außenwänden von Gebäuden sind Abstandsflächen von oberirdischen Gebäuden freizuhalten\. 2 /);
    expect(json.text).toMatch(/4 Eine Abstandsfläche ist nicht erforderlich vor Außenwänden,$/);
    expect(json.children?.map((c) => c.id)).toEqual([`${ID}/nr-1`, `${ID}/nr-2`]);
    for (const c of json.children!) expect(json.text).not.toContain(c.text!.slice(0, 30));
  });

  it("carries the same text in JSON and XML, attributed to both source items", () => {
    expect(ps).toHaveLength(1);
    expect(ps[0][2]).toBe(json.text);
    expect(ps[0][1]).toBe("#/texts/144 #/texts/146");
    expect(json.source?.sourceSpans.map((s) => [s.itemRef, s.page])).toEqual([["#/texts/144", 9], ["#/texts/146", 10]]);
  });

  it("previews the complete Absatz 1 subtree exactly as it is in the downloaded JSON", () => {
    const manifest = JSON.parse(readFileSync(resolve(DIR, "../manifest.json"), "utf8")) as { documents: DemoDocument[] };
    expect(manifest.documents.find((d) => d.id === "mbo")!.example.previewId).toBe(ID);
    const raw = read("teil-2_par-6.legal.json");
    const preview = jsonSubtree(raw, ID)!;
    // the subtree's lines, verbatim, from the file: from its opening line to the matching closing brace
    const lines = raw.split("\n");
    const start = lines.findIndex((l) => l === `      "id": "${ID}",`) - 1;
    const indent = lines[start].length - lines[start].trimStart().length;
    const end = lines.findIndex((l, i) => i > start && (l === `${" ".repeat(indent)}}` || l === `${" ".repeat(indent)}},`));
    const verbatim = lines.slice(start, end + 1).map((l) => l.slice(indent)).join("\n").replace(/,$/, "");
    expect(preview).toBe(verbatim);
    const node = JSON.parse(preview) as Node & { children: Node[] };
    expect(node.text).toBe(json.text);
    expect(node.children.map((c) => c.id)).toEqual([`${ID}/nr-1`, `${ID}/nr-2`]);
    expect(node.source?.sourceSpans.map((s) => s.itemRef)).toEqual(["#/texts/144", "#/texts/146"]);
    expect(preview).toContain('"itemRef": "#/texts/147"');
    expect(preview).toContain('"itemRef": "#/texts/148"');
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
