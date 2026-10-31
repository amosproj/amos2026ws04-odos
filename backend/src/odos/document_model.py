"""Internal Document Model.

A flat, document-ordered list of elements linked by ``parent_id`` /
``children_ids``. Every element keeps the verbatim Docling text and its
provenance so each node can be traced back to the PDF.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class ElementType(StrEnum):
    DOCUMENT = "document"
    FRONT_MATTER = "front_matter"  # everything before the table of contents
    TOC = "toc"
    TOC_ENTRY = "toc_entry"
    TEIL = "teil"
    KAPITEL = "kapitel"
    ABSCHNITT = "abschnitt"
    ANLAGE = "anlage"  # annex ("Anlage 1 ...")
    UNTERABSCHNITT = "unterabschnitt"
    PARAGRAPH = "paragraph"  # "§ n"
    ABSATZ = "absatz"  # "(n)"
    NUMMER = "nummer"  # "n."
    BUCHSTABE = "buchstabe"  # "a)"
    DOPPELBUCHSTABE = "doppelbuchstabe"  # "aa)"
    SENTENCE = "sentence"  # "Satz"; no parser emits it yet (sentence splitting is not implemented)
    TEXT = "text"  # unnumbered text
    UNMARKED_LIST_ITEM = "unmarked_list_item"
    FOOTNOTE_HEADING = "footnote_heading"
    FOOTNOTE = "footnote"
    TABLE = "table"
    UNRECOGNIZED = "unrecognized"
    PAGE_HEADER = "page_header"
    PAGE_FOOTER = "page_footer"
    # EU legislation (eu_parser). Names follow EU drafting terms, not German ones.
    DOC_TITLE = "doc_title"  # "VERORDNUNG (EU) 2023/1230 DES ..."
    PREAMBLE = "preamble"  # container: formula, citations, recitals, enacting formula
    PREAMBLE_FORMULA = "preamble_formula"  # "DAS EUROPÄISCHE PARLAMENT UND DER RAT ... -"
    CITATION = "citation"  # "gestützt auf ...", "nach Stellungnahme ..."
    RECITALS_INTRO = "recitals_intro"  # "in Erwägung nachstehender Gründe:"
    RECITAL = "recital"  # "(n)" in the preamble
    ENACTING_FORMULA = "enacting_formula"  # "HABEN FOLGENDE VERORDNUNG ERLASSEN:"
    CHAPTER = "chapter"  # "KAPITEL IX"
    SECTION = "section"  # "ABSCHNITT 1"
    ARTICLE = "article"  # "Artikel 54"
    ARTICLE_PARAGRAPH = "article_paragraph"  # "(1)" inside an article
    NUMBERED_POINT = "numbered_point"  # "1." (e.g. definitions)
    POINT = "point"  # "a)"
    SUBPOINT = "subpoint"  # "i)", "ii)" (roman)
    ANNEX = "annex"  # "ANHANG XII"
    ANNEX_PART = "annex_part"  # "TEIL A"
    ANNEX_HEADING = "annex_heading"  # "1.2.4.1. ..."
    CONCLUSIONS = "conclusions"  # container: final formula, place/date, signatures
    FINAL_FORMULA = "final_formula"  # "Diese Verordnung ist in allen ihren Teilen verbindlich ..."
    SIGNATURE = "signature"
    PICTURE = "picture"


class BoundingBox(BaseModel):
    l: float
    t: float
    r: float
    b: float
    coord_origin: str


class Provenance(BaseModel):
    page_no: int
    bbox: BoundingBox | None = None
    charspan: tuple[int, int] | None = None


class SourceSpan(BaseModel):
    """Part of one Docling item backing an element (extraction-hygiene segment).

    `start`/`end` index the item's verbatim `orig` text. Docling gives one box per item, so `bbox`
    is the box of the whole item (`bbox_scope`), not a tight box around the segment."""

    ref: str
    start: int
    end: int
    page_no: int | None = None
    bbox: BoundingBox | None = None
    bbox_scope: Literal["docling_item"] = "docling_item"


def _empty(v) -> bool:
    return not v


class TextRepair(BaseModel):
    """One character-level difference between Docling's text and the PDF text layer, and how it was resolved.

    `start`/`end` index the canonical (PDF-faithful) text of the source item `ref`; `docling` is what Docling
    had in that place, `restored` what the text now holds (equal to `docling` when Docling was right)."""

    ref: str
    kind: Literal["line_end_hyphen", "typography"]
    status: Literal["verified", "unresolved"]
    rule: str
    start: int
    end: int
    docling: str
    restored: str
    page: int | None = None
    evidence: str


class FootnoteRef(BaseModel):
    """One printed reference mark of a footnote, with the glyph box from the PDF text layer."""

    element_id: str
    mark: str
    page: int
    bbox: BoundingBox | None = None
    mark_class: str  # source_marks.classify: reference_attached | reference_spaced | text_mark
    evidence: str


class SentenceRange(BaseModel):
    """A half-open range [start, end) of Python str indices (Unicode code points) into an element's content_text."""

    element_id: str
    start: int
    end: int
    text_sha256: str  # of the element's content_text the offsets were computed on


class Sentence(BaseModel):
    """A legal sentence as ordered text ranges over one or more elements; the canonical text is never copied.

    `number` is set only when the PDF prints it (Satz number, verified against a superscript mark)."""

    id: str
    unit_id: str  # the § / Absatz / Artikel-paragraph whose sentences these are
    number: str | None = None
    marker: SentenceRange | None = None  # the printed Satz number inside the first range's text
    ranges: list[SentenceRange]
    status: Literal["verified", "regenerated_from_reviewed_text"] = "verified"
    method: Literal["printed_number", "punctuation"]
    mark_box: BoundingBox | None = None  # the printed superscript number's glyph box
    mark_page: int | None = None


class TocSpan(BaseModel):
    """Where a TOC entry's characters come from: [start, end) code points of a raw TOC element's content_text,
    or of one of its table cells (`cell` = [row, col]); `bbox` is that line's box when the PDF line is known."""

    element_id: str
    cell: list[int] | None = None
    start: int
    end: int
    page: int | None = None
    bbox: BoundingBox | None = None
    bbox_scope: Literal["text_line", "table_cell", "docling_item"]


class TocEntry(BaseModel):
    """A logical table-of-contents line, rebuilt from Docling's (possibly split or merged) TOC items."""

    id: str
    kind: str  # paragraph | article | teil | kapitel | abschnitt | unterabschnitt | anlage | annex | chapter | section
    marker: str
    number: str | None = None
    title: str | None = None
    level: int
    source_element_ids: list[str]  # the raw TOC elements this entry's characters come from
    source_spans: list[TocSpan] = Field(default_factory=list)
    target_id: str | None = None  # confirmed body element (kind, number, title and hierarchy agree)
    candidate_ids: list[str] = Field(default_factory=list)  # possible targets that need review
    status: Literal["linked", "candidate", "unmatched", "ambiguous"]
    evidence: str


class ParserWarning(BaseModel):
    code: str
    severity: Literal["info", "warning"] = "warning"
    message: str
    element_id: str | None = None
    source_ref: str | None = None
    # parser_error | extraction_uncertainty | valid_structure | needs_review (EU parser; omitted when not set)
    category: str | None = Field(default=None, exclude_if=lambda v: not v)


class TableCellSource(BaseModel):
    """One Docling table cell with its own box (converted to BOTTOMLEFT like all model boxes)."""

    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    text: str
    page_no: int | None = None
    bbox: BoundingBox | None = None


class TableData(BaseModel):
    num_rows: int
    num_cols: int
    rows: list[list[str]]
    cells: list[TableCellSource] = Field(default_factory=list, exclude_if=_empty)  # Docling's cells, where it gives boxes


class Element(BaseModel):
    id: str
    type: ElementType
    region: Literal["document", "front", "toc", "preamble", "body", "conclusions", "annex", "furniture"]
    parent_id: str | None = None
    children_ids: list[str] = Field(default_factory=list)
    number: str | None = None  # "1", "22a", ...
    marker: str | None = None  # "§ 1", "(2)", "3.", "a)"
    title: str | None = None  # headings only
    original_text: str = ""  # source text: Docling `orig`, with characters restored from the PDF text layer (text_repairs)
    content_text: str = ""  # original_text without the structural marker
    table: TableData | None = None
    source_refs: list[str] = Field(default_factory=list)  # Docling self_ref(s)
    docling_label: str | None = None
    pages: list[int] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)
    uncertain: bool = False
    uncertainty_reasons: list[str] = Field(default_factory=list)
    # Derived by the extraction-hygiene layer; omitted from JSON when they carry nothing.
    source_spans: list[SourceSpan] = Field(default_factory=list, exclude_if=_empty)  # partial-item provenance
    search_text: str | None = Field(default=None, exclude_if=_empty)  # normalised; None = same as original_text
    hygiene_flags: list[str] = Field(default_factory=list, exclude_if=_empty)
    # Source-text restoration: Docling's own text when it differs from original_text, and every repair with its evidence
    docling_text: str | None = Field(default=None, exclude_if=lambda v: v is None)
    text_repairs: list[TextRepair] = Field(default_factory=list, exclude_if=_empty)
    # footnotes: the element the footnote's reference mark stands in, proven from the PDF (parent_id/id unchanged).
    # anchor_id keeps its meaning: the anchor when there is exactly one; anchor_ids/footnote_refs list every reference.
    # exact highlight: one rectangle per PDF line of this element's own text, proven from the glyphs (internal, for
    # the viewer); empty = use the provenance boxes (approximate when they are the box of a whole, larger item)
    highlight_boxes: list[Provenance] = Field(default_factory=list, exclude_if=_empty)
    anchor_id: str | None = Field(default=None, exclude_if=lambda v: v is None)
    anchor_ids: list[str] = Field(default_factory=list, exclude_if=_empty)
    footnote_refs: list[FootnoteRef] = Field(default_factory=list, exclude_if=_empty)
    # Human review: set only in an effective (reviewed) model; original_text always stays the Docling text.
    reviewed: dict | None = Field(default=None, exclude_if=_empty)  # {"fields": {f: {"original", "corrected"}}, "corrections": [ids]}


class SourceInfo(BaseModel):
    filename: str | None = None
    mimetype: str | None = None
    docling_schema: str | None = None
    docling_version: str | None = None
    docling_binary_hash: str | None = None
    docling_json_sha256: str
    num_pages: int


class DocumentMetadata(BaseModel):
    title: str | None = None
    short_title: str | None = None
    ausfertigungsdatum: str | None = None
    stand: str | None = None
    vollzitat: str | None = None
    # Version statements found in the front matter, kept verbatim. Neither is an enactment date.
    stated_version_text: str | None = None
    version_year_month: str | None = None  # "YYYY-MM", only when the text says e.g. "FASSUNG NOVEMBER 2002"
    # EU legislation: values are verbatim from the document; ISO dates only where the text gives a full date.
    document_type: str | None = Field(default=None, exclude_if=_empty)  # "VERORDNUNG"
    document_number: str | None = Field(default=None, exclude_if=_empty)  # "2023/1230"
    issuing_bodies: str | None = Field(default=None, exclude_if=_empty)  # "DES EUROPÄISCHEN PARLAMENTS UND DES RATES"
    adoption_date_text: str | None = Field(default=None, exclude_if=_empty)  # "vom 14. Juni 2023"
    adoption_date: str | None = Field(default=None, exclude_if=_empty)
    subject: str | None = Field(default=None, exclude_if=_empty)
    eea_relevance: bool | None = Field(default=None, exclude_if=lambda v: v is None)
    publication_journal: str | None = Field(default=None, exclude_if=_empty)  # running header
    publication_reference: str | None = Field(default=None, exclude_if=_empty)  # "L 165/1"
    publication_date_text: str | None = Field(default=None, exclude_if=_empty)
    publication_date: str | None = Field(default=None, exclude_if=_empty)
    metadata_provenance: dict[str, list[str]] = Field(default_factory=dict, exclude_if=_empty)  # field -> element ids


class DocumentModel(BaseModel):
    model_version: str = "0.1"
    profile: str | None = Field(default=None, exclude_if=_empty)  # "eu_legislation"; None = German-law parser
    review: dict | None = Field(default=None, exclude_if=_empty)  # effective model only: {"model_revision", "corrections"}
    source: SourceInfo
    metadata: DocumentMetadata
    root_id: str
    elements: list[Element]
    furniture: list[Element]  # page headers/footers, outside the tree
    warnings: list[ParserWarning]
    # valid structural exceptions the parser recognised and verified (not problems): kept for transparency
    structure_notes: list[ParserWarning] = Field(default_factory=list, exclude_if=lambda v: not v)
    # derived annotations over the elements (no element, id or text is changed by them)
    sentences: list[Sentence] = Field(default_factory=list, exclude_if=_empty)
    toc_entries: list[TocEntry] = Field(default_factory=list, exclude_if=_empty)

    def by_id(self) -> dict[str, Element]:
        return {e.id: e for e in self.elements}

    def of_type(self, *types: ElementType) -> list[Element]:
        return [e for e in self.elements if e.type in types]

    def children(self, element_id: str) -> list[Element]:
        index = self.by_id()
        return [index[c] for c in index[element_id].children_ids]

    def path(self, element_id: str) -> list[Element]:
        index = self.by_id()
        out: list[Element] = []
        cur: Element | None = index[element_id]
        while cur is not None:
            out.append(cur)
            cur = index.get(cur.parent_id) if cur.parent_id else None
        return out[::-1]
