"""Canonical `DocumentModel` -> public `LegalDocument` (`document.json`, Custom Legal JSON 2.0).

A one-way, deterministic serialization: the model stays the single source of truth. Nothing is
invented: text, markers, titles and pages are the model's values, and absent values are left out. The model's
technical provenance (Docling items, boxes, character offsets) is not exported; node ids lead back to it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from odos.legal_json.view import (
    Footnote, FootnoteReference, Identifiers, LegalDocument, LegalSentence, Node, TextRange, TocEntryOut, TocTextRange, Version,
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


# ---- document ---------------------------------------------------------------------------------------------------------
def to_legal_json(model: DocumentModel) -> LegalDocument:
    profile = for_model(model)
    names = _Names(COMMON_TYPES | profile.json_types, profile.json_native_terms)
    index = model.by_id()
    root = index[model.root_id]
    front, toc, structure = [], [], []
    for cid in root.children_ids:
        el = index[cid]
        if el.type in FOOTNOTE_TYPES:
            continue
        node = _node(el, index, names)
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
        pageCount=model.source.num_pages,
        frontMatter=front,
        tableOfContents=toc,
        structure=structure,
        footnotes=[_footnote(e, index, model, names) for e in _footnote_roots(model, index)],
        tableOfContentsEntries=[_toc_entry(t) for t in model.toc_entries],
        sentences=[_sentence(s) for s in model.sentences],
    )


def _toc_entry(t) -> TocEntryOut:
    return TocEntryOut(
        id=t.id, kind=t.kind, marker=t.marker, number=t.number, title=t.title, level=t.level,
        targetElementId=t.target_id if t.status == "linked" else None,  # only confirmed links are published
        ranges=[TocTextRange(elementId=s.element_id, cell=s.cell, start=s.start, end=s.end) for s in t.source_spans],
    )  # fmt: skip


def _range(r) -> TextRange:
    return TextRange(elementId=r.element_id, start=r.start, end=r.end)


def _sentence(s) -> LegalSentence:
    return LegalSentence(
        id=s.id, unitId=s.unit_id, number=s.number, marker=_range(s.marker) if s.marker else None,
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


def _node(el: Element, index: dict[str, Element], names: _Names) -> Node:
    table = el.table
    return Node(
        id=el.id,
        type=names.types[el.type],
        germanType=names.native.get(el.type),
        number=el.number,
        marker=el.marker,
        title=el.title,
        text=own_text(el),
        numRows=table.num_rows if table else None,
        numCols=table.num_cols if table else None,
        rows=[list(row) for row in table.rows] if table else None,
        pages=list(el.pages),
        children=[_node(index[c], index, names) for c in el.children_ids if index[c].type not in FOOTNOTE_TYPES],
    )


# ---- footnotes --------------------------------------------------------------------------------------------------------
def _footnote_roots(model: DocumentModel, index: dict[str, Element]) -> list[Element]:
    """Footnote headings ("Fußnote" blocks) and page footnotes, in document order. Footnote text inside a
    heading block is that block's content, not a footnote of its own."""
    return [e for e in model.elements
            if e.type == T.FOOTNOTE_HEADING or (e.type == T.FOOTNOTE and index[e.parent_id].type != T.FOOTNOTE_HEADING)]  # fmt: skip


def _footnote(el: Element, index: dict[str, Element], model: DocumentModel, names: _Names) -> Footnote:
    if el.anchor_ids:  # proven from the PDF's reference marks (parsing.footnotes), possibly several
        anchors = [a for a in el.anchor_ids if a in index]
    else:
        single = footnote_anchor(el, index, model)
        anchors = [single] if single else []
    return Footnote(
        id=el.id, marker=el.marker, number=el.number, title=el.title, text=own_text(el), pages=list(el.pages),
        content=[_node(index[c], index, names) for c in el.children_ids],
        anchorElementIds=anchors,
        references=[FootnoteReference(elementId=r.element_id, marker=r.mark, page=r.page) for r in el.footnote_refs if r.element_id in index],
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
