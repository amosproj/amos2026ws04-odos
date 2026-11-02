import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeAll, describe, expect, it } from "vitest";
import { bboxToRect, highlightsOf } from "../structure";
import type { DocumentModel } from "../types";
import { jsonSubtree, type DemoDocument, type PipelineDetails } from "./fixtures";

// Generated from the partner's MBO PDF by `npm run demo:fixtures` and gitignored: skipped when not generated.
const DIR = resolve(__dirname, "../../public/demo/mbo");
const ID = "doc/teil-2/par-6/abs-1";

type Node = { id: string; text?: string; children?: Node[]; source?: { pages: number[]; sourceSpans: { itemRef: string; page: number }[] } };
const find = (n: Node): Node | undefined => (n.id === ID ? n : n.children?.map(find).find(Boolean));

describe.skipIf(!existsSync(DIR))("MBO § 6 (1) across pages 9 and 10", () => {
  // loaded in beforeAll, not while collecting: vitest runs a skipped suite's body too, and the files may not exist
  const read = (f: string) => readFileSync(resolve(DIR, f), "utf8");
  let model: DocumentModel;
  let json: Node;
  beforeAll(() => {
    model = JSON.parse(read("structure.json")) as DocumentModel;
    json = find(JSON.parse(read("teil-2_par-6.legal.json")) as Node)!;
  });

  it("is one Absatz text that runs on over the page break, with its Nummern kept apart", () => {
    expect(json.text).toMatch(/^1 Vor den Außenwänden von Gebäuden sind Abstandsflächen von oberirdischen Gebäuden freizuhalten\. 2 /);
    expect(json.text).toMatch(/4 Eine Abstandsfläche ist nicht erforderlich vor Außenwänden,$/);
    expect(json.children?.map((c) => c.id)).toEqual([`${ID}/nr-1`, `${ID}/nr-2`]);
    for (const c of json.children!) expect(json.text).not.toContain(c.text!.slice(0, 30));
  });

  it("carries the model's text in the JSON, attributed to both source items", () => {
    const el = model.elements.find((e) => e.id === ID)!;
    expect(json.text).toBe(el.content_text);
    expect(el.source_refs).toEqual(["#/texts/144", "#/texts/146"]);
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

describe.skipIf(!existsSync(resolve(DIR, "pipeline.json")))("MBO § 6 (1) processing details (pipeline.json)", () => {
  const read = (f: string) => readFileSync(resolve(DIR, f), "utf8");
  let p: PipelineDetails;
  let model: DocumentModel;
  beforeAll(() => {
    p = JSON.parse(read("pipeline.json")) as PipelineDetails;
    model = JSON.parse(read("structure.json")) as DocumentModel;
  });

  it("holds the Docling items of § 6 (1), including the page footer Docling put between pages 9 and 10", () => {
    expect(p.focusId).toBe(ID);
    expect(p.docling.items.map((t) => [t.self_ref, t.label, (t.prov ?? []).map((v) => v.page_no)])).toEqual([
      ["#/texts/143", "section_header", [9]], ["#/texts/144", "list_item", [9]], ["#/texts/145", "page_footer", [9]],
      ["#/texts/146", "text", [10]], ["#/texts/147", "list_item", [10]], ["#/texts/148", "list_item", [10]],
    ]);
    // the footer is page furniture: no structure element is built from it
    expect(p.elements.flatMap((e) => e.source_refs)).not.toContain("#/texts/145");
    expect(model.elements.flatMap((e) => e.source_refs)).not.toContain("#/texts/145");
  });

  it("matches the displayed structure element by element (same ids, links, sources and boxes)", () => {
    for (const e of p.elements) {
      const shown = model.elements.find((x) => x.id === e.id)!;
      for (const k of ["parent_id", "children_ids", "marker", "content_text", "source_refs", "pages", "provenance"] as const) expect(e[k]).toEqual(shown[k]);
    }
    const abs = p.elements.find((e) => e.id === ID)!;
    expect(abs.children_ids).toEqual([`${ID}/nr-1`, `${ID}/nr-2`]);
    expect(abs.hygiene_flags).toContain("page_break_continuation_merged_confirmed");
  });

  it("joins the Absatz text from the two Docling items around the page break", () => {
    const orig = (ref: string) => p.docling.items.find((t) => t.self_ref === ref)!.orig!;
    const abs = p.elements.find((e) => e.id === ID)!;
    expect(abs.original_text.startsWith(orig("#/texts/144"))).toBe(true);
    expect(abs.original_text.endsWith(orig("#/texts/146"))).toBe(true);
    expect(p.elements.find((e) => e.id === `${ID}/nr-1`)!.original_text).toBe(orig("#/texts/147"));
    expect(p.elements.find((e) => e.id === `${ID}/nr-2`)!.original_text).toBe(orig("#/texts/148"));
  });
});

describe.skipIf(!existsSync(resolve(DIR, "teil-2.legal-view.json")))("MBO simplified Legal JSON (teil-2.legal-view.json)", () => {
  const read = (f: string) => readFileSync(resolve(DIR, f), "utf8");
  type ViewNode = {
    id: string; type: string; nativeType?: string; number?: string; marker?: string; title?: string; text?: string; pages?: number[];
    omittedChildren?: number; children?: ViewNode[];
  };
  let root: ViewNode;
  let excerpt: ViewNode;
  beforeAll(() => {
    root = (JSON.parse(read("teil-2.legal-view.json")) as { structure: ViewNode[] }).structure[0];
    excerpt = JSON.parse(read("teil-2_par-6.legal.json")) as ViewNode;
  });
  const ids = (n: ViewNode): unknown => [n.id, ...(n.children ?? []).map(ids)];

  it("starts with Zweiter Teil and holds exactly § 6 with Absatz 1 (Nummer 1 and 2) and Absatz 2", () => {
    expect([root.marker, root.title]).toEqual(["Zweiter Teil", "Das Grundstück und seine Bebauung"]);
    expect(ids(root)).toEqual(["doc/teil-2", ["doc/teil-2/par-6", [ID, [`${ID}/nr-1`], [`${ID}/nr-2`]], ["doc/teil-2/par-6/abs-2"]]]);
    expect(root.omittedChildren).toBe(4); // §§ 4, 5, 7, 8
    expect(root.children![0].omittedChildren).toBe(6); // Absätze 3 to 8
  });

  it("copies ids, types, numbering, text and pages unchanged from the Legal JSON 1.1 excerpt", () => {
    const byId = (n: ViewNode, id: string): ViewNode | undefined => (n.id === id ? n : n.children?.map((c) => byId(c, id)).find(Boolean));
    for (const id of ["doc/teil-2/par-6", ID, `${ID}/nr-1`, `${ID}/nr-2`, "doc/teil-2/par-6/abs-2"]) {
      const v = byId(root, id)!;
      const e = byId(excerpt, id)! as ViewNode & { source: { pages: number[] } };
      expect([v.type, v.nativeType, v.number, v.marker, v.title, v.text]).toEqual([e.type, e.nativeType, e.number, e.marker, e.title, e.text]);
      expect(v.pages).toEqual(e.source.pages);
    }
    const abs = byId(root, ID)!;
    expect(abs.pages).toEqual([9, 10]);
    expect(abs.text).toMatch(/^1 Vor den Außenwänden von Gebäuden .* 4 Eine Abstandsfläche ist nicht erforderlich vor Außenwänden,$/);
  });

  it("leaves out the technical provenance", () => {
    expect(read("teil-2.legal-view.json")).not.toMatch(/sourceSpans|bbox|charStart|charEnd|bboxScope|itemRef/);
  });
});
