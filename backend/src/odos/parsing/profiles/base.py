"""What a legal profile declares: the genuine differences between legal systems, nothing else.

Shared operations (preprocessing, sentences, TOC normalization, footnote resolution, public JSON export) are
written once and read these declarations. A profile module holds data and small hooks only; it must not import
the shared operation modules at import time (they import the registry).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from odos.document_model import DocumentMetadata, DocumentModel, ElementType as T


@dataclass(frozen=True)
class TocVocabulary:
    """How TOC lines name the units of this legal system and how deep each unit sits."""

    kinds: dict[T, str]  # body element type -> TOC kind
    levels: dict[str, int]  # TOC kind -> depth (a container closes all deeper scopes)
    containers: tuple[str, ...]  # kinds that open a scope for the entries below them
    # (kind, regex on the whitespace-free line with the number as group 1, number as the parser stores it)
    markers: tuple[tuple[str, re.Pattern, Callable[[str | None], str | None]], ...]
    provisions: tuple[T, ...] = ()  # body headings every TOC should link (reported when unlinked)
    inline_marker: str | None = None  # a kind that may start further entries inside one line ("§ 1 A § 2 B")
    inline_citation: re.Pattern | None = None  # text after an inline marker that makes it a citation ("§ 65 Absatz 2")
    ordinal: re.Pattern | None = None  # "ErsterTeil": groups (ordinal stem, kind word)
    ordinal_numbers: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class LegalProfile:
    mode: str  # processing mode / router value ("german_law", "eu_legislation")
    model_profile: str | None  # DocumentModel.profile written by this profile's parser (None: German, historic)
    legal_system: str  # public JSON `legalSystem`
    language: str  # language of the text the recognizer reads ("de")
    # the profile's lifecycle steps (parsing.engine runs them in a fixed order)
    recognize: Callable[[Any, list, dict], DocumentModel]  # (SourceInfo, preprocessed items, page sizes) -> model
    resolve_footnotes: Callable[[DocumentModel, Any], Any] | None  # post-parse footnote evidence (None: done in recognize)
    # sentences: which elements number their sentences, which elements are list items
    sentence_units: frozenset[T]
    units_if_no_subunits: dict[T, T]  # a § / article without Absätze / paragraphs is itself the unit
    list_types: frozenset[T]
    toc: TocVocabulary
    # public JSON
    json_types: dict[T, str]
    json_native_terms: dict[T, str]
    json_nesting: dict[str, set[str]]  # unit -> allowed parents ("document" = top level)
    json_document_type: Callable[[DocumentMetadata], str]
    json_id_parts: Callable[[DocumentMetadata], tuple[str, ...] | None]  # document id from type/number, if any
    # outputs and pipeline integration
    write_reports: Callable[[DocumentModel, Path, Path], Any]
    build_akn: Callable[[DocumentModel, str, Path], dict]  # (model, retrieval date, out dir) -> {validation, text, result}
    has_structure: Callable[[DocumentModel], bool]  # False: the document is not this kind of legislation
    unsupported_summary: dict  # pipeline summary keys when has_structure is False
    unsupported_message: str
    summary: Callable[[DocumentModel, Path], dict]  # pipeline summary of a parsed document
    akn_summary: Callable[[dict], dict]  # pipeline summary of the AKN artifacts
    completed_message: Callable[[dict], str]  # pipeline message, given the AKN artifacts
    akn_refused_message: Callable[[Exception], str]  # pipeline message when AKN refuses (e.g. a date is not printed)
    capabilities: frozenset[str] = frozenset()  # optional features: "akn_excerpt" (§ excerpt CLI), "akn4eu" export
