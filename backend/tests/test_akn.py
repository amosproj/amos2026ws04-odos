import json
import shutil

import pytest
from lxml import etree

from odos.akn.generator import generate_excerpt
from odos.akn.mapping import AKN_NS, ODOS_NS
from odos.akn.validate import PINNED_SHA256, SCHEMA_DIR, SchemaIntegrityError, validate_xml
from odos.akn.verify import verify_text
from odos.akn.german_artifacts import build_artifacts
from odos.cli import retrieval_date_from_source
from odos.normalization.docling_reader import SourceItem
from odos.document_model import ElementType as T, Provenance, SourceInfo, TableData
from odos.parsing.profiles.german_law.recognizer import parse_items
from odos.parsing.profiles.german_law.rules import GERMAN_LAW_RULES

NS = {"a": AKN_NS, "odos": ODOS_NS}
DATE = "2026-10-27"


@pytest.fixture(scope="session")
def result(model):
    return generate_excerpt(model, ["1", "2"], DATE)


@pytest.fixture(scope="session")
def root(result):
    return etree.fromstring(result.xml)


def q(root, path):
    return root.xpath(path, namespaces=NS)


# ---- well-formedness and official XSD ----------------------------------------------------
def test_well_formed_utf8(result):
    assert result.xml.startswith(b"<?xml version='1.0' encoding='UTF-8'?>")
    result.xml.decode("utf-8")
    assert etree.fromstring(result.xml).tag == f"{{{AKN_NS}}}akomaNtoso"


def test_official_xsd_validation(result):
    v = validate_xml(result.xml)
    assert v.well_formed and v.valid and v.errors == []
    assert {f["file"]: f["sha256"] for f in v.schema_files} == PINNED_SHA256
    assert "OASIS" in v.schema_version and v.validator["name"] == "lxml.etree.XMLSchema"


def test_validator_rejects_invalid_documents(result):
    bad = result.xml.replace(b"<num ", b"<bogus/><num ", 1)
    v = validate_xml(bad)
    assert v.well_formed and not v.valid and v.errors and v.errors[0].line > 0
    dup = result.xml.replace(b'eId="part_1__chp_1__art_2"', b'eId="part_1__chp_1__art_1"', 1)
    assert not validate_xml(dup).valid  # xsd:unique on eId is enforced
    assert not validate_xml(b"<akomaNtoso>").well_formed


def test_modified_schema_is_refused(tmp_path, result):
    d = tmp_path / "schema"
    shutil.copytree(SCHEMA_DIR, d)
    (d / "akomantoso30.xsd").write_bytes((d / "akomantoso30.xsd").read_bytes() + b"\n")
    with pytest.raises(SchemaIntegrityError):
        validate_xml(result.xml, schema_dir=d)


# ---- hierarchy, numbering, headings ------------------------------------------------------------
def test_excerpt_hierarchy(root):
    assert [e.get("name") for e in q(root, "/a:akomaNtoso/a:act")] == ["bdsg"]
    arts = q(root, "/a:akomaNtoso/a:act/a:body/a:part/a:chapter/a:article")
    assert [q(a, "string(a:num)") for a in arts] == ["§ 1", "§ 2"]
    assert [q(a, "string(a:heading)") for a in arts] == ["Anwendungsbereich des Gesetzes", "Begriffsbestimmungen"]  # fmt: skip
    assert q(root, "string(//a:part/a:num)") == "Teil 1"
    assert q(root, "string(//a:chapter/a:num)") == "Kapitel 1"
    # § maps to article, never to AKN <paragraph>; Absatz maps to paragraph
    assert not q(root, "//a:article/a:article") and not q(root, "//a:body/a:paragraph")
    assert [len(q(a, "a:paragraph")) for a in arts] == [8, 5]
    assert [q(p, "string(a:num)") for p in q(arts[0], "a:paragraph")] == [f"({i})" for i in range(1, 9)]
    assert [q(p, "string(a:num)") for p in q(arts[1], "a:paragraph")] == [f"({i})" for i in range(1, 6)]
    p1 = q(arts[0], "a:paragraph")[0]
    assert [q(x, "string(a:num)") for x in q(p1, "a:point")] == ["1.", "2."]
    assert [q(x, "string(a:num)") for x in q(p1, "a:point[2]/a:point")] == ["a)", "b)"]
    assert q(p1, "string(a:wrapUp/a:p)").startswith("Für nichtöffentliche Stellen")
    assert [c.tag.split("}")[1] for c in p1][:3] == ["num", "intro", "point"]


def test_numbering_and_headings_match_model(model, result, root):
    idx = model.by_id()
    for t in result.entries:
        el = idx[t.model_id]
        if t.num_eId:
            assert q(root, f"string(//*[@eId='{t.num_eId}'])") == el.marker
        if t.heading_eId:
            assert q(root, f"string(//*[@eId='{t.heading_eId}'])") == el.title


# ---- eIds ----------------------------------------------------------------------------------------
def test_eids_unique_and_stable(model, result, root):
    eids = [e.get("eId") for e in root.iter() if isinstance(e.tag, str) and e.get("eId")]
    assert len(eids) == len(set(eids))
    assert "part_1__chp_1__art_1__para_1__point_2__point_a" in eids
    assert "part_1__chp_1__art_2__para_3__point_1" in eids
    again = generate_excerpt(model, ["1", "2"], DATE)
    assert [e.eId for e in again.entries] == [e.eId for e in result.entries]
    assert {e.eId for e in result.entries if e.eId} <= set(eids)


def test_repeated_numbers_get_distinct_eids(model):
    r = generate_excerpt(model, ["4"], DATE)  # § 4 (1) contains two separate 1.-2. lists
    eids = [e.get("eId") for e in etree.fromstring(r.xml).iter() if isinstance(e.tag, str) and e.get("eId")]  # fmt: skip
    assert len(eids) == len(set(eids))
    assert validate_xml(r.xml).valid


# ---- text preservation ---------------------------------------------------------------------------
def test_text_matches_model_content_and_order(model, result):
    t = verify_text(model, result)
    assert t["same_order_and_text"] and t["text_mismatches"] == []
    assert t["original_text_reconstruction_diffs"] == []
    assert t["atoms_in_xml"] == t["atoms_expected"] > 50


def test_every_included_element_text_is_verbatim(model, result, root):
    idx = model.by_id()
    for t in result.entries:
        el = idx[t.model_id]
        if t.model_type == "docTitle" or not t.text_eId or t.role == "container_shell":
            continue
        assert q(root, f"string(//*[@eId='{t.text_eId}'])") == el.content_text, el.id


def test_special_characters_roundtrip(result):
    text = result.xml.decode("utf-8")
    for ch in "§äöüß":
        assert ch in text
    non_ascii = {c for c in text if ord(c) > 127}
    assert non_ascii >= set("§äöüß")
    assert "&#" not in text  # written as real UTF-8, not character references


def _synthetic_model(items):
    info = SourceInfo(docling_json_sha256="0" * 64, num_pages=1)
    m = parse_items(info, items, GERMAN_LAW_RULES)
    m.metadata.ausfertigungsdatum = "01.01.2020"
    m.metadata.short_title = "TST"
    return m


def _it(i, label, text, marker=None, enumerated=None, table=None):
    return SourceItem(
        ref=f"#/texts/{i}", label=label, layer="body", orig=f"{marker} {text}" if marker else text,
        text=text, marker=marker, enumerated=enumerated, table=table,
        provenance=[Provenance(page_no=1)],
    )  # fmt: skip


def test_xml_escaping_and_illegal_characters():
    m = _synthetic_model([_it(0, "section_header", "§ 1 A & B <C>"), _it(1, "text", '(1) „Zitat“ & "x" <y> ß')])  # fmt: skip
    r = generate_excerpt(m, ["1"], DATE)
    root = etree.fromstring(r.xml)
    assert q(root, "string(//a:heading)") == "A & B <C>"
    assert q(root, "string(//a:paragraph/a:content/a:p)") == '„Zitat“ & "x" <y> ß'
    assert validate_xml(r.xml).valid
    bad = _synthetic_model([_it(0, "section_header", "§ 1 T"), _it(1, "text", "(1) a\x0cb")])
    with pytest.raises(ValueError, match="illegal in XML"):
        generate_excerpt(bad, ["1"], DATE)  # never silently stripped


def test_tables_and_footnotes_validate():
    table = TableData(num_rows=2, num_cols=2, rows=[["A", "B"], ["1", ""]])
    m = _synthetic_model([
        _it(0, "section_header", "§ 1 Titel"), _it(1, "text", "(1) Satz."),
        SourceItem(ref="#/tables/0", label="table", layer="body", orig="", text="", table=table,
                   provenance=[Provenance(page_no=1)]),
        _it(2, "section_header", "Fußnote"), _it(3, "text", "(+++ Hinweis +++)"),
    ])  # fmt: skip
    r = generate_excerpt(m, ["1"], DATE)
    v = validate_xml(r.xml)
    assert v.valid, [e.message for e in v.errors]
    root = etree.fromstring(r.xml)
    assert [q(td, "string(a:p)") for td in q(root, "//a:table//a:td")] == ["A", "B", "1", ""]
    assert q(root, "string(//a:notes/a:note/a:p)") == "(+++ Hinweis +++)"
    assert verify_text(m, r)["same_order_and_text"]


def test_text_before_enumeration_in_paragraph_without_absatz():
    m = _synthetic_model([
        _it(0, "section_header", "§ 1 Begriffe"), _it(1, "text", "Es bezeichnen die Begriffe:"),
        _it(2, "list_item", "Eins", "1.", True), _it(3, "list_item", "Zwei", "2.", True),
    ])  # fmt: skip
    r = generate_excerpt(m, ["1"], DATE)
    assert validate_xml(r.xml).valid and not r.unmapped
    assert verify_text(m, r)["same_order_and_text"]


# ---- uncertainty ------------------------------------------------------------------------------------
def test_uncertain_elements_are_kept_flagged_and_in_place(model, result, root):
    uncertain = [e for e in model.elements if e.uncertain and e.id in set(result.included_ids)]
    assert len(uncertain) == 3
    flagged = q(root, "//*[@odos:uncertain]")
    assert len(flagged) == 3
    for node in flagged:
        assert node.tag == f"{{{AKN_NS}}}p" and node.getparent().tag == f"{{{AKN_NS}}}wrapUp"
        assert node.get(f"{{{ODOS_NS}}}uncertain") == "text_after_list_attached_to_enclosing_container"
    assert {w["model_id"] for w in result.warnings if w["code"] == "UNCERTAIN_ELEMENT_INCLUDED"} == {e.id for e in uncertain}  # fmt: skip
    for e in uncertain:  # text is not altered
        t = next(x for x in result.entries if x.model_id == e.id)
        assert q(root, f"string(//*[@eId='{t.text_eId}'])") == e.content_text
    assert not result.unmapped


# ---- traceability -------------------------------------------------------------------------------------
def test_traceability_to_docling_and_pdf(model, result, root, raw_json):
    raw = json.loads(raw_json.read_text())
    for t in result.entries:
        assert t.source_refs and t.pages and t.provenance
        _, kind, i = t.source_refs[0].split("/")
        node = raw[kind][int(i)]
        assert t.pages[0] == node["prov"][0]["page_no"]
        assert t.provenance[0]["bbox"]["l"] == node["prov"][0]["bbox"]["l"]
        xml_node = q(root, f"//*[@eId='{t.eId}']")[0]
        assert xml_node.get(f"{{{ODOS_NS}}}src").split() == t.source_refs
    assert all(p >= 5 for t in result.entries if t.akn_element != "docTitle" for p in t.pages)


def test_every_body_node_with_content_is_traced(result, root):
    traced = {x for e in result.entries for x in (e.eId, e.num_eId, e.heading_eId, e.text_eId) if x}
    nodes = q(root, "//a:body//*[@odos:src]")
    assert nodes and all(el.get("eId") in traced for el in nodes)


# ---- excerpt accounting ----------------------------------------------------------------------------------
def test_excluded_content_is_accounted_for(model, result, root):
    all_ids = {e.id for e in [*model.elements, *model.furniture]}
    inc, exc = set(result.included_ids), {i for v in result.excluded.values() for i in v}
    assert inc.isdisjoint(exc) and inc | exc == all_ids
    assert {"doc/front-1", "doc/teil-1", "doc/teil-1/kapitel-1"} <= inc  # title + the two container shells
    assert not any(i.startswith("doc/teil-1/kapitel-1/par-3") for i in inc)
    assert result.excluded["page_furniture"] and result.excluded["table_of_contents"]
    assert len(result.excluded["front_matter"]) == sum(e.region == "front" for e in model.elements) - 1  # all but the title
    assert q(root, "string(//odos:excerpt/@complete)") == "false"
    assert q(root, "string(//odos:excerpt/@included-paragraphs)") == "1 2"
    assert result.excerpt["complete"] is False and result.excerpt["paragraphs_in_model"] == 86
    assert not [n for n in q(root, "//a:article/a:num") if n.text not in ("§ 1", "§ 2")]
    assert "NOT the complete" in result.xml.decode()
    with pytest.raises(ValueError):
        generate_excerpt(model, ["9999"], DATE)


def test_work_date_comes_from_source_not_invented(model, result, root):
    assert q(root, "string(//a:FRBRWork/a:FRBRdate/@date)") == "2017-06-30"
    assert q(root, "string(//a:FRBRWork/a:FRBRauthor/@href)") == "#unspecified"
    assert retrieval_date_from_source() == "2026-10-27"
    no_date = model.model_copy(deep=True)
    no_date.metadata.ausfertigungsdatum = None
    with pytest.raises(ValueError):
        generate_excerpt(no_date, ["1"], DATE)


# ---- determinism and artifacts --------------------------------------------------------------------------------
def test_deterministic_output(model, result, tmp_path):
    assert generate_excerpt(model, ["1", "2"], DATE).xml == result.xml
    a = build_artifacts(model, ["1", "2"], DATE, tmp_path / "a")
    b = build_artifacts(model, ["1", "2"], DATE, tmp_path / "b")
    for name in ("bdsg_excerpt.xml", "akn_validation_report.json", "akn_traceability.json"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), name
    rep = json.loads((tmp_path / "a" / "akn_validation_report.json").read_text(encoding="utf-8"))
    assert rep["valid"] is True and rep["errors"] == [] and rep["text_preservation"]["same_order_and_text"]
    assert rep["schema_version"] and rep["validator"]["libxml2"]
    assert a["validation"].xml_sha256 == rep["xml_sha256"]
