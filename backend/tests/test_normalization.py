import json
from pathlib import Path

import pytest

from odos.normalization.docling_reader import SourceItem, read_docling_json
from odos.document_model import ElementType as T, Provenance, SourceInfo
from odos.parsing import parse_document
from odos.parsing.profiles.german_law.recognizer import parse_items
from odos.parsing.profiles.german_law.report import build_report
from odos.parsing.profiles.german_law.rules import GERMAN_LAW_RULES

BACKEND = Path(__file__).resolve().parents[1]
BDSG = BACKEND / "data" / "input" / "BDSG.pdf"
RAW = BACKEND / "output" / "bdsg" / "docling_raw.json"


@pytest.fixture(scope="session")
def by_id(model):
    return model.by_id()


# ---- real BDSG -------------------------------------------------------------
def test_paragraphs_1_and_2_found_in_body_not_toc(model, by_id):
    for n, title in (("1", "Anwendungsbereich des Gesetzes"), ("2", "Begriffsbestimmungen")):
        p = by_id[f"doc/teil-1/kapitel-1/par-{n}"]
        assert p.type == T.PARAGRAPH and p.region == "body"
        assert p.marker == f"§ {n}" and p.title == title
        assert p.pages and p.pages[0] >= 5  # TOC ends on page 5, body starts after it


def test_toc_is_separate_from_body(model):
    assert not [e for e in model.elements if e.region == "toc" and e.type == T.PARAGRAPH]
    toc = model.by_id()["doc/toc"]
    assert toc.type == T.TOC and toc.children_ids
    body_paragraphs = {e.number for e in model.of_type(T.PARAGRAPH)}
    assert len(body_paragraphs) == len(model.of_type(T.PARAGRAPH)) == 86


def test_hierarchy(model, by_id):
    p1 = by_id["doc/teil-1/kapitel-1/par-1"]
    assert by_id[p1.parent_id].type == T.KAPITEL
    assert by_id[by_id[p1.parent_id].parent_id].type == T.TEIL
    assert [by_id[c].marker for c in p1.children_ids if by_id[c].type == T.ABSATZ] == [f"({i})" for i in range(1, 9)]  # fmt: skip
    nr2 = by_id["doc/teil-1/kapitel-1/par-1/abs-1/nr-2"]
    assert [by_id[c].marker for c in nr2.children_ids] == ["a)", "b)"]
    assert by_id[nr2.parent_id].type == T.ABSATZ
    # Abschnitt only inside Teil 2 / Kapitel 1
    assert {e.id for e in model.of_type(T.ABSCHNITT)} == {
        "doc/teil-2/kapitel-1/abschnitt-1",
        "doc/teil-2/kapitel-1/abschnitt-2",
    }
    allowed = {
        T.TEIL: {T.DOCUMENT}, T.KAPITEL: {T.TEIL}, T.ABSCHNITT: {T.KAPITEL},
        T.ABSATZ: {T.PARAGRAPH}, T.BUCHSTABE: {T.NUMMER},
    }  # fmt: skip
    for e in model.elements:
        if e.type in allowed:
            assert by_id[e.parent_id].type in allowed[e.type], e.id
        assert e.id in by_id[e.parent_id].children_ids if e.parent_id else True


def test_counts_of_real_structure(model):
    c = {t: len(model.of_type(t)) for t in (T.TEIL, T.KAPITEL, T.ABSCHNITT, T.PARAGRAPH)}
    assert c == {T.TEIL: 4, T.KAPITEL: 19, T.ABSCHNITT: 2, T.PARAGRAPH: 86}


def test_no_duplicate_ids(model):
    ids = [e.id for e in [*model.elements, *model.furniture]]
    assert len(ids) == len(set(ids))
    pids = [e.id for e in model.of_type(T.PARAGRAPH)]
    assert len(pids) == len(set(pids))


def test_provenance_preserved(model, raw_json):
    raw = json.loads(raw_json.read_text())
    for e in [*model.elements, *model.furniture]:
        if not e.source_refs:
            continue
        assert e.provenance and e.pages, e.id
        for p in e.provenance:
            assert 1 <= p.page_no <= 45 and p.bbox is not None
    _, kind, idx = model.by_id()["doc/teil-1/kapitel-1/par-1"].source_refs[0].split("/")
    node = raw[kind][int(idx)]
    p = model.by_id()["doc/teil-1/kapitel-1/par-1"].provenance[0]
    assert p.page_no == node["prov"][0]["page_no"]
    assert p.bbox.l == node["prov"][0]["bbox"]["l"]


def test_footnotes_and_tables(model, by_id):
    heads = model.of_type(T.FOOTNOTE_HEADING)
    assert len(heads) == 13  # 12 in the body + 1 in the front matter
    footnotes = model.of_type(T.FOOTNOTE)
    assert len(footnotes) == 12 and all(by_id[f.parent_id].type == T.FOOTNOTE_HEADING for f in footnotes)  # fmt: skip
    assert any("Textnachweis" in e.original_text for e in model.elements)
    tables = model.of_type(T.TABLE)
    assert len(tables) == 5 and all(t.table and t.table.rows and t.region == "toc" for t in tables)  # fmt: skip


def test_no_silent_content_loss(model, raw_json):
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
    assert rep["reverts_to_docling_exactly"] and rep["without_evidence"] == 0 and rep["verified_text_changes"] == 39


def test_nothing_invented(model):
    for e in model.elements:
        assert e.content_text in e.original_text or e.type in (T.DOCUMENT,), e.id
        if e.title:
            assert e.title.replace(" ", "") in e.original_text.replace(" ", "").replace("\n", "")


def test_ambiguous_content_is_flagged(model):
    ids = {e.id for e in model.elements if e.uncertain}
    r = next(e for e in model.elements if e.id == "doc/teil-1/kapitel-2/par-4/abs-1/run2-nr-1")
    assert not r.uncertain and "sentence_interlaced_list_restart" in r.hygiene_flags
    assert any(w.code == "HEADING_PATTERN_IN_TEXT" for w in model.warnings)  # "§ 63 Nummer 3 ..."


def test_stable_across_runs(raw_json):
    a = parse_document(raw_json, "german_law").model_dump_json()
    b = parse_document(raw_json, "german_law").model_dump_json()
    assert a == b


def test_normalize_cli_does_not_run_extraction(raw_json, tmp_path, monkeypatch):
    import odos.cli as cli

    monkeypatch.setattr(cli, "extract_pdf", lambda *a, **k: pytest.fail("extraction ran"))
    assert cli.main(["normalize", str(raw_json), "-o", str(tmp_path)]) == 0
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
    a = _item(1, "text", "(1) Es gilt für Gebäude")
    b = _item(2, "text", "und deren Umgebung.")
    a.provenance = [Provenance(page_no=1)]
    b.provenance = [Provenance(page_no=2)]
    m = _parse([_item(0, "section_header", "§ 1 A"), a, b])
    cont = [e for e in m.elements if "und deren Umgebung" in e.original_text][0]
    assert "continuation_across_page_break_attached_to_previous_element" in cont.uncertainty_reasons
    assert "possible_continuation_of_previous_element" not in cont.uncertainty_reasons
