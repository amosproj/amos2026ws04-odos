"""document.json: the public JSON serialization of the canonical DocumentModel (schema odos-legal-json 2.0)."""

import json

import pytest
from jsonschema import Draft202012Validator

from odos.legal_json.artifacts import SCHEMA_PATH, build_legal_json_artifacts, published_schema, serialize
from odos.legal_json.exporter import to_legal_json
from odos.legal_json.markers import marker_style
from odos.legal_json.nesting import validate_structure
from odos.legal_json.view import Node, json_schema
from odos.normalization.docling_reader import SourceItem
from odos.document_model import Provenance, SourceInfo
from odos.parsing.profiles.german_law.recognizer import parse_items
from odos.parsing.profiles.german_law.rules import GERMAN_LAW_RULES

# the synthetic documents always run; MBO and EU need the partner PDFs and skip without them
FIXTURES = {
    "synthetic_german": ("synthetic_german_model", "synthetic_german_raw_json", ("de", "de_legislation")),
    "synthetic_eu": ("synthetic_eu_model", "synthetic_eu_raw_json", ("eu", "eu_regulation")),
    "mbo": ("mbo_model", "mbo_raw_json", ("de", "de_legislation")),
    "eu": ("eu_model", "eu_raw_json", ("eu", "eu_regulation")),
}
# internal data and technical provenance that must never reach document.json (in any spelling)
FORBIDDEN = {"uncertain", "uncertainty_reasons", "uncertaintyReasons", "warnings", "structure_notes", "hygiene_flags",
             "hygieneFlags", "docling_label", "doclingLabel", "search_text", "reviewed", "review", "confidence",
             "region", "parent_id", "children_ids", "source_refs", "provenance",
             "source", "sourceSpans", "bbox", "bboxScope", "charStart", "charEnd", "itemRef", "numberSource", "textSha256",
             "markerStyle", "coordinateSystem", "sourceFile", "doclingJsonSha256", "left", "top", "right", "bottom",
             "source_spans", "highlight_boxes", "page_no", "self_ref"}  # fmt: skip


@pytest.fixture(scope="module", params=FIXTURES)
def case(request, tmp_path_factory):
    model_name, raw_name, header = FIXTURES[request.param]
    model, raw = request.getfixturevalue(model_name), request.getfixturevalue(raw_name)
    out = tmp_path_factory.mktemp(request.param)
    art = build_legal_json_artifacts(model, raw, out)
    return request.param, header, model, raw, art["document"], art["report"], json.loads((out / "document.json").read_text())


def nodes(doc):
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


def test_json_is_schema_valid_and_keeps_the_models_text(case):
    name, (system, doc_type), model, _, doc, rep, data = case
    assert (data["schemaVersion"], data["legalSystem"], data["documentType"]) == ("2.0", system, doc_type)
    assert rep["valid"] and rep["schema_valid"] and rep["structure_valid"], (rep["schema_errors"], rep["structure_errors"])
    assert not list(Draft202012Validator(published_schema()).iter_errors(data))
    t = rep["text_preservation"]
    assert t["identical_to_model"] and t["elements_exported"] == t["elements_expected"] == len(model.elements) - 1
    assert not (t["missing_elements"] or t["duplicated_elements"] or t["field_mismatches"] or t["source_items_unaccounted"])
    assert t["source_items_exported"] + t["source_items_excluded_as_page_furniture"] == t["source_items"]  # no Docling item lost
    index = model.by_id()
    for n in nodes(doc):  # the exported text is the canonical model's text
        el = index[n.id]
        assert n.marker == el.marker and n.title == el.title
        assert (n.text or "") == ("" if el.title is not None and el.content_text == el.title else el.content_text)
    sf = rep["source_fidelity"]  # and it matches the PDF's own text layer, apart from recorded word divisions
    if sf["pdf_text_layer"]:
        assert sf["unexplained_differences"] == [], sf["unexplained_differences"][:3]
    else:
        assert name == "synthetic_eu"  # the generated EU regulation has no PDF


def test_json_carries_legal_content_only_and_every_node_leads_back_to_the_model(case):
    name, _, model, raw, doc, rep, data = case
    assert not FORBIDDEN & set(keys(data)) and "pages" not in data  # provenance stays in the DocumentModel
    ids = [n.id for n in nodes(doc)] + [f.id for f in doc.footnotes]
    assert len(ids) == len(set(ids)) and set(ids) <= {e.id for e in model.elements}  # the model's stable ids
    assert serialize(to_legal_json(model)) == serialize(doc)  # deterministic
    index = model.by_id()
    assert not rep["text_preservation"]["elements_without_source"]
    for n in [*nodes(doc), *doc.footnotes]:
        assert n.pages == index[n.id].pages  # the pages the PDF viewer jumps to
    footnotes = [f for f in doc.footnotes if f.anchorElementIds]
    assert rep["footnotes"]["anchored"] == len(footnotes)
    if name != "synthetic_eu":  # elements the PDF viewer can highlight: Docling's boxes are kept in the model
        exported = [*nodes(doc), *doc.footnotes]
        with_boxes = [n for n in exported if any(p.bbox for p in index[n.id].provenance)]
        assert len(with_boxes) >= 0.99 * len(exported), (name, len(with_boxes), len(exported))


def test_marker_styles():
    for marker, type_, style in [
        ("§ 1", "section", "section_sign"), ("(3)", "subsection", "arabic"), ("a)", "letter", "alpha_lower"),
        ("aa)", "letter", "alpha_lower_double"), ("i)", "subpoint", "roman_lower"), ("KAPITEL IX", "chapter", "roman_upper"),
        ("1.2.4.1.", "heading", "decimal_hierarchy"), ("Erster Teil", "part", "ordinal_word"), ("Artikel 54", "article", "arabic"),
        ("( 1 )", "footnote", "arabic"), ("*)", "footnote", "symbol"),
    ]:  # fmt: skip
        assert marker_style(marker, type_) == style, marker


def test_real_mbo_in_the_german_vocabulary(mbo_model):
    doc = to_legal_json(mbo_model)
    assert (doc.id, doc.documentType, doc.legalSystem, doc.shortTitle) == ("mbo", "de_legislation", "de", "MBO")
    by = {n.id: n for n in nodes(doc)}
    teil = by["doc/teil-1"]
    assert (teil.type, teil.marker, teil.title, teil.text) == ("part", "Erster Teil", "Allgemeine Vorschriften", None)
    sec = by["doc/teil-1/par-2"]
    assert (sec.type, sec.nativeType, sec.marker, sec.title) == ("section", "Paragraph", "§ 2", "Begriffe")
    nr = by["doc/teil-1/par-2/abs-3/nr-2"]
    assert (nr.type, nr.nativeType, nr.marker, nr.text) == ("number", "Nummer", "2.", "Gebäudeklasse 2:")
    assert by["doc/anlage-1"].type == "annex" and by["doc/teil-3/abschnitt-3/par-23"].marker == "23"  # printed without "§": kept

    abs1 = by["doc/teil-2/par-6/abs-1"]  # § 6 (1) runs over the page break: one text, both pages
    el = mbo_model.by_id()[abs1.id]
    assert abs1.pages == [9, 10] and abs1.text == el.content_text
    assert sorted({p.page_no for p in el.provenance}) == [9, 10] and all(p.bbox for p in el.provenance)

    anchored = [f for f in doc.footnotes if f.anchorElementIds]  # 35 by superscript reference marks + the "*" note
    assert len(doc.footnotes) == 37 and len(anchored) == 36
    assert next(f for f in doc.footnotes if f.marker == "*").anchorElementIds == ["doc/front-4"]


def test_real_eu_regulation_in_the_eu_vocabulary(eu_model):
    doc = to_legal_json(eu_model)
    assert (doc.id, doc.documentType, doc.nativeDocumentType, doc.legalSystem) == ("verordnung-2023-1230", "eu_regulation", "VERORDNUNG", "eu")  # fmt: skip
    assert (doc.publicationDate, doc.adoptionDate, doc.identifiers.documentNumber) == ("2023-06-29", "2023-06-14", "2023/1230")
    assert [n.type for n in doc.structure][:2] == ["preamble", "chapter"] and doc.structure[-1].type == "annex"
    by = {n.id: n for n in nodes(doc)}
    p3 = by["doc/chp-2/art-11/para-3"]
    assert (p3.type, p3.nativeType, p3.marker, p3.pages) == ("paragraph", "Absatz", "(3)", [20])
    assert by["doc/chp-1/art-2/para-2/pt-p/sub-i"].type == "subpoint"
    tables = [n for n in nodes(doc) if n.type == "table"]  # annex tables keep their rows
    assert sorted((t.numRows, t.numCols) for t in tables) == [(25, 2), (27, 4)]
    assert all(t.rows == eu_model.by_id()[t.id].table.rows for t in tables)
    assert len(doc.footnotes) == len([f for f in doc.footnotes if f.anchorElementIds]) == 26


# ---- structural rules and the schema -------------------------------------------------------------------------------
def _node(id_, type_, children=(), **kw):
    return Node(id=id_, type=type_, children=list(children), **kw)


def _doc(system, structure, footnotes=()):
    item = lambda i, label, text: SourceItem(ref=f"#/texts/{i}", label=label, layer="body", orig=text, text=text,
                                             provenance=[Provenance(page_no=1)])  # fmt: skip
    model = parse_items(SourceInfo(docling_json_sha256="0" * 64, num_pages=2),
                        [item(0, "section_header", "§ 1 A"), item(1, "text", "Text.")], GERMAN_LAW_RULES)
    return to_legal_json(model).model_copy(update={"legalSystem": system, "structure": structure, "footnotes": list(footnotes)})


def test_invalid_nesting_is_rejected():
    bad = validate_structure(_doc("de", [_node("c", "chapter", [_node("s", "subsection")])]))
    assert any("'subsection' not allowed under 'chapter'" in e for e in bad)
    assert any("not allowed under 'preamble'" in e for e in validate_structure(_doc("eu", [_node("p", "preamble", [_node("x", "paragraph")])])))  # fmt: skip
    assert any("not a structural unit of de" in e for e in validate_structure(_doc("de", [_node("p", "preamble")])))
    assert "duplicate id: s" in validate_structure(_doc("de", [_node("s", "section"), _node("s", "section")]))


def test_published_schema_is_generated_from_the_classes():
    assert json.loads(SCHEMA_PATH.read_text(encoding="utf-8")) == json_schema(), (
        "schema drifted: regenerate with  python -c \"import json;from odos.legal_json.view import json_schema;"
        "print(json.dumps(json_schema(),indent=2,ensure_ascii=False))\" > schemas/odos-legal-json/2.0/legal-document.schema.json"
    )
