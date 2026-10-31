"""Legal sentences, table-of-contents normalization, superscript classification, schema 1.1 compatibility."""

import hashlib
import json
import re

import pytest
from jsonschema import Draft202012Validator

from odos.legal_json.artifacts import SCHEMA_1_0_PATH, build_legal_json_artifacts, published_schema
from odos.legal_json.exporter import load_source_context, to_legal_json
from odos.legal_json.legacy import downgrade_to_1_0
from odos.document_model import ElementType as T
from odos.normalization.reading_order import SmallMark
from odos.parsing.sentences import _boundary_ok, _own, sequence
from odos.normalization.source_marks import classify

FROZEN_1_0 = "1b54a158b0f45ef99fd8732c77cd9499a60a3a4fa3872a867803ab9105dc69c2"


def _text(model, s):
    by = model.by_id()
    return " ".join(_own(by[r.element_id])[r.start : r.end] for r in s.ranges)


def _of(model, unit):
    return [s for s in model.sentences if s.unit_id == unit]


# ---- superscript classification (synthetic) --------------------------------------------------------------------------
def _mk(text, prev_glyph, gb, next_glyph, ga, before=""):
    return SmallMark(text=text, left=0, bottom=0, right=1, top=1, prev=" ", next=" ", prev_glyph=prev_glyph,
                     next_glyph=next_glyph, gap_before=gb, gap_after=ga, before=before)  # fmt: skip


@pytest.mark.parametrize("mark,cls", [
    (_mk("1", ")", 27.8, "D", 2.7), "sentence_number"),          # "(1) 1Die"
    (_mk("2", ".", 6.8, "§", 1.2), "sentence_number"),            # "… 2§ 18 Abs."
    (_mk("3", "[", 0.4, "W", 0.9), "sentence_number"),            # "[3Wird"
    (_mk("2", ".", 10.1, "D", 4.1), "sentence_number"),           # "Zeugnisses. 2 Dies"
    (_mk("1", "G", 1.1, "f", 6.7), "reference_attached"),         # "VwVfG1 finden"
    (_mk("3", "]", 1.0, "", None), "reference_attached"),         # "statt.]3" at the line end
    (_mk("*)", "…", 0.5, "z", 4.0), "reference_attached"),        # "Land …*) zur"
    (_mk("1", "n", 5.4, "B", 13.1), "reference_spaced"),          # "der höheren 1 Bauaufsichtsbehörde"
    (_mk("1", "…", 5.5, "", None), "reference_spaced"),           # "7. … 1"
    (_mk("2", "m", 2.1, "B", 5.7, before=" 1 000 m"), "exponent"),  # "1 000 m2 Brutto-Grundfläche"
    (_mk("1", "", None, "n", 3.3), "ambiguous"),                  # glued to a lowercase word
])  # fmt: skip
def test_mark_classes(mark, cls):
    assert classify(mark) == cls


# ---- sentence boundaries (synthetic) ----------------------------------------------------------------------------------
@pytest.mark.parametrize("text,ok", [
    ("nach § 6 Abs. 5 Satz 2 gilt", False), ("gemäß Nr. 3 sind", False), ("z. B. Gebäude", False),
    ("vom 30. Juni 2017", False), ("mindestens 3 m. Die", True), ("(EU) 2016/679. Die", True),
    ("Beschäftigten zu. Über", True), ("bis zum 14. Januar 2027. Die", True), ("des Rates ( 12 ). Diese", True),
    ("das 35. Lebensjahr", None), ("Absatz 2. § 3", None), ("Teil B. Sie", None),
])  # fmt: skip
def test_sentence_end_rules(text, ok):
    assert _boundary_ok(text, text.rindex(".")) is ok  # the last period of the sample is the one in question


# ---- sentences in the real documents ----------------------------------------------------------------------------------
@pytest.mark.parametrize("unit,expected", [
    ("doc/teil-1/par-1/abs-1", [("1", "1 Dieses Gesetz gilt für bauliche Anlagen und Bauprodukte."), ("2", "2 Es gilt auch für")]),
    ("doc/teil-2/par-6/abs-5", [("1", "1 Die Tiefe der Abstandsflächen beträgt 0,4 H, mindestens 3 m."),
                                ("2", "2 In Gewerbe- und Industriegebieten genügt eine Tiefe von 0,2 H, mindestens 3 m."),
                                ("3", "3 Vor den Außenwänden"), ("4", "4 Werden von einer städtebaulichen Satzung")]),
    ("doc/teil-3/abschnitt-5/par-33/abs-1", [("1", "1 Für Nutzungseinheiten"), ("2", "2 Ein zweiter Rettungsweg")]),
    ("doc/teil-3/abschnitt-5/par-36/abs-3", [("1", "1 Notwendige Flure"), ("2", "2 Die Rauchabschnitte sollen nicht länger als 30 m sein."),
                                             ("3", "3 Die Abschlüsse"), ("4", "4 Notwendige Flure mit nur einer Fluchtrichtung"),
                                             ("5", "5 Die Sätze 1 bis 4 gelten nicht für offene Gänge nach Absatz 5.")]),
])  # fmt: skip
def test_mbo_numbered_sentences(mbo_model, unit, expected):
    got = _of(mbo_model, unit)
    assert [s.number for s in got] == [n for n, _ in expected]
    for s, (n, start) in zip(got, expected):
        assert _text(mbo_model, s).startswith(start) and s.id == f"{unit}/satz-{n}" and s.method == "printed_number"
        assert s.mark_box is not None and s.mark_page is not None  # every number is a printed superscript in the PDF


def test_sentences_span_lists_and_text_after_lists(mbo_model):
    s1, s2 = _of(mbo_model, "doc/teil-1/par-1/abs-2")
    assert [r.element_id.rsplit("/", 1)[1] for r in s1.ranges] == ["abs-2", *[f"nr-{k}" for k in range(1, 9)]]
    assert _text(mbo_model, s1).startswith("1 Dieses Gesetz gilt nicht für") and s2.ranges[0].element_id.endswith("/txt-1")
    p3 = _of(mbo_model, "doc/teil-1/par-2/abs-3")
    assert [s.number for s in p3] == ["1", "2", "3"] and len({r.element_id for r in p3[0].ranges}) > 5  # the Gebäudeklassen list
    a, b = _of(mbo_model, "doc/teil-5/abschnitt-3/par-65/abs-1")  # Satz 2 "Dies gilt nicht für" + Nr. 4, Nr. 5 as printed
    assert [r.element_id.rsplit("/", 1)[1] for r in b.ranges] == ["abs-1", "nr-4", "nr-5"]


def test_unresolved_numbering_is_left_unsplit(mbo_model):
    assert not _of(mbo_model, "doc/teil-3/abschnitt-4/par-28/abs-5")  # the PDF prints Satz 2 but no Satz 1
    assert any(w.code == "SENTENCE_SEGMENTATION_UNRESOLVED" and w.element_id.endswith("par-28/abs-5") for w in mbo_model.warnings)


@pytest.mark.parametrize("fixture", ["mbo_model", "model", "eu_model"])
def test_sentences_cover_their_units_exactly(request, fixture):
    m = request.getfixturevalue(fixture)
    by = m.by_id()
    for unit in {s.unit_id for s in m.sentences}:
        seq = sequence(m, by[unit])
        covered = {(r.element_id, i) for s in _of(m, unit) for r in s.ranges for i in range(r.start, r.end)}
        for el in seq:  # every non-space character of the unit is in exactly one sentence, nothing added
            text = _own(el)
            assert all((el.id, i) in covered for i, c in enumerate(text) if not c.isspace()), (unit, el.id)
        for s in _of(m, unit):
            for r in s.ranges:
                assert r.text_sha256 == hashlib.sha256(_own(by[r.element_id]).encode()).hexdigest()
    ids = [s.id for s in m.sentences]
    assert len(ids) == len(set(ids)) and not set(ids) & set(by)


def test_bdsg_and_eu_sentences_are_unnumbered_and_not_split_at_abbreviations(model, eu_model):
    for m in (model, eu_model):
        assert m.sentences and all(s.number is None and s.method == "punctuation" for s in m.sentences)
        for s in m.sentences:
            t = _text(m, s)
            assert not re.search(r"\b(Abs|Nr|Art|S|ABl|vgl|bzw)\.$", t), t[-60:]
    inside = [s for m in (model, eu_model) for s in m.sentences if re.search(r"\b(Abs|Nr|Art|ABl|vgl|bzw|S)\. \S", _text(m, s))]
    assert inside  # sentences that contain such abbreviations were kept whole


def test_review_correction_regenerates_affected_sentences(mbo_model):
    from odos.review.model import Correction
    from odos.review.service import build_effective_model

    unit = "doc/teil-2/par-6/abs-5"
    old = mbo_model.by_id()[unit].content_text
    new = old.replace("0,4 H, mindestens 3 m.", "0,4 H, mindestens 3 m (korrigiert).")
    c = Correction(id="c1", element_id=unit, field="content_text", original_value=old, previous_value=old, corrected_value=new,
                   timestamp="2026-10-30T00:00:00Z", review_revision=1, model_revision=1)  # fmt: skip
    eff = build_effective_model(mbo_model, [c], 1)
    after = [s for s in eff.sentences if s.unit_id == unit]
    assert [s.id for s in after] == [s.id for s in _of(mbo_model, unit)]  # numbered ids stable across revisions
    assert all(s.status == "regenerated_from_reviewed_text" and s.mark_box is None for s in after)
    assert all(r.text_sha256 == hashlib.sha256(new.encode()).hexdigest() for s in after for r in s.ranges)
    assert "(korrigiert)" in _text(eff, after[0])
    untouched = [s for s in eff.sentences if s.unit_id != unit]
    assert all(s.status == "verified" for s in untouched if s.method == "printed_number")


# ---- table of contents -----------------------------------------------------------------------------------------------
def test_mbo_toc_entries_rebuilt_and_linked(mbo_model):
    toc = {e.id: e for e in mbo_model.toc_entries}
    e46 = toc["toc/paragraph-46"]  # "§", "46" and the title sit in three different table rows of one visual line
    assert (e46.marker, e46.title, e46.status, e46.target_id) == ("§ 46", "Blitzschutzanlagen", "linked", "doc/teil-3/abschnitt-6/par-46")
    assert {s.cell[0] for s in e46.source_spans} == {34, 35} and all(s.bbox and s.page == 2 for s in e46.source_spans)
    for n, t in (("1", "Anwendungsbereich"), ("2", "Begriffe"), ("3", "Allgemeine Anforderungen")):  # one merged Docling item
        assert (toc[f"toc/paragraph-{n}"].title, toc[f"toc/paragraph-{n}"].status) == (t, "linked")
    assert toc["toc/abschnitt-7"].title == "Nutzungsbedingte Anforderungen" and toc["toc/abschnitt-7"].status == "linked"
    assert toc["toc/paragraph-47"].target_id == "doc/teil-3/abschnitt-7/par-47"  # Docling put this heading after § 56
    linked = [e for e in mbo_model.toc_entries if e.status == "linked"]
    assert len(linked) == 113 and len(mbo_model.toc_entries) == 115
    assert {e.id for e in mbo_model.toc_entries if e.status != "linked"} == {"toc/paragraph-72a", "toc/paragraph-73"}
    assert toc["toc/paragraph-73"].candidate_ids == ["doc/teil-5/abschnitt-3/par-73"] and toc["toc/paragraph-73"].target_id is None


def test_bdsg_toc_handles_letter_spacing_and_printed_order(model):
    toc = {e.id: e for e in model.toc_entries}
    assert sum(e.status == "linked" for e in model.toc_entries) == 103 and len(model.toc_entries) == 111
    assert toc["toc/kapitel-6"].status == "linked"  # letter-spaced "Ka p i t e l 6", printed between § 19 and § 20
    ids = [e.id for e in model.toc_entries]
    assert ids.index("toc/paragraph-19") < ids.index("toc/kapitel-6") < ids.index("toc/paragraph-20")
    assert toc["toc/paragraph-20"].target_id == "doc/teil-1/kapitel-6/par-20"
    assert all(e.target_id is None for e in model.toc_entries if e.status != "linked")


def test_toc_entries_never_invent_text(mbo_model, model):
    for m in (mbo_model, model):
        by = m.by_id()
        for e in m.toc_entries:
            src = []
            for s in e.source_spans:
                el = by[s.element_id]
                text = next(c.text for c in el.table.cells if [c.row, c.col] == s.cell) if s.cell else el.content_text
                src.append(text[s.start : s.end])
            joined = re.sub(r"\s", "", "".join(src))
            assert re.sub(r"\s", "", f"{e.marker}{e.title or ''}") in joined or re.sub(r"\s", "", e.title or "") in joined, e.id


# ---- public JSON 1.1 -----------------------------------------------------------------------------------------------
def test_frozen_1_0_schema_is_unchanged():
    assert hashlib.sha256(SCHEMA_1_0_PATH.read_bytes()).hexdigest() == FROZEN_1_0


@pytest.mark.parametrize("fixture,raw", [("mbo_model", "mbo_raw_json"), ("model", "raw_json"), ("eu_model", "eu_raw_json")])
def test_json_1_1_and_its_1_0_downgrade_validate(request, fixture, raw, tmp_path):
    m, r = request.getfixturevalue(fixture), request.getfixturevalue(raw)
    rep = build_legal_json_artifacts(m, r, tmp_path)["report"]
    assert rep["valid"] and rep["schema_valid"] and rep["downgrade_to_1_0_valid"] and rep["structure_valid"], rep["structure_errors"][:3]
    data = json.loads((tmp_path / "document.json").read_text())
    assert data["schemaVersion"] == "1.1" and not list(Draft202012Validator(published_schema("1.1")).iter_errors(data))
    old = downgrade_to_1_0(data)
    assert old["schemaVersion"] == "1.0" and not list(Draft202012Validator(published_schema("1.0")).iter_errors(old))
    assert old["structure"] == json.loads(json.dumps(old["structure"]))  # every 1.0 field kept
    for t in data.get("tableOfContentsEntries", []):  # only confirmed links are published
        assert ("targetElementId" in t) == (next(e for e in m.toc_entries if e.id == t["id"]).status == "linked")
    assert not {"status", "evidence", "method", "candidate_ids", "candidateIds"} & {k for s in data.get("sentences", []) for k in s}


def test_json_sentence_ranges_resolve_against_node_text(mbo_model, mbo_raw_json):
    doc = to_legal_json(mbo_model, load_source_context(mbo_raw_json))
    stack, texts = [*doc.structure], {}
    while stack:
        n = stack.pop()
        texts[n.id] = n.text
        stack.extend(n.children)
    s = next(x for x in doc.sentences if x.id == "doc/teil-2/par-6/abs-5/satz-2")
    (r,) = s.ranges
    assert texts[r.elementId][r.start : r.end].startswith("2 In Gewerbe- und Industriegebieten")
    assert hashlib.sha256(texts[r.elementId].encode()).hexdigest() == r.textSha256
    assert texts[s.marker.elementId][s.marker.start : s.marker.end] == "2" and s.numberSource.page == 10
