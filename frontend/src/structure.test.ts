import { describe, expect, it } from "vitest";
import { bboxToRect, buildTree, visibleKeys } from "./structure";
import type { DocElement, DocumentModel } from "./types";

const el = (id: string, type: string, parent: string | null, children: string[], extra: Partial<DocElement> = {}): DocElement => ({
  id, type, region: "body", parent_id: parent, children_ids: children, number: null, marker: null, title: null,
  original_text: id, content_text: id, table: null, source_refs: [], docling_label: null, pages: [1], provenance: [],
  uncertain: false, uncertainty_reasons: [], ...extra,
});

const model: DocumentModel = {
  model_version: "0.1",
  source: { filename: "x.pdf", docling_version: null, docling_json_sha256: "0", num_pages: 1 },
  metadata: { title: null, short_title: null, ausfertigungsdatum: null, stand: null, vollzitat: null },
  root_id: "doc",
  elements: [
    el("doc", "document", null, ["f1", "t1"], { region: "document" }),
    el("f1", "front_matter", "doc", [], { region: "front" }),
    el("t1", "teil", "doc", ["p1"], { marker: "Teil 1", title: "Allgemeines" }),
    el("p1", "paragraph", "t1", ["a1"], { marker: "§ 1", title: "Zweck" }),
    el("a1", "absatz", "p1", [], { marker: "(1)", uncertain: true, uncertainty_reasons: ["x"] }),
  ],
  furniture: [],
  warnings: [{ code: "W", severity: "warning", message: "m", element_id: "p1", source_ref: null }],
};

describe("buildTree", () => {
  it("keeps the model hierarchy and groups front matter", () => {
    const { roots, byKey } = buildTree(model);
    expect(roots.map((r) => r.label)).toEqual(["Front matter (1)", "Teil 1 Allgemeines"]);
    expect(byKey.get("t1")!.children[0].children[0].key).toBe("a1");
  });
  it("aggregates uncertain and warning counts upward", () => {
    const { byKey } = buildTree(model);
    expect(byKey.get("t1")!.uncertain).toBe(1);
    expect(byKey.get("t1")!.warnings).toBe(1);
    expect(byKey.get("p1")!.uncertain).toBe(1);
  });
  it("filters to flagged elements and their ancestors", () => {
    const { byKey, parentOf } = buildTree(model);
    const keep = visibleKeys(byKey, parentOf, "", true, (id) => id === "p1")!;
    expect([...keep].sort()).toEqual(["a1", "p1", "t1"]);
    expect(visibleKeys(byKey, parentOf, "", false, () => false)).toBeNull();
  });
});

describe("bboxToRect", () => {
  it("flips BOTTOMLEFT coordinates", () => {
    const r = bboxToRect({ l: 50, t: 700, r: 150, b: 680, coord_origin: "BOTTOMLEFT" }, 800, 2);
    expect(r).toEqual({ left: 100, top: 200, width: 200, height: 40 });
  });
  it("keeps TOPLEFT coordinates", () => {
    const r = bboxToRect({ l: 10, t: 20, r: 30, b: 60, coord_origin: "TOPLEFT" }, 800, 1);
    expect(r).toEqual({ left: 10, top: 20, width: 20, height: 40 });
  });
});

import { AKN_EU_NOTE, aknStatus } from "./exports";
import { TYPE_LABELS, hasPartialBox } from "./structure";

/** The EU profile's element types: each needs a display label. */
const EU_TYPES = new Set(["doc_title", "preamble", "recital", "citation", "article", "chapter", "annex", "annex_part", "annex_heading", "article_paragraph", "point", "subpoint", "numbered_point"]);

const euModel: DocumentModel = {
  ...model,
  profile: "eu_legislation",
  elements: [
    el("doc", "document", null, ["pre", "c1", "ax"], { region: "document" }),
    el("pre", "preamble", "doc", ["r1"], { region: "preamble", original_text: "", content_text: "" }),
    el("r1", "recital", "pre", [], { region: "preamble", marker: "(1)", content_text: "Erwägung", original_text: "(1) Erwägung" }),
    el("c1", "chapter", "doc", ["a1"], { marker: "KAPITEL I", title: "ALLGEMEINE BESTIMMUNGEN" }),
    el("a1", "article", "c1", ["p1"], { marker: "Artikel 1", title: "Gegenstand" }),
    el("p1", "article_paragraph", "a1", ["pt"], { marker: "(1)", uncertain: true, uncertainty_reasons: ["x"],
      source_spans: [{ ref: "#/texts/373", start: 0, end: 10, page_no: 20, bbox: null, bbox_scope: "docling_item" }] }),
    el("pt", "point", "p1", ["sub"], { marker: "a)" }),
    el("sub", "subpoint", "pt", [], { marker: "i)" }),
    el("ax", "annex", "doc", [], { region: "annex", marker: "ANHANG I", title: "KATEGORIEN" }),
  ],
};

describe("EU structure", () => {
  it("has a display label for every EU element type", () => {
    for (const t of ["recital", "chapter", "article", "article_paragraph", "point", "subpoint", "annex", "annex_part", "annex_heading", "footnote", "citation"])
      expect(TYPE_LABELS[t]).toBeTruthy();
    expect([...EU_TYPES].every((t) => t in TYPE_LABELS)).toBe(true);
    expect(TYPE_LABELS.subpoint).toBe("Sub-point (i)");
  });
  it("builds the tree in model order without regrouping EU regions", () => {
    const { roots, byKey } = buildTree(euModel);
    expect(roots.map((r) => r.key)).toEqual(["pre", "c1", "ax"]);
    expect(byKey.get("c1")!.children[0].children[0].children[0].key).toBe("pt");
    expect(byKey.get("a1")!.uncertain).toBe(1);
    expect(roots[0].label).toBe("Preamble");
  });
  it("labels recitals and articles with marker and title", () => {
    const { byKey } = buildTree(euModel);
    expect(byKey.get("r1")!.label).toBe("(1) Erwägung");
    expect(byKey.get("a1")!.label).toBe("Artikel 1 Gegenstand");
  });
  it("flags split elements whose box covers the whole source item", () => {
    const by = new Map(euModel.elements.map((e) => [e.id, e]));
    expect(hasPartialBox(by.get("p1")!)).toBe(true);
    expect(hasPartialBox(by.get("a1")!)).toBe(false);
  });
  it("reports the Akoma Ntoso status only from the pipeline summary", () => {
    expect(aknStatus({ akn_generated: false })).toEqual({ kind: "warn", title: "No Akoma Ntoso XML.", text: AKN_EU_NOTE });
    const ok = aknStatus({ akn_generated: true, akn_xsd_valid: true, akn_text_identical: true });
    expect(ok.kind).toBe("info");
    expect(ok.title).toMatch(/valid against the official OASIS XSD/);
    const bad = aknStatus({ akn_generated: true, akn_xsd_valid: false, akn_xsd_errors: 3 });
    expect(bad.kind).toBe("error");
    expect(bad.text).toMatch(/3 XSD error/);
    expect(aknStatus({ akn_generated: true, akn_xsd_valid: true, akn_text_identical: false }).kind).toBe("warn");
  });
});
