"""Canonical `DocumentModel` -> public `LegalDocument` (`document.json`).

A one-way, deterministic serialization: the model stays the single source of truth. Nothing is
invented: text, markers and titles are the model's values, coordinates come from the model's
provenance, page sizes from the Docling output, and absent values are left out.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from odos.legal_json.markers import marker_style
from odos.legal_json.view import (
    BoundingBox, CellSource, Footnote, FootnoteReference, Identifiers, LegalDocument, LegalSentence, Node, PageSize,
    SentenceNumberSource, Source, SourceFile, SourceSpan, TableCell, TextRange, TocEntryOut, TocSourceSpan, Version,
)  # fmt: skip
from odos.document_model import DocumentModel, Element, ElementType as T
from odos.parsing.profiles import LegalProfile, for_model

# element types every profile shares; each profile adds its own units (`LegalProfile.json_types`)
COMMON_TYPES: dict[T, str] = {
    T.SENTENCE: "sentence", T.TEXT: "text", T.UNRECOGNIZED: "text", T.TABLE: "table", T.PICTURE: "picture",
    T.FOOTNOTE: "text",  # only as the content of a "Fußnote" block; footnotes themselves are `footnotes[]`
    T.FRONT_MATTER: "frontMatter", T.DOC_TITLE: "documentTitle", T.TOC: "tableOfContents", T.TOC_ENTRY: "tocEntry",
    T.UNMARKED_LIST_ITEM: "item",
}  # fmt: skip

FOOTNOTE_TYPES = (T.FOOTNOTE, T.FOOTNOTE_HEADING)
FRONT_TYPES = (T.FRONT_MATTER, T.DOC_TITLE)
NO_ANCHOR_PARENTS = (T.DOCUMENT, T.FRONT_MATTER, T.DOC_TITLE, T.TOC, T.TOC_ENTRY, *FOOTNOTE_TYPES)


@dataclass(frozen=True)
class _Names:
    """Public type and native term of each element type, for the document's profile."""

    types: dict[T, str]
    native: dict[T, str]


@dataclass(frozen=True)
class SourceContext:
    """What the Docling output adds to the model: page sizes and how many boxes each source item has."""

    page_sizes: dict[int, tuple[float, float]] = field(default_factory=dict)
    boxes_per_item: dict[str, int] = field(default_factory=dict)


def load_source_context(docling_json: Path) -> SourceContext:
    raw = json.loads(Path(docling_json).read_bytes())
    sizes = {int(k): (v["size"]["width"], v["size"]["height"]) for k, v in (raw.get("pages") or {}).items()}
    boxes = {n["self_ref"]: len(n.get("prov") or []) for kind in ("texts", "tables", "pictures") for n in raw.get(kind) or []}
    return SourceContext(sizes, boxes)


# ---- document ---------------------------------------------------------------------------------------------------------
def to_legal_json(model: DocumentModel, ctx: SourceContext | None = None) -> LegalDocument:
    ctx = ctx or SourceContext()
    profile = for_model(model)
    names = _Names(COMMON_TYPES | profile.json_types, profile.json_native_terms)
    index = model.by_id()
    root = index[model.root_id]
    front, toc, structure = [], [], []
    for cid in root.children_ids:
        el = index[cid]
        if el.type in FOOTNOTE_TYPES:
            continue
        node = _node(el, index, ctx, names)
        (front if el.type in FRONT_TYPES else toc if el.type == T.TOC else structure).append(node)
    md = model.metadata
    return LegalDocument(
        id=_document_id(model, profile),
        title=md.title,
        shortTitle=md.short_title,
        documentType=profile.json_document_type(md),
        nativeDocumentType=md.document_type,
        legalSystem=profile.legal_system,
        language=profile.language,  # the recognizer's rules match text of this language only
        version=Version(statement=md.stand or md.stated_version_text, date=md.version_year_month),
        publicationDate=md.publication_date,
        adoptionDate=md.adoption_date,
        enactmentDate=_german_date(md.ausfertigungsdatum),
        subject=md.subject,
        identifiers=Identifiers(documentNumber=md.document_number, publicationJournal=md.publication_journal,
                                publicationReference=md.publication_reference, citation=md.vollzitat),  # fmt: skip
        sourceFile=SourceFile(filename=model.source.filename, doclingJsonSha256=model.source.docling_json_sha256),
        pageCount=model.source.num_pages,
        pages=[PageSize(number=n, width=w, height=h) for n, (w, h) in sorted(ctx.page_sizes.items())] or None,
        frontMatter=front,
        tableOfContents=toc,
        structure=structure,
        footnotes=[_footnote(e, index, model, ctx, names) for e in _footnote_roots(model, index)],
        tableOfContentsEntries=[_toc_entry(t) for t in model.toc_entries],
        sentences=[_sentence(s) for s in model.sentences],
    )


def _toc_entry(t) -> TocEntryOut:
    return TocEntryOut(
        id=t.id, kind=t.kind, marker=t.marker, number=t.number, title=t.title, level=t.level,
        targetElementId=t.target_id if t.status == "linked" else None,  # only confirmed links are published
        sourceSpans=[TocSourceSpan(elementId=s.element_id, cell=s.cell, start=s.start, end=s.end, page=s.page, bbox=_bbox(s.bbox),
                                   bboxScope="source_item" if s.bbox_scope == "docling_item" else s.bbox_scope) for s in t.source_spans],
    )  # fmt: skip


def _range(r) -> TextRange:
    return TextRange(elementId=r.element_id, start=r.start, end=r.end, textSha256=r.text_sha256)


def _sentence(s) -> LegalSentence:
    return LegalSentence(
        id=s.id, unitId=s.unit_id, number=s.number, marker=_range(s.marker) if s.marker else None,
        numberSource=SentenceNumberSource(page=s.mark_page, bbox=_bbox(s.mark_box)) if s.mark_box and s.mark_page else None,
        ranges=[_range(r) for r in s.ranges],
    )  # fmt: skip


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _document_id(model: DocumentModel, profile: LegalProfile) -> str:
    md = model.metadata
    if parts := profile.json_id_parts(md):  # e.g. "VERORDNUNG 2023/1230"
        return _slug(" ".join(parts))
    if md.short_title:
        return _slug(md.short_title)
    return f"doc-{model.source.docling_json_sha256[:12]}"


def _german_date(text: str | None) -> str | None:
    """'30.06.2017' -> '2017-06-30'; anything that is not a complete, valid date stays unset."""
    m = re.fullmatch(r"\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s*", text or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None


# ---- nodes ------------------------------------------------------------------------------------------------------------
def own_text(el: Element) -> str | None:
    """The element's own text. Headings carry it as `title` (content_text == title), so it is not repeated."""
    if el.title is not None and el.content_text == el.title:
        return None
    return el.content_text or None


def _node(el: Element, index: dict[str, Element], ctx: SourceContext, names: _Names) -> Node:
    type_ = names.types[el.type]
    table = el.table
    return Node(
        id=el.id,
        type=type_,
        nativeType=names.native.get(el.type),
        marker=el.marker,
        markerStyle=marker_style(el.marker, type_),
        number=el.number,
        title=el.title,
        text=own_text(el),
        numRows=table.num_rows if table else None,
        numCols=table.num_cols if table else None,
        rows=_rows(table) if table else None,
        source=source_of(el, ctx),
        children=[_node(index[c], index, ctx, names) for c in el.children_ids if index[c].type not in FOOTNOTE_TYPES],
    )


def _rows(table) -> list[list[TableCell]]:
    """The grid as Docling gives it; a cell carries its own box where Docling placed one (spanned positions: none)."""
    boxes = {(c.row, c.col): c for c in table.cells if c.bbox is not None and c.page_no is not None}
    out = []
    for r, row in enumerate(table.rows):
        cells = []
        for k, text in enumerate(row):
            c = boxes.get((r, k))
            src = CellSource(page=c.page_no, bbox=_bbox(c.bbox)) if c is not None and c.text == text else None
            cells.append(TableCell(text=text, source=src))
        out.append(cells)
    return out


def _bbox(b) -> BoundingBox | None:
    return BoundingBox(left=b.l, top=b.t, right=b.r, bottom=b.b) if b is not None else None


def _item_of_each_box(el: Element, ctx: SourceContext) -> list[str | None]:
    """The source item behind each provenance box. Unknown (None) unless it follows from the data."""
    n, refs = len(el.provenance), el.source_refs
    if len(refs) == n:
        return list(refs)
    if len(refs) == 1:
        return refs * n
    counts = [ctx.boxes_per_item.get(r) for r in refs]
    if None not in counts and sum(counts) == n:
        return [r for r, c in zip(refs, counts) for _ in range(c)]
    return [None] * n


def source_of(el: Element, ctx: SourceContext) -> Source:
    spans: list[SourceSpan] = []
    if el.source_spans:  # a segment of a Docling item (extraction-hygiene layer): character offsets are known
        for s in el.source_spans:
            box = s.bbox
            if box is None and len(el.source_refs) == 1:  # the item's own box, as the hygiene layer documents
                box = next((p.bbox for p in el.provenance if p.page_no == s.page_no), None)
            spans.append(SourceSpan(itemRef=s.ref, page=s.page_no, bbox=_bbox(box), charStart=s.start, charEnd=s.end))
    else:
        for p, ref in zip(el.provenance, _item_of_each_box(el, ctx)):
            cs = p.charspan
            spans.append(SourceSpan(itemRef=ref, page=p.page_no, bbox=_bbox(p.bbox),
                                    charStart=cs[0] if cs else None, charEnd=cs[1] if cs else None))  # fmt: skip
    return Source(pages=list(el.pages), sourceSpans=spans)


# ---- footnotes --------------------------------------------------------------------------------------------------------
def _footnote_roots(model: DocumentModel, index: dict[str, Element]) -> list[Element]:
    """Footnote headings ("Fußnote" blocks) and page footnotes, in document order. Footnote text inside a
    heading block is that block's content, not a footnote of its own."""
    return [e for e in model.elements
            if e.type == T.FOOTNOTE_HEADING or (e.type == T.FOOTNOTE and index[e.parent_id].type != T.FOOTNOTE_HEADING)]  # fmt: skip


def _footnote(el: Element, index: dict[str, Element], model: DocumentModel, ctx: SourceContext, names: _Names) -> Footnote:
    if el.anchor_ids:  # proven from the PDF's reference marks (parsing.footnotes), possibly several
        anchors = [a for a in el.anchor_ids if a in index]
    else:
        single = footnote_anchor(el, index, model)
        anchors = [single] if single else []
    return Footnote(
        id=el.id, marker=el.marker, number=el.number, title=el.title, text=own_text(el), source=source_of(el, ctx),
        content=[_node(index[c], index, ctx, names) for c in el.children_ids],
        anchorElementId=anchors[0] if len(anchors) == 1 else None,  # 1.0 meaning: the single anchor
        anchorElementIds=anchors,
        references=[FootnoteReference(elementId=r.element_id, marker=r.mark, page=r.page, bbox=_bbox(r.bbox))
                    for r in el.footnote_refs if r.element_id in index],  # fmt: skip
    )


def _descends_from(el: Element, ancestor_id: str, index: dict[str, Element]) -> bool:
    cur = el
    while cur.parent_id:
        if cur.parent_id == ancestor_id:
            return True
        cur = index[cur.parent_id]
    return False


def _in_footnote(el: Element, index: dict[str, Element]) -> bool:
    cur = el
    while cur is not None:
        if cur.type in FOOTNOTE_TYPES:
            return True
        cur = index.get(cur.parent_id) if cur.parent_id else None
    return False


def footnote_anchor(el: Element, index: dict[str, Element], model: DocumentModel) -> str | None:
    """The element a footnote belongs to, or None. Set only when the parser placed it without doubt AND the
    source evidence is re-checked here:
    * "Fußnote" block: it is printed directly after its anchor's content (document order);
    * page footnote "( n )": the anchor's text contains the reference "( n )" on a page they share.
    An ``anchor_id`` in the model was proven from the PDF's reference marks (``parsing.footnotes``) and is used as is."""
    if el.anchor_id is not None:
        return el.anchor_id if el.anchor_id in index else None
    if el.uncertain or not el.parent_id:
        return None
    anchor = index[el.parent_id]
    if anchor.type in NO_ANCHOR_PARENTS or anchor.region in ("front", "toc", "document"):
        return None
    if el.type == T.FOOTNOTE_HEADING:
        pos = next(i for i, e in enumerate(model.elements) if e.id == el.id)
        prev = next((e for e in reversed(model.elements[:pos]) if not _in_footnote(e, index)), None)
        if prev is not None and (prev.id == anchor.id or _descends_from(prev, anchor.id, index)):
            return anchor.id
        return None
    if el.number and set(el.pages) & set(anchor.pages):
        if re.search(rf"\(\s*{re.escape(el.number)}\s*\)", anchor.original_text):
            return anchor.id
    return None
