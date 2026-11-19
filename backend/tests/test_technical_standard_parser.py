"""Technical-standard parser (DIN, DIN EN, DIN ISO, DIN EN ISO, DIN VDE, DIN SPEC, ISO, IEC, EN).

Synthetic Docling output with invented text models the structures observed in real standards; each test that stems from a
defect found on the real DIN EN ISO 12100:2011-03 says so. The real PDF is copyrighted and not in Git: the end-to-end test
at the bottom runs only when ODOS_DIN_EN_ISO_12100_PDF (or backend/data/input/private/din_en_iso_12100.pdf) exists.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from odos.document_model import ElementType as T
from odos.legal_json.artifacts import build_legal_json_artifacts, published_schema, serialize
from odos.legal_json.exporter import to_legal_json
from odos.legal_json.nesting import validate_structure
from odos.legal_json.view import json_schema
from odos.normalization.docling_reader import read_docling_json
from odos.parsing import parse_document
from odos.parsing.profiles import PROFILES, get
from odos.parsing.profiles.technical_standard import TECHNICAL_STANDARD
from odos.parsing.profiles.technical_standard import recognizer as R

PRIVATE_PDF = Path(__file__).resolve().parents[1] / "data" / "input" / "private" / "din_en_iso_12100.pdf"


# ---- synthetic Docling documents with tables, pictures and nested captions --------------------------------------------
class Doc:
    """Builds a Docling JSON. Items are laid out top-down on their page unless `top` (PDF points from the page bottom) is given."""

    def __init__(self, pages: int, header: str = "DIN EN ISO 99999:2020-01"):
        self.pages, self.texts, self.tables, self.pictures, self.body, self.furniture, self.y = pages, [], [], [], [], [], {}
        for p in range(1, pages + 1):
            ref = self._text("page_header", header, p, 820.0, layer="furniture")
            self.furniture.append({"$ref": ref})

    def _box(self, page: int, top: float | None, left: float = 57.0, right: float = 538.0) -> dict:
        k = self.y.get(page, 0)
        self.y[page] = k + 1
        t = 760.0 - 30 * k if top is None else top
        return {"l": left, "t": float(t), "r": right, "b": float(t - 14), "coord_origin": "BOTTOMLEFT"}

    def _text(self, label: str, text: str, page: int, top: float | None = None, layer: str = "body", left: float = 57.0, right: float = 538.0) -> str:
        ref = f"#/texts/{len(self.texts)}"
        self.texts.append({"self_ref": ref, "label": label, "content_layer": layer, "orig": text, "text": text,
                           "prov": [{"page_no": page, "bbox": self._box(page, top, left, right), "charspan": [0, len(text)]}]})  # fmt: skip
        return ref

    def h(self, text, page, top=None, left=57.0, right=538.0):
        self.body.append({"$ref": self._text("section_header", text, page, top, left=left, right=right)})
        return self

    def x(self, text, page, top=None, label="text", left=57.0, right=538.0):
        self.body.append({"$ref": self._text(label, text, page, top, left=left, right=right)})
        return self

    def table(self, page, rows, caption=None):
        ref = f"#/tables/{len(self.tables)}"
        kids = [{"$ref": self._text("caption", caption, page, 700.0)}] if caption else []  # nested: not in the body tree
        self.tables.append({"self_ref": ref, "label": "table", "content_layer": "body", "children": kids,
                            "prov": [{"page_no": page, "bbox": self._box(page, None), "charspan": [0, 0]}],
                            "data": {"num_rows": len(rows), "num_cols": len(rows[0]), "grid": [[{"text": c} for c in r] for r in rows],
                                     "table_cells": [self._cell(r, c, v) for r, row in enumerate(rows) for c, v in enumerate(row)]}})  # fmt: skip
        self.body.append({"$ref": ref})
        return self

    @staticmethod
    def _cell(r: int, c: int, text: str) -> dict:
        top = 600.0 - 20 * r  # one box per cell, cells of a row on one line (the TOC joiner reads these)
        return {"start_row_offset_idx": r, "start_col_offset_idx": c, "row_span": 1, "col_span": 1, "text": text,
                "bbox": {"l": 60.0 + 150 * c, "t": top, "r": 200.0 + 150 * c, "b": top - 14, "coord_origin": "BOTTOMLEFT"}}  # fmt: skip

    def picture(self, page, caption=None, top=None):
        ref = f"#/pictures/{len(self.pictures)}"
        kids = [{"$ref": self._text("caption", caption, page, 100.0)}] if caption else []
        self.pictures.append({"self_ref": ref, "label": "picture", "content_layer": "body", "children": kids,
                              "prov": [{"page_no": page, "bbox": self._box(page, top), "charspan": [0, 0]}]})  # fmt: skip
        self.body.append({"$ref": ref})
        return self

    def save(self, path: Path) -> Path:
        doc = {"schema_name": "DoclingDocument", "version": "1.10.0",
               "origin": {"filename": "synthetic.pdf", "mimetype": "application/pdf", "binary_hash": 1},
               "body": {"children": self.body}, "furniture": {"children": self.furniture}, "groups": [],
               "tables": self.tables, "pictures": self.pictures, "texts": self.texts,
               "pages": {str(p): {"size": {"width": 595.0, "height": 842.0}, "page_no": p} for p in range(1, self.pages + 1)}}  # fmt: skip
        Path(path).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return Path(path)


def parse(doc: Doc, tmp_path: Path):
    path = doc.save(tmp_path / "docling_raw.json")
    return parse_document(path, "technical_standard"), path


def _continues(table) -> list[str]:
    return [f for f in table.hygiene_flags if f.startswith("table_continues")]


def by_number(model, *types):
    return {e.number: e for e in model.elements if e.number and (not types or e.type in types)}


def standard() -> Doc:
    """An invented DIN EN ISO standard with the structure of the real one: cover, TOC, forewords, deep clauses, terms,
    notes, figure/table captions nested under their item, a three-line annex heading, a national annex with its own
    bibliography, a closing bibliography."""
    d = Doc(pages=9)
    d.h("DIN EN ISO 99999", 1).x("Sicherheit von Beispielen", 1)
    d.h("Nationales Vorwort", 2).x("Dieses Dokument wurde vom Ausschuss erarbeitet.", 2)
    d.h("Nationaler Anhang NA", 2).x("(informativ)", 2).h("Literaturhinweise", 2)
    d.x("DIN 820-120, Normungsarbeit", 2).x("DIN EN 349, Mindestabstände", 2)
    d.h("EUROPÄISCHE NORM", 3).h("EN ISO 99999", 3).x("Mai 2010", 3)
    d.h("Inhalt", 4)
    d.table(4, [["1", "Anwendungsbereich ........", "5"], ["3.1", "Maschine ........", "6"], ["4.1", "Allgemeines ........", "7"]])
    d.h("Vorwort", 5).x("Dieses Dokument ersetzt eine frühere Ausgabe.", 5)
    d.h("1 Anwendungsbereich", 5).x("Dieses Dokument legt Begriffe fest.", 5)
    d.h("3 Begriffe", 6).x("Es gelten die folgenden Begriffe.", 6)
    d.h("3.1", 6).h("Maschine", 6).x("Gesamtheit verbundener Teile", 6)
    d.x("ANMERKUNG 1 Der Begriff schließt Anlagen ein.", 6).x("BEISPIEL Werkzeugmaschine", 6)
    d.h("3.2 Gefährdung", 6).x("potenzielle Schadensquelle", 6)
    d.h("3.3", 6).h("Schutzeinrichtungen", 6)
    d.h("3.3.1", 6).h("feste Einrichtung", 6).x("Einrichtung ohne Scharnier", 6)
    d.h("4 Strategie", 7).h("4.1 Allgemeines", 7).x("Folgende Schritte sind nötig:", 7)
    d.x("⎯ Grenzen festlegen", 7).x("a) Gefährdungen erkennen", 7).x("ii) Risiko einschätzen", 7)
    d.h("4.1.1 Einzelheiten", 7).x("Text der Einzelheiten.", 7)
    d.picture(7, caption="Bild 1 - Übersicht über den Prozess").picture(7)
    d.h("4.2 Zweiter Abschnitt", 7).x("Weiterer Text.", 7)
    d.h("5 Dokumentation", 7).x("Text.", 7)
    d.x("Siehe Bild A.1.", 8, top=500.0).picture(8, caption="Bild A.1 - Schematische Darstellung", top=400.0)
    d.h("Anhang A", 8, top=790.0).x("(informativ)", 8, top=770.0).h("Schematische Darstellung", 8, top=750.0)
    d.h("Anhang B (normativ) Beispiele", 9)
    d.h("B.1 Allgemeines", 9).table(9, [["a", "b"], ["c", "d"]], caption="Tabelle B.1")
    d.table(9, [["e", "f"]], caption="Tabelle B.1 (fortgesetzt)")
    d.h("Literaturhinweise", 9).x("[1] DIN EN ISO 13849-1, Sicherheit von Maschinen", 9).x("- Leerseite -", 9)
    return d


@pytest.fixture
def model(tmp_path):
    return parse(standard(), tmp_path)[0]


# ---- patterns ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("line,family,number,issue", [
    ("DIN EN ISO 12100:2011-03", "DIN EN ISO", "12100", "2011-03"),
    ("DIN VDE 0100-200:2023-06", "DIN VDE", "0100-200", "2023-06"),
    ("DIN SPEC 91345", "DIN SPEC", "91345", None),
    ("DIN 820-1:2014-06", "DIN", "820-1", "2014-06"),
    ("DIN VDE 0100-200 (VDE 0100-200):2023-06", "DIN VDE", "0100-200", "2023-06"),
    ("DIN SPEC 91345:2016-04 (D)", "DIN SPEC", "91345", "2016-04"),
    ("ISO/IEC 27000:2018(E)", "ISO/IEC", "27000", "2018"),
    ("ETSI EN 303 645 V2.1.1 (2020-06)", "ETSI EN", "303 645", None),
    ("DIN EN IEC 60529:2022-07", "DIN EN IEC", "60529", "2022-07"),
    ("DIN ISO/IEC 27001:2024-05", "DIN ISO/IEC", "27001", "2024-05"),
    ("ISO 9001:2015", "ISO", "9001", "2015"),
    ("IEC 61508-3", "IEC", "61508-3", None),
    ("EN 61000-6-2", "EN", "61000-6-2", None),
])  # fmt: skip
def test_title_families(line, family, number, issue):
    m = R.TITLE_RX.match(line)
    assert m and (m["family"], m["number"], m["issue"]) == (family, number, issue)


@pytest.mark.parametrize("line", ["Beispiele für Maschinen", "Beispielsweise gilt", "Notebook", "Anmerkung zur Norm", "Notwendig ist"])
def test_prose_is_not_a_note_or_example(line):
    assert not R.NOTE_RX.match(line) and not R.EXAMPLE_RX.match(line)


def test_notes_examples_captions_lists():
    assert R.NOTE_RX.match("ANMERKUNG 2 Text").group(2) == "2"
    assert R.NOTE_RX.match("NOTE 1 to entry: text").group(3) == "text"
    assert R.EXAMPLE_RX.match("BEISPIEL 1 Werkzeug").group(2) == "1"
    m = R.TABLE_CAPTION_RX.match("Tabelle B.1 (fortgesetzt)")
    assert (m.group(2), m.group(3), m.group(4)) == ("B.1", None, "fortgesetzt")
    assert R.TABLE_CAPTION_RX.match("Tabelle 2 - Risikoklassen").group(3) == "Risikoklassen"
    assert R.FIGURE_CAPTION_RX.match("Bild A.1 - Schematische Darstellung").group(2) == "A.1"
    assert not R.TABLE_CAPTION_RX.match("Tabelle 1 enthält die Werte.")
    assert R.DASH_RX.match("⎯ Verhalten") and R.ROMAN_LIST_RX.match("iii) Quellen")
    assert R.ANNEX_RX.match("Nationaler Anhang NA").group(2) == "NA"
    assert R.ANNEX_RX.match("Annex C (informative) Examples").group(3) == "informative"


# ---- hierarchy: driven by the printed number --------------------------------------------------------------------------
def test_siblings_and_children_follow_the_dotted_number(model):
    c = by_number(model, T.CLAUSE, T.DEFINITION)
    assert c["4.1"].parent_id == c["4"].id and c["4.2"].parent_id == c["4"].id  # 4.2 is not nested under 4.1
    assert c["4.1.1"].parent_id == c["4.1"].id
    assert c["5"].parent_id == "doc" and c["1"].parent_id == "doc"
    assert c["3.3.1"].parent_id == c["3.3"].id


def test_annex_clauses_nest_under_their_annex(model):
    annexes = {a.number: a for a in model.of_type(T.STANDARD_ANNEX)}
    b1 = next(e for e in model.elements if e.number == "B.1" and e.type == T.CLAUSE)
    assert b1.parent_id == annexes["B"].id


# ---- definitions (real: "3.1" and its term are two headers; "3.2 term" is one) ----------------------------------------------
def test_definitions_with_split_and_single_line_headings(model):
    defs = by_number(model, T.DEFINITION)
    assert defs["3.1"].title == "Maschine" and defs["3.2"].title == "Gefährdung"
    assert len(defs["3.1"].source_refs) == 2  # number header and term header, both kept
    assert [model.by_id()[c].type for c in defs["3.1"].children_ids] == [T.TEXT, T.NOTE, T.EXAMPLE]
    assert by_number(model, T.CLAUSE)["3"].hygiene_flags == ["clause_opens_terms_and_definitions"]


def test_group_of_definitions_is_a_clause(model):
    assert by_number(model)["3.3"].type == T.CLAUSE and by_number(model)["3.3.1"].type == T.DEFINITION
    assert any(n.code == "DEFINITION_GROUP_HEADING" for n in model.structure_notes)


# ---- annexes, bibliographies, covers -----------------------------------------------------------------------------------
def test_three_line_annex_heading_with_classification(model):
    a = {x.number: x for x in model.of_type(T.STANDARD_ANNEX)}
    assert (a["A"].classification, a["A"].title) == ("informative", "Schematische Darstellung")
    assert (a["B"].classification, a["B"].title) == ("normative", "Beispiele")  # one-line form
    assert a["NA"].marker == "Nationaler Anhang NA" and a["NA"].classification == "informative"


def test_national_annex_holds_its_bibliography_final_one_is_top_level(model):
    bibs = model.of_type(T.BIBLIOGRAPHY)
    assert sorted(b.parent_id for b in bibs) == ["doc", "doc/annex-na"]
    nested = next(b for b in bibs if b.parent_id != "doc")
    assert len(nested.children_ids) == 2 and all(model.by_id()[c].type == T.BIBLIOGRAPHIC_ENTRY for c in nested.children_ids)


def test_blank_page_marker_is_not_a_bibliographic_entry(model):
    blank = [e for e in model.elements if "blank_page_marker" in e.hygiene_flags]
    assert len(blank) == 1 and blank[0].type == T.TEXT


def test_embedded_cover_is_front_matter_not_part_of_the_bibliography(model):
    covers = [e for e in model.of_type(T.STANDARD_TITLE) if "embedded_standard_cover" in e.hygiene_flags]
    assert len(covers) == 1 and covers[0].parent_id == "doc" and covers[0].region == "front"
    assert not any("Mai 2010" in e.content_text for e in model.of_type(T.BIBLIOGRAPHIC_ENTRY))


# ---- tables, figures, pictures (real: all were swallowed as empty text, captions were dropped) ------------------------------
def test_tables_are_tables_with_captions_and_continuation(model):
    tabs = [e for e in model.of_type(T.TABLE) if e.region != "toc"]
    assert [(t.marker, t.title) for t in tabs] == [("Tabelle B.1", None), ("Tabelle B.1", "(fortgesetzt)")]
    assert tabs[0].table.rows == [["a", "b"], ["c", "d"]]
    assert [_continues(t) for t in tabs] == [[], []]  # same page: a second table, not a page continuation
    assert not any(e.type == T.TEXT and e.table for e in model.elements)


def test_table_over_a_page_break_is_linked(tmp_path):
    d = Doc(3).h("DIN 1", 1).h("1 Anwendungsbereich", 1).table(1, [["a", "b"]], "Tabelle 1 - Werte").table(2, [["c", "d"]], "Tabelle 1 (fortgesetzt)")
    d.table(3, [["e", "f"]])
    tabs = parse(d, tmp_path)[0].of_type(T.TABLE)
    assert [bool(_continues(t)) for t in tabs] == [False, True, True]
    assert _continues(tabs[1]) == [f"table_continues:{tabs[0].id}"] and tabs[2].marker is None


def test_picture_caption_becomes_a_figure_uncaptioned_picture_stays_a_picture(model):
    figs = {f.number: f for f in model.of_type(T.FIGURE)}
    assert figs["1"].title == "Übersicht über den Prozess" and len(figs["1"].source_refs) == 2
    assert len(model.of_type(T.PICTURE)) == 1


def test_nested_items_are_read_only_when_a_profile_asks_for_them(tmp_path):
    path = standard().save(tmp_path / "docling_raw.json")
    plain = {i.ref for i in read_docling_json(path)[1]}
    nested = {i.ref for i in read_docling_json(path, include_nested=True)[1]}
    assert len(nested) - len(plain) == 4  # four captions live only under their table/picture
    assert not get("german_law").read_nested_items and not get("eu_legislation").read_nested_items
    assert TECHNICAL_STANDARD.read_nested_items


# ---- reading order (real: page 72 listed the annex heading after its own figure) --------------------------------------------
def test_heading_printed_above_its_page_content_is_moved_before_it(model):
    annex = next(a for a in model.of_type(T.STANDARD_ANNEX) if a.number == "A")
    kinds = [model.by_id()[c].type for c in annex.children_ids]
    assert kinds == [T.TEXT, T.FIGURE] and annex.region == "annex"
    assert "reading_order_repaired_heading_moved_before_lower_page_items" in annex.hygiene_flags


def test_heading_in_the_middle_of_a_page_is_not_moved(tmp_path):
    d = Doc(2).h("DIN 1", 1).h("1 Anwendungsbereich", 1).x("Text davor.", 1).h("2 Begriffe", 1).x("Text.", 1)
    m = parse(d, tmp_path)[0]
    assert not any("reading_order_repaired" in f for e in m.elements for f in e.hygiene_flags)
    assert by_number(m)["2"].parent_id == "doc"


# ---- lists, notes, footnotes, formulas, continuation --------------------------------------------------------------------------
def test_list_markers_and_unique_ids(model):
    items = [e for e in model.elements if e.type in (T.DASH_ITEM, T.LIST_ITEM)]
    assert [(e.type, e.marker) for e in items] == [(T.DASH_ITEM, "⎯"), (T.LIST_ITEM, "a)"), (T.LIST_ITEM, "ii)")]
    ids = [e.id for e in model.elements]
    assert len(ids) == len(set(ids)) and not any(w.code == "DUPLICATE_ID_RESOLVED" for w in model.warnings)


def test_restarted_numbering_gets_run_ids_not_duplicates(tmp_path):
    d = Doc(1).h("DIN 1", 1).h("1 Anwendungsbereich", 1).x("a) eins", 1).x("b) zwei", 1).x("Zwischentext.", 1).x("a) wieder eins", 1)
    ids = [e.id for e in parse(d, tmp_path)[0].elements if e.type == T.LIST_ITEM]
    assert ids == ["doc/c-1/li-a", "doc/c-1/li-b", "doc/c-1/run2-li-a"]


def test_footnote_formula_and_page_break_continuation(tmp_path):
    d = Doc(2).h("DIN 1", 1).h("1 Anwendungsbereich", 1)
    d.x("Die Menge ergibt sich aus", 1, top=140.0).x("a = b + c        (1)", 1, label="formula")
    d.x("1) Ersetzt durch eine Neuausgabe.", 1, label="footnote")
    d.x("Das Ergebnis wird mit dem Faktor multipliziert und danach in", 1, top=110.0)
    d.x("einer zweiten Stufe weiterverarbeitet.", 2, top=770.0)
    m = parse(d, tmp_path)[0]
    assert [(e.number, e.marker) for e in m.of_type(T.FORMULA)] == [("1", "(1)")]
    fn = m.of_type(T.FOOTNOTE)
    assert len(fn) == 1 and fn[0].number == "1"
    merged = next(e for e in m.elements if "weiterverarbeitet" in e.content_text)
    assert merged.pages == [1, 2] and "page_break_continuation_merged_confirmed" in merged.hygiene_flags


# ---- table of contents (real: linked 52 of 65 entries once leaders and wrapped titles were handled) ------------------------------
def test_toc_container_and_entries_link_to_the_body(model):
    toc = model.by_id()["doc/toc"]
    assert toc.region == "toc" and [model.by_id()[c].type for c in toc.children_ids] == [T.TABLE]
    linked = {e.number: e for e in model.toc_entries if e.status == "linked"}
    assert set(linked) == {"1", "3.1", "4.1"}
    assert linked["3.1"].title == "Maschine" and linked["3.1"].target_id == by_number(model, T.DEFINITION)["3.1"].id


# ---- Legal JSON 2.0 ---------------------------------------------------------------------------------------------------------------
def test_legal_json_is_schema_valid_and_structurally_valid(model, tmp_path):
    doc = to_legal_json(model)
    assert (doc.documentType, doc.legalSystem, doc.id) == ("technical_standard", "ts", "din-en-iso-99999")
    data = json.loads(serialize(doc))
    assert list(Draft202012Validator(published_schema()).iter_errors(data)) == []
    assert validate_structure(doc) == []
    types = {n["type"] for n in data["structure"]}
    assert {"foreword", "clause", "annex", "bibliography"} <= types and "tableOfContents" not in types
    annexes = {n["number"]: n for n in data["structure"] if n["type"] == "annex"}
    assert annexes["A"]["classification"] == "informative" and annexes["B"]["classification"] == "normative"
    assert [n["type"] for n in data["tableOfContents"]] == ["tableOfContents"]
    assert any(n["type"] == "standardTitle" for n in data["frontMatter"])


def test_full_artifact_build_is_valid_and_keeps_order_and_text(tmp_path):
    d = standard()
    model, path = parse(d, tmp_path)
    rep = build_legal_json_artifacts(model, path, tmp_path)["report"]
    assert rep["valid"] and rep["text_preservation"]["identical_to_model"]
    assert all(rep["text_preservation"]["document_order_preserved"].values())
    assert rep["text_preservation"]["source_items_unaccounted"] == []


def test_published_schema_matches_the_view_classes():
    gen, pub = json_schema(), published_schema()
    assert set(gen["$defs"]["Node"]["properties"]["type"]["enum"]) == set(pub["$defs"]["Node"]["properties"]["type"]["enum"])
    assert gen["properties"]["legalSystem"]["enum"] == pub["properties"]["legalSystem"]["enum"] == ["de", "eu", "ts"]
    assert "classification" in pub["$defs"]["Node"]["properties"]


def test_every_item_is_accounted_for_exactly_once(tmp_path):
    from odos.parsing.accounting import content_accounting

    model, path = parse(standard(), tmp_path)
    _, items = read_docling_json(path, include_nested=True)
    acc = content_accounting(model, items)
    assert not acc["missing"] and not acc["duplicated"] and not acc["text_mismatches"]
    assert acc["source_non_whitespace_chars"] == acc["accounted_non_whitespace_chars"]


def test_a_document_without_numbered_clauses_has_no_structure(tmp_path):
    m = parse(Doc(1).x("Nur ein Absatz ohne Gliederung.", 1), tmp_path)[0]
    assert not TECHNICAL_STANDARD.has_structure(m)


def test_registered_next_to_the_existing_profiles():
    assert list(PROFILES) == ["german_law", "eu_legislation", "technical_standard"]


# ---- automatic routing: the upload path (all profiles, no mode) ----------------------------------------------------------------
LANG = {
    "de": dict(scope="1 Anwendungsbereich", norm="2 Normative Verweisungen", terms="3 Begriffe", general="4 Allgemeine Anforderungen",
               fore="Vorwort", intro="Einleitung", annex_a="Anhang A (normativ) Prüfverfahren", annex_b="Anhang B (informativ) Hinweise",
               biblio="Literaturhinweise", note="ANMERKUNG 1 Gilt auch für Sonderfälle.", tab="Tabelle 1 - Werte", tabc="Tabelle 1 (fortgesetzt)"),
    "en": dict(scope="1 Scope", norm="2 Normative references", terms="3 Terms and definitions", general="4 General requirements",
               fore="Foreword", intro="Introduction", annex_a="Annex A (normative) Test method", annex_b="Annex B (informative) Guidance",
               biblio="Bibliography", note="NOTE 1 Applies to special cases as well.", tab="Table 1 - Values", tabc="Table 1 (continued)"),
}
FAMILIES = [  # (family, identifier line as printed, language, expected document_type, expected number)
    ("DIN", "DIN 820-1:2014-06", "de", "DIN", "820-1"),
    ("DIN EN", "DIN EN 61439-1:2012-06", "de", "DIN EN", "61439-1"),
    ("DIN ISO", "DIN ISO 2768-1:1991-06", "de", "DIN ISO", "2768-1"),
    ("DIN EN ISO", "DIN EN ISO 13849-1:2016-06", "de", "DIN EN ISO", "13849-1"),
    ("DIN VDE", "DIN VDE 0100-410:2018-10", "de", "DIN VDE", "0100-410"),
    ("DIN VDE (VDE number in brackets)", "DIN VDE 0100-200 (VDE 0100-200):2023-06", "de", "DIN VDE", "0100-200"),
    ("DIN SPEC", "DIN SPEC 91345:2016-04 (D)", "de", "DIN SPEC", "91345"),
    ("ISO", "ISO 9001:2015", "en", "ISO", "9001"),
    ("ISO/IEC", "ISO/IEC 27001:2022", "en", "ISO/IEC", "27001"),
    ("IEC", "IEC 61508-3:2010", "en", "IEC", "61508-3"),
    ("EN", "EN 61000-6-2:2019", "en", "EN", "61000-6-2"),
    ("ETSI EN", "ETSI EN 303 645 V2.1.1 (2020-06)", "en", "ETSI EN", "303 645"),
]  # fmt: skip


def family_doc(ident: str, lang: str) -> Doc:
    w = LANG[lang]
    d = Doc(5, header=ident)
    d.h(ident, 1).x("Titel der Norm" if lang == "de" else "Title of the standard", 1)
    d.h(w["fore"], 2).x("Vorwort-Text.", 2).h(w["intro"], 2).x("Einleitung-Text.", 2)
    d.h(w["scope"], 3).x("Anwendungsbereich-Text.", 3).h(w["norm"], 3).x("Verweise.", 3).h(w["terms"], 3)
    d.h("3.1", 3).h("Maschine", 3).x("Gesamtheit verbundener Teile", 3).x(w["note"], 3)
    d.h("3.2 Gefährdung", 3).x("potenzielle Schadensquelle", 3)
    d.h(w["general"], 4).h("4.1 Allgemeines", 4).h("4.1.1 Einzelheiten", 4).x("Folgende Schritte sind nötig:", 4)
    d.x("⎯ Grenzen festlegen", 4, left=57).x("1) Erster Schritt", 4, left=75).x("2) Zweiter Schritt", 4, left=75).x("a) Unterschritt", 4, left=93)
    d.x("⎯ Risiko bewerten", 4, left=57).x("E = m c^2        (1)", 4, label="formula")
    d.table(4, [["a", "b"], ["c", "d"]], caption=w["tab"]).table(5, [["e", "f"]], caption=w["tabc"])
    d.h(w["annex_a"], 5).h("A.1 Allgemeines", 5).h(w["annex_b"], 5)
    d.h(w["biblio"], 5).x("[1] ISO 12100, Safety of machinery", 5)
    return d


def route(doc: Doc, tmp_path: Path):
    """What an upload does after Docling: every profile parses, exactly one must find its structure."""
    from odos.pipeline import _run_structured

    doc.save(tmp_path / "docling_raw.json")
    res = _run_structured(list(PROFILES.values()), tmp_path, {}, lambda stage: None)
    lj = json.loads((tmp_path / "document.json").read_text("utf-8")) if (tmp_path / "document.json").exists() else {}
    return res, lj


@pytest.mark.parametrize("family,ident,lang,doc_type,number", FAMILIES, ids=[f[0] for f in FAMILIES])
def test_every_family_is_routed_automatically_and_parsed(family, ident, lang, doc_type, number, tmp_path):
    from odos.pipeline import Outcome

    res, doc = route(family_doc(ident, lang), tmp_path)
    assert res.outcome == Outcome.COMPLETED, res.message
    assert res.summary["json_valid"] and res.summary["json_schema_valid"] and res.summary["profile"] == "technical_standard"
    assert (doc["documentType"], doc["legalSystem"]) == ("technical_standard", "ts")
    model = json.loads((tmp_path / "document_model.json").read_text("utf-8"))
    md = model["metadata"]
    assert (md["document_type"], md["document_number"]) == (doc_type, number)
    els = model["elements"]
    by_number = {e["number"]: e for e in els if e["type"] in ("clause", "definition") and e["number"]}
    assert {"1", "2", "3", "3.1", "3.2", "4", "4.1", "4.1.1", "A.1"} <= set(by_number)
    assert by_number["3.1"]["type"] == "definition" and by_number["3.1"]["title"] == "Maschine"
    annexes = {e["number"]: e["classification"] for e in els if e["type"] == "standard_annex"}
    assert annexes == {"A": "normative", "B": "informative"}
    assert any(e["type"] == "formula" and e["number"] == "1" for e in els)
    tabs = [e for e in els if e["type"] == "table"]
    assert len(tabs) == 2 and any(f.startswith("table_continues:") for f in tabs[1]["hygiene_flags"])
    assert sum(e["type"] == "bibliographic_entry" for e in els) == 1
    # nested list: 1) and 2) under the first dash item, a) under 2)
    by = {e["id"]: e for e in els}
    first_dash = next(e for e in els if e["type"] == "dash_item")
    assert [by[c]["marker"] for c in first_dash["children_ids"]] == ["1)", "2)"]
    assert [by[c]["marker"] for c in by[first_dash["children_ids"][1]]["children_ids"]] == ["a)"]
    assert model["warnings"] == [] or all(w["severity"] == "info" for w in model["warnings"])


def test_a_technical_standard_does_not_trigger_the_other_profiles(tmp_path):
    doc = family_doc("DIN EN ISO 13849-1:2016-06", "de").save(tmp_path / "docling_raw.json")
    assert {m: p.has_structure(parse_document(doc, m)) for m, p in PROFILES.items()} == {"german_law": False, "eu_legislation": False, "technical_standard": True}


def test_numbered_documents_without_a_standard_identifier_are_refused(tmp_path):
    from odos.pipeline import Outcome

    d = Doc(2, header="Benutzerhandbuch Pumpe").h("Benutzerhandbuch Pumpe", 1).h("1 Einleitung", 1).x("Willkommen.", 1).h("2 Installation", 1).h("2.1 Voraussetzungen", 1).x("Strom.", 1)
    d.h("2.2 Montage", 2).x("Schrauben.", 2).h("3 Wartung", 2)
    res, _ = route(d, tmp_path)
    assert res.outcome == Outcome.UNSUPPORTED


def test_an_identifier_without_any_structure_is_refused(tmp_path):
    from odos.pipeline import Outcome

    res, _ = route(Doc(1).h("DIN 820-1:2014-06", 1).x("Nur ein Deckblatt.", 1), tmp_path)
    assert res.outcome == Outcome.UNSUPPORTED


def test_standard_without_identifier_is_recognised_by_its_scope_and_normative_references(tmp_path):
    from odos.pipeline import Outcome

    d = Doc(2).h("Safety of examples", 1).h("1 Scope", 1).x("Text.", 1).h("2 Normative references", 1).x("None.", 1).h("3 Terms and definitions", 2)
    res, doc = route(d, tmp_path)
    assert res.outcome == Outcome.COMPLETED and doc["documentType"] == "technical_standard"


def test_toc_only_excerpt_of_an_identified_standard_is_accepted(tmp_path):
    from odos.pipeline import Outcome

    d = Doc(2).h("DIN SPEC 91345:2016-04 (D)", 1).h("Referenzarchitekturmodell", 1).x("Inhalt", 1)
    for line in ("Vorwort ........ 4", "1 Anwendungsbereich ........ 6", "2 Normative Verweisungen ........ 6", "3 Begriffe ........ 7"):
        d.x(line, 1)
    res, doc = route(d, tmp_path)
    assert res.outcome == Outcome.COMPLETED and doc["structure"] == []
    assert [len(n["children"]) for n in doc["tableOfContents"]] == [4]
    assert [e["number"] for e in json.loads((tmp_path / "document_model.json").read_text("utf-8"))["toc_entries"] if e["kind"] == "clause"] == ["1", "2", "3"]


def test_running_header_supplies_the_identifier_when_the_cover_has_none(tmp_path):
    d = Doc(3, header="ISO/IEC 27000:2018(E)").h("Information technology - Security techniques", 1).h("Foreword", 1).x("Text.", 1)
    d.h("1 Scope", 2).x("Text.", 2).h("2 Normative references", 2).x("None.", 2)
    m = parse(d, tmp_path)[0]
    assert (m.metadata.document_type, m.metadata.document_number, m.metadata.version_year_month) == ("ISO/IEC", "27000", "2018")


def test_edition_on_the_cover_and_bilingual_parts(tmp_path):
    d = Doc(4, header="IEC 61508-1").x("Edition 2.0 2010-04", 1).h("INTRODUCTION", 1).h("1 Scope", 2).x("Text.", 2).h("2 Normative references", 2).x("None.", 2)
    d.h("INTRODUCTION", 3).h("1 Domaine d'application", 3).x("Texte.", 3).h("2 Références normatives", 4).x("Aucune.", 4)
    m = parse(d, tmp_path)[0]
    assert m.metadata.version_year_month == "2010-04"
    again = [e for e in m.elements if "numbering_restarts_second_part" in e.hygiene_flags]
    assert [e.number for e in again] == ["1", "2"] and any(n.code == "NUMBERING_RESTARTS" for n in m.structure_notes)


def test_annex_heading_is_not_confused_with_a_sentence_about_an_annex(tmp_path):
    d = Doc(2).h("ETSI EN 303 645 V2.1.1 (2020-06)", 1).h("Introduction", 1)
    d.x("Annex A (informative) of the present document has been included to provide context.", 1)
    d.h("1 Scope", 2).x("Text.", 2).h("2 References", 2).x("None.", 2).h("Annex A (informative): Architecture", 2)
    m = parse(d, tmp_path)[0]
    assert [a.number for a in m.of_type(T.STANDARD_ANNEX)] == ["A"] and by_number(m, T.CLAUSE)["2"].parent_id == "doc"


def test_introduction_numbering_stays_in_the_introduction(tmp_path):
    d = Doc(2).h("ISO 9999:2020", 1).h("Introduction", 1).h("0.1 Overview", 1).x("Text.", 1).h("0.2 Purpose", 1).x("Text.", 1)
    d.h("1 Scope", 2).x("Text.", 2).h("2 Normative references", 2).x("None.", 2)
    m = parse(d, tmp_path)[0]
    intro = m.of_type(T.INTRODUCTION)[0]
    assert [m.by_id()[c].number for c in intro.children_ids if m.by_id()[c].type == T.CLAUSE] == ["0.1", "0.2"]
    assert by_number(m, T.CLAUSE)["1"].parent_id == "doc"


def test_numbered_paragraphs_keep_their_numbers_only_when_the_numbering_continues(tmp_path):
    d = Doc(1).h("ISO 9999:2020", 1).h("1 Scope", 1).x("1.1 This part covers the first matter in general terms.", 1)
    d.x("1.2 This part also covers the second matter of the series.", 1).x("5.7 A stray number that continues nothing at all.", 1)
    m = parse(d, tmp_path)[0]
    paras = [e for e in m.of_type(T.CLAUSE) if "numbered_paragraph" in e.uncertainty_reasons]
    assert [e.number for e in paras] == ["1.1", "1.2"] and all(e.title is None for e in paras)
    assert "5.7 A stray" in next(e for e in m.of_type(T.TEXT)).content_text


def test_control_characters_do_not_hide_the_contents_heading(tmp_path):
    m = parse(Doc(1).h("ISO 9999:2020", 1).h("Contents\x08", 1).x("1 Scope ........ 3", 1).x("2 Normative references ........ 3", 1).x("3 Terms ........ 4", 1), tmp_path)[0]
    assert "doc/toc" in m.by_id() and len(m.by_id()["doc/toc"].children_ids) == 3


def test_a_toc_cell_longer_than_its_published_text_still_validates(tmp_path):
    """Docling's table_cells text and the published grid can differ for merged dot-leader cells (real IEC 61508-1)."""
    d = Doc(2).h("IEC 61508-1", 1).h("CONTENTS", 1)
    d.table(1, [["1", "Scope ........................................ 9", ""]])
    doc = d.save(tmp_path / "docling_raw.json")
    data = json.loads(doc.read_text())
    data["tables"][0]["data"]["table_cells"][1]["text"] += "........"  # the cell text is longer than the grid text
    doc.write_text(json.dumps(data))
    m = parse_document(doc, "technical_standard")
    rep = build_legal_json_artifacts(m, doc, tmp_path)["report"]
    assert rep["structure_valid"], rep["structure_errors"]


def test_cover_table_stays_in_the_front_matter(tmp_path):
    d = Doc(2).table(1, [["Reference number", "ISO 9999:2020"]]).h("ISO 9999:2020", 1).h("1 Scope", 2).x("Text.", 2).h("2 Normative references", 2).x("None.", 2)
    doc = to_legal_json(parse(d, tmp_path)[0])
    assert [n.type for n in doc.frontMatter][:1] == ["table"] and not any(n.type == "table" for n in doc.structure)


# ---- structures verified in the VDE NormenBibliothek viewer (DIN VDE 0100-200:2023-06, DIN VDE 0100-410:2018-10) -------------
# Browser-view evidence only: the viewer shows the contents list and the markup of the entries, not the PDF layout.
def vde_0100_200_like() -> Doc:
    d = Doc(6, header="DIN VDE 0100-200 (VDE 0100-200):2023-06")
    d.h("DIN VDE 0100-200 (VDE 0100-200):2023-06", 1).x("Errichten von Niederspannungsanlagen", 1).x("Teil 200: Begriffe", 1)
    d.h("Vorwort", 2).x("Vorwort-Text.", 2).h("IEC 60050, TEIL 826: ELEKTRISCHE ANLAGEN", 2).x("Erläuterung.", 2).h("Einleitung", 2).x("Text.", 2)
    d.h("1 Anwendungsbereich", 3).x("Text.", 3).h("2 Normative Verweisungen", 3).x("Text.", 3).h("3 Begriffe", 3).x("Es gelten die folgenden Begriffe.", 3)
    d.h("HAUPTABSCHNITT 826-10 – KENNGRÖSSEN", 3).h("SECTION 826-10 – QUANTITIES", 3).h("SECTION 826-10 – GRANDEURS", 3)
    d.x("826-10-01 Beispielbegriff, f", 4).x("Erste deutsche Definition.", 4)
    d.table(4, [["example term", "terme exemple, m"], ["first english definition", "première définition"]]).x("[IEV 826-10-01]", 4)
    d.h("826-10-02", 4).h("zweiter Begriff, m", 4).x("Zweite deutsche Definition.", 4).x("[IEV 826-10-02]", 4)
    d.h("HAUPTABSCHNITT 826-11 – SPANNUNGEN UND STRÖME", 5).h("SECTION 826-11 – VOLTAGES AND CURRENTS", 5)
    d.x("826-11-01 dritter Begriff, f", 5).x("Dritte deutsche Definition.", 5)
    d.h("Stichwortverzeichnisse", 5).x("Beispielbegriff 826-10-01", 5).x("zweiter Begriff 826-10-02", 5)
    d.h("Anhang A (normativ) National festgelegte Begriffe", 6).h("A.1 Anlage und Netz", 6).x("Text.", 6)
    d.h("A.2 Elektrische Größen", 6).x("Text.", 6).h("Anhang B (informativ) Zusammenhang mit anderen Dokumenten", 6).h("Anhang C (informativ) Literaturhinweise", 6)
    return d


def test_iev_numbered_terminology_with_divisions_and_parallel_headings(tmp_path):
    m = parse(vde_0100_200_like(), tmp_path)[0]
    by = by_number(m)
    assert m.metadata.document_type == "DIN VDE" and m.metadata.document_number == "0100-200"
    d10, d11 = by["826-10"], by["826-11"]
    assert (d10.type, d10.parent_id, d10.marker, d10.title) == (T.CLAUSE, by["3"].id, "HAUPTABSCHNITT 826-10", "KENNGRÖSSEN")
    assert d11.parent_id == by["3"].id  # the next division is a sibling, not nested under the previous one
    assert [m.by_id()[c].hygiene_flags for c in d10.children_ids][:2] == [["parallel_language_heading"]] * 2  # EN and FR headings kept beside it
    assert all(by[n].type == T.DEFINITION for n in ("826-10-01", "826-10-02", "826-11-01"))
    assert by["826-10-01"].parent_id == d10.id and by["826-11-01"].parent_id == d11.id
    assert by["826-10-01"].title == "Beispielbegriff, f"  # the printed term with its gender marker, unchanged
    assert by["826-10-02"].title == "zweiter Begriff, m" and len(by["826-10-02"].source_refs) == 2  # number and term on two headers
    kids = [m.by_id()[c] for c in by["826-10-01"].children_ids]
    assert [k.type for k in kids] == [T.TEXT, T.TABLE, T.TEXT] and kids[2].hygiene_flags == ["source_reference"]


def test_index_and_annex_clauses_of_the_vde_terminology_standard(tmp_path):
    m = parse(vde_0100_200_like(), tmp_path)[0]
    assert [e.title for e in m.of_type(T.INDEX)] == ["Stichwortverzeichnisse"] and m.of_type(T.INDEX)[0].parent_id == "doc"
    annexes = {a.number: (a.classification, a.title) for a in m.of_type(T.STANDARD_ANNEX)}
    assert annexes == {"A": ("normative", "National festgelegte Begriffe"), "B": ("informative", "Zusammenhang mit anderen Dokumenten"),
                       "C": ("informative", "Literaturhinweise")}
    assert by_number(m)["A.1"].parent_id == by_number(m, T.STANDARD_ANNEX)["A"].id


def test_vde_terminology_standard_is_routed_and_valid(tmp_path):
    from odos.pipeline import Outcome

    res, doc = route(vde_0100_200_like(), tmp_path)
    assert res.outcome == Outcome.COMPLETED and res.summary["json_valid"], res.message
    assert {n["type"] for n in doc["structure"]} >= {"foreword", "introduction", "clause", "index", "annex"}


def vde_0100_410_like() -> Doc:
    d = Doc(5, header="DIN VDE 0100-410 (VDE 0100-410):2018-10")
    d.h("DIN VDE 0100-410 (VDE 0100-410):2018-10", 1).x("Errichten von Niederspannungsanlagen", 1)
    d.h("Nationales Vorwort", 2).x("Text.", 2).h("Europäisches Vorwort", 2).x("Text.", 2).h("Anerkennungsnotiz", 2).x("Text.", 2)
    d.h("Europäisches Vorwort zur Änderung A11", 2).x("Text.", 2)
    d.h("410 Einleitung", 3).x("Text.", 3).h("410.1 Anwendungsbereich", 3).x("Text.", 3).h("410.2 Normative Verweisungen", 3).x("Text.", 3)
    d.h("411 Schutzmaßnahme: Automatische Abschaltung", 3).h("411.1 Allgemeines", 3).x("Text.", 3).h("411.3 Fehlerschutz", 3).h("411.3.2 Automatische Abschaltung im Fehlerfall", 4)
    d.x("411.3.2.1 Eine Schutzvorrichtung muss die Versorgung abschalten.", 4).x("ANMERKUNG Bei IT-Systemen ist dies nicht nötig.", 4)
    d.x("411.3.2.2 Die in Tabelle 41.1 angegebenen Zeiten gelten für Endstromkreise.", 4)
    d.x("Tabelle 41.1 – Maximale Abschaltzeiten", 4).table(4, [["System", "50 V"], ["TN", "0,8 s"]])
    d.x("411.3.2.3 In TN-Systemen ist eine Abschaltzeit nicht festgelegt.", 4).x("411.3.2.4 In TT-Systemen gilt Entsprechendes.", 4).x("411.3.2.5", 4)
    d.x("Wenn die Abschaltung durch eine Einrichtung erfolgt, gilt Folgendes.", 4).x("411.3.2.6 Weitere Anforderungen bleiben unberührt.", 4)
    d.h("412 Doppelte Isolierung", 5).h("412.1 Allgemeines", 5).x("Text.", 5)
    d.h("Anhang A (normativ) Vorkehrungen für den Basisschutz", 5).h("A.2 Abdeckungen", 5).h("A.2.1", 5).h("A.2.2", 5).x("Text.", 5)
    return d


def test_part_prefixed_numbering_inline_paragraph_numbers_and_amendment_forewords(tmp_path):
    m = parse(vde_0100_410_like(), tmp_path)[0]
    by = by_number(m)
    assert m.metadata.document_type == "DIN VDE" and m.metadata.version_year_month == "2018-10"
    assert [f.title for f in m.of_type(T.FOREWORD)] == ["Nationales Vorwort", "Europäisches Vorwort", "Europäisches Vorwort zur Änderung A11"]
    assert by["410"].parent_id == "doc" and by["410.1"].parent_id == by["410"].id and by["411"].parent_id == "doc"  # no "1 Scope"
    assert by["411.3.2"].parent_id == by["411.3"].id
    paras = [e for e in m.of_type(T.CLAUSE) if "numbered_paragraph" in e.uncertainty_reasons]
    assert [e.number for e in paras] == ["411.3.2.1", "411.3.2.2", "411.3.2.3", "411.3.2.4", "411.3.2.5", "411.3.2.6"] and all(e.parent_id == by["411.3.2"].id for e in paras)
    bare = by["411.3.2.5"]  # a number alone on its line: the paragraph below belongs to it
    assert bare.content_text == "" and [m.by_id()[c].type for c in bare.children_ids] == [T.TEXT]


def test_caption_above_a_table_and_annex_clauses_without_titles(tmp_path):
    m = parse(vde_0100_410_like(), tmp_path)[0]
    tab = m.of_type(T.TABLE)[0]
    assert (tab.number, tab.marker, tab.title) == ("41.1", "Tabelle 41.1", "Maximale Abschaltzeiten")
    by = by_number(m)
    assert by["A.2.1"].title is None and by["A.2.2"].title is None and by["A.2.1"].parent_id == by["A.2"].id


@pytest.mark.parametrize("line,family,number", [
    ("DIN VDE 0833-4 (VDE 0833-4) Berichtigung 1:2026-12", "DIN VDE", "0833-4"),
    ("DIN CLC/TS 50711 (VDE V 0115-711):2026-12", "DIN CLC/TS", "50711"),
    ("DIN EN IEC 61326-1 (VDE 0843-20-1):2026-12", "DIN EN IEC", "61326-1"),
    ("VDE 0800-208 (VDE 0800-208):2026-12", "VDE", "0800-208"),
    ("VDE-AR-N 4105 (VDE-AR-N 4105) Anwendungsregel:2026-03", "VDE-AR-N", "4105"),
    ("DIN EN ISO 9001:2015-11 (D/E)", "DIN EN ISO", "9001"),
    ("DIN EN ISO/IEC 27001/A1:2024-11", "DIN EN ISO/IEC", "27001"),
    ("DIN ISO 31000:2018-10 (D)", "DIN ISO", "31000"),
    ("DIN EN 619:2022-07 (D)", "DIN EN", "619"),
])
def test_identifier_forms_seen_in_the_vde_and_din_catalogues(line, family, number):
    m = R.TITLE_RX.match(line)
    assert m and (m["family"], m["number"]) == (family, number)


def test_dotted_numbers_and_iev_numbers_do_not_mix_with_document_numbers():
    assert not R.CLAUSE_RX.match("13849-1 Sicherheit") and R.CLAUSE_RX.match("826-11-01 Begriff") and R.CLAUSE_RX.match("411.3.2.1 Text")


def test_a_contents_list_in_a_single_table_is_recognised_without_a_heading_item(tmp_path):
    rows = [["Inhalt", "Inhalt", "Seite"]] + [[f"{t} ........", f"{t} ........", str(i + 3)] for i, t in enumerate(["Vorwort", "1 Anwendungsbereich", "2 Normative Verweisungen", "3 Begriffe"])]
    d = Doc(1, header="DIN ISO 31000:2018-10 (D)").h("DIN ISO 31000:2018-10 (D)", 1).h("Risikomanagement - Leitlinien", 1).table(1, rows)
    res, doc = route(d, tmp_path)
    from odos.pipeline import Outcome

    assert res.outcome == Outcome.COMPLETED and doc["structure"] == [] and len(doc["tableOfContents"]) == 1


def test_toc_annex_marker_does_not_read_a_standard_name_as_an_annex_letter():
    rx = TECHNICAL_STANDARD.toc.markers[0][1]
    assert rx.match("AnhangB(informativ)Weitere") and rx.match("AnhangZA(informativ)") and not rx.match("AnhangISO/TC176zu")


# ---- review round: annex spellings, contents-table repairs, definition entries on text lines -------------------------------------------
@pytest.mark.parametrize("line,letter,norm", [
    ("Annex A (informative)", "A", "informative"), ("ANNEX A (informative)", "A", "informative"), ("ANHANG A (normativ)", "A", "normativ"),
    ("Annexe A (informative)", "A", "informative"), ("Annexe ZA (normative)", "ZA", "normative"), ("Annex AA (normative)", "AA", "normative"),
    ("Nationaler Anhang NA (informativ)", "NA", "informativ"), ("Annex SL", "SL", None), ("Annex A: Titel", "A", None),
])
def test_annex_heading_spellings(line, letter, norm):
    m = R.ANNEX_RX.match(line)
    assert m and m.group(2) == letter and (m.group(3) or None) == norm


@pytest.mark.parametrize("line", ["Anhang A.1 Titel", "Annex 1 (informative)", "Appendix A", "Annexes", "Anhangs A"])
def test_not_an_annex_heading(line):
    assert not R.ANNEX_RX.match(line)


def test_capitalised_and_french_annexes_get_their_classification(tmp_path):
    d = Doc(2, header="IEC 61508-1").h("IEC 61508-1", 1).h("1 Scope", 1).x("Text.", 1).h("2 Normative references", 1).x("None.", 1)
    d.h("ANNEX A (informative) Guidance", 2).h("Annexe B (normative) Méthode", 2)
    m = parse(d, tmp_path)[0]
    assert {a.number: a.classification for a in m.of_type(T.STANDARD_ANNEX)} == {"A": "informative", "B": "normative"}


def test_toc_annex_marker_without_brackets_and_in_capitals():
    rx = TECHNICAL_STANDARD.toc.markers[0][1]
    assert [bool(rx.match(x)) for x in ("AnhangAErläuterung", "ANNEXA(informative)", "AnnexeB(normative)", "AnhangISO/TC176")] == [True, True, True, False]


def toc_table_doc(rows) -> Doc:
    d = Doc(2, header="DIN EN ISO 9001:2015-11 (D/E)").h("DIN EN ISO 9001:2015-11 (D/E)", 1).h("Qualitätsmanagementsysteme", 1)
    d.table(1, [["Inhalt", "Inhalt", "Seite"], *rows])
    d.h("1 Anwendungsbereich", 2).x("Text.", 2).h("2 Normative Verweisungen", 2).x("Text.", 2).h("3 Begriffe", 2).x("Text.", 2)
    return d


def test_a_toc_cell_with_two_numbers_is_two_entries_never_one_glued_number(tmp_path):
    rows = [["1", "Anwendungsbereich ........", "3"], ["2 3", "Normative Verweisungen ........", "4"], ["4", "Begriffe ........", "9"], ["5", "Literatur ........", "9"]]
    m = parse(toc_table_doc(rows), tmp_path)[0]
    nums = [(e.number, e.title, e.status) for e in m.toc_entries if e.kind == "clause"]
    assert [n for n, _, _ in nums][:3] == ["1", "2", "3"] and not any(n in ("23", "2.3") for n, _, _ in nums)
    assert nums[1][1] == "Normative Verweisungen" and nums[2][1] is None and nums[2][2] != "linked"  # the second number has no title


def test_two_language_toc_rows_become_two_entries_with_clean_titles(tmp_path):
    rows = [["1", "Anwendungsbereich ........", "3", "1", "Scope ........", "3"], ["2", "Normative Verweisungen ........", "4", "2", "Normative references ........", "4"],
            ["3", "Begriffe ........", "5", "3", "Terms and definitions ........", "5"], ["Vorwort", "........", "6", "Foreword", "........", "6"]]
    m = parse(toc_table_doc(rows), tmp_path)[0]
    clause = [(e.number, e.title, e.status) for e in m.toc_entries if e.kind == "clause"]
    assert clause == [("1", "Anwendungsbereich", "linked"), ("2", "Normative Verweisungen", "linked"), ("3", "Begriffe", "linked"),  # left column
                      ("1", "Scope", "candidate"), ("2", "Normative references", "candidate"), ("3", "Terms and definitions", "candidate")]  # right column


def test_toc_row_repair_is_off_for_the_other_profiles():
    assert not get("german_law").toc.split_toc_rows and not get("eu_legislation").toc.split_toc_rows


def test_lone_number_line_and_its_term_line_form_one_definition(tmp_path):
    d = Doc(2, header="DIN VDE 0100-200 (VDE 0100-200):2023-06").h("DIN VDE 0100-200 (VDE 0100-200):2023-06", 1)
    d.h("1 Anwendungsbereich", 1).x("Text.", 1).h("2 Normative Verweisungen", 1).x("Text.", 1).h("3 Begriffe", 1)
    d.h("HAUPTABSCHNITT 826-10 – KENNGRÖSSEN", 2)
    d.x("826-10-01", 2).x("Nennspannung (einer elektrischen Anlage), f", 2).x("Spannung, durch die die Anlage gekennzeichnet ist.", 2)
    d.x("nominal voltage (of an electrical installation)", 2).x("tension nominale (d’une installation électrique), f", 2)
    d.x("826-10-02", 2).x("Fehlerspannung, f", 2).x("Spannung zwischen einer Stelle und Erde.", 2)
    m = parse(d, tmp_path)[0]
    by = by_number(m)
    assert (by["826-10-01"].type, by["826-10-01"].title) == (T.DEFINITION, "Nennspannung (einer elektrischen Anlage), f")
    assert len(by["826-10-01"].source_refs) == 2  # the number line and the term line, both kept
    kids = [m.by_id()[c] for c in by["826-10-01"].children_ids]
    assert [k.content_text[:7] for k in kids] == ["Spannun", "nominal", "tension"]  # the three languages stay together under their entry
    assert by["826-10-02"].parent_id == by["826-10"].id and by["826-10-02"].title == "Fehlerspannung, f"


def test_a_lone_number_followed_by_a_sentence_is_a_numbered_paragraph_not_a_term(tmp_path):
    d = Doc(2, header="ISO 9999:2020").h("ISO 9999:2020", 1).h("1 Scope", 1).x("Text.", 1).h("2 Normative references", 1).x("Text.", 1).h("3 Terms and definitions", 1)
    d.h("3.1 general", 1).x("3.1.1", 1).x("This sentence is a paragraph, not a term.", 1)
    m = parse(d, tmp_path)[0]
    para = by_number(m)["3.1.1"]
    assert para.title is None and "numbered_paragraph" in para.uncertainty_reasons


# ---- document variants from the InPro inventory, layouts observed in the VDE NormenBibliothek ------------------------------------------
@pytest.mark.parametrize("line,family,number,variant", [
    ("DIN VDE 0100-100 (VDE 0100-100):2009-06", "DIN VDE", "0100-100", None),
    ("DIN VDE 0100-100 (VDE 0100-100) Berichtigung 1:2022-03", "DIN VDE", "0100-100", "Berichtigung 1"),
    ("DIN VDE 0100-100 (VDE 0100-100) Entwurf", "DIN VDE", "0100-100", "Entwurf"),
    ("DIN VDE 0100-751 (VDE 0100-751) -  Entwurf", "DIN VDE", "0100-751", "Entwurf"),
    ("E DIN VDE 0100-420 (VDE 0100-420):2026-05", "DIN VDE", "0100-420", "Entwurf"),
    ("E DIN EN ISO 13849-1:2026-03", "DIN EN ISO", "13849-1", "Entwurf"),
    ("DIN VDE 0100-443/A3 (VDE 0100-443/A3):2022-09", "DIN VDE", "0100-443", "A3"),
    ("DIN VDE 0100-443A3 (VDE 0100-443A3) Entwurf", "DIN VDE", "0100-443", "Entwurf A3"),
    ("DIN EN IEC 61439-1/AA (VDE 0660-600-1/AA):2024-09", "DIN EN IEC", "61439-1", "AA"),
    ("DIN VDE 0100-520 (VDE 0100-520) Beiblatt 1:2014-07", "DIN VDE", "0100-520", "Beiblatt 1"),
    ("DIN VDE 0100 (VDE 0100) Beiblatt 2:2001-05", "DIN VDE", "0100", "Beiblatt 2"),
    ("DIN VDE V 0100-551-1 (VDE V 0100-551-1):2018-05", "DIN VDE V", "0100-551-1", None),
    ("DIN VDE V 0100-0718 (VDE V 0100-0718)", "DIN VDE V", "0100-0718", None),
    ("DIN EN ISO/IEC 27001/A1:2024-11", "DIN EN ISO/IEC", "27001", "A1"),
    ("EN ISO 9001:2015/A1:2024", "EN ISO", "9001", "A1"),
    ("ISO 9001:2015/Amd 1:2024", "ISO", "9001", "Amd 1"),
    ("IEC 61010-1:2010/AMD1:2016", "IEC", "61010-1", "AMD1"),
    ("DIN ISO/TS 15066:2017-04", "DIN ISO/TS", "15066", None),
    ("VDE-AR-N 4110 (VDE-AR-N 4110) Ber1 zur Anwendungsregel:2024-11", "VDE-AR-N", "4110", "Ber1 zur Anwendungsregel"),
    ("VDMA 24578:2018-03", "VDMA", "24578", None),
    ("DIN 14675 Beiblatt 1:2014-12", "DIN", "14675", "Beiblatt 1"),
    ("DIN 14675/A1:2006-12", "DIN", "14675", "A1"),
    ("E DIN 14675-1/A1:2019-01", "DIN", "14675-1", "Entwurf A1"),
])
def test_identifier_and_variant_of_every_form_in_the_inventory(line, family, number, variant):
    from odos.document_model import DocumentMetadata

    m = R._ident(line)
    assert m is not None
    md = DocumentMetadata()
    R._set_identifier(md, m, line)
    assert (md.document_type, md.document_number, md.document_variant) == (family, number, variant)


def test_variants_of_one_standard_get_different_document_ids():
    ids = []
    for line in ("DIN VDE 0100-520:2014-07", "DIN VDE 0100-520 (VDE 0100-520) Beiblatt 1:2014-07", "DIN VDE 0100-520 (VDE 0100-520) Beiblatt 2:2014-07",
                 "DIN VDE 0100-520 (VDE 0100-520) Berichtigung 1:2015-01", "E DIN VDE 0100-520:2026-01", "DIN VDE 0100-520/A1:2020-01"):
        from odos.document_model import DocumentMetadata

        md = DocumentMetadata()
        R._set_identifier(md, R._ident(line), line)
        ids.append("-".join(TECHNICAL_STANDARD.json_id_parts(md)))
    assert len(set(ids)) == len(ids), ids


def amendment_draft() -> Doc:
    """DIN VDE 0100-443/A3 (draft amendment): front matter with a comment table, the list of changes, the base standard's title as a
    heading, instruction lines that cite the base standard's clause numbers. No clause structure of its own."""
    d = Doc(3, header="DIN VDE 0100-443/A3 (VDE 0100-443/A3):2022-09")
    d.h("DIN VDE 0100-443/A3 (VDE 0100-443/A3):2022-09", 1).x("Errichten von Niederspannungsanlagen", 1)
    d.h("Anwendungsbeginn", 1).x("Anwendungsbeginn dieser Norm ist ... .", 1).h("Nationales Vorwort", 1).x("Das Dokument wurde erarbeitet.", 1)
    d.table(1, [["Zur Berücksichtigung bei der Kommentierung", "Hinweis"]])
    d.x("Gegenüber der Vorgängerfassung wurden folgende wesentliche Änderungen vorgenommen:", 2).x("a) Die Übersicht wurde erweitert.", 2).x("b) Abschnitt 443.6.2 wurde überarbeitet.", 2)
    d.h("Errichten von Niederspannungsanlagen – Teil 4-44: Schutz bei Überspannungen", 2)
    d.x("Ändere Abschnitt 443.6.2 der DIN VDE 0100-443 (VDE 0100-443) wie folgt:", 3).x("Der geänderte Text lautet wie folgt.", 3)
    return d


def test_amendment_draft_is_routed_valid_and_keeps_its_instruction_lines(tmp_path):
    from odos.pipeline import Outcome

    res, doc = route(amendment_draft(), tmp_path)
    assert res.outcome == Outcome.COMPLETED and res.summary["json_valid"], res.message
    model = json.loads((tmp_path / "document_model.json").read_text("utf-8"))
    assert model["metadata"]["document_variant"] == "A3" and doc["id"] == "din-vde-0100-443-a3"
    assert doc["shortTitle"] == "DIN VDE 0100-443 A3:2022-09"
    assert not [e for e in model["elements"] if e["type"] == "clause"]  # 443.6.2 is a citation of the base standard, not a clause here
    text = " ".join(e["content_text"] for e in model["elements"])
    assert "Ändere Abschnitt 443.6.2" in text and "Der geänderte Text lautet" in text
    fore = next(e for e in model["elements"] if e["type"] == "foreword")
    assert any(e["type"] == "table" for e in model["elements"] if e["parent_id"] == fore["id"])  # the comment table stays in the foreword


def test_corrigendum_with_a_base_clause_heading_does_not_turn_quoted_numbers_into_structure(tmp_path):
    d = Doc(1, header="DIN VDE 0100-560 (VDE 0100-560) Berichtigung 1:2023-10").h("DIN VDE 0100-560 (VDE 0100-560) Berichtigung 1:2023-10", 1)
    d.x("Für diese Berichtigung ist das nationale Arbeitsgremium zuständig.", 1).x("Betrifft nur die deutsche Fassung.", 1)
    d.h("560.7 Stromkreise für Sicherheitszwecke", 1).x("Der zweite Satz von 560.7.2", 1)
    d.x("560.7.2 Stromkreise dürfen Bereiche nicht durchqueren, die als Fluchtweg dienen.", 1).x("wird durch Folgenden ersetzt:", 1)
    d.x("560.7.2 Stromkreise dürfen Bereiche nicht durchqueren.", 1)
    m = parse(d, tmp_path)[0]
    assert m.metadata.document_variant == "Berichtigung 1" and TECHNICAL_STANDARD.has_structure(m)
    assert [c.number for c in m.of_type(T.CLAUSE)] == ["560.7"]  # the quoted 560.7.2 continues nothing: it stays text
    assert sum("560.7.2" in e.content_text for e in m.of_type(T.TEXT)) == 3  # the citation and both quoted paragraphs


def test_supplement_that_is_only_a_continued_table_is_accepted(tmp_path):
    from odos.pipeline import Outcome

    d = Doc(3, header="DIN VDE 0100 (VDE 0100) Beiblatt 2:2001-05").h("DIN VDE 0100 (VDE 0100) Beiblatt 2:2001-05", 1)
    d.table(1, [["Nr.", "Norm"], ["1", "A"]], caption="Tabelle 1 – Übersicht")
    d.table(2, [["Nr.", "Norm"], ["2", "B"]], caption="Tabelle 1 (fortgesetzt)").table(3, [["Nr.", "Norm"], ["3", "C"]], caption="Tabelle 1 (fortgesetzt)")
    res, doc = route(d, tmp_path)
    assert res.outcome == Outcome.COMPLETED and doc["id"] == "din-vde-0100-beiblatt-2"
    tabs = [e for e in json.loads((tmp_path / "document_model.json").read_text("utf-8"))["elements"] if e["type"] == "table"]
    assert [(t["marker"], t["title"]) for t in tabs] == [("Tabelle 1", "Übersicht"), ("Tabelle 1", "(fortgesetzt)"), ("Tabelle 1", "(fortgesetzt)")]
    assert [bool([f for f in t.get("hygiene_flags", []) if f.startswith("table_continues")]) for t in tabs] == [False, True, True]


def test_pre_standard_with_the_bibliography_before_the_annexes(tmp_path):
    d = Doc(3, header="DIN VDE V 0100-551-2 (VDE V 0100-551-2):2023-10").h("DIN VDE V 0100-551-2 (VDE V 0100-551-2):2023-10", 1)
    d.h("Anwendungsbeginn", 1).x("Anwendungsbeginn dieses Dokuments ist 2023-10-01.", 1).h("Vorwort", 1).x("Text.", 1)
    d.h("1 Anwendungsbereich", 2).x("Text.", 2).h("2 Normative Verweisungen", 2).x("Text.", 2).h("3 Begriffe", 2).x("Text.", 2).h("4 Anforderungen", 2).h("4.1 Allgemein", 2).x("Text.", 2)
    d.h("Literaturhinweise", 3).x("DIN VDE 0100-551-1, Errichten von Niederspannungsanlagen", 3).x("DIN VDE 0100-710, Medizinisch genutzte Bereiche", 3)
    d.h("Anhang A (informativ) Zusammenhang mit anderen Dokumenten", 3).x("Text.", 3).h("Anhang B (informativ) Geschalteter Bezugsleiter", 3).x("Text.", 3)
    m = parse(d, tmp_path)[0]
    assert (m.metadata.document_type, m.metadata.document_number) == ("DIN VDE V", "0100-551-2")
    top = [(e.type, e.number or e.title) for e in m.elements if e.parent_id == "doc" and e.type in (T.BIBLIOGRAPHY, T.STANDARD_ANNEX)]
    assert top == [(T.BIBLIOGRAPHY, "Literaturhinweise"), (T.STANDARD_ANNEX, "A"), (T.STANDARD_ANNEX, "B")]
    assert len(m.of_type(T.BIBLIOGRAPHIC_ENTRY)) == 2 and all(a.classification == "informative" for a in m.of_type(T.STANDARD_ANNEX))
    assert by_number(m, T.STANDARD_ANNEX)["A"].children_ids  # the annex text is not swallowed by the bibliography


def test_draft_is_a_standard_with_the_draft_variant(tmp_path):
    d = Doc(2, header="E DIN EN ISO 13849-1:2026-03").h("E DIN EN ISO 13849-1:2026-03", 1).h("Vorwort", 1).x("Text.", 1)
    d.h("1 Anwendungsbereich", 2).x("Text.", 2).h("2 Normative Verweisungen", 2).x("Text.", 2)
    res, doc = route(d, tmp_path)
    assert doc["id"] == "din-en-iso-13849-1-entwurf" and doc["documentType"] == "technical_standard"


# ---- language editions and amendment bodies ------------------------------------------------------------------------------------------------
def _edition(ident: str, tmp_path: Path):
    d = Doc(2, header=ident).h(ident, 1).h("1 Scope", 1).x("Text.", 1).h("2 Normative references", 1).x("None.", 1)
    res, doc = route(d, tmp_path)
    return doc, json.loads((tmp_path / "document_model.json").read_text("utf-8"))


@pytest.mark.parametrize("ident,doc_id,language", [
    ("DIN SPEC 91345:2016-04 (D)", "din-spec-91345-de", "de"),
    ("DIN SPEC 91345:2016-04 (E)", "din-spec-91345-en", "en"),
    ("DIN EN ISO 9001:2015-11 (D/E)", "din-en-iso-9001-de-en", "de,en"),
    ("DIN EN ISO 9001:2008-12 (D/E/F)", "din-en-iso-9001-de-en-fr", "de,en,fr"),
    ("ISO/IEC 27000:2018(E)", "iso-iec-27000-en", "en"),
    ("DIN EN ISO 12100:2011-03", "din-en-iso-12100", "en"),  # no mark printed: the id is unchanged; the language comes from the (English) fixture headings
])
def test_language_editions_of_one_standard_get_distinct_ids(ident, doc_id, language, tmp_path):
    doc, model = _edition(ident, tmp_path)
    assert doc["id"] == doc_id and doc["language"] == language
    assert model["metadata"].get("language") == (language if "(" in ident and ident.rstrip().endswith(")") else None)


def test_the_two_language_editions_never_share_an_id(tmp_path):
    ids = {_edition(i, tmp_path / n)[0]["id"] for n, i in (("d", "DIN SPEC 91345:2016-04 (D)"), ("e", "DIN SPEC 91345:2016-04 (E)"), ("n", "DIN SPEC 91345:2016-04"))
           if (tmp_path / n).mkdir() is None}
    assert len(ids) == 3


def test_amendment_instructions_leave_the_foreword_and_stay_top_level_text(tmp_path):
    m = parse(amendment_draft(), tmp_path)[0]
    by = m.by_id()
    foreword = m.of_type(T.FOREWORD)[0]
    flagged = {e.id: e for e in m.elements if {"amendment_instruction", "amendment_base_title"} & set(e.hygiene_flags)}
    assert [(e.parent_id, e.type, e.hygiene_flags) for e in flagged.values()] == [("doc", T.TEXT, ["amendment_base_title"]), ("doc", T.TEXT, ["amendment_instruction"])]
    # the foreword keeps what belongs to it: its text, the comment table and the list of changes
    assert [by[c].type for c in foreword.children_ids] == [T.TEXT, T.TABLE, T.TEXT, T.LIST_ITEM, T.LIST_ITEM]
    after = [e for e in m.elements if e.parent_id == "doc" and e.region == "body"]
    assert [e.content_text[:12] for e in after] == ["Errichten vo", "Ändere Absch", "Der geändert"]  # original order, nothing invented between them
    assert not m.of_type(T.CLAUSE) and all(e.region == "body" for e in after)


def test_amendment_structure_reaches_the_legal_json_without_new_hierarchy(tmp_path):
    from odos.pipeline import Outcome

    res, doc = route(amendment_draft(), tmp_path)
    assert res.outcome == Outcome.COMPLETED and res.summary["json_valid"]
    assert [(n["type"], (n.get("title") or n.get("text") or "")[:12]) for n in doc["structure"]] == \
        [("foreword", "Nationales V"), ("text", "Errichten vo"), ("text", "Ändere Absch"), ("text", "Der geändert")]
    assert all(not n.get("children") for n in doc["structure"][1:])


@pytest.mark.parametrize("line", [
    "Ändere Abschnitt 443.6.2 der DIN VDE 0100-443 (VDE 0100-443) wie folgt:", "Ersetze Tabelle 2 durch die folgende Tabelle:",
    "Ergänze im Anhang A nach Absatz 3 den folgenden Satz:", "Streiche Anmerkung 2 in Abschnitt 5 wie folgt:",
    "Replace Clause 3.2 as follows:", "Add after Table 4 the following Note:", "Delete Annex C:",
])
def test_instruction_lines(line):
    assert R.INSTRUCTION_RX.match(line)


@pytest.mark.parametrize("line", [
    "Die Tabelle 2 wird ersetzt.", "Abschnitt 5 enthält Anforderungen:", "Replacement parts are listed in Table 4.", "Änderung A1 zu DIN VDE 0100-443",
    "Ersatz für DIN EN 349:1993-06", "Add the values and divide.",
])
def test_ordinary_sentences_are_not_instructions(line):
    assert not R.INSTRUCTION_RX.match(line)


def test_english_amendment_without_a_foreword_and_an_instruction_inside_an_open_body(tmp_path):
    d = Doc(2, header="EN ISO 9001:2015/A1:2024").h("EN ISO 9001:2015/A1:2024", 1).x("Amendment 1", 1)
    d.x("Replace Clause 5.1.1 with the following text:", 1).x("The new text.", 1)
    m = parse(d, tmp_path)[0]
    assert (m.metadata.document_number, m.metadata.document_variant) == ("9001", "A1")
    assert [(e.parent_id, e.region, e.hygiene_flags) for e in m.elements if "amendment_instruction" in e.hygiene_flags] == [("doc", "body", ["amendment_instruction"])]
    d2 = Doc(2, header="DIN VDE 0100-443/A3 (VDE 0100-443/A3):2022-09").h("DIN VDE 0100-443/A3 (VDE 0100-443/A3):2022-09", 1).h("1 Anwendungsbereich", 1).x("Text.", 1)
    d2.x("Ändere Abschnitt 443.6.2 wie folgt:", 1)
    m2 = parse(d2, tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path)[0]
    inst = next(e for e in m2.elements if "amendment_instruction" in e.hygiene_flags)
    assert inst.parent_id == by_number(m2)["1"].id  # inside an open clause the line stays where it is printed, only flagged


@pytest.mark.parametrize("headings,detected", [
    (("1 Scope", "2 Normative references", "3 Terms and definitions"), "en"),
    (("1 Anwendungsbereich", "2 Normative Verweisungen", "3 Begriffe"), "de"),
    (("1 Domaine d’application", "2 Références normatives", "3 Termes et définitions"), "fr"),
])
def test_language_is_read_from_the_unit_headings_and_does_not_change_the_id(headings, detected, tmp_path):
    d = Doc(2, header="ISO 9999:2020").h("ISO 9999:2020", 1)
    for h in headings:
        d.h(h, 1).x("Text.", 1)
    res, doc = route(d, tmp_path)
    model = json.loads((tmp_path / "document_model.json").read_text("utf-8"))["metadata"]
    assert doc["language"] == detected and model.get("language_detected") == detected and "language" not in model
    assert doc["id"] == "iso-9999"  # only a language mark printed with the identifier belongs in the id


def test_a_bilingual_document_reports_both_languages(tmp_path):
    d = Doc(2, header="IEC 61508-1").h("IEC 61508-1", 1).h("1 Scope", 1).x("T.", 1).h("2 Normative references", 1).x("T.", 1)
    d.h("1 Domaine d’application", 2).x("T.", 2).h("2 Références normatives", 2).x("T.", 2)
    assert route(d, tmp_path)[1]["language"] == "en,fr"


def test_too_little_evidence_leaves_the_profile_default(tmp_path):
    d = Doc(1, header="ISO 9999:2020").h("ISO 9999:2020", 1).h("1 Scope", 1).x("T.", 1).h("2 Normative references", 1).x("T.", 1)
    assert route(d, tmp_path)[1]["language"] == "en"  # two headings are enough
    d2 = Doc(1, header="ISO 9999:2020").h("ISO 9999:2020", 1).h("1 Scope", 1).x("T.", 1).h("2 Other things", 1).x("T.", 1).h("3 Terms and definitions", 1).x("T.", 1)
    (tmp_path / "b").mkdir()
    assert route(d2, tmp_path / "b")[1]["language"] == "en"
    d3 = Doc(1, header="ISO 9999:2020").h("ISO 9999:2020", 1).h("1 Scope", 1).x("T.", 1).h("2 Other things", 1).x("T.", 1).h("3 More things", 1).x("T.", 1)
    (tmp_path / "c").mkdir()
    assert route(d3, tmp_path / "c")[1]["language"] == "de"  # one heading: no detection, the profile default


# ---- layouts seen in the licensed Nautos viewer: bilingual parallel columns, bare issue line on the cover ----------------------------------
LEFT, RIGHT = dict(left=57, right=290), dict(left=310, right=538)


def bilingual_doc() -> Doc:
    """DIN EN ISO 9001-style "Deutsche und Englische Fassung": German left, English right, same clause numbers, as a column-aware
    extractor reads it (left column, then right column, page by page)."""
    d = Doc(3, header="EN ISO 9001:2015 (D/E)").h("DIN EN ISO 9001:2015-11", 1)
    d.h("1 Anwendungsbereich", 2, **LEFT).x("Dieses Dokument legt Anforderungen fest.", 2, **LEFT).h("2 Normative Verweisungen", 2, **LEFT).x("Keine.", 2, **LEFT)
    d.h("1 Scope", 2, **RIGHT).x("This document specifies requirements.", 2, **RIGHT).h("2 Normative references", 2, **RIGHT).x("None.", 2, **RIGHT)
    d.h("3 Begriffe", 3, **LEFT).x("Es gelten die Begriffe.", 3, **LEFT).h("4 Kontext", 3, **LEFT).x("Text der Organisation.", 3, **LEFT)
    d.h("3 Terms and definitions", 3, **RIGHT).x("The terms apply.", 3, **RIGHT).h("4 Context", 3, **RIGHT).x("Text of the organization.", 3, **RIGHT)
    return d


def test_parallel_language_columns_become_two_complete_editions(tmp_path):
    m = parse(bilingual_doc(), tmp_path)[0]
    tops = [(e.number, e.title, e.pages) for e in m.of_type(T.CLAUSE) if e.parent_id == "doc"]
    assert tops == [("1", "Anwendungsbereich", [2]), ("2", "Normative Verweisungen", [2]), ("3", "Begriffe", [3]), ("4", "Kontext", [3]),
                    ("1", "Scope", [2]), ("2", "Normative references", [2]), ("3", "Terms and definitions", [3]), ("4", "Context", [3])]
    editions = {e.title: [f for f in e.hygiene_flags if f.startswith("parallel_edition")] for e in m.of_type(T.CLAUSE)}
    assert editions["Begriffe"] == ["parallel_edition:1"] and editions["Terms and definitions"] == ["parallel_edition:2"]
    assert [e.number for e in m.of_type(T.CLAUSE) if "numbering_restarts_second_part" in e.hygiene_flags] == ["1", "2", "3", "4"]  # only the English ones
    by = m.by_id()
    assert all(by[c].content_text.startswith(("Dieses", "Keine", "Es gelten", "Text der")) for e in m.of_type(T.CLAUSE) if e.title in ("Anwendungsbereich", "Normative Verweisungen", "Begriffe", "Kontext") for c in e.children_ids)


def test_bilingual_columns_reach_a_valid_legal_json_with_both_languages(tmp_path):
    from odos.pipeline import Outcome

    res, doc = route(bilingual_doc(), tmp_path)
    assert res.outcome == Outcome.COMPLETED and res.summary["json_valid"]
    assert doc["language"] == "de,en" and doc["id"] == "din-en-iso-9001-de-en"  # the (D/E) mark stands only in the running header
    assert [n["title"] for n in doc["structure"]] == ["Anwendungsbereich", "Normative Verweisungen", "Begriffe", "Kontext",
                                                       "Scope", "Normative references", "Terms and definitions", "Context"]


def test_a_two_column_text_without_repeated_headings_keeps_its_reading_order(tmp_path):
    d = Doc(3, header="ISO 9999:2020").h("ISO 9999:2020", 1)
    d.h("1 Scope", 2, **LEFT).x("Text eins.", 2, **LEFT).h("2 Normative references", 2, **LEFT).x("Text zwei.", 2, **LEFT)
    d.h("3 Terms and definitions", 2, **RIGHT).x("Text drei.", 2, **RIGHT).h("4 General", 2, **RIGHT).x("Text vier.", 2, **RIGHT)
    d.h("5 Requirements", 3, **LEFT).x("Text fünf.", 3, **LEFT).h("6 Tests", 3, **LEFT).x("Text sechs.", 3, **LEFT)
    d.h("7 Report", 3, **RIGHT).x("Text sieben.", 3, **RIGHT).h("8 Annexes", 3, **RIGHT).x("Text acht.", 3, **RIGHT)
    m = parse(d, tmp_path)[0]
    assert [e.number for e in m.of_type(T.CLAUSE)] == ["1", "2", "3", "4", "5", "6", "7", "8"]  # one text read column by column: untouched
    assert not any(f.startswith("parallel_edition") for e in m.elements for f in e.hygiene_flags)


def test_single_column_and_sparse_pages_are_untouched(tmp_path):
    d = Doc(2, header="ISO 9999:2020").h("ISO 9999:2020", 1).h("1 Scope", 2, **LEFT).x("Text.", 2, **LEFT).h("1 Scope", 2, **RIGHT).x("Text.", 2, **RIGHT)
    m = parse(d, tmp_path)[0]  # two items per column: below the evidence threshold
    assert not any(f.startswith("parallel_edition") for e in m.elements for f in e.hygiene_flags)


def test_foreword_and_vorwort_pair_up_without_numbers(tmp_path):
    d = Doc(2, header="ISO 9999:2020 (D/E)").h("ISO 9999:2020 (D/E)", 1)
    d.h("Vorwort", 2, **LEFT).x("Text eins.", 2, **LEFT).x("Text zwei.", 2, **LEFT).x("Text drei.", 2, **LEFT)
    d.h("Foreword", 2, **RIGHT).x("Text one.", 2, **RIGHT).x("Text two.", 2, **RIGHT).x("Text three.", 2, **RIGHT)
    m = parse(d, tmp_path)[0]
    assert [f.title for f in m.of_type(T.FOREWORD)] == ["Vorwort", "Foreword"]
    assert [len(m.by_id()[f.id].children_ids) for f in m.of_type(T.FOREWORD)] == [3, 3]


def test_bare_year_month_line_on_a_cover_is_the_issue(tmp_path):
    d = Doc(2, header="DIN 14675-1").h("DIN 14675-1", 1).x("2020-01", 1).h("Brandmeldeanlagen", 1).x("Ersatz für DIN 14675-1:2018-04", 1)
    d.h("Vorwort", 1).x("Dieses Dokument wurde erarbeitet.", 1).h("1 Anwendungsbereich", 2).x("T.", 2).h("2 Normative Verweisungen", 2).x("T.", 2)
    m = parse(d, tmp_path)[0]
    assert (m.metadata.document_number, m.metadata.version_year_month) == ("14675-1", "2020-01")
    assert [f.title for f in m.of_type(T.FOREWORD)] == ["Vorwort"]


# ---- real PDFs of several families through the whole upload path (Docling included) --------------------------------------------------
REAL_DIR = Path(__file__).resolve().parents[1] / "data" / "input" / "private" / "standards"


@pytest.mark.slow
@pytest.mark.parametrize("pdf", sorted(REAL_DIR.glob("*.pdf")) or [None], ids=lambda p: p.name if p else "no-pdfs")
def test_real_standard_pdfs_route_automatically(pdf, tmp_path):
    if pdf is None:
        pytest.skip("place official standard PDFs or previews under backend/data/input/private/standards/ (Git-ignored)")
    from odos.pipeline import Outcome, run_pipeline

    res = run_pipeline(pdf, tmp_path)  # no mode: the document's own structure decides
    assert res.outcome == Outcome.COMPLETED, res.message
    assert res.summary["profile"] == "technical_standard" and res.summary["json_valid"]


# ---- real DIN EN ISO 12100:2011-03 (98 pages) ------------------------------------------------------------------------------------
def _real_pdf() -> Path:
    pdf = Path(os.environ.get("ODOS_DIN_EN_ISO_12100_PDF") or PRIVATE_PDF)
    if not pdf.is_file():
        pytest.skip("set ODOS_DIN_EN_ISO_12100_PDF or place the PDF at backend/data/input/private/din_en_iso_12100.pdf")
    return pdf


@pytest.mark.slow
def test_real_din_en_iso_12100_end_to_end(tmp_path):
    from odos.artifact_names import DOCUMENT_MODEL, LEGAL_JSON, LEGAL_JSON_REPORT, VALIDATION_REPORT
    from odos.pipeline import Outcome, run_pipeline

    result = run_pipeline(_real_pdf(), tmp_path, mode="technical_standard")
    assert result.outcome == Outcome.COMPLETED, result.message
    doc, rep, acc = (json.loads((tmp_path / n).read_text("utf-8")) for n in (LEGAL_JSON, LEGAL_JSON_REPORT, VALIDATION_REPORT))
    model = json.loads((tmp_path / DOCUMENT_MODEL).read_text("utf-8"))
    assert rep["valid"] and acc["accounting"]["exact"]  # every Docling item (incl. nested captions) appears exactly once
    assert (doc["documentType"], doc["legalSystem"], doc["version"]["date"], doc["pageCount"]) == ("technical_standard", "ts", "2011-03", 98)

    nodes, stack = [], list(doc["structure"])
    while stack:
        n = stack.pop(0)
        nodes.append(n)
        stack = n.get("children", []) + stack
    clauses = {n["number"]: n for n in nodes if n["type"] in ("clause", "definition") and not n["id"].startswith("doc/annex")}
    for top in "1234567":  # main clauses of the standard, each with its printed title and PDF page (printed page + 10)
        assert top in clauses
    assert clauses["1"]["title"] == "Anwendungsbereich" and clauses["1"]["pages"] == [16]
    assert max(n.count(".") for n in clauses) >= 3  # deep numbering is kept (e.g. 6.3.5.6)
    assert {n for n in clauses if n.startswith("3.") and n.count(".") == 1} >= {f"3.{i}" for i in range(1, 40)}
    assert sum(n["type"] == "definition" for n in nodes) == 55 and sum(n["type"] == "note" for n in nodes) == 84
    annexes = {n["number"]: n["classification"] for n in doc["structure"] if n["type"] == "annex"}
    assert annexes == {"NA": "informative", "A": "informative", "B": "informative", "C": "informative", "ZA": "informative"}
    assert sorted(n["number"] for n in nodes if n["type"] == "figure") == ["1", "2", "3", "4", "A.1"]
    annex_a = next(n for n in doc["structure"] if n["type"] == "annex" and n["number"] == "A")
    assert any(c["type"] == "figure" for c in annex_a["children"])  # Docling listed the heading after its figure
    assert sum(n["type"] == "table" for n in nodes) + sum(n["type"] == "table" for n in doc["tableOfContents"][0]["children"]) == 24
    linked = sum(e["status"] == "linked" for e in model["toc_entries"])
    assert linked >= 50  # of 65 printed TOC lines; annex lines cannot link (shared linker reads body-region units only)
