"""Document classification and routing."""

import json
from pathlib import Path

import pytest

import pdfgen
from odos.classification import classify_lines, lines_from_docling, lines_from_pdf, route
from odos.classification.model import Band, DocumentType as D, SupportStatus
from odos.classification.text_source import Line, Lines

BACKEND = Path(__file__).resolve().parents[1]
BDSG = BACKEND / "data" / "input" / "BDSG.pdf"


def classify_bytes(tmp_path, data: bytes, name: str = "document.pdf"):
    p = tmp_path / name
    p.write_bytes(data)
    return classify_lines(lines_from_pdf(p))


def rules(r):
    return {e.rule_id for e in r.evidence}


# ---- real documents ----------------------------------------------------------------------------------------------
def test_bdsg_is_german_law():
    r = classify_lines(lines_from_pdf(BDSG))
    assert r.document_type == D.GERMAN_LAW and r.confidence_band == Band.HIGH
    assert r.suggested_processing_mode == "german_law" and r.supported and r.support_status == SupportStatus.SUPPORTED
    assert {"de_paragraph_headings", "de_ausfertigungsdatum", "de_vollzitat", "de_bgbl"} <= rules(r)
    assert r.points["german_law"] > r.points["german_model_regulation"] and r.points["eu_regulation"] == 0


def test_musterbauordnung_is_model_regulation_routed_to_german_law(mbo_pdf):
    r = classify_lines(lines_from_pdf(mbo_pdf))
    assert r.document_type == D.GERMAN_MODEL_REGULATION  # type metadata is kept ...
    assert r.suggested_processing_mode == "german_law" and r.supported  # ... while the German parser is used
    assert {"de_model_title", "de_paragraph_headings"} <= rules(r)
    assert any("Model regulation" in w for w in r.warnings)


def test_eu_machinery_regulation(eu_pdf):
    r = classify_lines(lines_from_pdf(eu_pdf))
    assert r.document_type == D.EU_REGULATION and r.confidence_band == Band.HIGH
    assert r.suggested_processing_mode == "eu_legislation" and r.supported
    assert {"eu_regulation_title", "eu_enacting_formula_regulation", "eu_official_journal", "eu_recitals_intro",
            "eu_article_headings", "eu_final_formula_regulation", "eu_recital_sequence"} <= rules(r)
    title = next(e for e in r.evidence if e.rule_id == "eu_regulation_title")
    assert title.page == 1 and "2023/1230" in title.snippet and title.source_ref.startswith("pdf_text_layer:p1:")
    assert r.points["eu_regulation"] - r.points["eu_directive"] >= 8  # the regulation/directive margin comes from title, formulas


@pytest.mark.parametrize("name,raw,expected,mode", [
    ("BDSG", "output/bdsg/docling_raw.json", D.GERMAN_LAW, "german_law"),
    ("MBO", "output/mbo/docling_raw.json", D.GERMAN_MODEL_REGULATION, "german_law"),
    ("EU", "output/eu/docling_raw.json", D.EU_REGULATION, "eu_legislation"),
])
def test_existing_docling_output_gives_the_same_answer_with_docling_refs(name, raw, expected, mode):
    p = BACKEND / raw
    if not p.exists():
        pytest.skip(f"{raw} not available")
    r = classify_lines(lines_from_docling(p))
    assert (r.document_type, r.suggested_processing_mode) == (expected, mode) and r.input.source == "docling"
    assert all(e.source_ref is None or e.source_ref.startswith("#/") for e in r.evidence)  # Docling item refs


# ---- synthetic documents --------------------------------------------------------------------------------------------------
def test_synthetic_iso_standard_is_recognised_but_not_supported(tmp_path):
    r = classify_bytes(tmp_path, pdfgen.iso_standard())
    assert r.document_type == D.TECHNICAL_STANDARD and r.confidence_band == Band.HIGH
    assert r.suggested_processing_mode == "extract_only" and not r.supported
    assert r.support_status == SupportStatus.RECOGNISED_NOT_SUPPORTED
    assert {"std_identifier_title", "std_scope_clause", "std_normative_references", "std_ics", "std_copyright"} <= rules(r)
    assert any("Custom JSON" in w for w in r.warnings)


def test_synthetic_eu_directive_is_not_routed_to_the_regulation_parser(tmp_path):
    r = classify_bytes(tmp_path, pdfgen.eu_directive())
    assert r.document_type == D.EU_DIRECTIVE
    assert r.suggested_processing_mode == "extract_only" and r.candidate_mode is None and not r.supported
    assert r.support_status == SupportStatus.RECOGNISED_NOT_SUPPORTED
    assert {"eu_directive_title", "eu_enacting_formula_directive", "eu_final_formula_directive"} <= rules(r)
    assert any("not routed to the EU regulation parser" in w for w in r.warnings)
    assert r.points["eu_directive"] > r.points["eu_regulation"]


def test_synthetic_eu_regulation(tmp_path):
    r = classify_bytes(tmp_path, pdfgen.eu_regulation())
    assert r.document_type == D.EU_REGULATION and r.suggested_processing_mode == "eu_legislation"


def test_non_legal_pdf_is_unknown(tmp_path):
    r = classify_bytes(tmp_path, pdfgen.shopping_list())
    assert r.document_type == D.UNKNOWN and r.suggested_processing_mode == "extract_only"
    assert r.support_status == SupportStatus.UNSUPPORTED and not r.supported and r.confidence_band == Band.LOW
    assert any("scanned" in w or "Very little text" in w for w in r.warnings)


# ---- ambiguous and misleading documents -----------------------------------------------------------------------------------------
def test_filename_is_ignored(tmp_path):
    r = classify_bytes(tmp_path, pdfgen.shopping_list(), name="BDSG_Bundesdatenschutzgesetz_VERORDNUNG_EU_2023.pdf")
    assert r.document_type == D.UNKNOWN
    r2 = classify_bytes(tmp_path, pdfgen.german_law(), name="einkaufsliste.pdf")
    assert r2.document_type == D.GERMAN_LAW


def test_statute_title_without_paragraph_structure_is_not_classified_as_law(tmp_path):
    r = classify_bytes(tmp_path, pdfgen.german_law(n_par=0, with_markers=True))  # BGBl, Vollzitat, '...gesetz' title, no §
    assert r.confidence_band == Band.LOW and not r.supported  # markers alone never reach medium/high
    assert r.suggested_processing_mode == "extract_only" and r.support_status in (SupportStatus.UNCERTAIN, SupportStatus.UNSUPPORTED)  # fmt: skip
    assert any("no '§ n' structure" in w for w in r.warnings) and "de_paragraph_headings" not in rules(r)


def test_title_with_muster_does_not_make_a_model_regulation(tmp_path):
    r = classify_bytes(tmp_path, pdfgen.german_law(title="Gesetz zur Einführung einer Musterfeststellungsklage"))
    assert r.document_type == D.GERMAN_LAW  # 'Muster...' needs ORDNUNG/GESETZ/... and a ministers' conference or Fassung


def test_standard_that_cites_eu_regulation_and_paragraphs_stays_a_standard(tmp_path):
    lines = ["DIN EN ISO 12100:2011", "Sicherheit von Maschinen - Allgemeine Gestaltungsleitsätze", "ICS 13.110", "Vorwort",
             "1 Anwendungsbereich", "2 Normative Verweisungen", "3 Begriffe", "© DIN 2011"] + pdfgen.FILLER * 3
    lines += ["Diese Norm unterstützt die Verordnung (EU) 2023/1230 und die Anforderungen aus § 3 ProdSG."]
    r = classify_bytes(tmp_path, pdfgen.make_pdf(pdfgen.paginate(lines)))
    assert r.document_type == D.TECHNICAL_STANDARD and r.points["eu_regulation"] == 0 and r.points["german_law"] == 0


def test_official_journal_item_without_articles_is_not_an_eu_act(tmp_path):
    lines = ["Amtsblatt der Europäischen Union", "L 1/1", "MITTEILUNG DER KOMMISSION", "Hinweis zur Anwendung"] + pdfgen.FILLER * 4
    r = classify_bytes(tmp_path, pdfgen.make_pdf(pdfgen.paginate(lines)))
    assert r.document_type == D.UNKNOWN and r.suggested_processing_mode == "extract_only"
    assert any("Official Journal indicators found but no article structure" in w for w in r.warnings)


def test_weak_evidence_gives_low_band_and_extract_only(tmp_path):
    lines = [f"§ {i} Titel" for i in range(1, 7)] + pdfgen.FILLER * 6  # six headings and nothing else
    r = classify_bytes(tmp_path, pdfgen.make_pdf(pdfgen.paginate(lines)))
    assert r.document_type in (D.GERMAN_LAW, D.UNKNOWN)
    assert r.confidence_band == Band.LOW and r.suggested_processing_mode == "extract_only" and not r.supported
    if r.document_type == D.GERMAN_LAW:
        assert r.support_status == SupportStatus.UNCERTAIN and r.candidate_mode == "german_law"


def test_confidence_is_a_documented_band_not_a_probability():
    r = classify_lines(Lines(lines=[Line(page=1, text="x")], pages_total=1, pages_scanned=1, source="pdf_text_layer"))
    assert r.confidence_band in set(Band) and "not a probability" in r.confidence_note
    assert not hasattr(r, "confidence_score") and all(isinstance(v, int) for v in r.points.values())


def test_classification_is_deterministic_and_serialisable():
    a = classify_lines(lines_from_pdf(BDSG)).model_dump_json()
    assert classify_lines(lines_from_pdf(BDSG)).model_dump_json() == a
    assert json.loads(a)["evidence"][0]["source_ref"]


# ---- routing -------------------------------------------------------------------------------------------------------------------------
def test_router_suggests_and_records_overrides(tmp_path):
    de = classify_lines(lines_from_pdf(BDSG))
    d = route(de)
    assert (d.chosen_mode, d.manual_override, d.warnings) == ("german_law", False, [])
    ok = route(de, "german_law")
    assert not ok.manual_override
    wrong = route(de, "eu_legislation")
    assert wrong.manual_override and wrong.chosen_mode == "eu_legislation" and "classified as german_law" in wrong.warnings[0]
    assert route(de, "extract_only").manual_override


def test_router_never_blocks_but_flags_directive_override(tmp_path):
    r = classify_bytes(tmp_path, pdfgen.eu_directive())
    d = route(r, "eu_legislation")
    assert d.manual_override and d.chosen_mode == "eu_legislation"
    assert any("directives were not verified" in w for w in d.warnings)
    assert route(r).chosen_mode == "extract_only"
    assert route(None).chosen_mode == "extract_only"  # no classification: safe default
