"""The shared parsing engine and the legal profiles (Phase 3).

* the registry and dispatch: every structured mode is a registered profile, unknown modes/profiles are errors;
* the lifecycle runs its stages in the documented order;
* the profile tables are exactly the tables the shared modules held before Phase 3 (copied below, verbatim), split
  by profile: nothing was added to or dropped from a profile that has documents;
* the TOC vocabulary is the profile's: an EU TOC is matched with EU markers, not German ones;
* profiles import no shared operation module (no import cycles).
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from odos.legal_json.exporter import COMMON_TYPES
from odos.parsing import engine
from odos.document_model import DocumentMetadata, DocumentModel, Element, ElementType as T, SourceInfo
from odos.parsing.profiles import EU_LEGISLATION, GERMAN_LAW, PROFILES, for_legal_system, for_model, get, structured_modes
from odos.parsing.toc import normalize_toc

DE, EU = GERMAN_LAW, EU_LEGISLATION


# ---- registry ---------------------------------------------------------------------------------------------------------
def test_registry_and_lookup():
    assert structured_modes() == ("german_law", "eu_legislation") and set(PROFILES) == set(structured_modes())
    assert get("german_law") is DE and get("eu_legislation") is EU
    for bad in ("auto", "extract_only", "", None):
        with pytest.raises(ValueError):
            get(bad)
    info = SourceInfo(docling_json_sha256="0" * 64, num_pages=1)
    model = DocumentModel(source=info, metadata=DocumentMetadata(), root_id="doc", elements=[], furniture=[], warnings=[])
    assert for_model(model) is DE  # stored German models carry no profile (historic): still readable
    assert for_model(model.model_copy(update={"profile": "eu_legislation"})) is EU
    with pytest.raises(ValueError):
        for_model(model.model_copy(update={"profile": "technical_standard"}))
    assert for_legal_system("de") is DE and for_legal_system("eu") is EU


def test_processing_modes_and_router_use_the_registry():
    from odos.classification.router import STRUCTURED
    from odos.pipeline import ProcessingMode

    assert {m.value for m in ProcessingMode} == {"extract_only", *structured_modes()}
    assert set(STRUCTURED) == set(structured_modes())


def test_akn_cli_dispatches_by_capability(tmp_path, eu_model, model, capsys):
    """`odos akn`: a profile with the § excerpt capability (German) writes the excerpt; any other profile its whole
    document. The files are exactly the generators' output."""
    from odos.akn.eu_generator import generate_eu_akn
    from odos.akn.generator import generate_excerpt
    from odos.cli import main

    date = "2026-10-27"
    (tmp_path / "eu").mkdir()
    (tmp_path / "eu" / "document_model.json").write_text(eu_model.model_dump_json(indent=2), encoding="utf-8")
    assert main(["akn", str(tmp_path / "eu" / "document_model.json"), "--retrieval-date", date]) == 0
    assert (tmp_path / "eu" / "document_akn.xml").read_bytes() == generate_eu_akn(eu_model, date).xml
    assert (tmp_path / "eu" / "akn_text_preservation.json").is_file()
    assert "order preserved: True" in capsys.readouterr().out
    (tmp_path / "de").mkdir()
    (tmp_path / "de" / "document_model.json").write_text(model.model_dump_json(indent=2), encoding="utf-8")
    assert main(["akn", str(tmp_path / "de" / "document_model.json"), "--retrieval-date", date, "--paragraphs", "1", "2"]) == 0
    assert (tmp_path / "de" / "bdsg_excerpt.xml").read_bytes() == generate_excerpt(model, ["1", "2"], date).xml
    assert not (tmp_path / "de" / "document_akn.xml").exists()


def test_akn4eu_export_is_a_capability_of_the_eu_profile():
    assert "akn4eu" in EU.capabilities and "akn4eu" not in DE.capabilities
    assert "akn_excerpt" in DE.capabilities and "akn_excerpt" not in EU.capabilities


def test_artifact_names_have_one_source():
    from odos.artifact_names import AKN_XML, ARTIFACTS

    assert ARTIFACTS["akn_xml"][0] == AKN_XML == "document_akn.xml"  # every profile's build_akn writes this name
    assert list(ARTIFACTS) == ["docling_raw", "extracted_md", "document_model", "legal_json", "legal_json_validation_report",
                               "validation_report", "akn_xml", "akn_validation_report", "akn_traceability", "akn_text_report",
                               "reading_order_evidence"]  # API artifact types and their order (the status lists them so)


def test_profiles_import_no_shared_operation_module():
    """Importing the registry loads only the profiles, their package inits and data modules (the model, language
    data): never the engine, a recognizer, the sentences/TOC operations or an exporter (no import cycles)."""
    probe = ("import sys; before = set(sys.modules); import odos.parsing.profiles; "
             "print(sorted(m for m in set(sys.modules) - before if m.startswith('odos')))")  # fmt: skip
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True).stdout.strip()
    assert out == str(sorted(["odos", "odos.document_model", "odos.normalization", "odos.normalization.lang_de", "odos.parsing",
                              "odos.parsing.profiles", "odos.parsing.profiles.base", "odos.parsing.profiles.eu_legislation",
                              "odos.parsing.profiles.german_law"])), out  # fmt: skip


# ---- lifecycle --------------------------------------------------------------------------------------------------------
def test_stage_order_is_the_documented_lifecycle(raw_json, model):
    names = ["read_source", "load_evidence", "preprocess", "parse_structure", "finalize_structure", "resolve_footnotes",
             "segment_sentences", "normalize_toc"]  # fmt: skip
    assert [n for n, _ in engine.STAGES] == names
    trace: list[str] = []
    m = engine.parse(raw_json, DE, trace)
    assert trace == names
    assert m.model_dump_json() == model.model_dump_json()  # the public entry point is this lifecycle


def test_only_the_recognizer_assigns_ids(eu_raw_json, eu_model):
    seen = {}

    def spy(name, fn):
        def run(s):
            fn(s)
            if s.model is not None:
                seen[name] = [e.id for e in s.model.elements] + [e.id for e in s.model.furniture]

        return name, run

    stages = engine.STAGES
    try:
        engine.STAGES = tuple(spy(n, f) for n, f in stages)
        m = engine.parse(eu_raw_json, EU)
    finally:
        engine.STAGES = stages
    after_recognizer = seen["parse_structure"]
    for name in ("finalize_structure", "resolve_footnotes", "segment_sentences", "normalize_toc"):
        assert sorted(seen[name]) == sorted(after_recognizer), name  # moved between tree and furniture at most
    assert m.model_dump_json() == eu_model.model_dump_json()


# ---- profile tables = the tables before Phase 3 -----------------------------------------------------------------------
# verbatim copies of legal_json/exporter.py, legal_json/nesting.py, sentences.py and toc.py at the Phase 3 baseline
OLD_TYPE_MAP = {
    T.TEIL: "part", T.KAPITEL: "chapter", T.ABSCHNITT: "division", T.UNTERABSCHNITT: "subdivision",
    T.PARAGRAPH: "section", T.ABSATZ: "subsection", T.NUMMER: "number", T.BUCHSTABE: "letter",
    T.DOPPELBUCHSTABE: "letter", T.ANLAGE: "annex", T.UNMARKED_LIST_ITEM: "item",
    T.PREAMBLE: "preamble", T.PREAMBLE_FORMULA: "preambleFormula", T.CITATION: "citation",
    T.RECITALS_INTRO: "recitalsIntro", T.RECITAL: "recital", T.ENACTING_FORMULA: "enactingFormula",
    T.CHAPTER: "chapter", T.SECTION: "section", T.ARTICLE: "article", T.ARTICLE_PARAGRAPH: "paragraph",
    T.NUMBERED_POINT: "point", T.POINT: "point", T.SUBPOINT: "subpoint", T.ANNEX: "annex",
    T.ANNEX_PART: "part", T.ANNEX_HEADING: "heading", T.CONCLUSIONS: "conclusions",
    T.FINAL_FORMULA: "finalFormula", T.SIGNATURE: "signature", T.PICTURE: "picture",
    T.SENTENCE: "sentence", T.TEXT: "text", T.UNRECOGNIZED: "text", T.TABLE: "table", T.FOOTNOTE: "text",
    T.FRONT_MATTER: "frontMatter", T.DOC_TITLE: "documentTitle", T.TOC: "tableOfContents", T.TOC_ENTRY: "tocEntry",
}  # fmt: skip
OLD_NATIVE_DE = {
    T.TEIL: "Teil", T.KAPITEL: "Kapitel", T.ABSCHNITT: "Abschnitt", T.UNTERABSCHNITT: "Unterabschnitt",
    T.PARAGRAPH: "Paragraph", T.ABSATZ: "Absatz", T.SENTENCE: "Satz", T.NUMMER: "Nummer", T.BUCHSTABE: "Buchstabe",
    T.DOPPELBUCHSTABE: "Doppelbuchstabe", T.ANLAGE: "Anlage",
}  # fmt: skip
OLD_NATIVE_EU = {
    T.CHAPTER: "Kapitel", T.SECTION: "Abschnitt", T.ARTICLE: "Artikel", T.ARTICLE_PARAGRAPH: "Absatz",
    T.SENTENCE: "Satz", T.NUMBERED_POINT: "Nummer", T.POINT: "Buchstabe", T.SUBPOINT: "Ziffer", T.RECITAL: "Erwägungsgrund",
    T.ANNEX: "Anhang", T.ANNEX_PART: "Teil", T.ANNEX_HEADING: "Nummer",
}  # fmt: skip
OLD_NESTING = {
    "de": {"part": {"document"}, "chapter": {"document", "part"}, "division": {"document", "part", "chapter"},
           "subdivision": {"division"}, "section": {"document", "part", "chapter", "division", "subdivision"},
           "subsection": {"section"}, "sentence": {"section", "subsection", "number", "letter"},
           "number": {"section", "subsection", "annex"}, "letter": {"number", "letter"}, "annex": {"document"}},
    "eu": {"preamble": {"document"}, "preambleFormula": {"preamble"}, "citation": {"preamble"}, "recitalsIntro": {"preamble"},
           "recital": {"preamble"}, "enactingFormula": {"preamble"}, "title": {"document"}, "chapter": {"document", "title"},
           "section": {"chapter"}, "article": {"document", "chapter", "section"}, "paragraph": {"article", "heading"},
           "sentence": {"article", "paragraph", "point", "subpoint", "recital"},
           "point": {"article", "paragraph", "point", "annex", "part", "heading"}, "subpoint": {"point", "heading"},
           "numeral": {"subpoint"}, "annex": {"document"}, "part": {"annex"}, "heading": {"annex", "part", "heading"},
           "conclusions": {"document"}, "finalFormula": {"conclusions"}, "signature": {"conclusions"}},
}  # fmt: skip
OLD_UNIT_TYPES = {T.ABSATZ, T.ARTICLE_PARAGRAPH, T.RECITAL}
OLD_UNIT_IF_NO_SUBUNITS = {T.PARAGRAPH: T.ABSATZ, T.ARTICLE: T.ARTICLE_PARAGRAPH}
OLD_LIST_TYPES = {T.NUMMER, T.BUCHSTABE, T.DOPPELBUCHSTABE, T.UNMARKED_LIST_ITEM, T.POINT, T.NUMBERED_POINT, T.SUBPOINT}
OLD_TOC_KIND = {T.TEIL: "teil", T.KAPITEL: "kapitel", T.ABSCHNITT: "abschnitt", T.UNTERABSCHNITT: "unterabschnitt",
                T.PARAGRAPH: "paragraph", T.ANLAGE: "anlage", T.ARTICLE: "article", T.CHAPTER: "chapter", T.SECTION: "section",
                T.ANNEX: "annex"}  # fmt: skip
OLD_TOC_LEVEL = {"teil": 1, "kapitel": 2, "abschnitt": 3, "unterabschnitt": 4, "paragraph": 5, "article": 5, "anlage": 1,
                 "chapter": 2, "section": 3, "annex": 1}  # fmt: skip
OLD_TOC_MARKERS = [
    ("paragraph", r"§(?!§)(\d+[a-z]?)(?![\d])"), ("article", r"(?:Artikel|ARTIKEL)(\d+[a-z]?)"),
    ("teil", r"(?:Teil|TEIL)(\d+|[A-Z](?![a-z]))"), ("kapitel", r"(?:Kapitel|KAPITEL)(\d+|[IVXLC]+(?![a-z]))"),
    ("unterabschnitt", r"(?:Unterabschnitt|UNTERABSCHNITT)(\d+)"), ("abschnitt", r"(?:Abschnitt|ABSCHNITT)(\d+)"),
    ("anlage", r"(?:Anlage|ANLAGE|Anhang|ANHANG)(\d+|[IVXLC]+(?![a-z]))?"),
]  # fmt: skip
GERMAN_TYPES = {T.TEIL, T.KAPITEL, T.ABSCHNITT, T.UNTERABSCHNITT, T.PARAGRAPH, T.ABSATZ, T.NUMMER, T.BUCHSTABE,
                T.DOPPELBUCHSTABE, T.ANLAGE, T.UNMARKED_LIST_ITEM}  # fmt: skip


def test_json_tables_are_the_old_tables_split_by_profile():
    assert not set(DE.json_types) & set(EU.json_types) and not set(COMMON_TYPES) & (set(DE.json_types) | set(EU.json_types))
    assert COMMON_TYPES | DE.json_types | EU.json_types == OLD_TYPE_MAP
    assert DE.json_native_terms == OLD_NATIVE_DE and EU.json_native_terms == OLD_NATIVE_EU
    assert DE.json_nesting == OLD_NESTING["de"] and EU.json_nesting == OLD_NESTING["eu"]


def test_sentence_tables_are_the_old_tables_split_by_profile():
    assert DE.sentence_units | EU.sentence_units == OLD_UNIT_TYPES and not DE.sentence_units & EU.sentence_units
    assert DE.units_if_no_subunits | EU.units_if_no_subunits == OLD_UNIT_IF_NO_SUBUNITS
    assert DE.list_types | EU.list_types == OLD_LIST_TYPES and not DE.list_types & EU.list_types
    assert DE.list_types <= GERMAN_TYPES and DE.sentence_units <= GERMAN_TYPES


def test_german_toc_vocabulary_is_the_old_one():
    voc = DE.toc
    assert voc.kinds == {t: k for t, k in OLD_TOC_KIND.items() if t in GERMAN_TYPES}
    assert voc.levels == {k: v for k, v in OLD_TOC_LEVEL.items() if k in {*voc.kinds.values(), "article"}}
    assert [(k, rx.pattern) for k, rx, _ in voc.markers] == OLD_TOC_MARKERS
    assert all(num(n) == n for _, _, num in voc.markers for n in ("1", "IV", None))  # numbers stay as printed
    assert voc.inline_marker == "paragraph" and voc.provisions == (T.PARAGRAPH,)


def _toc_model(profile: str | None) -> DocumentModel:
    def el(id_, type_, region, parent, children=(), **kw):
        return Element(id=id_, type=type_, region=region, parent_id=parent, children_ids=list(children), **kw)

    lines = ["KAPITEL I Allgemeine Bestimmungen", "Artikel 1 Gegenstand", "Artikel 2 Begriffsbestimmungen"]
    toc_items = [el(f"doc/toc/entry-{i}", T.TOC_ENTRY, "toc", "doc/toc", content_text=t, original_text=t, source_refs=[f"#/texts/{i}"])
                 for i, t in enumerate(lines, start=1)]  # fmt: skip
    elements = [
        el("doc", T.DOCUMENT, "document", None, ["doc/toc", "doc/chp-1"]),
        el("doc/toc", T.TOC, "toc", "doc", [e.id for e in toc_items]),
        *toc_items,
        el("doc/chp-1", T.CHAPTER, "body", "doc", ["doc/chp-1/art-1"], number="I", marker="KAPITEL I",
           title="Allgemeine Bestimmungen", content_text="Allgemeine Bestimmungen"),
        el("doc/chp-1/art-1", T.ARTICLE, "body", "doc/chp-1", number="1", marker="Artikel 1", title="Gegenstand", content_text="Gegenstand"),
    ]  # fmt: skip
    return DocumentModel(profile=profile, source=SourceInfo(docling_json_sha256="0" * 64, num_pages=1), metadata=DocumentMetadata(),
                         root_id="doc", elements=elements, furniture=[], warnings=[])  # fmt: skip


@pytest.mark.parametrize("line, expected", [
    ("KAPITELIVLieferketten", ("chapter", "IV")), ("KAPITELIInverkehrbringen", ("chapter", "I")),
    ("ABSCHNITT2Notifizierung", ("section", "2")), ("ANHANGIVListe", ("annex", "IV")), ("ANHANG", ("annex", None)),
    ("TEILAGrundlegende", ("part", "A")), ("TEILIIAnforderungen", ("part", "II")), ("Artikel12aBegriffe", ("article", "12a")),
])  # fmt: skip
def test_eu_toc_markers_on_compact_lines(line, expected):
    from odos.parsing.toc import _markers

    assert [(k, n) for _, _, k, n in _markers(line, EU.toc)] == [expected]


def test_eu_toc_is_matched_with_the_eu_vocabulary():
    eu = _toc_model("eu_legislation")
    normalize_toc(eu)
    got = {e.id: (e.kind, e.number, e.status, e.target_id) for e in eu.toc_entries}
    assert got == {
        "toc/chapter-I": ("chapter", "I", "linked", "doc/chp-1"),  # printed numbers, as the EU parser stores them
        "toc/article-1": ("article", "1", "linked", "doc/chp-1/art-1"),
        "toc/article-2": ("article", "2", "unmatched", None),  # no body article 2: nothing invented
    }
    # the German vocabulary reads the same lines as German units, which an EU body does not have
    de = _toc_model(None)
    normalize_toc(de)
    assert [e.status for e in de.toc_entries] == ["unmatched", "unmatched", "unmatched"]
    assert [e.kind for e in de.toc_entries] == ["kapitel", "article", "article"]
