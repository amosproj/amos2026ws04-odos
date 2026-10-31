"""Exact highlight rectangles from PDF glyphs, and the normalized TOC order / regeneration after review."""

import re
from datetime import datetime, timezone

from odos.normalization.highlight import IGNORE, boxes_for, glyph_map
from odos.document_model import BoundingBox
from odos.normalization.reading_order import GlyphLine, load_evidence

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


def test_every_partial_element_is_exact_or_approximate_never_wrong(eu_model, eu_raw_json, model, mbo_model):
    ev = load_evidence(eu_raw_json)
    partial = [e for e in eu_model.elements if e.source_spans]
    assert partial and all(e.highlight_boxes for e in partial)
    for e in partial:
        assert _glyph_text(ev, e.highlight_boxes) == _compact(f"{e.marker or ''}{e.content_text}" if e.marker and not e.content_text.startswith(e.marker) else e.original_text.replace("\n", "")), e.id
        own = [p.bbox for p in e.provenance]
        for b in e.highlight_boxes:  # inside the Docling boxes the element came from
            assert any(o.l - 2 <= b.bbox.l and b.bbox.r <= o.r + 2 and o.b - 2 <= b.bbox.b and b.bbox.t <= o.t + 2 for o in own), e.id
    for m in (model, mbo_model):  # German laws: boxes only on partial elements
        assert all(e.source_spans for e in m.elements if e.highlight_boxes)


# ---- conservative alignment (synthetic) -------------------------------------------------------------------------------
def _ln(text, top, left=0.0):
    return GlyphLine(top=top, bottom=top - 10, text=text, xs=[(left + i, left + i + 1) for i in range(len(text))])


BOX = [(1, BoundingBox(l=-5, t=200, r=500, b=0, coord_origin="BOTTOMLEFT"))]


def test_alignment_maps_whole_lines_in_order_and_skips_foreign_lines():
    lines = {1: [_ln("(1) Erster Absatz", 100), _ln("fremde Zeile", 90), _ln("geht weiter.", 80)]}
    text = "(1) Erster Absatz geht weiter."
    m = glyph_map(text, BOX, lines)
    boxes = boxes_for(text, 0, len(text), m, lines)
    assert [round(b.bbox.t) for b in boxes] == [100, 80]  # the foreign line is not part of the highlight


def test_alignment_refuses_what_it_cannot_prove():
    assert glyph_map("Abschnitt eins", BOX, {1: [_ln("Abschnitt zwei", 100)]}) is None  # text differs
    rep = {1: [_ln("gleiche Zeile", 100), _ln("gleiche Zeile", 90)]}
    assert glyph_map("gleiche Zeile", BOX, rep) is None  # the same line text twice: which one is ours is not proven
    assert glyph_map("ab", [(1, BoundingBox(l=0, t=10, r=5, b=0, coord_origin="TOPLEFT"))], {1: [_ln("ab", 5)]}) is None
    assert glyph_map("Teil", BOX, {}) is None  # no glyph evidence for the page


# ---- TOC ----------------------------------------------------------------------------------------------------------
def test_mbo_page_3_toc_is_in_printed_order(mbo_model):
    page3 = [e for e in mbo_model.toc_entries if any(s.page == 3 for s in e.source_spans)]
    assert [e.marker for e in page3[:14]] == [
        "Siebenter Abschnitt", "§ 47", "§ 48", "§ 49", "§ 50", "§ 51", "Vierter Teil",
        "§ 52", "§ 53", "§ 54", "§ 55", "§ 56", "Fünfter Teil", "Erster Abschnitt"]  # fmt: skip
    assert all(e.status == "linked" and e.target_id for e in page3)
    assert page3[0].target_id == "doc/teil-3/abschnitt-7" and page3[6].target_id == "doc/teil-4"


def test_raw_toc_correction_regenerates_derived_entries(mbo_model):
    from odos.review.model import Correction
    from odos.review.service import build_effective_model

    raw = mbo_model.by_id()["doc/toc/entry-2"]  # Docling merged "§ 1 … § 2 … § 3 …" into one item
    new = raw.content_text.replace("Begriffe", "Begriffsbestimmungen")
    c = Correction(id="c1", element_id=raw.id, field="content_text", original_value=raw.content_text, previous_value=raw.content_text,
                   corrected_value=new, timestamp=datetime.now(timezone.utc), review_revision=1, model_revision=1)  # fmt: skip
    eff = build_effective_model(mbo_model, [c], 1)
    toc = {e.id: e for e in eff.toc_entries}
    assert toc["toc/paragraph-2"].title == "Begriffsbestimmungen" and toc["toc/paragraph-2"].status == "candidate"  # no longer matches
    assert toc["toc/paragraph-1"].status == "linked" and toc["toc/paragraph-1"].evidence.startswith("regenerated from reviewed text")
    assert [e.id for e in eff.toc_entries] == [e.id for e in mbo_model.toc_entries]  # same entries, same order, same ids
    assert {e.id: e.evidence for e in eff.toc_entries if "entry-2" not in "".join(e.source_element_ids)} == \
           {e.id: e.evidence for e in mbo_model.toc_entries if "entry-2" not in "".join(e.source_element_ids)}  # fmt: skip
    assert mbo_model.by_id()["doc/toc/entry-2"].content_text != new  # the original model is untouched
