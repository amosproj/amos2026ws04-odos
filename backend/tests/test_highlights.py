"""Exact highlight rectangles from PDF glyphs, and the PDF text-layer evidence they rest on."""

import json

from odos.normalization.highlight import IGNORE, boxes_for, glyph_map
from odos.document_model import BoundingBox
from odos.normalization.reading_order import GlyphLine, load_evidence, write_evidence
from odos.parsing import parse_document

ART47 = [f"doc/chp-7/art-47/para-{n}" for n in (1, 2, 3, 4)]


def _compact(s: str) -> str:
    return "".join(c for c in s if not c.isspace() and c not in IGNORE)


def _glyph_text(ev, boxes) -> str:
    """The PDF characters inside the given rectangles, line by line."""
    out = []
    for b in boxes:
        for ln in ev.glyph_lines.get(b.page_no) or ev.glyph_lines.get(str(b.page_no)):
            if abs(ln.top - b.bbox.t) < 0.01 and abs(ln.bottom - b.bbox.b) < 0.01:
                out.append("".join(c for c, (l, r) in zip(ln.text, ln.xs) if l >= b.bbox.l - 0.01 and r <= b.bbox.r + 0.01))
    return _compact("".join(out))


def _overlap(a, b) -> bool:
    return a.page_no == b.page_no and min(a.bbox.r, b.bbox.r) > max(a.bbox.l, b.bbox.l) and min(a.bbox.t, b.bbox.t) > max(a.bbox.b, b.bbox.b)


# ---- EU Art. 47 ------------------------------------------------------------------------------------------------------
def test_article_47_paragraphs_get_exact_non_overlapping_boxes(eu_model, eu_raw_json):
    ev = load_evidence(eu_raw_json)
    by = eu_model.by_id()
    p1, p2, p3, p4 = (by[i] for i in ART47)
    assert [len(p.highlight_boxes) for p in (p1, p2, p3)] == [2, 6, 6]  # one rectangle per printed line
    assert not p4.highlight_boxes and not p4.source_spans  # its own Docling item: the provenance box is already exact
    for p in (p1, p2, p3):  # the rectangles hold exactly this paragraph's characters, nothing of a neighbour
        assert _glyph_text(ev, p.highlight_boxes) == _compact(f"{p.marker}{p.content_text}"), p.id
    every = [(p.id, b) for p in (p1, p2, p3) for b in p.highlight_boxes] + [(p4.id, b) for b in p4.provenance]
    for i, (ia, a) in enumerate(every):
        for ib, b in every[i + 1 :]:
            if ia != ib:
                assert not _overlap(a, b), (ia, ib)
    for p in (p1, p2, p3):  # the reading-order uncertainty is not resolved by geometry: it stays for review
        assert p.uncertain and "reading_order_uncertain:repaired_from_pdf_text_layer" in p.uncertainty_reasons


def test_every_partial_element_is_exact_or_inside_its_docling_boxes(eu_model, eu_raw_json, synthetic_german_model, mbo_model):
    ev = load_evidence(eu_raw_json)
    partial = [e for e in eu_model.elements if e.source_spans]
    assert partial and all(e.highlight_boxes for e in partial)
    for e in partial:
        assert _glyph_text(ev, e.highlight_boxes) == _compact(f"{e.marker or ''}{e.content_text}" if e.marker and not e.content_text.startswith(e.marker) else e.original_text.replace("\n", "")), e.id
        own = [p.bbox for p in e.provenance]
        for b in e.highlight_boxes:  # inside the Docling boxes the element came from
            assert any(o.l - 2 <= b.bbox.l and b.bbox.r <= o.r + 2 and o.b - 2 <= b.bbox.b and b.bbox.t <= o.t + 2 for o in own), e.id
    for m in (synthetic_german_model, mbo_model):  # German laws: boxes only on partial elements
        assert all(e.source_spans for e in m.elements if e.highlight_boxes)


# ---- conservative alignment (synthetic) -------------------------------------------------------------------------------
def _ln(text, top, left=0.0):
    return GlyphLine(top=top, bottom=top - 10, text=text, xs=[(left + i, left + i + 1) for i in range(len(text))])


BOX = [(1, BoundingBox(l=-5, t=200, r=500, b=0, coord_origin="BOTTOMLEFT"))]


def test_alignment_maps_whole_lines_and_refuses_what_it_cannot_prove():
    lines = {1: [_ln("(1) Erster Absatz", 100), _ln("fremde Zeile", 90), _ln("geht weiter.", 80)]}
    text = "(1) Erster Absatz geht weiter."
    boxes = boxes_for(text, 0, len(text), glyph_map(text, BOX, lines), lines)
    assert [round(b.bbox.t) for b in boxes] == [100, 80]  # the foreign line is not part of the highlight

    assert glyph_map("Abschnitt eins", BOX, {1: [_ln("Abschnitt zwei", 100)]}) is None  # text differs
    twice = {1: [_ln("gleiche Zeile", 100), _ln("gleiche Zeile", 90)]}
    assert glyph_map("gleiche Zeile", BOX, twice) is None  # the same line text twice: which one is ours is not proven
    assert glyph_map("Teil", BOX, {}) is None  # no glyph evidence for the page


# ---- missing or unreadable PDF -------------------------------------------------------------------------------------
def test_missing_or_unreadable_pdf_is_recorded_and_nothing_is_restored(synthetic_german_raw_json, tmp_path):
    raw = tmp_path / "docling_raw.json"
    raw.write_bytes(synthetic_german_raw_json.read_bytes())
    write_evidence(tmp_path / "missing.pdf", raw)
    ev = load_evidence(raw)
    assert ev.error and not ev.item_text
    assert not any(e.text_repairs for e in parse_document(raw, "german_law").elements)  # without evidence: Docling's text

    stub = tmp_path / "stub.pdf"
    stub.write_bytes(b"%PDF-1.4\n%stub\n")
    recorded = json.loads(write_evidence(stub, raw).read_text())  # recorded, not raised
    assert recorded["error"] and recorded["pages"] == {}
