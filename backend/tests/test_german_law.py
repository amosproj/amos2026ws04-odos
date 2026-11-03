"""The German-law profile end to end on the synthetic law (tests/synthetic_german.py): always runs, needs no partner
document. Its generated PDF has a real text layer, so footnote anchors and printed Satz numbers are proven from the
PDF as they are for real laws. The real Musterbauordnung is covered in tests/private/test_mbo.py and test_api.py.

Glyph coordinates come from pdfium and may differ in the last decimals between platforms, so structure and validity
are asserted instead of hashes."""

import json
import shutil

from odos.document_model import ElementType as T
from odos.parsing import engine, parse_document
from odos.parsing.profiles import GERMAN_LAW


def test_structure_numbering_and_metadata(synthetic_german_raw_json, synthetic_german_model):
    m = synthetic_german_model
    trace: list[str] = []
    again = engine.parse(synthetic_german_raw_json, GERMAN_LAW, trace)
    assert trace == [name for name, _ in engine.STAGES] and again.model_dump_json() == m.model_dump_json()  # deterministic
    assert not m.warnings and not any(e.uncertain for e in m.elements)  # a clean law raises nothing

    md = m.metadata
    assert (md.title, md.short_title) == ("Beispielgesetz über Prüfverfahren", "BspG")
    assert md.ausfertigungsdatum == "15.03.2099" and md.vollzitat == "Beispielgesetz über Prüfverfahren vom 15. März 2099 (BGBl. I S. 1)"

    idx = m.by_id()
    expected = {
        "doc/teil-1": T.TEIL, "doc/teil-1/kapitel-1": T.KAPITEL, "doc/teil-1/kapitel-1/par-1": T.PARAGRAPH,
        "doc/teil-1/kapitel-1/par-1/abs-2": T.ABSATZ, "doc/teil-1/kapitel-1/par-2/abs-1/nr-3": T.NUMMER,
        "doc/teil-1/kapitel-1/par-2/abs-1/nr-3/lit-b": T.BUCHSTABE, "doc/teil-2/par-5": T.PARAGRAPH,
        "doc/teil-2/par-5/txt-1": T.TEXT, "doc/anlage-1": T.ANLAGE, "doc/anlage-1/table-1": T.TABLE,
    }  # fmt: skip
    assert {i: idx[i].type for i in expected} == expected
    par2 = idx["doc/teil-1/kapitel-1/par-2"]
    assert (par2.marker, par2.number, par2.title) == ("§ 2", "2", "Begriffsbestimmungen")
    assert idx["doc/teil-1/kapitel-1/par-2/abs-1/nr-3"].children_ids == ["doc/teil-1/kapitel-1/par-2/abs-1/nr-3/lit-a", "doc/teil-1/kapitel-1/par-2/abs-1/nr-3/lit-b"]  # fmt: skip
    assert idx["doc/anlage-1/table-1"].table.rows == [["Nr.", "Prüfgegenstand"], ["1", "Unterlagen"], ["2", "Verfahren"]]
    assert all(f.region == "furniture" for f in m.furniture) and len(m.furniture) == 6  # running headers and footers stay outside


def test_table_of_contents_is_linked_to_the_body(synthetic_german_model):
    entries = {t.id: t for t in synthetic_german_model.toc_entries}
    assert list(entries) == ["toc/teil-1", "toc/kapitel-1", "toc/paragraph-1", "toc/paragraph-2", "toc/kapitel-2", "toc/paragraph-3",
                             "toc/paragraph-4", "toc/teil-2", "toc/paragraph-5", "toc/anlage-1"]  # printed order
    assert all(t.status == "linked" for t in entries.values())  # kind, number, title and enclosing headings agree
    assert entries["toc/paragraph-3"].target_id == "doc/teil-1/kapitel-2/par-3" and entries["toc/anlage-1"].target_id == "doc/anlage-1"


def test_footnote_anchor_and_sentences_are_proven_by_the_pdf(synthetic_german_model):
    m = synthetic_german_model
    fn = m.by_id()["doc/teil-1/kapitel-1/par-2/fn-1"]  # anchored by its superscript reference mark in the PDF
    assert fn.type == T.FOOTNOTE and fn.anchor_ids == ["doc/teil-1/kapitel-1/par-2/abs-2"]
    assert fn.footnote_refs[0].bbox is not None and "footnote_anchor_from_pdf_reference_mark" in fn.hygiene_flags

    by_unit: dict[str, list] = {}
    for s in m.sentences:
        by_unit.setdefault(s.unit_id, []).append(s)
    printed = by_unit["doc/teil-1/kapitel-2/par-3/abs-1"]  # "1 … 2 …": the printed Satz numbers
    assert [(s.method, s.number, s.status) for s in printed] == [("printed_number", "1", "verified"), ("printed_number", "2", "verified")]
    assert [s.method for s in by_unit["doc/teil-1/kapitel-2/par-3/abs-2"]] == ["punctuation", "punctuation"]  # split at "Eingang. Sie"


def test_without_the_pdf_text_layer_nothing_is_proven(synthetic_german_raw_json, tmp_path):
    """The text layer is what proves footnote anchors and printed Satz numbers: the same Docling JSON without it keeps
    the footnote unanchored and the numbered Absatz unsplit, with a warning, instead of guessing."""
    shutil.copy(synthetic_german_raw_json, tmp_path / "docling_raw.json")  # no pdf_text_lines.json next to it
    m = parse_document(tmp_path / "docling_raw.json", "german_law")
    assert m.by_id()["doc/teil-1/kapitel-1/par-2/fn-1"].anchor_ids == []
    assert not [s for s in m.sentences if s.unit_id == "doc/teil-1/kapitel-2/par-3/abs-1"]
    assert {w.code for w in m.warnings} >= {"SENTENCE_SEGMENTATION_UNRESOLVED"}


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
    res = pl.run_pipeline(pdf, out, pl.ProcessingMode.GERMAN_LAW)
    s = res.summary
    assert res.outcome == pl.Outcome.COMPLETED
    assert (s["paragraphs"], s["parser_warnings"], s["uncertain_elements"], s["toc_found"]) == (5, 0, 0, True)
    assert s["json_valid"] and s["json_schema_valid"] and s["json_text_identical"]
    doc = json.loads((out / "document.json").read_text())
    assert (doc["schemaVersion"], doc["legalSystem"], doc["documentType"]) == ("2.0", "de", "de_legislation")
    assert json.loads((out / "document_model.json").read_text())["metadata"]["short_title"] == "BspG"
