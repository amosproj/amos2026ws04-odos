import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ElementDetail } from "./components/ElementDetail";
import { buildTree, clickAction, hasPartialBox, highlightsOf } from "./structure";
import type { DocElement, DocumentModel, TocEntry } from "./types";

const el = (id: string, type: string, region: DocElement["region"], parent: string | null, kids: string[], text = ""): DocElement => ({
  id, type, region, parent_id: parent, children_ids: kids, number: null, marker: null, title: null, original_text: text,
  content_text: text, table: null, source_refs: [], docling_label: null, pages: [3], provenance: [], uncertain: false, uncertainty_reasons: [],
});

const entry = (id: string, marker: string, title: string, target: string | null, status: TocEntry["status"] = "linked"): TocEntry => ({
  id, kind: "paragraph", marker, number: null, title, level: 5, source_element_ids: ["doc/toc/entry-1"], target_id: target,
  candidate_ids: target ? [] : ["doc/teil-1/par-14"], status, evidence: target ? "agree" : "title differs",
});

// raw Docling TOC item: merged and in Docling's (wrong) order; the normalized entries are in printed order
const model = {
  model_version: "0.1", source: { filename: "x.pdf", docling_version: null, docling_json_sha256: "0", num_pages: 3 },
  metadata: { title: null, short_title: null, ausfertigungsdatum: null, stand: null, vollzitat: null },
  root_id: "doc", furniture: [], warnings: [],
  elements: [
    el("doc", "document", "document", null, ["doc/toc", "doc/teil-3"]),
    el("doc/toc", "toc", "toc", "doc", ["doc/toc/entry-1"], "Inhaltsverzeichnis"),
    el("doc/toc/entry-1", "toc_entry", "toc", "doc/toc", [], "§ 12 Grundregeln § 16 Beauftragte Fünfter Abschnitt Beispielanforderungen"),
    el("doc/teil-3", "teil", "body", "doc", ["doc/teil-3/abschnitt-7"]),
    el("doc/teil-3/abschnitt-7", "abschnitt", "body", "doc/teil-3", []),
  ],
  toc_entries: [
    entry("toc/abschnitt-7", "Fünfter Abschnitt", "Beispielanforderungen", "doc/teil-3/abschnitt-7"),
    entry("toc/paragraph-12", "§ 12", "Grundregeln", "doc/teil-4/par-12"),
    entry("toc/paragraph-14", "§ 14", "Geltungsdauer der Genehmigung", null, "candidate"),
  ],
} as DocumentModel;

describe("normalized table of contents", () => {
  const { roots, byKey } = buildTree(model);
  const toc = roots.find((r) => r.key === "doc/toc")!;

  it("lists the normalized entries in printed order and keeps the raw items in their own group", () => {
    expect(toc.children.map((c) => c.label)).toEqual([
      "Fünfter Abschnitt Beispielanforderungen", "§ 12 Grundregeln", "§ 14 Geltungsdauer der Genehmigung",
      "Raw Docling TOC items (1)",
    ]);
    const raw = toc.children[3];
    expect(raw.children.map((c) => c.key)).toEqual(["doc/toc/entry-1"]);
    expect(raw.children[0].element?.content_text).toContain("§ 12 Grundregeln § 16"); // raw text untouched, still editable
  });

  it("navigates from a confirmed entry to its body element, and not from an unconfirmed one", () => {
    expect(clickAction(byKey.get("tocentry:toc/abschnitt-7")!)).toEqual({ select: "doc/teil-3/abschnitt-7" });
    expect(clickAction(byKey.get("tocentry:toc/paragraph-14")!)).toBeNull(); // candidate: no proven target
    expect(clickAction(byKey.get("doc/toc/entry-1")!)).toEqual({ select: "doc/toc/entry-1" }); // raw item: review as before
    expect(clickAction(byKey.get("group:toc-raw")!)).toEqual({ toggle: "group:toc-raw" });
  });

  it("leaves models without normalized entries as before", () => {
    const { roots: plain } = buildTree({ ...model, toc_entries: undefined });
    expect(plain.find((r) => r.key === "doc/toc")!.children.map((c) => c.key)).toEqual(["doc/toc/entry-1"]);
  });
});

describe("exact highlights", () => {
  const partial: DocElement = {
    ...el("doc/chp-7/art-47/para-2", "article_paragraph", "body", null, [], "Die Befugnis"),
    provenance: [{ page_no: 36, bbox: { l: 68, t: 229, r: 528, b: 179, coord_origin: "BOTTOMLEFT" }, charspan: null }],
    source_spans: [{ ref: "#/texts/746", start: 0, end: 566, page_no: 36, bbox: null, bbox_scope: "docling_item" }],
  };
  const exact = [
    { page_no: 36, bbox: { l: 69, t: 230, r: 528, b: 220, coord_origin: "BOTTOMLEFT" }, charspan: null },
    { page_no: 36, bbox: { l: 68, t: 176, r: 107, b: 169, coord_origin: "BOTTOMLEFT" }, charspan: null },
  ];

  it("draws the proven line rectangles instead of the item box and drops the approximate marking", () => {
    expect(highlightsOf({ ...partial, highlight_boxes: exact })).toEqual({ boxes: exact, approximate: false });
    expect(hasPartialBox({ ...partial, highlight_boxes: exact })).toBe(false);
    const html = renderToStaticMarkup(<ElementDetail element={{ ...partial, highlight_boxes: exact }} warnings={[]} eId={null} onGoToPage={() => {}} />);
    expect(html).toContain("Exact highlight: 2 line rectangle(s)");
    expect(html).not.toContain("Approximate highlight");
  });

  it("keeps the approximate fallback where no geometry was proven", () => {
    expect(highlightsOf(partial)).toEqual({ boxes: partial.provenance, approximate: true });
    expect(renderToStaticMarkup(<ElementDetail element={partial} warnings={[]} eId={null} onGoToPage={() => {}} />)).toContain("Approximate highlight");
  });
});
