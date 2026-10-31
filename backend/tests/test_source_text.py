"""Source-faithful text: characters Docling normalised away are restored from the PDF text layer, with evidence."""

import json
import re

import pytest

from odos.legal_json.artifacts import build_legal_json_artifacts
from odos.normalization.reading_order import load_evidence
from odos.normalization.source_text import Lexicon, _pdf_text, align, restore, revert


def _restore(docling, pdf, lexicon=()):
    return restore(docling, [pdf], "#/texts/1", [1], Lexicon(list(lexicon)), "pypdfium2 test")


# ---- rules (synthetic) ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("docling,pdf,expected,status,rule", [
    ("In Gewerbeund Industriegebieten", "In Gewerbe\x02\r\nund Industriegebieten", "In Gewerbe- und Industriegebieten", "verified", "suspended_hyphen_before_conjunction"),
    ("ein CEZeichen", "ein CE\x02\r\nZeichen", "ein CE-Zeichen", "verified", "hyphen_before_capital"),
    ("50 m³ BruttoRauminhalt", "50 m³ Brutto\x02\r\nRauminhalt", "50 m³ Brutto-Rauminhalt", "verified", "hyphen_before_capital"),
    ("Behandlungs-, Sport, Spiel-", "Behandlungs-, Sport-\r\n, Spiel-", "Behandlungs-, Sport-, Spiel-", "verified", "hyphen_before_non_letter"),
    ("ALLGEMEINEVORSCHRIFTEN", "ALLGEMEINE\x02\r\nVORSCHRIFTEN", "ALLGEMEINE-VORSCHRIFTEN", "unresolved", "no_document_evidence"),
    ("das Wort wiederholung", "das Wort wieder\x02\r\nholung", "das Wort wieder-holung", "unresolved", "no_document_evidence"),
])  # fmt: skip
def test_line_end_hyphen_rules(docling, pdf, expected, status, rule):
    text, repairs, _ = _restore(docling, pdf)
    assert text == expected and [(r.status, r.rule) for r in repairs] == [(status, rule)]
    assert revert(text, repairs) == docling  # Docling's text is always recoverable


def test_document_evidence_decides_lowercase_continuations():
    lex = ["öffentlich-rechtlich gesichert", "der Brandschutznachweis ist", "Brandschutznachweise"]
    text, (r,), _ = _restore("wenn öffentlichrechtlich", "wenn öffentlich\x02\r\nrechtlich", lex)
    assert text == "wenn öffentlich-rechtlich" and (r.status, r.rule) == ("verified", "hyphenated_form_elsewhere_in_document")
    text, (r,), _ = _restore("Brandschutznachweisen", "Brandschutznach\x02\r\nweisen", lex)
    assert text == "Brandschutznachweisen" and (r.status, r.rule, r.restored) == ("verified", "joined_form_elsewhere_in_document", "")
    text, (r,), _ = _restore("abcdef", "abc\x02\r\ndef", ["abc-def", "abcdef"])
    assert (text, r.status, r.rule) == ("abc-def", "unresolved", "conflicting_document_evidence")  # printed hyphen kept


def test_typography_is_restored_and_ligatures_and_soft_hyphens_are_not_changes():
    text, repairs, _ = _restore('Bezeichnung "Architekt" - S. 35', "Bezeichnung „Architekt“ – S. 35")
    assert text == "Bezeichnung „Architekt“ – S. 35" and {r.kind for r in repairs} == {"typography"}
    assert _restore("Mitglied\xadstaaten", "Mitglied\x02\r\nstaaten")[1] == []  # the PDF's soft hyphen, kept by Docling
    assert _restore("die Beschaffenheit", "die Beschaﬀenheit")[1] == []  # ligature: same text


def test_any_other_difference_is_never_repaired():
    assert align("Gewerbe und", "Gewerbe oder") is None
    assert _restore("3 Satz", "2 Satz") is None
    assert align('Wort "x"', "Wort «x»") is None  # not one of Docling's normalisations


# ---- real documents against their PDFs --------------------------------------------------------------------------------
def test_mbo_restorations(mbo_model):
    by = mbo_model.by_id()
    a = by["doc/teil-2/par-6/abs-5"]
    assert "In Gewerbe- und Industriegebieten" in a.content_text and "Gewerbeund" in a.docling_text
    (r,) = [r for r in a.text_repairs if r.rule == "suspended_hyphen_before_conjunction"]
    assert r.page == 10 and "line end" in r.evidence and r.evidence.startswith("pypdfium2")
    text = {e.id: e.original_text for e in mbo_model.elements}
    joined = " ".join(text.values())
    for printed in ("CE-Zeichen", "Brutto-Rauminhalt", "Netto-Raumfläche", "Brutto-Grundfläche", "Umwelt-Rechtsbehelfs",
                    "dicht- und", "Schall- und", "Mittel- und", "Bemessungs- und", "Sport-, Spiel-", "„Architekt“",
                    "ECTS-Leistungspunkten", "öffentlich-rechtlich"):  # fmt: skip
        assert printed in joined, printed
    assert "S. 35 – Maschinenrichtlinie" in text["doc/teil-1/par-1/abs-2/nr-8"]
    assert "Brandschutznachweisen" in joined and "Brandschutznach-weisen" not in joined  # a word division: Docling right
    unresolved = [(e, r) for e in mbo_model.elements for r in e.text_repairs if r.status == "unresolved"]
    assert len(unresolved) == 1 and "thematisch-naturwissenschaftlichen" in unresolved[0][0].original_text
    e = unresolved[0][0]
    assert e.uncertain and "source_text_uncertain:no_document_evidence" in e.uncertainty_reasons
    assert any(w.code == "LINE_END_HYPHEN_UNRESOLVED" and w.element_id == e.id for w in mbo_model.warnings)


def test_bdsg_and_eu_restorations(model, eu_model, eu_raw_json):
    by = model.by_id()
    assert "„personenbezogene Daten“" in by["doc/teil-3/kapitel-1/par-46/nr-1"].content_text
    assert any("Schiffs- und Busverkehrs" in e.original_text for e in model.elements)
    assert eu_model.by_id()["doc/preamble/formula"].original_text.endswith("UNION —")
    from odos.normalization.docling_reader import read_docling_json

    _, items = read_docling_json(eu_raw_json)  # the EU's own soft hyphens (word divisions) are all still there
    assert sum(e.original_text.count("\xad") for e in eu_model.elements) == sum(i.orig.count("\xad") for i in items if not i.is_furniture) - _soft_in_furniture(eu_model)  # fmt: skip


def _soft_in_furniture(m):
    return sum(e.original_text.count("\xad") for e in m.furniture)


# ---- source fidelity of document.json -------------------------------------------------------------------------------
@pytest.fixture(scope="module", params=["bdsg", "mbo", "eu"])
def fidelity(request, tmp_path_factory):
    m_name, raw_name = {"bdsg": ("model", "raw_json"), "mbo": ("mbo_model", "mbo_raw_json"), "eu": ("eu_model", "eu_raw_json")}[request.param]  # fmt: skip
    model, raw = request.getfixturevalue(m_name), request.getfixturevalue(raw_name)
    out = tmp_path_factory.mktemp(request.param)
    rep = build_legal_json_artifacts(model, raw, out)["report"]
    return request.param, model, raw, rep, json.loads((out / "document.json").read_text())


def test_json_text_matches_the_pdf_text_layer(fidelity):
    name, model, raw, rep, _ = fidelity
    sf = rep["source_fidelity"]
    assert sf["pdf_text_layer"] and sf["unexplained_differences"] == [], sf["unexplained_differences"][:3]
    assert sf["items_compared"] == sf["identical"] + sf["identical_except_recorded_word_divisions"]
    assert sf["items_compared"] > {"bdsg": 780, "mbo": 1170, "eu": 1800}[name]
    assert rep["text_preservation"]["identical_to_model"]  # and still equal to the canonical model


def test_toc_holds_no_page_numbers(fidelity):
    name, _, _, _, data = fidelity
    for toc in data["tableOfContents"]:
        assert not [c for c in toc.get("children", []) if re.fullmatch(r"\s*\d{1,3}\s*", c.get("text") or "")]


@pytest.mark.parametrize("par,absatz,page,path", [
    ("6", "5", 10, ["Zweiter Teil", "§ 6", "(5)"]), ("33", "1", 29, ["Dritter Teil", "Fünfter Abschnitt", "§ 33", "(1)"]),
    ("36", "3", 33, ["Dritter Teil", "Fünfter Abschnitt", "§ 36", "(3)"]), ("37", "5", 34, ["Dritter Teil", "Fünfter Abschnitt", "§ 37", "(5)"]),
])  # fmt: skip
def test_acceptance_samples_against_the_pdf(mbo_model, mbo_raw_json, par, absatz, page, path):
    ev = load_evidence(mbo_raw_json)
    a = next(e for e in mbo_model.elements if e.type.value == "absatz" and e.number == absatz
             and mbo_model.by_id()[e.parent_id].number == par and mbo_model.by_id()[e.parent_id].type.value == "paragraph")  # fmt: skip
    assert [x.marker for x in mbo_model.path(a.id)[1:]] == path and a.pages == [page]
    (ref,) = a.source_refs
    events = align(a.original_text, _pdf_text(ev.item_text[ref])[0])
    assert events is not None and all(e[0] == "hyphen" and e[3] for e in events)  # identical to the PDF, printed hyphens included
    nxt = mbo_model.elements[[e.id for e in mbo_model.elements].index(a.id) + 1]
    assert nxt.marker in (f"({int(absatz) + 1})", f"§ {int(par) + 1}")  # nothing of the next unit is inside


# ---- footnote anchors from reference marks ---------------------------------------------------------------------------
def test_every_proven_anchor_holds_its_reference_mark(mbo_model, mbo_raw_json):
    ev = load_evidence(mbo_raw_json)
    by = mbo_model.by_id()
    from odos.normalization.source_marks import classify, is_reference

    proven = [f for f in mbo_model.elements if f.type.value == "footnote" and f.anchor_ids and f.docling_label == "footnote"]
    assert len(proven) == 35
    for f in proven:
        mark = re.match(r"^\s*(\d+|\*+\)?)", f.original_text).group(1).rstrip(")")
        for r in f.footnote_refs:  # every reference: a reference-class mark of that number, inside the anchor's box
            a = by[r.element_id]
            box = next(p.bbox for p in a.provenance if p.page_no == r.page)
            inside = [m for m in ev.small_marks[r.page] if m.text.rstrip(")") == mark and is_reference(classify(m))
                      and box.l - 1 <= (m.left + m.right) / 2 <= box.r + 1 and box.b - 1 <= (m.bottom + m.top) / 2 <= box.t + 1]  # fmt: skip
            assert inside, (f.id, r.element_id)


def test_no_mark_is_both_a_reference_and_a_sentence_number(mbo_model):
    refs = {(r.page, round(r.bbox.l, 2), round(r.bbox.b, 2)) for f in mbo_model.elements for r in f.footnote_refs if r.bbox}
    nums = {(s.mark_page, round(s.mark_box.l, 2), round(s.mark_box.b, 2)) for s in mbo_model.sentences if s.mark_box}
    assert refs and nums and not refs & nums and len(refs) == sum(len(f.footnote_refs) for f in mbo_model.elements if f.footnote_refs and f.footnote_refs[0].bbox)  # fmt: skip


def test_ambiguous_pages_keep_footnotes_unanchored(mbo_model):
    open_ = [f for f in mbo_model.elements if f.type.value == "footnote" and f.docling_label == "footnote" and not f.anchor_ids]
    assert [f.id for f in open_] == ["doc/teil-5/abschnitt-5/par-82/fn-2"]  # a competing unclear mark ("]26") on its page
    w = next(w for w in mbo_model.warnings if w.code == "FOOTNOTE_REFERENCE_UNRESOLVED")
    assert w.element_id == open_[0].id and "26" in w.message
