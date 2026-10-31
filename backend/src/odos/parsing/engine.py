"""The shared parsing lifecycle: Docling JSON -> canonical `DocumentModel`, the same for every legal profile.

The stages run in this fixed order; each one only reads what the stages before it produced:

1. ``read_source``         Docling items and page sizes (``docling_reader``).
2. ``load_evidence``       the PDF text layer (``reading_order.load_evidence``: text lines, small marks, glyph
                           lines, region lines). Ignored unless it is bound to the same PDF and Docling hashes.
3. ``preprocess``          ``hygiene.apply_hygiene``: running furniture -> layout overlaps -> reading-order repair
                           (works on Docling's text, so before restoration) -> text restoration (``source_text``;
                           before segmentation, whose offsets index the canonical text) -> segmentation of merged
                           items -> highlight geometry (needs the final segments).
4. ``parse_structure``     the profile's recognizer (``LegalProfile.recognize``): the only stage that assigns
                           element ids. Everything after it annotates or moves elements, never renumbers them.
5. ``finalize_structure``  page furniture that Docling labelled as body text leaves the legal structure for
                           ``model.furniture`` (``parsing.furniture.detach_page_furniture``); ids are kept.
6. ``resolve_footnotes``   the profile's footnote strategy on the final tree (German: "*" notes and superscript
                           reference marks; it needs the page furniture detached). EU acts have none here: their
                           "( n )" marks decide the footnote ids, so the recognizer anchors them in stage 4.
7. ``segment_sentences``   ``sentences.segment`` (units and list types from the profile; printed Satz numbers
                           from the evidence share the mark classifier with stage 6).
8. ``normalize_toc``       ``toc.normalize_toc`` (the profile's ``TocVocabulary``); needs the final body to link to.

Validation (content accounting, sequence and structure reports) is not a parsing stage: it reads the finished
model and is written by ``LegalProfile.write_reports``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from odos.normalization.docling_reader import SourceItem, read_docling_json, read_page_sizes
from odos.document_model import DocumentModel, SourceInfo
from odos.parsing.profiles import LegalProfile


@dataclass
class ParseState:
    """What the stages hand on to each other."""

    path: Path
    profile: LegalProfile
    info: SourceInfo | None = None
    items: list[SourceItem] | None = None
    page_sizes: dict[int, tuple[float, float]] | None = None
    evidence: Any = None
    model: DocumentModel | None = None


def read_source(s: ParseState) -> None:
    s.info, s.items = read_docling_json(s.path)
    s.page_sizes = read_page_sizes(s.path)


def load_evidence(s: ParseState) -> None:
    from odos.normalization.reading_order import load_evidence as load

    s.evidence = load(s.path)


def preprocess(s: ParseState) -> None:
    from odos.normalization.hygiene import apply_hygiene

    s.items = apply_hygiene(s.items, s.page_sizes, s.evidence).items


def parse_structure(s: ParseState) -> None:
    s.model = s.profile.recognize(s.info, s.items, s.page_sizes)


def finalize_structure(s: ParseState) -> None:
    from odos.parsing.furniture import detach_page_furniture

    detach_page_furniture(s.model)


def resolve_footnotes(s: ParseState) -> None:
    if s.profile.resolve_footnotes is not None:
        s.profile.resolve_footnotes(s.model, s.evidence)


def segment_sentences(s: ParseState) -> None:
    from odos.parsing.sentences import segment

    segment(s.model, s.evidence)


def normalize_toc(s: ParseState) -> None:
    from odos.parsing.toc import normalize_toc as normalize

    normalize(s.model, s.evidence)


STAGES: tuple[tuple[str, Callable[[ParseState], None]], ...] = (
    ("read_source", read_source),
    ("load_evidence", load_evidence),
    ("preprocess", preprocess),
    ("parse_structure", parse_structure),
    ("finalize_structure", finalize_structure),
    ("resolve_footnotes", resolve_footnotes),
    ("segment_sentences", segment_sentences),
    ("normalize_toc", normalize_toc),
)


def parse(path: Path, profile: LegalProfile, trace: list[str] | None = None) -> DocumentModel:
    """Run the lifecycle on a Docling JSON file. `trace`, if given, receives the name of each stage as it ends."""
    state = ParseState(path=Path(path), profile=profile)
    for name, stage in STAGES:
        stage(state)
        if trace is not None:
            trace.append(name)
    return state.model
