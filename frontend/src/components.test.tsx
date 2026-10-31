import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ElementDetail } from "./components/ElementDetail";
import { MetadataPanel } from "./components/MetadataPanel";
import type { DocElement, DocumentModel } from "./types";

const base: DocElement = {
  id: "doc/chp-2/art-11/para-3", type: "article_paragraph", region: "body", parent_id: null, children_ids: [], number: "3",
  marker: "(3)", title: null, original_text: "(3) Die Hersteller bewahren", content_text: "Die Hersteller bewahren", table: null,
  source_refs: ["#/texts/373"], docling_label: "text", pages: [20],
  provenance: [{ page_no: 20, bbox: { l: 1, t: 500, r: 100, b: 100, coord_origin: "BOTTOMLEFT" }, charspan: [659, 1280] }],
  uncertain: true, uncertainty_reasons: ["segment_boundary_uncertain:text_after_marker_not_capitalised"],
  source_spans: [{ ref: "#/texts/373", start: 659, end: 1280, page_no: 20, bbox: null, bbox_scope: "docling_item" }],
  hygiene_flags: ["split_from_merged_docling_item"],
};

describe("ElementDetail for EU elements", () => {
  it("explains the approximate highlight, uncertainty and source range", () => {
    const html = renderToStaticMarkup(<ElementDetail element={base} warnings={[]} eId={null} onGoToPage={() => {}} />);
    expect(html).toContain("Paragraph (3)");
    expect(html).toContain("Approximate highlight");
    expect(html).toContain("659–1280");
    expect(html).toContain("segment_boundary_uncertain");
    expect(html).toContain("split_from_merged_docling_item");
    expect(html).toContain("p. 20");
  });
  it("shows no approximation notice for ordinary elements", () => {
    const html = renderToStaticMarkup(<ElementDetail element={{ ...base, source_spans: undefined, uncertain: false, uncertainty_reasons: [] }} warnings={[]} eId={null} onGoToPage={() => {}} />);
    expect(html).not.toContain("Approximate highlight");
  });
});

describe("MetadataPanel", () => {
  const model = {
    profile: "eu_legislation", source: { filename: "EU.pdf", docling_version: "1.10.0", docling_json_sha256: "0", num_pages: 102 },
    metadata: { title: "VERORDNUNG (EU) 2023/1230", short_title: null, ausfertigungsdatum: null, stand: null, vollzitat: null,
      document_number: "2023/1230", adoption_date_text: "vom 14. Juni 2023", adoption_date: "2023-06-14",
      publication_reference: "L 165/1", metadata_provenance: { document_number: ["doc/title"], publication_reference: ["furniture/p1-page_header-3"] } },
    root_id: "doc", elements: [{ ...base, id: "doc/title" }], furniture: [], warnings: [], model_version: "0.1",
  } as unknown as DocumentModel;
  it("lists metadata with source links and hides empty German fields", () => {
    const html = renderToStaticMarkup(<MetadataPanel model={model} onSelect={() => {}} />);
    expect(html).toContain("2023/1230");
    expect(html).toContain("2023-06-14");
    expect(html).toContain("EU legislation (prototype)");
    expect(html).toContain(">source<");
    expect(html).toContain("(page header)");
    expect(html).not.toContain("Ausfertigungsdatum");
  });
});
