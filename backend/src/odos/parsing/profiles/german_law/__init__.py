"""German-law profile: § provisions, Teil/Kapitel/Abschnitt/Unterabschnitt, Absatz, Nummer, Buchstabe, Anlage.

This package holds everything German-law specific: the recognition rules (`rules`), the recognizer (`recognizer`)
and the validation report (`report`). This module declares what the shared engine and operations need to know about
German legislation; its hooks import the package's modules lazily (no import cycles).
"""

from __future__ import annotations

import re
from pathlib import Path

from odos.normalization.lang_de import ORDINAL_STEMS
from odos.document_model import DocumentModel, ElementType as T
from odos.parsing.profiles.base import LegalProfile, TocVocabulary

_ORD = "|".join(sorted((s for s in ORDINAL_STEMS), key=len, reverse=True))


def _same(n):
    return n


TOC = TocVocabulary(
    kinds={T.TEIL: "teil", T.KAPITEL: "kapitel", T.ABSCHNITT: "abschnitt", T.UNTERABSCHNITT: "unterabschnitt",
           T.PARAGRAPH: "paragraph", T.ANLAGE: "anlage"},  # fmt: skip
    levels={"teil": 1, "kapitel": 2, "abschnitt": 3, "unterabschnitt": 4, "paragraph": 5, "article": 5, "anlage": 1},
    containers=("teil", "kapitel", "abschnitt", "unterabschnitt"),
    # on the whitespace-free line; "Artikel" (Artikelgesetze) and "Anhang" are German usage too
    markers=(
        ("paragraph", re.compile(r"§(?!§)(\d+[a-z]?)(?![\d])"), _same),
        ("article", re.compile(r"(?:Artikel|ARTIKEL)(\d+[a-z]?)"), _same),
        ("teil", re.compile(r"(?:Teil|TEIL)(\d+|[A-Z](?![a-z]))"), _same),
        ("kapitel", re.compile(r"(?:Kapitel|KAPITEL)(\d+|[IVXLC]+(?![a-z]))"), _same),
        ("unterabschnitt", re.compile(r"(?:Unterabschnitt|UNTERABSCHNITT)(\d+)"), _same),
        ("abschnitt", re.compile(r"(?:Abschnitt|ABSCHNITT)(\d+)"), _same),
        ("anlage", re.compile(r"(?:Anlage|ANLAGE|Anhang|ANHANG)(\d+|[IVXLC]+(?![a-z]))?"), _same),
    ),
    provisions=(T.PARAGRAPH,),
    inline_marker="paragraph",
    inline_citation=re.compile(r"^(Abs\.|Absatz|Absätze|Nr\.|Satz|Buchst)"),
    ordinal=re.compile(rf"({_ORD})(?:er|e|es|en)?(Teil|Kapitel|Abschnitt|Unterabschnitt)"),  # stems: "Erst" + "er"
    ordinal_numbers=ORDINAL_STEMS,
)


def _recognize(info, items, page_sizes) -> DocumentModel:
    from odos.parsing.profiles.german_law.recognizer import parse_items
    from odos.parsing.profiles.german_law.rules import GERMAN_LAW_RULES

    return parse_items(info, items, GERMAN_LAW_RULES)


def _resolve_footnotes(model: DocumentModel, evidence) -> None:
    from odos.parsing.footnotes import anchor_page_footnotes, recognise_marked_notes

    recognise_marked_notes(model, evidence)  # "* ..." notes in the front matter / TOC
    anchor_page_footnotes(model, evidence)  # superscript reference marks


def _write_reports(model, docling_json: Path, out_dir: Path):
    from odos.parsing.profiles.german_law.report import write_outputs

    return write_outputs(model, docling_json, out_dir)


def _build_akn(model, retrieval_date: str, out: Path) -> dict:
    from odos.akn.german_artifacts import build_artifacts
    from odos.artifact_names import AKN_XML

    pars = [p.number for p in model.of_type(T.PARAGRAPH)]
    return build_artifacts(model, pars, retrieval_date, out, xml_name=AKN_XML, undated_policy="processing_date")


def _summary(model, docling_json: Path) -> dict:
    return {
        "paragraphs": len(model.of_type(T.PARAGRAPH)),
        "elements": len(model.elements),
        "parser_warnings": len(model.warnings),
        "uncertain_elements": sum(e.uncertain for e in model.elements),
        "toc_found": any(e.type == T.TOC for e in model.elements),
    }


def _akn_summary(art: dict) -> dict:
    v = art["validation"]
    return {"akn_generated": True, "akn_xsd_valid": v.valid, "akn_xsd_errors": len(v.errors),
            "akn_text_identical": art["text"]["same_order_and_text"]}  # fmt: skip


GERMAN_LAW = LegalProfile(
    mode="german_law",
    model_profile=None,
    legal_system="de",
    language="de",
    recognize=_recognize,
    resolve_footnotes=_resolve_footnotes,
    sentence_units=frozenset({T.ABSATZ}),
    units_if_no_subunits={T.PARAGRAPH: T.ABSATZ},
    list_types=frozenset({T.NUMMER, T.BUCHSTABE, T.DOPPELBUCHSTABE, T.UNMARKED_LIST_ITEM}),
    toc=TOC,
    json_types={
        T.TEIL: "part", T.KAPITEL: "chapter", T.ABSCHNITT: "division", T.UNTERABSCHNITT: "subdivision",
        T.PARAGRAPH: "section", T.ABSATZ: "subsection", T.NUMMER: "number", T.BUCHSTABE: "letter",
        T.DOPPELBUCHSTABE: "letter", T.ANLAGE: "annex",
    },  # fmt: skip
    # German drafting terms (Handbuch der Rechtsförmlichkeit)
    json_native_terms={
        T.TEIL: "Teil", T.KAPITEL: "Kapitel", T.ABSCHNITT: "Abschnitt", T.UNTERABSCHNITT: "Unterabschnitt",
        T.PARAGRAPH: "Paragraph", T.ABSATZ: "Absatz", T.SENTENCE: "Satz", T.NUMMER: "Nummer", T.BUCHSTABE: "Buchstabe",
        T.DOPPELBUCHSTABE: "Doppelbuchstabe", T.ANLAGE: "Anlage",
    },  # fmt: skip
    json_nesting={
        "part": {"document"},
        "chapter": {"document", "part"},
        "division": {"document", "part", "chapter"},
        "subdivision": {"division"},
        "section": {"document", "part", "chapter", "division", "subdivision"},
        "subsection": {"section"},
        "sentence": {"section", "subsection", "number", "letter"},
        "number": {"section", "subsection", "annex"},
        "letter": {"number", "letter"},  # under a letter only as a double letter "aa)" (checked in nesting)
        "annex": {"document"},
    },
    json_document_type=lambda md: "de_legislation",
    json_id_parts=lambda md: None,
    write_reports=_write_reports,
    build_akn=_build_akn,
    has_structure=lambda model: bool(model.of_type(T.PARAGRAPH)),
    unsupported_summary={"paragraphs": 0},
    unsupported_message=("This document does not look like German legislation: no section headings of the form "
                         "'§ <number> <title>' were found after a table of contents or at the start of the text. "
                         "ODOS does not produce a legal structure or Akoma Ntoso XML for it. The Docling extraction "
                         "(raw JSON and Markdown) is still available."),  # fmt: skip
    summary=_summary,
    akn_summary=_akn_summary,
    completed_message=lambda art: "German-law prototype conversion. Structure rules are tuned to the BDSG; other laws may be incomplete — check the warnings.",  # fmt: skip
    akn_refused_message=lambda exc: f"Legal structure extracted, but Akoma Ntoso XML was not generated: {exc}",
    capabilities=frozenset({"akn_excerpt"}),
)
