// Small builders for the tests. Never imported by the application.
import type { DocElement, DocumentModel, Provenance } from "./types";

export const el = (id: string, type: string, parent: string | null, children: string[], extra: Partial<DocElement> = {}): DocElement => ({
  id, type, region: "body", parent_id: parent, children_ids: children, number: null, marker: null, title: null,
  original_text: id, content_text: id, source_refs: [], pages: [1], provenance: [], uncertain: false, uncertainty_reasons: [], ...extra,
});

export const modelOf = (elements: DocElement[], extra: Partial<DocumentModel> = {}): DocumentModel => ({
  source: { num_pages: 1 }, root_id: elements[0].id, elements, ...extra,
});

/** A box in Docling's BOTTOMLEFT coordinates on `page`. */
export const box = (page: number, l: number, t: number, r: number, b: number): Provenance => ({
  page_no: page, bbox: { l, t, r, b, coord_origin: "BOTTOMLEFT" }, charspan: null,
});
