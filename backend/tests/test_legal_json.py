"""document.json: the public JSON serialization of the canonical DocumentModel (schema odos-legal-json 1.1; legacy 1.0)."""

import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from odos.legal_json.artifacts import SCHEMA_PATH, build_legal_json_artifacts, published_schema, serialize
from odos.legal_json.exporter import load_source_context, to_legal_json
from odos.legal_json.markers import marker_style
from odos.legal_json.nesting import validate_structure
from odos.legal_json.view import LegalDocument, Node, Source, json_schema
from odos.normalization.docling_reader import SourceItem, read_page_sizes
from odos.document_model import Element, ElementType as T, Provenance, SourceInfo
from odos.parsing.profiles.german_law.recognizer import parse_items
from odos.parsing.profiles.german_law.rules import GERMAN_LAW_RULES

SRC = Path(__file__).resolve().parents[1] / "src" / "odos"
DOCS = ["bdsg", "mbo", "eu"]
FIXTURES = {"bdsg": ("model", "raw_json"), "mbo": ("mbo_model", "mbo_raw_json"), "eu": ("eu_model", "eu_raw_json")}
# internal data that must never reach document.json (in any spelling)
FORBIDDEN = {"uncertain", "uncertainty_reasons", "uncertaintyReasons", "warnings", "structure_notes", "hygiene_flags",
             "hygieneFlags", "docling_label", "doclingLabel", "search_text", "reviewed", "review", "confidence",
             "region", "parent_id", "children_ids", "source_refs", "provenance"}  # fmt: skip


@pytest.fixture(scope="module", params=DOCS)
def case(request, tmp_path_factory):
    m_name, raw_name = FIXTURES[request.param]
    model, raw = request.getfixturevalue(m_name), request.getfixturevalue(raw_name)
    out = tmp_path_factory.mktemp(request.param)
    art = build_legal_json_artifacts(model, raw, out)
    return request.param, model, raw, art["document"], art["report"], json.loads((out / "document.json").read_text())


def nodes(doc: LegalDocument):
    stack = [*doc.frontMatter, *doc.tableOfContents, *doc.structure, *(c for f in doc.footnotes for c in f.content)]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(n.children)


def keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from keys(v)


# ---- validity and text preservation ----------------------------------------------------------------------------------
def test_json_schema_structure_and_text_are_valid(case):
    name, model, _, doc, rep, data = case
    assert rep["valid"] and rep["schema_valid"] and rep["structure_valid"], (rep["schema_errors"], rep["structure_errors"])
    assert not list(Draft202012Validator(published_schema()).iter_errors(data))
    t = rep["text_preservation"]
    assert t["identical_to_model"] and t["elements_exported"] == t["elements_expected"] == len(model.elements) - 1
    assert not (t["missing_elements"] or t["duplicated_elements"] or t["field_mismatches"] or t["source_items_unaccounted"])
    assert all(t["document_order_preserved"].values())
    assert t["source_items_exported"] + t["source_items_excluded_as_page_furniture"] == t["source_items"]


def test_text_is_the_canonical_models_text(case):
    _, model, _, doc, _, _ = case
    index = model.by_id()
    for n in nodes(doc):
        el = index[n.id]
        assert n.marker == el.marker and n.title == el.title
        assert (n.text or "") == ("" if el.title is not None and el.content_text == el.title else el.content_text)


def test_no_internal_or_review_data_and_unique_ids(case):
    _, model, _, doc, _, data = case
    assert not FORBIDDEN & set(keys(data))
    ids = [n.id for n in nodes(doc)] + [f.id for f in doc.footnotes]
    assert len(ids) == len(set(ids)) and set(ids) <= {e.id for e in model.elements}  # the internal, stable ids


def test_export_is_deterministic(case):
    _, model, raw, doc, _, _ = case
    assert serialize(to_legal_json(model, load_source_context(raw))) == serialize(doc)


# ---- provenance and coordinates ----------------------------------------------------------------------------------------
def test_boxes_are_the_models_provenance_in_one_coordinate_system(case):
    _, model, raw, doc, _, _ = case
    sizes = read_page_sizes(raw)
    assert doc.coordinateSystem.origin == "bottom-left" and doc.coordinateSystem.unit == "pt"
    assert {p.number: (p.width, p.height) for p in doc.pages} == sizes and len(doc.pages) == doc.pageCount
    index = model.by_id()
    for n in nodes(doc):
        el = index[n.id]
        assert n.source.pages == el.pages
        if el.source_spans:
            assert [(s.itemRef, s.charStart, s.charEnd) for s in n.source.sourceSpans] == [(s.ref, s.start, s.end) for s in el.source_spans]  # fmt: skip
        else:
            assert [(s.page, s.bbox.left, s.bbox.top, s.bbox.right, s.bbox.bottom) for s in n.source.sourceSpans] == \
                   [(p.page_no, p.bbox.l, p.bbox.t, p.bbox.r, p.bbox.b) for p in el.provenance]  # fmt: skip
        for s in n.source.sourceSpans:
            assert s.itemRef in el.source_refs
            if s.bbox:  # inside the page, top above bottom: what the PDF highlighter (bboxToRect) expects
                w, h = sizes[s.page]
                assert 0 <= s.bbox.left <= s.bbox.right <= w + 0.5 and 0 <= s.bbox.bottom <= s.bbox.top <= h + 0.5


def test_multi_page_items_map_each_box_to_its_item(model, raw_json):
    doc = to_legal_json(model, load_source_context(raw_json))
    two = [n for n in nodes(doc) if len(n.source.pages) > 1]
    assert two and all(s.itemRef for n in two for s in n.source.sourceSpans)


# ---- footnotes -----------------------------------------------------------------------------------------------------
def test_footnote_anchors_only_with_source_evidence(case):
    name, model, _, doc, rep, _ = case
    index = model.by_id()
    anchored = [f for f in doc.footnotes if f.anchorElementIds]
    if name == "mbo":  # 35 proven by superscript reference marks + the "*" note; 1 stays unresolved, never guessed
        assert len(doc.footnotes) == 37 and len(anchored) == 36
        assert all(f.anchorElementIds == index[f.id].anchor_ids for f in anchored)
        assert all((f.anchorElementId is not None) == (len(f.anchorElementIds) == 1) for f in doc.footnotes)  # 1.0 meaning kept
        assert sum(len(f.anchorElementIds) > 1 for f in doc.footnotes) == 3  # one "*)" note referenced on several elements
        assert next(f for f in doc.footnotes if f.marker == "*").anchorElementId == "doc/front-4"
    if name == "bdsg":
        assert len(doc.footnotes) == 13 and len(anchored) == 12
        assert all(index[f.anchorElementId].type == T.PARAGRAPH and f.title == "Fußnote" and f.content for f in anchored)
        assert next(f for f in doc.footnotes if not f.anchorElementId).id.startswith("doc/front")
    if name == "eu":
        assert len(doc.footnotes) == len(anchored) == 26
        for f in anchored:
            a = index[f.anchorElementId]
            assert re.search(rf"\(\s*{f.number}\s*\)", a.original_text) and set(f.source.pages) & set(a.pages)
    assert rep["footnotes"]["anchored"] == len(anchored)


def _item(i, label, text, marker=None, enumerated=None, page=1):
    return SourceItem(ref=f"#/texts/{i}", label=label, layer="body", orig=(f"{marker} {text}" if marker else text), text=text,
                      marker=marker, enumerated=enumerated, provenance=[Provenance(page_no=page)])  # fmt: skip


def _parse(items):
    return parse_items(SourceInfo(docling_json_sha256="0" * 64, num_pages=2), items, GERMAN_LAW_RULES)


def test_footnote_reference_on_another_page_is_not_an_anchor(eu_model):
    m = eu_model.model_copy(deep=True)
    fn = next(e for e in m.elements if e.type == T.FOOTNOTE)
    fn.pages = [max(m.by_id()[fn.parent_id].pages) + 1]
    assert next(f for f in to_legal_json(m).footnotes if f.id == fn.id).anchorElementId is None


# ---- markers, numbering, tables, examples ------------------------------------------------------------------------------
@pytest.mark.parametrize("marker,type_,style", [
    ("§ 1", "section", "section_sign"), ("(3)", "subsection", "arabic"), ("2.", "number", "arabic"),
    ("a)", "letter", "alpha_lower"), ("i)", "letter", "alpha_lower"), ("aa)", "letter", "alpha_lower_double"),
    ("i)", "subpoint", "roman_lower"), ("(iv)", "subpoint", "roman_lower"), ("ii)", "subpoint", "roman_lower"),
    ("KAPITEL IX", "chapter", "roman_upper"), ("ANHANG XII", "annex", "roman_upper"), ("TEIL A", "part", "alpha_upper"),
    ("1.2.4.1.", "heading", "decimal_hierarchy"), ("Erster Teil", "part", "ordinal_word"), ("Artikel 54", "article", "arabic"),
    ("Anlage 1", "annex", "arabic"), ("( 1 )", "footnote", "arabic"), ("*)", "footnote", "symbol"), ("[1.", "number", "arabic"),
    ("Teil 1", "part", "arabic"), ("23", "section", "arabic"), ("(A)", "point", "alpha_upper"),
])  # fmt: skip
def test_marker_style(marker, type_, style):
    assert marker_style(marker, type_) == style


def test_german_example_mbo(mbo_model, mbo_raw_json):
    doc = to_legal_json(mbo_model, load_source_context(mbo_raw_json))
    assert (doc.id, doc.documentType, doc.legalSystem, doc.shortTitle) == ("mbo", "de_legislation", "de", "MBO")
    assert doc.version.date == "2002-11" and doc.enactmentDate is None  # the PDF states no Ausfertigungsdatum
    by = {n.id: n for n in nodes(doc)}
    teil = by["doc/teil-1"]
    assert (teil.type, teil.marker, teil.markerStyle, teil.title, teil.text) == ("part", "Erster Teil", "ordinal_word", "Allgemeine Vorschriften", None)  # fmt: skip
    sec = by["doc/teil-1/par-2"]
    assert (sec.type, sec.nativeType, sec.marker, sec.markerStyle, sec.title) == ("section", "Paragraph", "§ 2", "section_sign", "Begriffe")
    sub = by["doc/teil-1/par-2/abs-3"]
    assert (sub.type, sub.nativeType, sub.marker, sub.text) == ("subsection", "Absatz", "(3)", "1 Gebäude werden in folgende Gebäudeklassen eingeteilt:")  # fmt: skip
    nr = by["doc/teil-1/par-2/abs-3/nr-2"]
    assert (nr.type, nr.nativeType, nr.marker, nr.text) == ("number", "Nummer", "2.", "Gebäudeklasse 2:")
    assert [c.type for c in nr.children] == ["text"] and nr.children[0].text.startswith("Gebäude mit einer Höhe bis zu 7 m")
    assert by["doc/anlage-1"].type == "annex" and by["doc/teil-3/abschnitt-3/par-23"].marker == "23"  # printed without "§": kept


def test_eu_example(eu_model, eu_raw_json):
    doc = to_legal_json(eu_model, load_source_context(eu_raw_json))
    assert (doc.id, doc.documentType, doc.nativeDocumentType, doc.legalSystem) == ("verordnung-2023-1230", "eu_regulation", "VERORDNUNG", "eu")  # fmt: skip
    assert (doc.publicationDate, doc.adoptionDate, doc.identifiers.documentNumber) == ("2023-06-29", "2023-06-14", "2023/1230")
    assert [n.type for n in doc.structure][:2] == ["preamble", "chapter"] and doc.structure[-1].type == "annex"
    by = {n.id: n for n in nodes(doc)}
    p3 = by["doc/chp-2/art-11/para-3"]
    assert (p3.type, p3.nativeType, p3.marker) == ("paragraph", "Absatz", "(3)")
    assert [(s.itemRef, s.charStart, s.charEnd, s.page) for s in p3.source.sourceSpans] == [("#/texts/373", 659, 1280, 20)]
    sp = by["doc/chp-1/art-2/para-2/pt-p/sub-i"]
    assert (sp.type, sp.marker, sp.markerStyle) == ("subpoint", "i)", "roman_lower")
    assert by["doc/chp-1/art-2/para-2/pt-p"].markerStyle == "alpha_lower"
    assert {by[i].type for i in by if by[i].nativeType == "Erwägungsgrund"} == {"recital"}


def test_tables_keep_rows_and_toc_is_separate(eu_model, eu_raw_json, model, raw_json):
    eu = to_legal_json(eu_model, load_source_context(eu_raw_json))
    index = eu_model.by_id()
    tables = [n for n in nodes(eu) if n.type == "table"]
    assert len(tables) == 2 and all(n.id.startswith("doc/annex-12/") for n in tables)
    for t in tables:
        assert [[c.text for c in row] for row in t.rows] == index[t.id].table.rows
        assert (t.numRows, t.numCols) == (index[t.id].table.num_rows, index[t.id].table.num_cols)
    assert sorted((t.numRows, t.numCols) for t in tables) == [(25, 2), (27, 4)]
    de = to_legal_json(model, load_source_context(raw_json))
    assert [n.type for n in de.tableOfContents] == ["tableOfContents"]
    assert {c.type for c in de.tableOfContents[0].children} == {"tocEntry", "table"}
    assert not [n for n in de.structure for x in [n] if x.type in ("tableOfContents", "tocEntry")]


# ---- structural rules, sentences -------------------------------------------------------------------------------------
def _node(id_, type_, children=(), **kw):
    return Node(id=id_, type=type_, source=Source(pages=[], sourceSpans=[]), children=list(children), **kw)


def _doc(system, structure, footnotes=()):
    base = to_legal_json(_parse([_item(0, "section_header", "§ 1 A"), _item(1, "text", "Text.")]))
    return base.model_copy(update={"legalSystem": system, "structure": structure, "footnotes": list(footnotes)})


def test_invalid_nesting_is_rejected():
    bad = validate_structure(_doc("de", [_node("c", "chapter", [_node("s", "subsection")])]))
    assert any("'subsection' not allowed under 'chapter'" in e for e in bad)
    assert any("not allowed under 'preamble'" in e for e in validate_structure(_doc("eu", [_node("p", "preamble", [_node("x", "paragraph")])])))  # fmt: skip
    letters = _node("n", "number", [_node("l", "letter", [_node("l2", "letter", marker="b)", markerStyle="alpha_lower")])])
    assert any("double letter" in e for e in validate_structure(_doc("de", [_node("s", "section", [letters])])))
    assert any("not a structural unit of de" in e for e in validate_structure(_doc("de", [_node("p", "preamble")])))
    assert any("must not have children" in e for e in validate_structure(_doc("de", [_node("s", "section", [_node("t", "text", [_node("u", "text")])])])))  # fmt: skip
    dup = validate_structure(_doc("de", [_node("s", "section"), _node("s", "section")]))
    assert "duplicate id: s" in dup
    from odos.legal_json.view import Footnote

    dangling = Footnote(id="f", source=Source(pages=[], sourceSpans=[]), anchorElementId="nowhere")
    assert any("anchorElementId 'nowhere'" in e for e in validate_structure(_doc("de", [_node("s", "section")], [dangling])))


def test_sentences_are_supported_by_model_schema_and_rules():
    m = _parse([_item(0, "section_header", "§ 1 Zweck"), _item(1, "text", "(1) Erster Satz. Zweiter Satz.")])
    abs1 = m.by_id()["doc/par-1/abs-1"]
    for i, text in enumerate(["Erster Satz.", "Zweiter Satz."], start=1):
        s = Element(id=f"{abs1.id}/sent-{i}", type=T.SENTENCE, region="body", parent_id=abs1.id, number=str(i), content_text=text)
        abs1.children_ids.append(s.id)
        m.elements.append(s)
    doc = to_legal_json(m)
    sub = doc.structure[0].children[0]
    assert [(c.type, c.nativeType, c.text) for c in sub.children] == [("sentence", "Satz", "Erster Satz."), ("sentence", "Satz", "Zweiter Satz.")]  # fmt: skip
    assert not validate_structure(doc)
    assert not list(Draft202012Validator(published_schema()).iter_errors(doc.model_dump(mode="json")))
    assert any("'sentence' not allowed under 'chapter'" in e for e in validate_structure(_doc("de", [_node("c", "chapter", [_node("x", "sentence")])])))  # fmt: skip


# ---- legacy 1.0 -------------------------------------------------------------------------------------------------------
def test_downgrade_information_loss_is_reported(case):
    name, _, _, doc, rep, data = case
    loss = rep["downgrade_to_1_0_information_loss"]
    dropped = loss["dropped"]
    count = lambda field_: dropped.get(field_, {}).get("values", 0)  # noqa: E731
    assert count("sentences") == len(data.get("sentences", [])) and count("tableOfContentsEntries") == len(data.get("tableOfContentsEntries", []))  # fmt: skip
    assert count("footnote.references") == sum(len(f.references) for f in doc.footnotes)
    assert count("footnote.anchorElementIds") == sum(len(f.anchorElementIds) for f in doc.footnotes)
    cells = [c for n in nodes(doc) for row in (n.rows or []) for c in row if c.source is not None]
    assert count("cell.source") == len(cells)
    assert loss["footnotes_with_several_anchors"] == [f.id for f in doc.footnotes if len(f.anchorElementIds) > 1]
    assert all(f.anchorElementId is None for f in doc.footnotes if f.id in loss["footnotes_with_several_anchors"])
    assert loss["lossless"] is (not dropped) and not loss["lossless"]  # all three documents carry 1.1 annotations
    assert rep["valid"] and rep["downgrade_to_1_0_valid"]  # information loss is reported, it does not invalidate
    assert set(dropped) <= {"sentences", "tableOfContentsEntries", "footnote.anchorElementIds", "footnote.references", "cell.source"}  # fmt: skip
    if name != "eu":
        assert count("tableOfContentsEntries") > 0 and count("sentences") > 0


def test_a_1_0_document_loses_nothing(case):
    from odos.legal_json import view
    from odos.legal_json.legacy import downgrade_information_loss, downgrade_to_1_0

    assert view.downgrade_to_1_0 is downgrade_to_1_0  # the documented import path for 1.0 consumers keeps working

    data = case[5]
    assert downgrade_information_loss(downgrade_to_1_0(data)) == {"lossless": True, "dropped": {}, "footnotes_with_several_anchors": []}


# ---- one source of truth -------------------------------------------------------------------------------------------
def test_published_schema_is_generated_from_the_classes():
    assert json.loads(SCHEMA_PATH.read_text(encoding="utf-8")) == json_schema(), (
        "schema drifted: regenerate with  python -c \"import json;from odos.legal_json.view import json_schema;"
        "print(json.dumps(json_schema(),indent=2,ensure_ascii=False))\" > schemas/odos-legal-json/1.1/legal-document.schema.json"
    )


def test_only_the_exporter_builds_the_public_json():
    users = [p.relative_to(SRC).as_posix() for p in SRC.rglob("*.py")
             if "legal_json" not in p.parts and re.search(r"legal_json\.view|LegalDocument|to_legal_json", p.read_text(encoding="utf-8"))]  # fmt: skip
    assert users == [], users  # everything else works on the canonical DocumentModel; document.json is never read back


def test_reviewed_model_exports_corrections_without_review_data(model):
    m = model.model_copy(deep=True)
    el = m.by_id()["doc/teil-1/kapitel-1/par-1/abs-2"]
    el.content_text = "korrigierter Text"
    el.reviewed = {"fields": {"content_text": {"original": "x", "corrected": "korrigierter Text"}}, "corrections": ["c1"]}
    m.review = {"model_revision": 1, "corrections": ["c1"]}
    data = to_legal_json(m).model_dump(mode="json")
    assert not FORBIDDEN & set(keys(data))
    assert '"korrigierter Text"' in json.dumps(data, ensure_ascii=False)
