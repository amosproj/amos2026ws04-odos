"""Source-verified reading-order repair (PDF text layer) for overlapping Docling layout boxes."""

import json
import re

import pytest

from odos.normalization.docling_reader import SourceItem, read_docling_json, read_page_sizes
from odos.normalization.hygiene import apply_hygiene
from odos.document_model import BoundingBox, Provenance
from odos.normalization.reading_order import EVIDENCE_NAME, TextLayerEvidence, TextLine, _norm, load_evidence, write_evidence

ART47 = ["doc/chp-7/art-47/para-1", "doc/chp-7/art-47/para-2", "doc/chp-7/art-47/para-3"]


# ---- the real case: Regulation (EU) 2023/1230, Art. 47 -------------------------------------------------------------------------
def test_art47_paragraphs_end_with_their_own_last_lines(eu_model):
    by = eu_model.by_id()
    ends = [by[i].content_text.rsplit(" ", 2)[-2:] for i in ART47]
    assert ends == [["Bedingungen", "übertragen."], ["jeweiligen", "Zeitraums."], ["nicht", "berührt."]]
    assert "doc/chp-7/art-47/para-3/txt-1" not in by  # the stray item is not a separate element any more
    for i, (stray_start, stray_end) in zip(ART47, [(0, 23), (24, 34), (35, 43)]):
        e = by[i]
        assert [(s.ref, s.start, s.end) for s in e.source_spans][-1] == ("#/texts/748", stray_start, stray_end)
        assert e.source_refs[-1] == "#/texts/748" and e.uncertain  # still for review
        assert e.uncertainty_reasons[-2:] == ["reading_order_uncertain:layout_box_overlaps_other_item",
                                              "reading_order_uncertain:repaired_from_pdf_text_layer"]  # fmt: skip


def test_art47_repair_matches_the_pdf_text_layer_independently(eu_model, eu_raw_json):
    """Independent check: each repaired paragraph equals the PDF's own visual lines from its "(n)" to the
    line before the next "(n)" (compared without whitespace and soft hyphens)."""
    ev = load_evidence(eu_raw_json)
    lines = [ln.text for ln in ev.pages[36]]
    head = lines.index("Ausübung der Befugnisübertragung")  # heading of Art. 47 (Art. 46 ends on the same page)
    starts = [next(k for k, t in enumerate(lines) if k > head and t.startswith(f"({n}) ")) for n in (1, 2, 3, 4)]
    by = eu_model.by_id()
    for n, i in enumerate(ART47):
        pdf_text = _norm("".join(lines[starts[n] : starts[n + 1]]))
        assert _norm(f"{by[i].marker} {by[i].content_text}") == pdf_text, i


def test_art47_repair_report_and_evidence(eu_raw_json):
    ev = load_evidence(eu_raw_json)
    # p.36: the overlapping boxes of Art. 47; p.24: the inferred split boundary "… ob a) …" of Art. 16(2)
    assert ev is not None and list(ev.pages) == [24, 36] and ev.extractor.startswith("pypdfium2") and ev.error is None
    _, items = read_docling_json(eu_raw_json)
    rep = apply_hygiene(items, read_page_sizes(eu_raw_json), ev).report
    (r,) = rep["reading_order_repairs"]
    assert r["repaired"] and r["stray_item"] == "#/texts/748" and ev.pdf_sha256 in r["evidence"]
    assert [(m["text"], m["appended_to"]) for m in r["moves"]] == [
        ("Bedingungen übertragen.", "#/texts/745"), ("Zeitraums.", "#/texts/746"), ("berührt.", "#/texts/747")]
    assert rep["accounting"]["ok"]  # every character of every Docling item still accounted for, exactly once


def test_without_evidence_nothing_is_repaired_and_items_stay_flagged(eu_raw_json):
    _, items = read_docling_json(eu_raw_json)
    rep = apply_hygiene(items, read_page_sizes(eu_raw_json), None)
    assert [r["repaired"] for r in rep.report["reading_order_repairs"]] == [False]
    stray = [i for i in rep.items if i.ref == "#/texts/748"]
    assert len(stray) == 1 and stray[0].order_flags == ["layout_box_overlaps_other_item"] and not stray[0].parts


def test_evidence_for_another_extraction_is_ignored(eu_raw_json, tmp_path):
    raw = tmp_path / "docling_raw.json"
    raw.write_bytes(eu_raw_json.read_bytes() + b" ")  # a different JSON (other sha256)
    (tmp_path / EVIDENCE_NAME).write_bytes((eu_raw_json.parent / EVIDENCE_NAME).read_bytes())
    assert load_evidence(raw) is None


def test_unreadable_pdf_is_recorded_not_raised(eu_raw_json, tmp_path):
    raw = tmp_path / "docling_raw.json"
    raw.write_bytes(eu_raw_json.read_bytes())
    pdf = tmp_path / "stub.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%stub\n")
    ev = json.loads(write_evidence(pdf, raw).read_text())
    assert ev["error"] and ev["pages"] == {}


def test_evidence_without_overlaps_has_item_text_but_no_lines(raw_json):
    ev = load_evidence(raw_json)  # BDSG: no overlapping layout boxes; written by the fixture from the PDF
    assert ev is not None and ev.error is None and ev.pages == {}
    assert len(ev.item_text) == 875 and ev.small_marks  # every text item's PDF text, and the superscript marks


def test_missing_pdf_is_recorded_and_nothing_is_restored(raw_json, tmp_path):
    raw = tmp_path / "docling_raw.json"
    raw.write_bytes(raw_json.read_bytes())
    write_evidence(tmp_path / "missing.pdf", raw)
    ev = load_evidence(raw)
    assert ev.error and not ev.item_text
    from odos.parsing import parse_document

    assert not any(e.text_repairs for e in parse_document(raw, "german_law").elements)  # without evidence: Docling's text


# ---- refusals (synthetic) -------------------------------------------------------------------------------------------------------
def _item(ref, text, top, bottom, left=68.0, right=528.0):
    prov = [Provenance(page_no=1, bbox=BoundingBox(l=left, t=top, r=right, b=bottom, coord_origin="BOTTOMLEFT"), charspan=(0, len(text)))]
    return SourceItem(ref=ref, label="text", layer="body", orig=text, text=text, provenance=prov)


def _line(text, top):
    return TextLine(top=top, bottom=top - 9, left=68, right=528, text=text)


def _ev(lines):
    return TextLayerEvidence(pdf_sha256="0" * 64, docling_json_sha256="0" * 64, extractor="test", pages={1: lines})


A = "(1) Erster Absatz mit einer"
A2 = "langen Zeile."
B = "(2) Zweiter Absatz."
STRAY = "Ende eins. Ende zwei."


def test_continuation_lines_are_repaired():
    items = [_item("#/texts/1", A, 260, 250), _item("#/texts/2", B, 230, 220), _item("#/texts/3", "Ende eins. Ende zwei.", 249, 200, right=160)]
    lines = [_line(A, 259), _line("Ende eins.", 248), _line(B, 229), _line("Ende zwei.", 218)]
    out = apply_hygiene(items, {1: (595.0, 842.0)}, _ev(lines))
    assert [i.orig for i in out.items] == [A + " Ende eins.", B + " Ende zwei."] and out.report["accounting"]["ok"]


@pytest.mark.parametrize(("lines", "reason"), [
    # a stray line in the MIDDLE of another paragraph (that paragraph's lines become non-contiguous): never repaired
    ([_line(A, 259), _line("Ende eins.", 248), _line(A2, 240), _line(B, 229), _line("Ende zwei.", 218)], "2 items with non-contiguous"),
    # the text layer lacks a line of the stray item: the remaining lines cannot be matched, unverifiable
    ([_line(A, 259), _line(B, 229), _line("Ende zwei.", 218)], "matches 0 items"),
    # a line that two items could own: ambiguous
    ([_line("(1)", 259)], "matches 2 items"),
])  # fmt: skip
def test_unprovable_cases_are_refused(lines, reason):
    first = A + " " + A2 if any(ln.text == A2 for ln in lines) else A
    items = [_item("#/texts/1", first, 260, 238), _item("#/texts/2", B, 230, 220), _item("#/texts/3", STRAY, 249, 200, right=160)]
    if reason == "matches 2 items":
        items = [_item("#/texts/1", "(1)", 260, 250), _item("#/texts/2", "(1)", 255, 200, right=160)]
    out = apply_hygiene(items, {1: (595.0, 842.0)}, _ev(lines))
    (r,) = out.report["reading_order_repairs"]
    assert not r["repaired"] and re.search(reason, r["reason"]), r
    assert [i.orig for i in out.items] == [i.orig for i in items] and all(i.order_flags for i in out.items)
