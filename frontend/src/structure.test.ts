import { describe, expect, it } from "vitest";
import { TYPE_LABELS, bboxToRect, buildTree, clickAction, firstPage, hasPartialBox, highlightsOf, rectsOnPage, visibleKeys } from "./structure";
import { box, el, modelOf } from "./testing";
import type { TocEntry } from "./types";

const model = modelOf([
  el("doc", "document", null, ["f1", "t1"], { region: "document" }),
  el("f1", "front_matter", "doc", [], { region: "front" }),
  el("t1", "teil", "doc", ["p1"], { marker: "Teil 1", title: "Allgemeines" }),
  el("p1", "paragraph", "t1", ["a1"], { marker: "§ 1", title: "Zweck" }),
  el("a1", "absatz", "p1", [], { marker: "(1)", original_text: "Dieses Gesetz regelt den Zweck." }),
]);

describe("hierarchical structure", () => {
  it("keeps the model hierarchy and groups front matter", () => {
    const { roots, byKey, parentOf } = buildTree(model);
    expect(roots.map((r) => r.label)).toEqual(["Front matter (1)", "Teil 1 Allgemeines"]);
    expect(byKey.get("t1")!.children[0].children[0].key).toBe("a1");
    expect(parentOf.get("a1")).toBe("p1");
    expect(parentOf.get("f1")).toBe("group:front");
  });
  it("searches the text and keeps the ancestors of every hit", () => {
    const { byKey, parentOf } = buildTree(model);
    expect([...visibleKeys(byKey, parentOf, " zweck ")!].sort()).toEqual(["a1", "p1", "t1"]);
    expect(visibleKeys(byKey, parentOf, "gibt es nicht")!.size).toBe(0);
    expect(visibleKeys(byKey, parentOf, "  ")).toBeNull();
  });
  it("selects an element on click and toggles groups", () => {
    const { byKey } = buildTree(model);
    expect(clickAction(byKey.get("p1")!)).toEqual({ select: "p1" });
    expect(clickAction(byKey.get("group:front")!)).toEqual({ toggle: "group:front" });
  });
  it("has a label for every German and EU element type", () => {
    for (const t of ["teil", "abschnitt", "paragraph", "absatz", "nummer", "buchstabe", "recital", "chapter", "article", "article_paragraph",
      "numbered_point", "point", "subpoint", "annex", "annex_part", "annex_heading", "citation", "footnote", "doc_title", "preamble"])
      expect(TYPE_LABELS[t], t).toBeTruthy();
    expect(TYPE_LABELS.subpoint).toBe("Sub-point (i)");
  });
  it("builds an EU tree in model order and labels recitals and articles with marker and title", () => {
    const eu = modelOf([
      el("doc", "document", null, ["pre", "c1"], { region: "document" }),
      el("pre", "preamble", "doc", ["r1"], { region: "preamble", original_text: "", content_text: "" }),
      el("r1", "recital", "pre", [], { region: "preamble", marker: "(1)", content_text: "Erwägung", original_text: "(1) Erwägung" }),
      el("c1", "chapter", "doc", ["a1"], { marker: "KAPITEL I", title: "ALLGEMEINE BESTIMMUNGEN" }),
      el("a1", "article", "c1", [], { marker: "Artikel 1", title: "Gegenstand" }),
    ], { profile: "eu_legislation" });
    const { roots, byKey } = buildTree(eu);
    expect(roots.map((r) => r.key)).toEqual(["pre", "c1"]);
    expect(roots[0].label).toBe("Preamble");
    expect(byKey.get("r1")!.label).toBe("(1) Erwägung");
    expect(byKey.get("a1")!.label).toBe("Artikel 1 Gegenstand");
  });
});

describe("normalized table of contents", () => {
  const entry = (id: string, marker: string, title: string, target: string | null, status: TocEntry["status"] = "linked"): TocEntry =>
    ({ id, marker, title, target_id: target, status, evidence: target ? "agree" : "title differs" });
  // raw Docling TOC item: merged and in Docling's (wrong) order; the normalized entries are in printed order
  const m = modelOf([
    el("doc", "document", null, ["doc/toc", "doc/teil-3"], { region: "document" }),
    el("doc/toc", "toc", "doc", ["doc/toc/entry-1"], { region: "toc", original_text: "Inhaltsverzeichnis" }),
    el("doc/toc/entry-1", "toc_entry", "doc/toc", [], { region: "toc", original_text: "§ 12 Grundregeln § 16 Beauftragte" }),
    el("doc/teil-3", "teil", "doc", ["doc/teil-3/abschnitt-7"]),
    el("doc/teil-3/abschnitt-7", "abschnitt", "doc/teil-3", []),
  ], {
    toc_entries: [
      entry("toc/abschnitt-7", "Fünfter Abschnitt", "Beispielanforderungen", "doc/teil-3/abschnitt-7"),
      entry("toc/paragraph-14", "§ 14", "Geltungsdauer der Genehmigung", null, "candidate"),
    ],
  });
  const { roots, byKey } = buildTree(m);
  const toc = roots.find((r) => r.key === "doc/toc")!;

  it("lists the normalized entries in printed order and keeps the raw items in their own group", () => {
    expect(toc.children.map((c) => c.label)).toEqual([
      "Fünfter Abschnitt Beispielanforderungen", "§ 14 Geltungsdauer der Genehmigung", "Raw Docling TOC items (1)",
    ]);
    expect(toc.children[2].children.map((c) => c.key)).toEqual(["doc/toc/entry-1"]);
  });
  it("navigates from a confirmed entry to its body element, and not from an unconfirmed one", () => {
    expect(clickAction(byKey.get("tocentry:toc/abschnitt-7")!)).toEqual({ select: "doc/teil-3/abschnitt-7" });
    expect(clickAction(byKey.get("tocentry:toc/paragraph-14")!)).toBeNull(); // candidate: no proven target
    expect(clickAction(byKey.get("group:toc-raw")!)).toEqual({ toggle: "group:toc-raw" });
  });
  it("leaves models without normalized entries as they are", () => {
    const plain = buildTree({ ...m, toc_entries: undefined }).roots.find((r) => r.key === "doc/toc")!;
    expect(plain.children.map((c) => c.key)).toEqual(["doc/toc/entry-1"]);
  });
});

describe("PDF highlights and navigation", () => {
  it("flips BOTTOMLEFT coordinates", () => {
    expect(bboxToRect({ l: 50, t: 700, r: 150, b: 680, coord_origin: "BOTTOMLEFT" }, 800, 2)).toEqual({ left: 100, top: 200, width: 200, height: 40 });
  });
  it("keeps TOPLEFT coordinates", () => {
    expect(bboxToRect({ l: 10, t: 20, r: 30, b: 60, coord_origin: "TOPLEFT" }, 800, 1)).toEqual({ left: 10, top: 20, width: 20, height: 40 });
  });

  const partial = el("p", "article_paragraph", null, [], {
    provenance: [box(36, 68, 229, 528, 179)],
    source_spans: [{ ref: "#/texts/746", start: 0, end: 566, page_no: 36, bbox: null, bbox_scope: "docling_item" }],
  });
  const exact = [box(36, 69, 230, 528, 220), box(36, 68, 176, 107, 169)];

  it("draws the proven line rectangles instead of the item box and drops the approximate marking", () => {
    expect(highlightsOf({ ...partial, highlight_boxes: exact })).toEqual({ boxes: exact, approximate: false });
    expect(hasPartialBox({ ...partial, highlight_boxes: exact })).toBe(false);
  });
  it("keeps the approximate fallback where no geometry was proven", () => {
    expect(highlightsOf(partial)).toEqual({ boxes: partial.provenance, approximate: true });
    expect(hasPartialBox(partial)).toBe(true);
    expect(highlightsOf(null)).toEqual({ boxes: [], approximate: false });
  });
  it("follows a text that runs over a page break: both boxes belong to the element, each page draws its own", () => {
    const absatz = el("a", "absatz", null, [], { pages: [9, 10], provenance: [box(9, 65, 63, 531, 52), box(10, 65, 776, 531, 696)] });
    const { boxes, approximate } = highlightsOf(absatz);
    expect(boxes.map((b) => b.page_no)).toEqual([9, 10]);
    expect(approximate).toBe(false);
    expect(firstPage(absatz)).toBe(9); // selecting the element jumps to the page where the text starts
    expect(rectsOnPage(boxes, 9, 842, 1)).toEqual([{ left: 65, top: 842 - 63, width: 466, height: 11 }]);
    expect(rectsOnPage(boxes, 10, 842, 1)).toHaveLength(1);
    expect(rectsOnPage(boxes, 11, 842, 1)).toEqual([]);
    expect(firstPage(null)).toBeNull();
  });
});
