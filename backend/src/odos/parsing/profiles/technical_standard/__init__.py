"""Technical-standard profile: generic structural parser for DIN, DIN EN, DIN ISO, DIN EN ISO,
DIN VDE, DIN SPEC and standalone ISO / IEC / EN standards.

This profile targets *structural* parsing, not the technical content of the standard. It recognises:

* the standard's title block (e.g. ``DIN EN ISO 12100:2011-03``) and its metadata
* forewords (national / European / international) and introduction / scope
* dotted-number clauses ``1``, ``1.1``, ``1.1.1`` with arbitrary depth
* terms and definitions inside clause 3 (the standard ISO/IEC Directives convention)
* notes (``ANMERKUNG``, ``NOTE``), examples (``BEISPIEL``, ``EXAMPLE``)
* figures with captions (``Bild N — ...``, ``Figure N — ...``)
* tables with captions (``Tabelle N — ...``, ``Table N — ...``)
* annexes with their normativity attribute (``Anhang A (normativ)`` vs ``(informativ)``)
* bibliographies (``Literaturhinweise`` / ``Bibliography``)
* dash-bulleted and ``a)`` / ``1)`` enumerations common in technical standards
* numbered mathematical formulas (``(n)`` at the right margin)

The profile reuses the same shared engine, StructureBuilder, Legal JSON 2.0 schema and element model as
the German-law and EU-legislation profiles; nothing is hardcoded to a single standard family.
"""

from __future__ import annotations

import re
from pathlib import Path

from odos.document_model import DocumentMetadata, DocumentModel, ElementType as T
from odos.parsing.profiles.base import LegalProfile, TocVocabulary


def _same(n):
    return n


# --- document-type recognition (used by metadata) ---------------------------------------------------------
# Order matters: longer/more specific prefixes first.
STANDARD_FAMILIES: tuple[tuple[str, re.Pattern], ...] = (
    ("DIN EN ISO/IEC", re.compile(r"^DIN\s+EN\s+ISO/IEC\b")),
    ("DIN EN ISO", re.compile(r"^DIN\s+EN\s+ISO\b")),
    ("DIN EN IEC", re.compile(r"^DIN\s+EN\s+IEC\b")),
    ("DIN EN", re.compile(r"^DIN\s+EN\b")),
    ("DIN ISO/IEC", re.compile(r"^DIN\s+ISO/IEC\b")),
    ("DIN ISO", re.compile(r"^DIN\s+ISO\b")),
    ("DIN IEC", re.compile(r"^DIN\s+IEC\b")),
    ("DIN VDE", re.compile(r"^DIN\s+VDE\b")),
    ("DIN SPEC", re.compile(r"^DIN\s+SPEC\b")),
    ("DIN", re.compile(r"^DIN\b")),
    ("EN ISO", re.compile(r"^EN\s+ISO\b")),
    ("EN IEC", re.compile(r"^EN\s+IEC\b")),
    ("EN", re.compile(r"^EN\b")),
    ("ISO/IEC", re.compile(r"^ISO/IEC\b")),
    ("ISO", re.compile(r"^ISO\b")),
    ("IEC", re.compile(r"^IEC\b")),
    ("VDE", re.compile(r"^VDE\b")),
)


def _none(n):
    return None


# The compact (whitespace-free) TOC line starts with the printed number: "3.1Maschine....16", "AnhangC(informativ)...".
TOC = TocVocabulary(
    kinds={T.CLAUSE: "clause", T.DEFINITION: "clause", T.STANDARD_ANNEX: "annex", T.BIBLIOGRAPHY: "bibliography",
           T.FOREWORD: "foreword", T.INTRODUCTION: "introduction"},  # fmt: skip
    levels={"foreword": 1, "introduction": 1, "clause": 2, "annex": 1, "bibliography": 1},
    containers=(),  # the dotted number carries the hierarchy; no enclosing-heading check
    markers=(
        ("annex", re.compile(r"(?i:NationalerAnhang|Anhang|Annexe?)([A-Z]{1,2})(?=[^A-Za-z]|$|[A-Z][a-zäöüé])"), _same),
        ("clause", re.compile(r"((?:\d+|[A-Z]{1,2})(?:\.\d+)*(?:\.\d+)+|\d+)(?=[A-Za-zÄÖÜäöü])"), _same),
        ("foreword", re.compile(r"(Vorwort|Foreword)"), _none),
        ("introduction", re.compile(r"(Einleitung|Introduction)"), _none),
        ("bibliography", re.compile(r"(Literaturhinweise|Bibliography)"), _none),
    ),
    provisions=(T.CLAUSE,),
    split_toc_rows=True,  # DIN/ISO contents tables: two numbers in one cell, or the same number again for a second language
    title_trailer=re.compile(r"[\s.\u2026]{3,}\d*\s*$"),  # "Maschine ........ 16"
)


def _recognize(info, items, page_sizes) -> DocumentModel:
    from odos.parsing.profiles.technical_standard.recognizer import parse_ts_items

    return parse_ts_items(info, items, page_sizes)


def _write_reports(model, docling_json: Path, out_dir: Path):
    from odos.parsing.profiles.technical_standard.report import write_ts_outputs

    return write_ts_outputs(model, docling_json, out_dir)


def _summary(model, docling_json: Path) -> dict:
    return {
        "profile": model.profile,
        "clauses": len(model.of_type(T.CLAUSE)),
        "definitions": len(model.of_type(T.DEFINITION)),
        "annexes": len(model.of_type(T.STANDARD_ANNEX)),
        "figures": len(model.of_type(T.FIGURE)),
        "tables": len(model.of_type(T.TABLE)),
        "formulas": len(model.of_type(T.FORMULA)),
        "notes": len(model.of_type(T.NOTE)),
        "examples": len(model.of_type(T.EXAMPLE)),
        "bibliographic_entries": len(model.of_type(T.BIBLIOGRAPHIC_ENTRY)),
        "elements": len(model.elements),
        "parser_warnings": len(model.warnings),
        "uncertain_elements": sum(e.uncertain for e in model.elements),
    }


_SCOPE = re.compile(r"^(scope|anwendungsbereich|domaine d.application)\b", re.I)
_NORMATIVE = re.compile(r"^(normative references|normative verweisungen|r.f.rences normatives)\b", re.I)


_BODY_UNITS = (T.CLAUSE, T.DEFINITION, T.FOREWORD, T.INTRODUCTION, T.STANDARD_ANNEX, T.BIBLIOGRAPHY, T.INDEX, T.TABLE, T.FIGURE)


def _has_structure(model: DocumentModel) -> bool:
    """A technical standard: a standard identifier (DIN EN ISO 12100, ETSI EN 303 645, ...) plus any structure of its own, or numbered
    clauses with the clause fingerprint of the ISO/IEC drafting rules (Scope, Normative references). Numbered clauses alone are not
    enough: manuals and contracts have them too. Corrigenda, amendments and supplements often have no clauses at all, only forewords,
    tables or a contents list, so for an identified document those count as well."""
    clauses = [c for c in model.of_type(T.CLAUSE, T.DEFINITION) if c.number]
    titles = [c.title or "" for c in clauses if "." not in c.number]
    fingerprint = any(_SCOPE.match(x) for x in titles) and any(_NORMATIVE.match(x) for x in titles)
    if not model.metadata.document_number:
        return bool(clauses) and fingerprint
    toc = model.by_id().get("doc/toc")
    toc_lines = max(len(model.toc_entries), len(toc.children_ids) if toc is not None else 0)
    return toc_lines >= 3 or any(e.type in _BODY_UNITS and e.region != "toc" for e in model.elements)


def _document_id_parts(md: DocumentMetadata) -> tuple[str, ...] | None:
    if md.document_type and md.document_number:
        return (md.document_type, md.document_number, *([md.document_variant] if md.document_variant else []),
                *([md.language] if md.language else []))
    return None


def _document_type(md: DocumentMetadata) -> str:
    return "technical_standard"


TECHNICAL_STANDARD = LegalProfile(
    mode="technical_standard",
    model_profile="technical_standard",
    legal_system="ts",
    language="de",  # recognizer tuned for German-language DIN; English patterns included for ISO / IEC originals
    recognize=_recognize,
    resolve_footnotes=None,
    # Technical standards do not carry the German "Satz" numbering concept; structural clauses are
    # the canonical unit. We leave sentence segmentation out for the prototype — the model stays
    # structurally accurate and consumers can segment on demand from the exported clause text.
    sentence_units=frozenset(),
    units_if_no_subunits={},
    list_types=frozenset({T.LIST_ITEM, T.DASH_ITEM}),
    toc=TOC,
    json_types={
        T.STANDARD_TITLE: "standardTitle",
        T.FOREWORD: "foreword",
        T.INTRODUCTION: "introduction",
        T.CLAUSE: "clause",
        T.DEFINITION: "definition",
        T.NOTE: "note",
        T.EXAMPLE: "example",
        T.FIGURE: "figure",
        T.FORMULA: "formula",
        T.BIBLIOGRAPHY: "bibliography",
        T.BIBLIOGRAPHIC_ENTRY: "bibliographicEntry",
        T.INDEX: "index",
        T.LIST_ITEM: "listItem",
        T.DASH_ITEM: "dashItem",
        T.STANDARD_ANNEX: "annex",
    },
    json_native_terms={
        T.FOREWORD: "Vorwort",
        T.INTRODUCTION: "Einleitung",
        T.CLAUSE: "Abschnitt",
        T.DEFINITION: "Definition",
        T.NOTE: "Anmerkung",
        T.EXAMPLE: "Beispiel",
        T.FIGURE: "Bild",
        T.FORMULA: "Formel",
        T.BIBLIOGRAPHY: "Literaturhinweise",
        T.BIBLIOGRAPHIC_ENTRY: "Literaturquelle",
        T.INDEX: "Stichwortverzeichnis",
        T.STANDARD_ANNEX: "Anhang",
    },
    json_nesting={
        "standardTitle": {"document"},
        "foreword": {"document"},
        "introduction": {"document"},
        "clause": {"document", "clause", "annex", "foreword", "introduction"},
        "definition": {"clause", "definition"},
        "note": {"clause", "definition", "annex", "foreword", "introduction", "listItem", "dashItem", "figure", "table"},
        "example": {"clause", "definition", "annex", "foreword", "introduction", "listItem", "dashItem"},
        "figure": {"clause", "definition", "annex", "introduction", "foreword"},
        "formula": {"clause", "definition", "annex", "foreword", "introduction", "listItem"},
        "bibliography": {"document", "annex"},  # a national annex (DIN "Nationaler Anhang NA") holds its own bibliography
        "bibliographicEntry": {"bibliography"},
        "index": {"document"},
        "listItem": {"clause", "definition", "annex", "foreword", "introduction", "listItem", "dashItem", "note", "example"},
        "dashItem": {"clause", "definition", "annex", "foreword", "introduction", "listItem", "dashItem", "note", "example"},
        "annex": {"document"},
        "sentence": {"clause", "definition", "annex", "introduction", "foreword", "listItem", "dashItem"},
    },
    json_document_type=_document_type,
    json_id_parts=_document_id_parts,
    write_reports=_write_reports,
    has_structure=_has_structure,
    unsupported_summary={"clauses": 0},
    unsupported_message=(
        "No technical standard structure was found: numbered clauses ('1 Scope', '3.1 term') together with a standard "
        "identifier (e.g. 'DIN EN ISO 12100') or the Scope / Normative references clauses are required. "
        "ODOS does not produce a technical-standard Legal JSON for this document. The Docling extraction "
        "(raw JSON and Markdown) is still available."
    ),
    summary=_summary,
    read_nested_items=True,  # DIN figures and tables keep their captions as children of the picture/table
    completed_message=(
        "Technical standard (prototype): structure extracted and Custom Legal JSON generated. "
        "Structural rules cover DIN, DIN EN, DIN ISO, DIN EN ISO, DIN VDE, DIN SPEC and standalone ISO/IEC/EN "
        "standards; review parser warnings before downstream use."
    ),
)
