import json

import pytest

from odos.normalization.docling_reader import SourceItem, read_docling_json
from odos.document_model import BoundingBox, ElementType as T, Provenance, SourceInfo
from odos.parsing import parse_document
from odos.parsing.profiles.german_law.recognizer import parse_items
from odos.parsing.profiles.german_law.report import build_report
from odos.parsing.profiles.german_law.rules import GERMAN_LAW_RULES


# ---- the synthetic German law (tests/synthetic_german.py): the real-document checks, without a partner document ----
def test_no_duplicate_ids(synthetic_german_model):
    model = synthetic_german_model
    ids = [e.id for e in [*model.elements, *model.furniture]]
    assert len(ids) == len(set(ids))
    pids = [e.id for e in model.of_type(T.PARAGRAPH)]
    assert len(pids) == len(set(pids))


def test_provenance_preserved(synthetic_german_model, synthetic_german_raw_json):
    model = synthetic_german_model
    raw = json.loads(synthetic_german_raw_json.read_text())
    for e in [*model.elements, *model.furniture]:
        if not e.source_refs:
            continue
        assert e.provenance and e.pages, e.id
        for p in e.provenance:
            assert p.page_no >= 1 and p.bbox is not None
    _, kind, idx = model.by_id()["doc/teil-1/kapitel-1/par-1"].source_refs[0].split("/")
    node = raw[kind][int(idx)]
    p = model.by_id()["doc/teil-1/kapitel-1/par-1"].provenance[0]
    assert p.page_no == node["prov"][0]["page_no"]
    assert p.bbox.l == node["prov"][0]["bbox"]["l"]


def test_no_silent_content_loss(synthetic_german_model, synthetic_german_raw_json):
    model, raw_json = synthetic_german_model, synthetic_german_raw_json
    _, items = read_docling_json(raw_json)
    src = {i.ref: i for i in items}
    refs = [r for e in [*model.elements, *model.furniture] for r in e.source_refs]
    assert sorted(refs) == sorted(src)  # every Docling item exactly once
    for e in [*model.elements, *model.furniture]:
        for r in e.source_refs:  # Docling's own text, kept next to the PDF-restored text when they differ
            assert (e.docling_text if e.docling_text is not None else e.original_text) == src[r].orig
    report = build_report(model, raw_json)
    assert not report.docling_items_missing and not report.docling_items_duplicated
    assert not report.text_mismatches
    rep = report.source_text_repairs
    assert rep["reverts_to_docling_exactly"] and rep["without_evidence"] == 0


def test_nothing_invented(synthetic_german_model):
    for e in synthetic_german_model.elements:
        assert e.content_text in e.original_text or e.type in (T.DOCUMENT,), e.id
        if e.title:
            assert e.title.replace(" ", "") in e.original_text.replace(" ", "").replace("\n", "")


def test_stable_across_runs(synthetic_german_raw_json):
    a = parse_document(synthetic_german_raw_json, "german_law").model_dump_json()
    b = parse_document(synthetic_german_raw_json, "german_law").model_dump_json()
    assert a == b


def test_normalize_cli_does_not_run_extraction(synthetic_german_raw_json, tmp_path, monkeypatch):
    import odos.cli as cli

    monkeypatch.setattr(cli, "extract_pdf", lambda *a, **k: pytest.fail("extraction ran"))
    assert cli.main(["normalize", str(synthetic_german_raw_json), "-o", str(tmp_path)]) == 0
    assert (tmp_path / "document_model.json").stat().st_size > 0
    assert (tmp_path / "validation_report.md").exists()


# ---- synthetic units (no Docling needed) -----------------------------------------
def _item(i, label, text, marker=None, enumerated=None, page=1):
    return SourceItem(
        ref=f"#/texts/{i}", label=label, layer="furniture" if label.startswith("page_") else "body",
        orig=(f"{marker} {text}" if marker else text), text=text, marker=marker,
        enumerated=enumerated, provenance=[Provenance(page_no=page)],
    )  # fmt: skip


def _parse(items):
    info = SourceInfo(docling_json_sha256="x", num_pages=1)
    return parse_items(info, items, GERMAN_LAW_RULES)


def test_synthetic_other_law_without_toc():
    m = _parse([
        _item(0, "section_header", "Abschnitt 1 Allgemeines"),
        _item(1, "section_header", "§ 1 Zweck"),
        _item(2, "text", "(1) Erster Satz:"),
        _item(3, "list_item", "alpha", "1.", True),
        _item(4, "list_item", "beta", "2.", True),
        _item(5, "text", "Schlusssatz."),
        _item(6, "text", "(2) Zweiter Absatz."),
        _item(7, "section_header", "§ 2 Begriffe"),
        _item(8, "text", "Nur ein Satz ohne Absatzzählung."),
    ])  # fmt: skip
    ids = [e.id for e in m.elements]
    assert "doc/abschnitt-1/par-1/abs-1/nr-2" in ids
    assert m.by_id()["doc/abschnitt-1/par-1/abs-1/txt-1"].uncertain  # text after list
    assert m.by_id()["doc/abschnitt-1/par-2/txt-1"].type == T.TEXT
    assert any(w.code == "NO_TOC_FOUND" for w in m.warnings)


def test_synthetic_unknown_header_and_orphans_are_kept():
    m = _parse([
        _item(0, "section_header", "Präambel"),
        _item(1, "text", "(1) Absatz ohne Paragraph."),
        _item(2, "list_item", "ohne Marker", None, False),
    ])
    types = [e.type for e in m.elements]
    assert T.UNRECOGNIZED in types and T.UNMARKED_LIST_ITEM in types
    assert sum(1 for e in m.elements if e.source_refs) == 3
    codes = {w.code for w in m.warnings}
    assert {"UNRECOGNIZED_HEADING", "ABSATZ_OUTSIDE_PARAGRAPH", "LIST_ITEM_WITHOUT_RECOGNIZED_MARKER"} <= codes  # fmt: skip


def test_text_that_looks_like_a_heading_stays_text_with_a_warning():
    m = _parse([
        _item(0, "section_header", "§ 1 A"),
        _item(1, "text", "(1) Es gilt."),
        _item(2, "text", "§ 63 Nummer 3 bleibt unberührt."),
    ])  # fmt: skip
    assert any(w.code == "HEADING_PATTERN_IN_TEXT" for w in m.warnings)
    assert [e.number for e in m.of_type(T.PARAGRAPH)] == ["1"]  # not turned into a § 63


def test_synthetic_sequence_gaps_warn_but_do_not_drop():
    m = _parse([
        _item(0, "section_header", "§ 1 A"),
        _item(1, "text", "(1) a"),
        _item(2, "text", "(3) c"),
        _item(3, "section_header", "§ 1 A again"),
    ])
    assert len(m.of_type(T.ABSATZ)) == 2 and len(m.of_type(T.PARAGRAPH)) == 2
    codes = {w.code for w in m.warnings}
    assert {"ABSATZ_SEQUENCE", "PARAGRAPH_ORDER", "DUPLICATE_ID_RESOLVED"} <= codes


# ---- German-law rules found with the Musterbauordnung (synthetic, no Docling) ---------------------------------
def _toc_doc(body):
    """Merged TOC lines (several § per item) followed by a body whose headings are split over two items."""
    return [
        _item(0, "section_header", "Titel des Gesetzes"),
        _item(1, "section_header", "Inhaltsverzeichnis"),
        _item(2, "section_header", "Erster Teil Allgemeines"),
        _item(3, "section_header", "§ 1 Zweck § 2 Begriffe"),  # merged, two § in one header: not a body start
        _item(4, "list_item", "§ 3 Weiteres", "-", False),
        *body,
    ]


def test_body_start_with_split_heading_and_absatz_list_items():
    m = _parse(_toc_doc([
        _item(10, "section_header", "Erster Teil"), _item(11, "section_header", "Allgemeines"),
        _item(12, "section_header", "§ 1"), _item(13, "section_header", "Zweck"),
        _item(14, "list_item", "1 Dieses Gesetz gilt.", "(1)", True),
        _item(15, "section_header", "§ 2 Begriffe"), _item(16, "text", "Ein Satz ohne Absatz."),
    ]))
    assert m.by_id()["doc/teil-1"].region == "body" and m.by_id()["doc/teil-1"].title == "Allgemeines"
    assert m.by_id()["doc/teil-1/par-1"].title == "Zweck" and m.by_id()["doc/teil-1/par-1"].source_refs == ["#/texts/12", "#/texts/13"]  # fmt: skip
    assert m.by_id()["doc/teil-1/par-1/abs-1"].type == T.ABSATZ  # list_item "(1)" is an Absatz
    assert m.by_id()["doc/toc"].children_ids and all(m.by_id()[c].region == "toc" for c in m.by_id()["doc/toc"].children_ids)  # fmt: skip
    assert [p.number for p in m.of_type(T.PARAGRAPH)] == ["1", "2"]


def test_ordinal_headings_and_anlage():
    m = _parse([
        _item(0, "section_header", "Zweiter Teil Besondere Vorschriften"), _item(1, "section_header", "Dritter Abschnitt Mehr"),
        _item(2, "section_header", "§ 4a Titel"), _item(3, "text", "Text."),
        _item(4, "section_header", "Anlage 1 (zu § 4a)"), _item(5, "text", "Inhalt der Anlage."),
        _item(6, "list_item", "Erstens", "1.", True),
    ])
    by = m.by_id()
    assert by["doc/teil-2"].number == "2" and by["doc/teil-2"].marker == "Zweiter Teil"
    assert by["doc/teil-2/abschnitt-3/par-4a"].type == T.PARAGRAPH
    assert by["doc/anlage-1"].parent_id == "doc" and by["doc/anlage-1/nr-1"].type == T.NUMMER
    assert not m.warnings or all(w.code != "UNEXPECTED_PARENT" for w in m.warnings)


def test_numeric_heading_only_continues_the_paragraph_sequence():
    m = _parse([
        _item(0, "section_header", "§ 22 Erste"), _item(1, "text", "Text."),
        _item(2, "section_header", "23 Zertifizierung"), _item(3, "text", "(1) Absatz."),
        _item(4, "section_header", "99 Kein Paragraph"), _item(5, "text", "Anderes."),
    ])
    p = {e.number: e for e in m.of_type(T.PARAGRAPH)}
    assert set(p) == {"22", "23"} and p["23"].marker == "23" and p["23"].uncertain  # not rewritten to "§ 23"
    assert any(e.type == T.UNRECOGNIZED and e.original_text == "99 Kein Paragraph" for e in m.elements)  # kept, not guessed


def test_absatz_and_nummer_mislabelled_as_headers_and_bracketed_nummer():
    m = _parse([
        _item(0, "section_header", "§ 1 A"), _item(1, "section_header", "(1) Ausgenommen sind"),
        _item(2, "section_header", "1. folgende Anlagen:"), _item(3, "list_item", "Garagen", "a)", True),
        _item(4, "list_item", "[1. optional Text", None, False), _item(5, "footnote", "1 gemäß Landesvorschrift"),
    ])
    by = m.by_id()
    assert not by["doc/par-1/abs-1"].uncertain and "absatz_labelled_section_header_by_docling_confirmed" in by["doc/par-1/abs-1"].hygiene_flags
    assert by["doc/par-1/abs-1/nr-1/lit-a"].type == T.BUCHSTABE
    assert [e.type for e in m.elements if e.source_refs and e.source_refs[0] == "#/texts/5"] == [T.FOOTNOTE]
    assert any(e.original_text.startswith("[1.") and e.type == T.NUMMER for e in m.elements)


def test_page_break_continuation_stays_with_its_item():
    a = _item(1, "list_item", "9. die Anordnung von Treppen,", "9.", True)
    b = _item(2, "list_item", "Fluren und Rettungswegen,", None, False)
    c = _item(3, "list_item", "10. die Beleuchtung,", "10.", True)
    b.provenance = [Provenance(page_no=2)]
    m = _parse([_item(0, "section_header", "§ 1 A"), _item(9, "text", "(1) Es gilt:"), a, b, c])
    cont = m.by_id()["doc/par-1/abs-1/nr-9/txt-1"]
    assert cont.type == T.UNMARKED_LIST_ITEM and cont.uncertain and "continuation_across_page_break" in cont.uncertainty_reasons[1]  # fmt: skip
    assert m.by_id()["doc/par-1/abs-1/nr-10"].parent_id == "doc/par-1/abs-1"  # the list went on


def test_enumeration_closing_clause_is_confirmed():
    """Text after a list that starts lowercase and the previous item lacks sentence-end punctuation."""
    m = _parse([
        _item(0, "section_header", "§ 1 A"),
        _item(1, "text", "(1) Es gilt für"),
        _item(2, "list_item", "Gebäude,", "1.", True),
        _item(3, "list_item", "Anlagen,", "2.", True),
        _item(4, "text", "soweit dies erforderlich ist."),
    ])
    closing = m.by_id()["doc/par-1/abs-1/txt-1"]
    assert not closing.uncertain
    assert "enumeration_closing_clause_confirmed" in closing.hygiene_flags
    assert not any(w.code == "POSSIBLE_CONTINUATION" for w in m.warnings)


def test_enumeration_closing_clause_not_confirmed_when_uppercase():
    """Uppercase text after a list stays uncertain (could be a new sentence, not a closing clause)."""
    m = _parse([
        _item(0, "section_header", "§ 1 A"),
        _item(1, "text", "(1) Es gilt:"),
        _item(2, "list_item", "Gebäude,", "1.", True),
        _item(3, "text", "Weitere Bestimmungen gelten."),
    ])
    txt = m.by_id()["doc/par-1/abs-1/txt-1"]
    assert txt.uncertain
    assert "text_after_list_attached_to_enclosing_container" in txt.uncertainty_reasons


def test_satz_n_in_unmarked_list_item_is_confirmed():
    """Docling list_item without marker starting with '2 Satz...' is a Satz-N continuation."""
    m = _parse([
        _item(0, "section_header", "§ 1 A"),
        _item(1, "text", "(1) Erster Satz:"),
        _item(2, "list_item", "alpha", "1.", True),
        _item(3, "list_item", "beta", "2.", True),
        _item(4, "list_item", "2 Satz 1 gilt auch für den Fall", None, False),
    ])
    satz = [e for e in m.elements if "2 Satz 1 gilt" in e.original_text][0]
    assert not satz.uncertain
    assert "unmarked_list_item_satz_n_confirmed" in satz.hygiene_flags


def test_nummer_labelled_as_section_header_by_docling_is_confirmed():
    """Docling labels a numbered item as 'section_header' but the parser recognizes the marker — confirmed."""
    m = _parse([
        _item(0, "section_header", "§ 1 A"),
        _item(1, "text", "(1) Es gilt:"),
        _item(2, "section_header", "1. Werbeanlagen an der Stätte,"),
        _item(3, "section_header", "2. einzelne Hinweiszeichen."),
    ])
    nr1 = m.by_id()["doc/par-1/abs-1/nr-1"]
    assert not nr1.uncertain
    assert "numbered_item_labelled_section_header_by_docling_confirmed" in nr1.hygiene_flags


def test_no_redundant_possible_continuation_with_page_break():
    """When a page-break continuation reason exists, possible_continuation is not added redundantly."""
    a = _item(1, "text", "(1) Es gilt für")
    n = _item(2, "list_item", "Gebäude und", "1.", True)
    b = _item(3, "text", "deren Umgebung.")
    a.provenance = n.provenance = [Provenance(page_no=1)]
    b.provenance = [Provenance(page_no=2)]
    m = _parse([_item(0, "section_header", "§ 1 A"), a, n, b])
    cont = [e for e in m.elements if "deren Umgebung" in e.original_text][0]
    assert cont.parent_id == "doc/par-1/abs-1/nr-1"  # a Nummer runs on: stays its own flagged element
    assert "continuation_across_page_break_attached_to_previous_element" in cont.uncertainty_reasons
    assert "possible_continuation_of_previous_element" not in cont.uncertainty_reasons


def _bbox(t: float, b: float) -> BoundingBox:
    return BoundingBox(l=60, t=t, r=530, b=b, coord_origin="BOTTOMLEFT")


def test_absatz_text_over_a_page_break_is_one_text():
    """The text of an Absatz runs on lowercase on the next page before its list: one Absatz, both sources kept."""
    a = _item(1, "text", "(1) 1 Vor den Wänden sind Flächen von")
    b = _item(2, "text", "oberirdischen Gebäuden freizuhalten. 2 Sie sind nicht erforderlich vor Wänden,")
    n1 = _item(3, "list_item", "die an der Grenze stehen, oder", "1.", True)
    n2 = _item(4, "list_item", "soweit Abstände zulässig sind.", "2.", True)
    a.provenance = [Provenance(page_no=9, bbox=_bbox(62, 51), charspan=(0, len(a.orig)))]
    b.provenance = [Provenance(page_no=10, bbox=_bbox(776, 696), charspan=(0, len(b.orig)))]
    n1.provenance = n2.provenance = [Provenance(page_no=10)]
    m = _parse([_item(0, "section_header", "§ 6 Abstände"), a, b, n1, n2])
    by = m.by_id()
    abs1 = by["doc/par-6/abs-1"]
    assert abs1.content_text == "1 Vor den Wänden sind Flächen von oberirdischen Gebäuden freizuhalten. 2 Sie sind nicht erforderlich vor Wänden,"
    assert abs1.original_text == a.orig + "\n" + b.orig  # the source pieces, one per line
    assert abs1.source_refs == ["#/texts/1", "#/texts/2"] and abs1.pages == [9, 10]
    assert [(p.page_no, p.charspan) for p in abs1.provenance] == [(9, (0, len(a.orig))), (10, (0, len(b.orig)))]
    assert abs1.children_ids == ["doc/par-6/abs-1/nr-1", "doc/par-6/abs-1/nr-2"]
    assert not abs1.uncertain and "page_break_continuation_merged_confirmed" in abs1.hygiene_flags
    assert not any("txt" in e.id for e in m.elements)


def test_uppercase_text_after_a_page_break_stays_separate():
    """A capitalised line on the next page may start a new sentence: kept as its own flagged element."""
    a = _item(1, "text", "(1) Es gilt für Gebäude")
    b = _item(2, "text", "Deren Umgebung bleibt unberührt.")
    a.provenance = [Provenance(page_no=1)]
    b.provenance = [Provenance(page_no=2)]
    m = _parse([_item(0, "section_header", "§ 1 A"), a, b])
    cont = m.by_id()["doc/par-1/abs-1/txt-1"]
    assert cont.uncertain and "continuation_across_page_break_attached_to_previous_element" in cont.uncertainty_reasons
    assert m.by_id()["doc/par-1/abs-1"].source_refs == ["#/texts/1"]
