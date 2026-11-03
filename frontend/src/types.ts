// The slice of the ODOS DocumentModel the demonstration reads (backend/src/odos/document_model.py). The demo fixture
// script (scripts/build-demo-fixtures.mjs) writes it as structure.json; fields the demo never shows are left out.

/** A Docling bounding box in PDF points. */
export interface BoundingBox {
  l: number;
  t: number;
  r: number;
  b: number;
  coord_origin: string; // "BOTTOMLEFT" or "TOPLEFT"
}

/** Where a piece of text sits in the PDF: page, box and the character range of its source item. */
export interface Provenance {
  page_no: number;
  bbox: BoundingBox | null;
  charspan: [number, number] | null;
}

/** A segment of a split Docling item. Its box covers the whole item, not just this segment. */
export interface SourceSpan {
  ref: string;
  start: number;
  end: number;
  page_no: number | null;
  bbox: BoundingBox | null;
  bbox_scope: "docling_item";
}

export interface DocElement {
  id: string;
  type: string;
  region: "document" | "front" | "toc" | "preamble" | "body" | "conclusions" | "annex" | "furniture";
  parent_id: string | null;
  children_ids: string[];
  number: string | null;
  marker: string | null;
  title: string | null;
  original_text: string;
  content_text: string;
  source_refs: string[]; // the Docling items the text comes from (several when it runs over a page break)
  pages: number[];
  provenance: Provenance[];
  uncertain: boolean; // parser metadata kept in the data; the demo does not display it
  uncertainty_reasons: string[];
  source_spans?: SourceSpan[]; // present only for segments of a split Docling item
  highlight_boxes?: Provenance[]; // exact per-line rectangles proven from the PDF glyphs (else provenance is drawn)
}

/** One line of the document's printed table of contents, linked to its body element when that is proven. */
export interface TocEntry {
  id: string;
  marker: string;
  title: string | null;
  target_id: string | null; // confirmed body element (kind, number, title and hierarchy agree)
  status: "linked" | "candidate" | "unmatched" | "ambiguous";
  evidence: string;
}

export interface DocumentModel {
  profile?: string | null; // "eu_legislation"; absent for the German-law parser
  metadata?: { title?: string | null };
  source: { num_pages: number };
  root_id: string;
  elements: DocElement[];
  toc_entries?: TocEntry[]; // normalized TOC lines in printed order
}
