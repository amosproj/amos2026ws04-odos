import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { highlightsOf } from "../structure";
import type { DocElement, DocumentModel } from "../types";
import type { DemoDocument } from "./fixtures";


const DEMO = resolve(__dirname, "../../public/demo");
const WORK: Record<string, string> = { mbo: "mbo", "eu-2023-1230": "eu" };
const TECHNICAL = /"(source|sourceSpans|bbox|bboxScope|charStart|charEnd|itemRef|numberSource|textSha256|markerStyle|coordinateSystem|sourceFile)"\s*:/;

type Node = { id: string; pages?: number[]; text?: string; children?: Node[] };
const walk = (n: Node): Node[] => [n, ...(n.children ?? []).flatMap(walk)];
const find = (nodes: Node[], id: string): Node | undefined => {
  for (const n of nodes) {
    const hit = n.id === id ? n : find(n.children ?? [], id);
    if (hit) return hit;
  }
  return undefined;
};
const docs = existsSync(resolve(DEMO, "manifest.json"))
  ? (JSON.parse(readFileSync(resolve(DEMO, "manifest.json"), "utf8")) as { documents: DemoDocument[] }).documents
  : [];

describe.skipIf(!docs.length).each(docs)("Legal JSON 2.0 excerpt of $id", (doc) => {
  const read = (f: string) => readFileSync(resolve(DEMO, f), "utf8");
  const text = () => read(doc.files.json);
  const model = () => JSON.parse(read(doc.files.structure)) as DocumentModel;

  it("is a Legal JSON 2.0 excerpt without technical provenance", () => {
    expect(text()).not.toMatch(TECHNICAL);
    expect(text()).not.toContain('"nativeType"');
    expect((JSON.parse(text()) as { germanType?: string }).germanType).toBeTruthy();
  });

  it("names document model elements only, with their text and pages, and each one can be highlighted in the PDF", () => {
    const byId = new Map<string, DocElement>(model().elements.map((e) => [e.id, e]));
    const nodes = walk(JSON.parse(text()) as Node);
    expect(nodes.length).toBeGreaterThan(3);
    for (const n of nodes) {
      const el = byId.get(n.id);
      expect(el, n.id).toBeDefined();
      expect(n.pages ?? []).toEqual(el!.pages);
      // the highlight comes from the model element (or, for a container without text of its own, its children)
      const located = (e: DocElement): boolean => highlightsOf(e).boxes.length > 0 || e.children_ids.some((c) => byId.has(c) && located(byId.get(c)!));
      expect(located(el!), n.id).toBe(true);
    }
  });

  const work = resolve(__dirname, "../../.demo-work", WORK[doc.id] ?? doc.id, "document.json");
  it.skipIf(!existsSync(work))("copies its nodes from the pipeline's document.json", () => {
    const legal = JSON.parse(readFileSync(work, "utf8")) as { schemaVersion: string; structure: Node[] };
    expect(legal.schemaVersion).toBe("2.0");
    const excerpt = JSON.parse(text()) as Node;
    for (const n of walk(excerpt)) {
      const { children: shown, ...fields } = n;
      const { children: all, ...original } = find(legal.structure, n.id)!;
      // same keys in the same order with the same values; only the one key is named differently
      const renamed = Object.entries(original).map(([k, v]) => [k === "nativeType" ? "germanType" : k, v]);
      expect(Object.entries(fields)).toEqual(renamed);
      // children are left out (off the path to the shown nodes), never reordered
      const kept = new Set((shown ?? []).map((c) => c.id));
      expect((all ?? []).map((c) => c.id).filter((id) => kept.has(id))).toEqual((shown ?? []).map((c) => c.id));
    }
  });
});
