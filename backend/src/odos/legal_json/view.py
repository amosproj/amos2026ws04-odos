"""Public JSON representation of a legal document (`document.json`, schema odos-legal-json 2.0).

Output-only serialization classes. They are built solely by `odos.legal_json.exporter.to_legal_json`
from the canonical `DocumentModel`; nothing reads `document.json` back as input. The published JSON
Schema is generated from these classes (`json_schema()`), so there is one definition of the format.

2.0 carries the legal structure and text only. Technical provenance (Docling item references, boxes, character
offsets into source items, coordinate system, page sizes) stays in the DocumentModel, which the node `id`s refer to.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "2.0"
SCHEMA_ID = "https://github.com/amosproj/amos2026ws04-odos/schemas/odos-legal-json/2.0/legal-document.schema.json"

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

DocumentType = Literal["de_legislation", "eu_regulation", "eu_directive", "eu_decision", "eu_legislation", "technical_standard"]


def _none(v) -> bool:
    return v is None


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Node(_Out):
    id: str = Field(description="the element id of the DocumentModel (stable, unique)")
    type: NodeType
    nativeType: str | None = Field(default=None, exclude_if=_none, description="term of the source legal tradition")
    number: str | None = Field(default=None, exclude_if=_none)
    marker: str | None = Field(default=None, exclude_if=_none, description="exact marker as printed")
    title: str | None = Field(default=None, exclude_if=_none)
    text: str | None = Field(default=None, exclude_if=_none, description="the element's own text, without marker, title or children")
    numRows: int | None = Field(default=None, exclude_if=_none)
    numCols: int | None = Field(default=None, exclude_if=_none)
    rows: list[list[str]] | None = Field(default=None, exclude_if=_none, description="table cell texts, row by row")
    pages: list[int] = Field(default_factory=list, exclude_if=lambda v: not v, description="PDF pages the element is printed on")
    children: list[Node] = Field(default_factory=list, exclude_if=lambda v: not v)


class Footnote(_Out):
    id: str
    marker: str | None = Field(default=None, exclude_if=_none)
    number: str | None = Field(default=None, exclude_if=_none)
    title: str | None = Field(default=None, exclude_if=_none)
    text: str | None = Field(default=None, exclude_if=_none)
    pages: list[int] = Field(default_factory=list, exclude_if=lambda v: not v)
    content: list[Node] = Field(default_factory=list, exclude_if=lambda v: not v)
    anchorElementIds: list[str] = Field(default_factory=list, exclude_if=lambda v: not v,
                                        description="the elements the footnote belongs to, set only when source evidence establishes them")
    references: list[FootnoteReference] = Field(default_factory=list, exclude_if=lambda v: not v,
                                                description="each printed reference mark")


class FootnoteReference(_Out):
    elementId: str
    marker: str
    page: int


class TextRange(_Out):
    """[start, end) in Python str indices (Unicode code points) into the `text` of node `elementId` in this file."""

    elementId: str
    start: int
    end: int


class LegalSentence(_Out):
    """A legal sentence as ordered text ranges, possibly across several nodes (an Absatz, its list items and the
    text after the list). Text is never repeated: read it from the referenced nodes."""

    id: str
    unitId: str
    number: str | None = Field(default=None, exclude_if=_none, description="only when the document prints the Satz number")
    marker: TextRange | None = Field(default=None, exclude_if=_none, description="where the printed number stands")
    ranges: list[TextRange]


class TocTextRange(_Out):
    """[start, end) into the text of a tableOfContents node (or of one of its table cells)."""

    elementId: str = Field(description="a node of tableOfContents")
    cell: list[int] | None = Field(default=None, exclude_if=_none, description="[row, col] when the text is in a table cell")
    start: int
    end: int


class TocEntryOut(_Out):
    """One logical TOC line, rebuilt from the raw tableOfContents nodes (which stay unchanged)."""

    id: str
    kind: str
    marker: str
    number: str | None = Field(default=None, exclude_if=_none)
    title: str | None = Field(default=None, exclude_if=_none)
    level: int
    targetElementId: str | None = Field(default=None, exclude_if=_none, description="only for a confirmed link")
    ranges: list[TocTextRange]


class Version(_Out):
    statement: str | None = None
    date: str | None = None


class Identifiers(_Out):
    documentNumber: str | None = Field(default=None, exclude_if=_none)
    publicationJournal: str | None = Field(default=None, exclude_if=_none)
    publicationReference: str | None = Field(default=None, exclude_if=_none)
    citation: str | None = Field(default=None, exclude_if=_none)


class LegalDocument(_Out):
    schemaVersion: Literal["2.0"] = SCHEMA_VERSION
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
    pageCount: int
    frontMatter: list[Node]
    tableOfContents: list[Node]
    structure: list[Node]
    footnotes: list[Footnote]
    tableOfContentsEntries: list[TocEntryOut] = Field(default_factory=list, exclude_if=lambda v: not v)
    sentences: list[LegalSentence] = Field(default_factory=list, exclude_if=lambda v: not v)


Footnote.model_rebuild()


def json_schema() -> dict:
    schema = LegalDocument.model_json_schema(mode="serialization")
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": SCHEMA_ID, **schema}
