"""Public JSON representation of a legal document (`document.json`, schema odos-legal-json 1.1).

Output-only serialization classes. They are built solely by `odos.legal_json.exporter.to_legal_json`
from the canonical `DocumentModel`; nothing reads `document.json` back as input. The published JSON
Schema is generated from these classes (`json_schema()`), so there is one definition of the format.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# the documented path for 1.0 consumers (Documentation/legal-json.md); the 1.0 code lives in legal_json.legacy
from odos.legal_json.legacy import downgrade_to_1_0  # noqa: F401

SCHEMA_VERSION = "1.1"  # 1.1 = 1.0 + optional sentences, TOC entries, multiple footnote references, cell boxes
SCHEMA_ID = "https://github.com/amosproj/amos2026ws04-odos/schemas/odos-legal-json/1.1/legal-document.schema.json"

NodeType = Literal[
    # general
    "part", "title", "chapter", "division", "subdivision", "section", "article", "subsection", "paragraph",
    "sentence", "number", "letter", "point", "subpoint", "numeral", "annex", "heading", "text", "item",
    "table", "picture",
    # EU preamble and conclusions
    "preamble", "preambleFormula", "citation", "recitalsIntro", "recital", "enactingFormula",
    "conclusions", "finalFormula", "signature",
    # outside the legal body
    "frontMatter", "documentTitle", "tableOfContents", "tocEntry",
]  # fmt: skip

MarkerStyle = Literal[
    "arabic", "roman_upper", "roman_lower", "alpha_lower", "alpha_upper", "alpha_lower_double",
    "decimal_hierarchy", "section_sign", "ordinal_word", "symbol",
]  # fmt: skip

DocumentType = Literal["de_legislation", "eu_regulation", "eu_directive", "eu_decision", "eu_legislation", "technical_standard"]


def _none(v) -> bool:
    return v is None


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class BoundingBox(_Out):
    """PDF user space in points, origin bottom-left (top > bottom). See `CoordinateSystem`."""

    left: float
    top: float
    right: float
    bottom: float


class SourceSpan(_Out):
    itemRef: str | None = Field(default=None, exclude_if=_none, description="Docling item reference, e.g. '#/texts/373'")
    page: int | None = Field(default=None, exclude_if=_none)
    bbox: BoundingBox | None = Field(default=None, exclude_if=_none)
    charStart: int | None = Field(default=None, exclude_if=_none, description="offset into the source item's verbatim text")
    charEnd: int | None = Field(default=None, exclude_if=_none)
    bboxScope: Literal["source_item"] = Field(
        default="source_item", description="the box covers the whole source item, not only this span's characters"
    )


class Source(_Out):
    pages: list[int]
    sourceSpans: list[SourceSpan]


class CellSource(_Out):
    page: int
    bbox: BoundingBox


class TableCell(_Out):
    text: str
    source: CellSource | None = Field(default=None, exclude_if=_none, description="1.1: the cell's own box, where Docling gives one")


class Node(_Out):
    id: str
    type: NodeType
    nativeType: str | None = Field(default=None, exclude_if=_none, description="term of the source legal tradition")
    marker: str | None = Field(default=None, exclude_if=_none, description="exact marker as printed")
    markerStyle: MarkerStyle | None = Field(default=None, exclude_if=_none)
    number: str | None = Field(default=None, exclude_if=_none)
    title: str | None = Field(default=None, exclude_if=_none)
    text: str | None = Field(default=None, exclude_if=_none, description="the element's own text, without marker, title or children")
    numRows: int | None = Field(default=None, exclude_if=_none)
    numCols: int | None = Field(default=None, exclude_if=_none)
    rows: list[list[TableCell]] | None = Field(default=None, exclude_if=_none)
    source: Source
    children: list[Node] = Field(default_factory=list, exclude_if=lambda v: not v)


class Footnote(_Out):
    id: str
    marker: str | None = Field(default=None, exclude_if=_none)
    number: str | None = Field(default=None, exclude_if=_none)
    title: str | None = Field(default=None, exclude_if=_none)
    text: str | None = Field(default=None, exclude_if=_none)
    source: Source
    content: list[Node] = Field(default_factory=list, exclude_if=lambda v: not v)
    anchorElementId: str | None = Field(description="the single anchor, set only when source evidence establishes it; "
                                                     "null when there is none or more than one (see anchorElementIds)")
    anchorElementIds: list[str] = Field(default_factory=list, exclude_if=lambda v: not v,
                                        description="1.1: every element that prints a reference to this footnote")
    references: list[FootnoteReference] = Field(default_factory=list, exclude_if=lambda v: not v,
                                                description="1.1: each printed reference mark, with its glyph box where known")


class FootnoteReference(_Out):
    elementId: str
    marker: str
    page: int
    bbox: BoundingBox | None = Field(default=None, exclude_if=_none, description="the reference mark's own glyph box")


class TextRange(_Out):
    """[start, end) in Python str indices (Unicode code points) into the `text` of node `elementId` in this file."""

    elementId: str
    start: int
    end: int
    textSha256: str = Field(description="SHA-256 (UTF-8) of that node's `text`: detects a range used on another revision")


class SentenceNumberSource(_Out):
    page: int
    bbox: BoundingBox


class LegalSentence(_Out):
    """1.1: a legal sentence as ordered text ranges, possibly across several nodes (an Absatz, its list items and
    the text after the list). Text is never repeated: read it from the referenced nodes."""

    id: str
    unitId: str
    number: str | None = Field(default=None, exclude_if=_none, description="only when the document prints the Satz number")
    marker: TextRange | None = Field(default=None, exclude_if=_none, description="where the printed number stands")
    numberSource: SentenceNumberSource | None = Field(default=None, exclude_if=_none, description="the printed number's glyph box")
    ranges: list[TextRange]


class TocSourceSpan(_Out):
    elementId: str = Field(description="a node of tableOfContents")
    cell: list[int] | None = Field(default=None, exclude_if=_none, description="[row, col] when the text is in a table cell")
    start: int
    end: int
    page: int | None = Field(default=None, exclude_if=_none)
    bbox: BoundingBox | None = Field(default=None, exclude_if=_none)
    bboxScope: Literal["text_line", "table_cell", "source_item"]


class TocEntryOut(_Out):
    """1.1: one logical TOC line, rebuilt from the raw tableOfContents nodes (which stay unchanged)."""

    id: str
    kind: str
    marker: str
    number: str | None = Field(default=None, exclude_if=_none)
    title: str | None = Field(default=None, exclude_if=_none)
    level: int
    targetElementId: str | None = Field(default=None, exclude_if=_none, description="only for a confirmed link")
    sourceSpans: list[TocSourceSpan]


class Version(_Out):
    statement: str | None = None
    date: str | None = None


class Identifiers(_Out):
    documentNumber: str | None = Field(default=None, exclude_if=_none)
    publicationJournal: str | None = Field(default=None, exclude_if=_none)
    publicationReference: str | None = Field(default=None, exclude_if=_none)
    citation: str | None = Field(default=None, exclude_if=_none)


class SourceFile(_Out):
    filename: str | None = None
    doclingJsonSha256: str


class PageSize(_Out):
    number: int
    width: float
    height: float


class CoordinateSystem(_Out):
    space: Literal["pdf_user_space"] = "pdf_user_space"
    unit: Literal["pt"] = "pt"
    origin: Literal["bottom-left"] = "bottom-left"
    note: str = "top > bottom; top-left viewer y = page height - top"


class LegalDocument(_Out):
    schemaVersion: Literal["1.1"] = SCHEMA_VERSION
    id: str
    title: str | None
    shortTitle: str | None = Field(default=None, exclude_if=_none)
    documentType: DocumentType
    nativeDocumentType: str | None = Field(default=None, exclude_if=_none)
    legalSystem: Literal["de", "eu"]
    language: str
    version: Version
    publicationDate: str | None = Field(default=None, exclude_if=_none)
    adoptionDate: str | None = Field(default=None, exclude_if=_none)
    enactmentDate: str | None = Field(default=None, exclude_if=_none)
    subject: str | None = Field(default=None, exclude_if=_none)
    identifiers: Identifiers
    sourceFile: SourceFile
    pageCount: int
    coordinateSystem: CoordinateSystem = CoordinateSystem()
    pages: list[PageSize] | None = Field(default=None, exclude_if=_none)
    frontMatter: list[Node]
    tableOfContents: list[Node]
    structure: list[Node]
    footnotes: list[Footnote]
    tableOfContentsEntries: list[TocEntryOut] = Field(default_factory=list, exclude_if=lambda v: not v)  # 1.1
    sentences: list[LegalSentence] = Field(default_factory=list, exclude_if=lambda v: not v)  # 1.1


Footnote.model_rebuild()

def json_schema() -> dict:
    schema = LegalDocument.model_json_schema(mode="serialization")
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": SCHEMA_ID, **schema}
