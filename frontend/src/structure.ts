import type { DocElement, DocumentModel, ParserWarning, Provenance, TocEntry } from "./types";

// Document structure display: tree, labels, filters and the PDF highlight geometry of elements.

export interface TreeNode {
  key: string;
  label: string;
  element: DocElement | null; // null for synthetic groups and normalized TOC entries
  children: TreeNode[];
  uncertain: number; // flagged elements in this subtree (including this one)
  warnings: number;
  toc?: TocEntry; // a normalized TOC entry (read-only); clicking it opens its confirmed body element
}

export const TYPE_LABELS: Record<string, string> = {
  teil: "Teil",
  kapitel: "Kapitel",
  abschnitt: "Abschnitt",
  anlage: "Anlage",
  unterabschnitt: "Unterabschnitt",
  paragraph: "§",
  absatz: "Absatz",
  nummer: "Nummer",
  buchstabe: "Buchstabe",
  doppelbuchstabe: "Doppelbuchstabe",
  text: "Text",
  unmarked_list_item: "List item",
  footnote_heading: "Footnote",
  footnote: "Footnote text",
  table: "Table",
  toc: "Table of contents",
  toc_entry: "TOC entry",
  front_matter: "Front matter",
  unrecognized: "Unrecognized",
  // EU legislation
  doc_title: "Title",
  preamble: "Preamble",
  preamble_formula: "Opening formula",
  citation: "Citation",
  recitals_intro: "Recitals intro",
  recital: "Recital",
  enacting_formula: "Enacting formula",
  chapter: "Chapter",
  section: "Section",
  article: "Article",
  article_paragraph: "Paragraph",
  numbered_point: "Point (1.)",
  point: "Point (a)",
  subpoint: "Sub-point (i)",
  annex: "Annex",
  annex_part: "Annex part",
  annex_heading: "Annex heading",
  conclusions: "Conclusions",
  final_formula: "Final formula",
  signature: "Signature",
};

/** A split element's box is the box of the whole Docling item, not of its own text — unless the backend proved
 *  exact per-line rectangles from the PDF glyphs (`highlight_boxes`). */
export function hasPartialBox(e: DocElement): boolean {
  if (e.highlight_boxes?.length) return false;
  return (e.source_spans ?? []).some((s) => s.bbox_scope === "docling_item");
}

/** What the PDF viewer draws for an element: exact line rectangles where proven, otherwise its provenance boxes. */
export function highlightsOf(e: DocElement | null | undefined): { boxes: Provenance[]; approximate: boolean } {
  if (!e) return { boxes: [], approximate: false };
  if (e.highlight_boxes?.length) return { boxes: e.highlight_boxes, approximate: false };
  return { boxes: e.provenance, approximate: hasPartialBox(e) };
}

/** Closest Akoma Ntoso element, shown as a hint only (see Documentation/akn-mapping.md). */
export const AKN_HINT: Record<string, string> = {
  teil: "part", kapitel: "chapter", abschnitt: "section", unterabschnitt: "subsection",
  anlage: "hcontainer", paragraph: "article", absatz: "paragraph", nummer: "point", buchstabe: "point", doppelbuchstabe: "point",
};

export function elementLabel(e: DocElement, max = 90): string {
  const head = [e.marker, e.title ?? e.content_text ?? e.original_text].filter(Boolean).join(" ").replace(/\s+/g, " ").trim();
  const text = head || e.original_text.replace(/\s+/g, " ").trim() || TYPE_LABELS[e.type] || e.type;
  return text.length > max ? text.slice(0, max - 1) + "…" : text;
}

export function warningsByElement(warnings: ParserWarning[]): Map<string, ParserWarning[]> {
  const m = new Map<string, ParserWarning[]>();
  for (const w of warnings) if (w.element_id) m.set(w.element_id, [...(m.get(w.element_id) ?? []), w]);
  return m;
}

/** Builds the display tree from the flat model; nothing is hidden or reordered. */
export function buildTree(model: DocumentModel): { roots: TreeNode[]; byKey: Map<string, TreeNode>; parentOf: Map<string, string> } {
  const byId = new Map(model.elements.map((e) => [e.id, e]));
  const wmap = warningsByElement(model.warnings);
  const byKey = new Map<string, TreeNode>();
  const parentOf = new Map<string, string>();

  const make = (e: DocElement): TreeNode => {
    const children = e.children_ids.map((c) => byId.get(c)).filter((x): x is DocElement => !!x).map(make);
    const node: TreeNode = {
      key: e.id, label: elementLabel(e), element: e, children,
      uncertain: (e.uncertain ? 1 : 0) + children.reduce((a, c) => a + c.uncertain, 0),
      warnings: (wmap.get(e.id)?.length ?? 0) + children.reduce((a, c) => a + c.warnings, 0),
    };
    byKey.set(node.key, node);
    children.forEach((c) => parentOf.set(c.key, node.key));
    return node;
  };

  const root = byId.get(model.root_id);
  const top = (root?.children_ids ?? []).map((c) => byId.get(c)).filter((x): x is DocElement => !!x);
  const front = top.filter((e) => e.region === "front");
  const roots: TreeNode[] = [];
  if (front.length) {
    const kids = front.map(make);
    const group: TreeNode = {
      key: "group:front", label: `Front matter (${front.length})`, element: null, children: kids,
      uncertain: kids.reduce((a, c) => a + c.uncertain, 0), warnings: kids.reduce((a, c) => a + c.warnings, 0),
    };
    byKey.set(group.key, group);
    kids.forEach((k) => parentOf.set(k.key, group.key));
    roots.push(group);
  }
  for (const e of top.filter((e) => e.region !== "front")) {
    const node = make(e);
    if (e.type === "toc" && model.toc_entries?.length) tocView(node, model.toc_entries, byKey, parentOf);
    roots.push(node);
  }
  return { roots, byKey, parentOf };
}

/** What clicking a tree row does: select an element, open a TOC entry's confirmed body element, or toggle a group.
 *  An unconfirmed TOC entry does nothing (it is read-only and has no proven target). */
export function clickAction(n: TreeNode): { select: string } | { toggle: string } | null {
  if (n.toc) return n.toc.target_id ? { select: n.toc.target_id } : null;
  if (n.element) return { select: n.key };
  return { toggle: n.key };
}

/** The TOC shows the normalized entries in printed order; Docling's raw TOC items stay available (and editable)
 *  in their own group. Nothing of the raw items is changed or hidden. */
function tocView(toc: TreeNode, entries: TocEntry[], byKey: Map<string, TreeNode>, parentOf: Map<string, string>): void {
  const raw = toc.children;
  const rawGroup: TreeNode = {
    key: "group:toc-raw", label: `Raw Docling TOC items (${raw.length})`, element: null, children: raw,
    uncertain: raw.reduce((a, c) => a + c.uncertain, 0), warnings: raw.reduce((a, c) => a + c.warnings, 0),
  };
  raw.forEach((c) => parentOf.set(c.key, rawGroup.key));
  const items: TreeNode[] = entries.map((t) => ({
    key: `tocentry:${t.id}`, label: [t.marker, t.title].filter(Boolean).join(" ") || t.id, element: null, children: [],
    uncertain: 0, warnings: 0, toc: t,
  }));
  for (const n of [...items, rawGroup]) {
    byKey.set(n.key, n);
    parentOf.set(n.key, toc.key);
  }
  toc.children = [...items, rawGroup];
}

/** Keys of nodes matching the filters plus their ancestors. null = no filter active. */
export function visibleKeys(
  byKey: Map<string, TreeNode>, parentOf: Map<string, string>, query: string, onlyFlagged: boolean, hasWarning: (id: string) => boolean,
): Set<string> | null {
  const q = query.trim().toLowerCase();
  if (!q && !onlyFlagged) return null;
  const keep = new Set<string>();
  for (const n of byKey.values()) {
    const e = n.element;
    if (!e) continue;
    const textOk = !q || (e.original_text + " " + (e.title ?? "")).toLowerCase().includes(q);
    const flagOk = !onlyFlagged || e.uncertain || hasWarning(e.id);
    if (textOk && flagOk) {
      let k: string | undefined = n.key;
      while (k && !keep.has(k)) {
        keep.add(k);
        k = parentOf.get(k);
      }
    }
  }
  return keep;
}

export interface Rect { left: number; top: number; width: number; height: number }

/** Converts a Docling bounding box (PDF points) to CSS pixels on a page of height `pageHeight` points. */
export function bboxToRect(b: NonNullable<Provenance["bbox"]>, pageHeight: number, scale: number): Rect {
  const top = b.coord_origin.toUpperCase().includes("BOTTOM") ? pageHeight - b.t : b.t;
  const height = Math.abs(b.t - b.b);
  return { left: b.l * scale, top: top * scale, width: (b.r - b.l) * scale, height: height * scale };
}
