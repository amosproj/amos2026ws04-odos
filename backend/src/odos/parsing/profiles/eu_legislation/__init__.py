"""EU-legislation profile: preamble (citations, recitals), KAPITEL/ABSCHNITT/Artikel, numbered paragraphs, points,
ANHANG/TEIL, conclusions. Prototype verified on German-language regulations of the Official Journal (2023/1230).

This package holds everything EU-legislation specific: the recognizer with its rules (`recognizer`; footnotes are
anchored there, while the structure is built, because their "( n )" reference marks decide which element carries
them) and the validation report (`report`). Hooks import the package's modules lazily (no import cycles).
"""

from __future__ import annotations

import re
from pathlib import Path

from odos.document_model import DocumentModel, ElementType as T
from odos.parsing.profiles.base import LegalProfile, TocVocabulary


def _same(n):
    return n


# the EU parser stores the printed number ("IX", "A"), so TOC numbers stay printed too. Markers are matched on the
# whitespace-free line: "(?![a-z])" ends a numeral before the title ("KAPITELIVLieferketten" -> "IV", not "IVL")
TOC = TocVocabulary(
    kinds={T.CHAPTER: "chapter", T.SECTION: "section", T.ARTICLE: "article", T.ANNEX: "annex", T.ANNEX_PART: "part"},
    levels={"chapter": 2, "section": 3, "article": 5, "annex": 1, "part": 2},
    containers=("chapter", "section"),
    markers=(
        ("article", re.compile(r"Artikel(\d+[a-z]?)"), _same),
        ("chapter", re.compile(r"KAPITEL([IVXLC]+(?![a-z]))"), _same),
        ("section", re.compile(r"ABSCHNITT(\d+|[IVXLC]+(?![a-z]))"), _same),
        ("annex", re.compile(r"ANHANG([IVXLC]+(?![a-z]))?"), _same),
        ("part", re.compile(r"TEIL(\d+|[IVX]+(?![a-z])|[A-Z](?![a-z]))"), _same),
    ),
    provisions=(T.ARTICLE,),
)

DOCUMENT_TYPES = {"VERORDNUNG": "eu_regulation", "RICHTLINIE": "eu_directive", "BESCHLUSS": "eu_decision"}


def _recognize(info, items, page_sizes) -> DocumentModel:
    from odos.parsing.profiles.eu_legislation.recognizer import parse_eu_items

    return parse_eu_items(info, items, page_sizes)


def _write_reports(model, docling_json: Path, out_dir: Path):
    from odos.parsing.profiles.eu_legislation.report import write_eu_outputs

    return write_eu_outputs(model, docling_json, out_dir)


def _build_akn(model, retrieval_date: str, out: Path) -> dict:
    from odos.akn.eu_artifacts import build_eu_akn_artifacts

    return build_eu_akn_artifacts(model, retrieval_date, out)


def _summary(model, docling_json: Path) -> dict:
    from odos.parsing.profiles.eu_legislation.report import build_eu_report

    rep = build_eu_report(model, docling_json)
    return {
        "profile": model.profile,
        "recitals": len(model.of_type(T.RECITAL)),
        "chapters": len(model.of_type(T.CHAPTER)),
        "articles": len(model.of_type(T.ARTICLE)),
        "annexes": len(model.of_type(T.ANNEX)),
        "elements": len(model.elements),
        "parser_warnings": len(model.warnings),
        "uncertain_elements": sum(e.uncertain for e in model.elements),
        "source_accounting_exact": rep.accounting["exact"],
    }


def _akn_summary(art: dict) -> dict:
    v, t = art["validation"], art["text"]
    return {
        "akn_generated": True,
        "akn_xsd_valid": v.valid,
        "akn_xsd_errors": len(v.errors),
        "akn_text_identical": t["same_order_and_text"],
        "akn_document_order_preserved": t["document_order_preserved"],
        "akn_unmapped": len(t["unmapped"]),
    }


def _completed_message(art: dict) -> str:
    v = art["validation"]
    status = "valid against the official OASIS XSD (Akoma Ntoso 3.1)" if v.valid else f"INVALID ({len(v.errors)} XSD errors, see the validation report)"  # fmt: skip
    return f"EU legislation (prototype): structure extracted and Akoma Ntoso XML generated, {status}."


def _document_id_parts(md) -> tuple[str, ...] | None:
    return (md.document_type, md.document_number) if md.document_type and md.document_number else None


EU_LEGISLATION = LegalProfile(
    mode="eu_legislation",
    model_profile="eu_legislation",
    legal_system="eu",
    language="de",
    recognize=_recognize,
    resolve_footnotes=None,
    sentence_units=frozenset({T.ARTICLE_PARAGRAPH, T.RECITAL}),
    units_if_no_subunits={T.ARTICLE: T.ARTICLE_PARAGRAPH},
    list_types=frozenset({T.POINT, T.NUMBERED_POINT, T.SUBPOINT}),
    toc=TOC,
    json_types={
        T.PREAMBLE: "preamble", T.PREAMBLE_FORMULA: "preambleFormula", T.CITATION: "citation",
        T.RECITALS_INTRO: "recitalsIntro", T.RECITAL: "recital", T.ENACTING_FORMULA: "enactingFormula",
        T.CHAPTER: "chapter", T.SECTION: "section", T.ARTICLE: "article", T.ARTICLE_PARAGRAPH: "paragraph",
        T.NUMBERED_POINT: "point", T.POINT: "point", T.SUBPOINT: "subpoint", T.ANNEX: "annex",
        T.ANNEX_PART: "part", T.ANNEX_HEADING: "heading", T.CONCLUSIONS: "conclusions",
        T.FINAL_FORMULA: "finalFormula", T.SIGNATURE: "signature",
    },  # fmt: skip
    # the German words of German-language EU acts
    json_native_terms={
        T.CHAPTER: "Kapitel", T.SECTION: "Abschnitt", T.ARTICLE: "Artikel", T.ARTICLE_PARAGRAPH: "Absatz",
        T.SENTENCE: "Satz", T.NUMBERED_POINT: "Nummer", T.POINT: "Buchstabe", T.SUBPOINT: "Ziffer", T.RECITAL: "Erwägungsgrund",
        T.ANNEX: "Anhang", T.ANNEX_PART: "Teil", T.ANNEX_HEADING: "Nummer",
    },  # fmt: skip
    json_nesting={
        "preamble": {"document"},
        "preambleFormula": {"preamble"},
        "citation": {"preamble"},
        "recitalsIntro": {"preamble"},
        "recital": {"preamble"},
        "enactingFormula": {"preamble"},
        "title": {"document"},
        "chapter": {"document", "title"},
        "section": {"chapter"},
        "article": {"document", "chapter", "section"},
        "paragraph": {"article", "heading"},
        "sentence": {"article", "paragraph", "point", "subpoint", "recital"},
        "point": {"article", "paragraph", "point", "annex", "part", "heading"},
        "subpoint": {"point", "heading"},
        "numeral": {"subpoint"},
        "annex": {"document"},
        "part": {"annex"},
        "heading": {"annex", "part", "heading"},
        "conclusions": {"document"},
        "finalFormula": {"conclusions"},
        "signature": {"conclusions"},
    },
    json_document_type=lambda md: DOCUMENT_TYPES.get((md.document_type or "").upper(), "eu_legislation"),
    json_id_parts=_document_id_parts,
    write_reports=_write_reports,
    build_akn=_build_akn,
    has_structure=lambda model: bool(model.of_type(T.ARTICLE)),
    unsupported_summary={"articles": 0},
    unsupported_message=("No EU article structure ('Artikel <n>') was found. ODOS does not produce an EU legal structure "
                         "for this document. The Docling extraction (raw JSON and Markdown) is still available."),  # fmt: skip
    summary=_summary,
    akn_summary=_akn_summary,
    completed_message=_completed_message,
    akn_refused_message=lambda exc: f"EU legislation structure extracted (prototype). Akoma Ntoso XML was not generated: {exc}",
    capabilities=frozenset({"akn4eu"}),
)
