"""The German-law profile end to end on the synthetic law (tests/synthetic_german.py): always runs, needs no partner
document. Its generated PDF has a real text layer, so footnote anchors and printed Satz numbers are proven from the
PDF as they are for real laws.

Covered: the shared lifecycle, metadata, Teil / Kapitel / § / Absatz / Nummer / Buchstabe / Anlage, the table of
contents and its verified links, a page footnote with its superscript reference, printed and punctuation-based
sentences, document.json 1.1 (schema, nesting, text, the 1.0 downgrade), Akoma Ntoso (XSD, text, order), and the
whole pipeline run. There is no golden baseline for it: glyph coordinates come from pdfium and may differ in the last
decimals between platforms, so structure and validity are asserted instead."""

import json
import shutil

import synthetic_german

from odos.akn.german_artifacts import build_artifacts
from odos.artifact_names import AKN_XML
from odos.document_model import ElementType as T
from odos.legal_json.artifacts import build_legal_json_artifacts
from odos.parsing import engine, parse_document
from odos.parsing.profiles import GERMAN_LAW


def test_parsed_through_the_shared_lifecycle(synthetic_german_raw_json, synthetic_german_model):
    trace: list[str] = []
    m = engine.parse(synthetic_german_raw_json, GERMAN_LAW, trace)
    assert trace == [name for name, _ in engine.STAGES]
    assert m.model_dump_json() == synthetic_german_model.model_dump_json()  # deterministic
    assert m.profile is None  # German law: stored without a profile value, as always
    assert not m.warnings and not any(e.uncertain for e in m.elements)  # a clean law raises nothing


def test_metadata_is_read_from_the_printed_front_matter(synthetic_german_model):
    md = synthetic_german_model.metadata
    assert (md.title, md.short_title) == ("Beispielgesetz über Prüfverfahren", "BspG")
    assert md.ausfertigungsdatum == "15.03.2099" and md.stand.startswith("Zuletzt geändert")
    assert md.vollzitat == "Beispielgesetz über Prüfverfahren vom 15. März 2099 (BGBl. I S. 1)"


def test_sections_paragraphs_and_numbering(synthetic_german_model):
    idx = synthetic_german_model.by_id()
    expected = {
        "doc/teil-1": T.TEIL, "doc/teil-1/kapitel-1": T.KAPITEL, "doc/teil-1/kapitel-1/par-1": T.PARAGRAPH,
        "doc/teil-1/kapitel-1/par-1/abs-2": T.ABSATZ, "doc/teil-1/kapitel-1/par-2/abs-1/nr-3": T.NUMMER,
        "doc/teil-1/kapitel-1/par-2/abs-1/nr-3/lit-b": T.BUCHSTABE, "doc/teil-1/kapitel-2/par-4/abs-1/nr-2": T.NUMMER,
        "doc/teil-2/par-5": T.PARAGRAPH, "doc/teil-2/par-5/txt-1": T.TEXT, "doc/anlage-1": T.ANLAGE, "doc/anlage-1/table-1": T.TABLE,
    }  # fmt: skip
    assert {i: idx[i].type for i in expected} == expected
    assert [idx[i].number for i in ("doc/teil-1/kapitel-1/par-2", "doc/teil-1/kapitel-2/par-3", "doc/teil-2/par-5")] == ["2", "3", "5"]
    nr3 = idx["doc/teil-1/kapitel-1/par-2/abs-1/nr-3"]
    assert nr3.children_ids == ["doc/teil-1/kapitel-1/par-2/abs-1/nr-3/lit-a", "doc/teil-1/kapitel-1/par-2/abs-1/nr-3/lit-b"]  # Buchstaben under their Nummer
    assert idx["doc/teil-1/kapitel-1/par-2"].title == "Begriffsbestimmungen" and idx["doc/teil-1/kapitel-1/par-2"].marker == "§ 2"
    assert [r.rows for r in [idx["doc/anlage-1/table-1"].table]] == [[["Nr.", "Prüfgegenstand"], ["1", "Unterlagen"], ["2", "Verfahren"]]]


def test_running_page_furniture_is_kept_outside_the_structure(synthetic_german_model):
    furniture = synthetic_german_model.furniture
    assert [f.type for f in furniture].count(T.PAGE_HEADER) == 3 and [f.type for f in furniture].count(T.PAGE_FOOTER) == 3
    assert all(f.region == "furniture" for f in furniture)


def test_table_of_contents_is_normalized_and_linked(synthetic_german_model):
    entries = {t.id: t for t in synthetic_german_model.toc_entries}
    assert list(entries) == ["toc/teil-1", "toc/kapitel-1", "toc/paragraph-1", "toc/paragraph-2", "toc/kapitel-2", "toc/paragraph-3",
                             "toc/paragraph-4", "toc/teil-2", "toc/paragraph-5", "toc/anlage-1"]  # printed order
    assert all(t.status == "linked" for t in entries.values())  # kind, number, title and enclosing headings agree
    assert entries["toc/paragraph-3"].target_id == "doc/teil-1/kapitel-2/par-3" and entries["toc/anlage-1"].target_id == "doc/anlage-1"
    assert entries["toc/paragraph-3"].title == "Antrag" and entries["toc/paragraph-3"].level > entries["toc/kapitel-2"].level


def test_page_footnote_is_anchored_by_its_superscript_reference(synthetic_german_model):
    fn = synthetic_german_model.by_id()["doc/teil-1/kapitel-1/par-2/fn-1"]
    assert fn.type == T.FOOTNOTE and fn.anchor_ids == ["doc/teil-1/kapitel-1/par-2/abs-2"] and fn.anchor_id == fn.anchor_ids[0]
    ref = fn.footnote_refs[0]
    assert (ref.mark, ref.page, ref.mark_class) == ("1", 2, "reference_attached") and ref.bbox is not None
    assert "footnote_anchor_from_pdf_reference_mark" in fn.hygiene_flags


def test_sentences_printed_numbers_and_punctuation(synthetic_german_model):
    by_unit: dict[str, list] = {}
    for s in synthetic_german_model.sentences:
        by_unit.setdefault(s.unit_id, []).append(s)
    assert [(s.id, s.method, s.number) for s in by_unit["doc/teil-1/kapitel-2/par-3/abs-1"]] == [
        ("doc/teil-1/kapitel-2/par-3/abs-1/satz-1", "printed_number", "1"), ("doc/teil-1/kapitel-2/par-3/abs-1/satz-2", "printed_number", "2")]  # fmt: skip
    assert all(s.mark_box is not None and s.status == "verified" for s in by_unit["doc/teil-1/kapitel-2/par-3/abs-1"])  # proven by the PDF marks
    assert [s.method for s in by_unit["doc/teil-1/kapitel-2/par-3/abs-2"]] == ["punctuation", "punctuation"]  # "… Eingang. Sie prüft …"
    idx = synthetic_german_model.by_id()
    second = by_unit["doc/teil-1/kapitel-2/par-3/abs-2"][1].ranges[0]
    assert idx[second.element_id].content_text[second.start : second.end] == "Sie prüft den Antrag unverzüglich."
    assert "doc/teil-1/kapitel-1/par-2/abs-1/nr-1" not in {r.element_id for s in synthetic_german_model.sentences for r in s.ranges[:1]}  # a list item starts no sentence


def test_legal_json_1_1_and_its_1_0_downgrade(synthetic_german_model, synthetic_german_raw_json, tmp_path):
    rep = build_legal_json_artifacts(synthetic_german_model, synthetic_german_raw_json, tmp_path)["report"]
    assert rep["valid"] and rep["schema_valid"] and rep["structure_valid"] and rep["downgrade_to_1_0_valid"]
    assert rep["text_preservation"]["identical_to_model"]
    doc = json.loads((tmp_path / "document.json").read_text())
    assert (doc["schemaVersion"], doc["legalSystem"], doc["documentType"], doc["enactmentDate"]) == ("1.1", "de", "de_legislation", "2099-03-15")
    assert doc["id"] == "bspg" and doc["identifiers"]["citation"].startswith("Beispielgesetz über Prüfverfahren vom")

    def walk(nodes):
        for n in nodes:
            yield n
            yield from walk(n.get("children", []))

    types = {n["type"] for n in walk(doc["structure"])}
    assert {"part", "chapter", "section", "subsection", "number", "letter", "annex", "table", "text"} <= types  # the shared contract's German terms
    section = next(n for n in walk(doc["structure"]) if n["id"] == "doc/teil-1/kapitel-1/par-2")
    assert (section["nativeType"], section["number"], section["title"]) == ("Paragraph", "2", "Begriffsbestimmungen")
    fn = doc["footnotes"][0]
    assert fn["anchorElementId"] == "doc/teil-1/kapitel-1/par-2/abs-2" and fn["references"][0]["marker"] == "1"
    assert len(doc["tableOfContentsEntries"]) == 10 and all(t["targetElementId"] for t in doc["tableOfContentsEntries"])
    assert len(doc["sentences"]) == len(synthetic_german_model.sentences)
    lost = rep["downgrade_to_1_0_information_loss"]["dropped"]
    assert lost["sentences"]["values"] == len(doc["sentences"]) and lost["tableOfContentsEntries"]["values"] == 10


def test_akoma_ntoso_is_valid_and_complete(synthetic_german_model, tmp_path):
    pars = [p.number for p in synthetic_german_model.of_type(T.PARAGRAPH)]
    art = build_artifacts(synthetic_german_model, pars, "2099-03-16", tmp_path)
    assert pars == ["1", "2", "3", "4", "5"]
    assert art["validation"].valid, art["validation"].errors
    assert art["text"]["same_order_and_text"] and not art["result"].unmapped


def test_pipeline_run_with_the_german_profile(synthetic_german_raw_json, tmp_path, monkeypatch):
    import odos.pipeline as pl
    from odos.extraction import ExtractionResult

    def fake_extract(pdf, out_dir, do_ocr=False):  # Docling replaced by the synthetic extraction of the same PDF
        out_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(synthetic_german_raw_json, out_dir / "docling_raw.json")
        (out_dir / "extracted.md").write_text("(synthetic)")
        return ExtractionResult(source=pdf, json_path=out_dir / "docling_raw.json", markdown_path=out_dir / "extracted.md",
                                status="success", pages=3, text_items=40, tables=1, warnings=[])  # fmt: skip

    monkeypatch.setattr(pl, "extract_pdf", fake_extract)
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes((synthetic_german_raw_json.parent / "original.pdf").read_bytes())
    out = tmp_path / "out"
    res = pl.run_pipeline(pdf, out, pl.ProcessingMode.GERMAN_LAW, "2099-03-16")
    s = res.summary
    assert res.outcome == pl.Outcome.COMPLETED and res.message.startswith("German-law prototype conversion")
    assert (s["paragraphs"], s["parser_warnings"], s["uncertain_elements"], s["toc_found"]) == (5, 0, 0, True)
    assert s["json_valid"] and s["akn_generated"] and s["akn_xsd_valid"] and s["akn_text_identical"]
    assert (out / AKN_XML).is_file()
    assert json.loads((out / "document_model.json").read_text())["metadata"]["short_title"] == "BspG"


def test_without_the_pdf_text_layer_nothing_is_proven(synthetic_german_raw_json, tmp_path):
    """The evidence is what proves footnote anchors and printed Satz numbers: the same Docling JSON without it keeps
    the footnote unanchored and the numbered Absatz unsplit, with warnings, instead of guessing."""
    shutil.copy(synthetic_german_raw_json, tmp_path / "docling_raw.json")  # no pdf_text_lines.json next to it
    m = parse_document(tmp_path / "docling_raw.json", "german_law")
    assert m.by_id()["doc/teil-1/kapitel-1/par-2/fn-1"].anchor_ids == []
    assert not [s for s in m.sentences if s.unit_id == "doc/teil-1/kapitel-2/par-3/abs-1"]
    assert {w.code for w in m.warnings} >= {"SENTENCE_SEGMENTATION_UNRESOLVED"}
