"""Akoma Ntoso generation for EU legislation, on the real Regulation (EU) 2023/1230."""

import json
import re

import pytest
from lxml import etree

from odos.akn.eu_artifacts import build_eu_akn_artifacts, text_preservation
from odos.akn.eu_generator import generate_eu_akn
from odos.akn.mapping import AKN_NS, ODOS_NS
from odos.akn.validate import validate_xml
from odos.normalization.docling_reader import read_docling_json
from odos.document_model import ElementType as T

NS = {"a": AKN_NS, "odos": ODOS_NS}
DATE = "2026-10-27"


@pytest.fixture(scope="module")
def gen(eu_model):
    return generate_eu_akn(eu_model, DATE)


@pytest.fixture(scope="module")
def root(gen):
    return etree.fromstring(gen.xml)


def q(node, path):
    return node.xpath(path, namespaces=NS)


# ---- official XSD ----------------------------------------------------------------------------------------------
def test_valid_against_official_xsd(gen):
    v = validate_xml(gen.xml)
    assert v.well_formed and v.valid and v.errors == [], [e.message for e in v.errors[:5]]


def test_validator_still_rejects_broken_documents(gen):
    assert not validate_xml(gen.xml.replace(b"<recital ", b"<bogus/><recital ", 1)).valid
    dup = gen.xml.replace(b'eId="chp_1__art_2"', b'eId="chp_1__art_1"', 1)
    assert not validate_xml(dup).valid


# ---- structure and counts ----------------------------------------------------------------------------------------
def test_document_type_and_counts(root):
    act = q(root, "/a:akomaNtoso/a:act")[0]
    assert act.get("name") == "regulation"
    assert len(q(act, "a:preamble/a:recitals/a:recital")) == 86
    assert len(q(act, "a:body/a:chapter")) == 9
    assert len(q(act, "a:body/a:chapter/a:article")) == 54
    assert len(q(act, "a:attachments/a:attachment/a:doc[@name='annex']")) == 12
    assert len(q(act, "a:preamble/a:citations/a:citation")) == 5
    assert [f.get("name") for f in q(act, "a:preamble/a:formula")] == ["openingFormula", "enactingFormula"]
    assert [f.get("name") for f in q(act, "a:conclusions/a:formula")] == ["finalFormula", "doneAt"]
    assert q(act, "a:conclusions/a:container[@name='signatures']/a:table")


def test_order_of_main_parts(root):
    act = q(root, "/a:akomaNtoso/a:act")[0]
    assert [etree.QName(c).localname for c in act] == ["meta", "preface", "preamble", "body", "conclusions", "attachments"]
    assert [q(r, "string(a:num)") for r in q(act, "a:preamble/a:recitals/a:recital")] == [f"({i})" for i in range(1, 87)]
    assert [q(a, "string(a:num)") for a in q(act, "a:body//a:article")] == [f"Artikel {i}" for i in range(1, 55)]
    assert [q(a, "string(a:num)") for a in q(act, "a:attachments/a:attachment")][-1] == "ANHANG XII"


def test_article_paragraph_point_hierarchy(root):
    art2 = q(root, "//a:article[@eId='chp_1__art_2']")[0]
    p2 = q(art2, "a:paragraph[@eId='chp_1__art_2__para_2']")[0]
    assert [q(x, "string(a:num)") for x in q(p2, "a:point")] == [f"{c})" for c in "abcdefghijklmnopq"]
    assert [q(x, "string(a:num)") for x in q(p2, "a:point[a:num='p)']/a:point")] == ["i)", "ii)", "iii)", "iv)", "v)", "vi)"]
    art11 = q(root, "//a:article[@eId='chp_2__art_11']")[0]
    assert [q(x, "string(a:num)") for x in q(art11, "a:paragraph")] == [f"({i})" for i in range(1, 11)]
    art3 = q(root, "//a:article[@eId='chp_1__art_3']")[0]
    assert len(q(art3, "a:point")) == 36 and q(art3, "string(a:intro/a:p)").startswith("Für die Zwecke dieser Verordnung")


def test_annex_structure(root):
    a3 = q(root, "//a:attachment[@eId='att_3']")[0]
    assert q(a3, "string(a:num)") == "ANHANG III"
    assert [q(p, "string(a:num)") for p in q(a3, "a:doc/a:mainBody/a:part")] == ["TEIL A", "TEIL B"]
    lvl = q(a3, ".//a:level[@eId='att_3__part_b__lvl_1__lvl_1.2__lvl_1.2.4__lvl_1.2.4.1']")[0]
    assert q(lvl, "string(a:num)") == "1.2.4.1." and q(lvl, "string(a:heading)").startswith("N o r m a l e s")  # verbatim
    assert q(a3, "a:doc/a:meta/a:identification/a:FRBRWork/a:FRBRthis/@value")[0].endswith("/!annex_3")
    a12 = q(root, "//a:attachment[@eId='att_12']")[0]
    assert len(q(a12, "a:doc/a:mainBody/a:table")) == 2


# ---- metadata ----------------------------------------------------------------------------------------------------
def test_authentic_metadata(root, eu_model):
    md = eu_model.metadata
    w = q(root, "/a:akomaNtoso/a:act/a:meta/a:identification/a:FRBRWork")[0]
    assert q(w, "string(a:FRBRdate/@date)") == md.adoption_date == "2023-06-14" and q(w, "string(a:FRBRdate/@name)") == "adoption"
    assert q(w, "string(a:FRBRnumber/@value)") == "2023/1230" and q(w, "string(a:FRBRcountry/@value)") == "eu"
    e = q(root, "/a:akomaNtoso/a:act/a:meta/a:identification/a:FRBRExpression")[0]
    assert q(e, "string(a:FRBRdate/@date)") == "2023-06-29" and q(e, "string(a:FRBRdate/@name)") == "publication"
    pub = q(root, "/a:akomaNtoso/a:act/a:meta/a:publication")[0]
    assert (pub.get("number"), pub.get("date"), pub.get("showAs")) == ("L 165/1", "2023-06-29", "Amtsblatt der Europäischen Union")
    assert q(root, "string(//a:TLCOrganization[@eId='issuingBodies']/@showAs)") == "DES EUROPÄISCHEN PARLAMENTS UND DES RATES"
    assert q(root, "string(//a:preface//a:docDate/@date)") == "2023-06-14"
    assert q(root, "string(//a:preface//a:docDate)") == "vom 14. Juni 2023"
    assert q(root, "//odos:identifiers[@derived]")  # derived URIs are declared as such
    assert b"eli/" not in gen_xml(eu_model) and b"CELEX" not in gen_xml(eu_model)  # nothing not printed in the PDF


def gen_xml(m):
    return generate_eu_akn(m, DATE).xml


def test_refuses_without_authentic_metadata(eu_model):
    broken = eu_model.model_copy(deep=True)
    broken.metadata.adoption_date = None
    with pytest.raises(ValueError, match="refusing to invent"):
        generate_eu_akn(broken, DATE)


# ---- text, order, ids, provenance -------------------------------------------------------------------------------------
def test_exact_text_and_order(eu_model, gen):
    t = text_preservation(eu_model, gen)
    assert t["same_order_and_text"] and t["text_mismatches"] == [] and t["original_text_reconstruction_diffs"] == []
    assert t["document_order_preserved"] and t["atoms_in_xml"] == t["atoms_expected"] == 2927  # 2926 - the repaired-away stray item + the nums of Annex III 3.6.2 paragraphs (1), (2)
    assert t["note_atoms_expected"] == 26
    assert t["elements_not_in_xml"] == {"document_root": 1, "page_furniture": 404, "unmapped": 0} and not gen.unmapped
    assert t["counts"] == {"recitals": 86, "chapters": 9, "articles": 54, "annexes": 12}


def test_every_model_element_is_in_the_xml(eu_model, gen):
    inc = set(gen.included_ids)
    missing = [e.id for e in eu_model.elements if e.id not in inc and e.type != T.DOCUMENT]
    assert missing == []


def test_eids_unique_and_deterministic(eu_model, gen, root):
    eids = [n.get("eId") for n in root.iter() if isinstance(n.tag, str) and n.get("eId")]
    assert len(eids) == len(set(eids))
    again = generate_eu_akn(eu_model, DATE)
    assert again.xml == gen.xml


def test_xml_nodes_point_to_docling_items_and_spans(eu_model, gen, root, eu_raw_json):
    _, items = read_docling_json(eu_raw_json)
    src = {i.ref: i for i in items}
    for entry in gen.entries:
        node = q(root, f"//*[@eId='{entry.eId}']")
        assert node, entry.model_id
        if entry.source_refs:
            assert node[0].get(f"{{{ODOS_NS}}}src") is not None or entry.akn_element in ("docTitle", "docDate")
    spans = q(root, "//*[@odos:span]")
    assert len(spans) >= 22
    for n in spans:
        for tok in n.get(f"{{{ODOS_NS}}}span").split():
            ref, rng = tok.split("@")
            s, e = map(int, rng.split("-"))
            assert ref in src and 0 <= s < e <= len(src[ref].orig)
    para3 = q(root, "//a:paragraph[@eId='chp_2__art_11__para_3']")[0]
    assert para3.get(f"{{{ODOS_NS}}}span") == "#/texts/373@659-1280"
    seg = next(e for e in gen.entries if e.model_id == "doc/chp-2/art-11/para-3")
    assert seg.source_spans[0]["start"] == 659 and seg.source_spans[0]["bbox_scope"] == "docling_item"


def test_uncertainty_is_carried_into_xml_and_traceability(eu_model, gen, root):
    uncertain = {e.id for e in eu_model.elements if e.uncertain}
    traced = {e.model_id for e in gen.entries if e.uncertain}
    assert traced == uncertain and len(uncertain) == 3  # Art. 47(1)-(3): overlapping layout boxes, repaired for review
    assert len(q(root, "//*[@odos:uncertain]")) >= 3
    assert "reading_order_uncertain" in q(root, "string(//a:paragraph[@eId='chp_7__art_47__para_3']/@odos:uncertain)")
    assert q(root, "string(//a:point[@eId='chp_1__art_2__para_2__point_i']/@odos:uncertain)") == ""  # decided by layout
    assert "layout_box_overlaps_other_item" in q(root, "string(//a:paragraph[@eId='chp_7__art_47__para_1']/@odos:uncertain)")


def test_footnotes_anchored(root):
    notes = q(root, "/a:akomaNtoso/a:act/a:meta/a:notes/a:note")
    assert len(notes) == 26
    eids = {n.get("eId") for n in root.iter() if isinstance(n.tag, str) and n.get("eId")}
    for n in notes:
        assert n.get(f"{{{ODOS_NS}}}anchor") in eids
        assert re.match(r"^\( \d+ \)", q(n, "string(a:p)"))
    assert q(root, "string(//a:note[@odos:anchor='preamble__recs__rec_1']/a:p)").startswith("( 3 ) Richtlinie 2006/42/EG")


def test_artifacts_written(eu_model, tmp_path):
    art = build_eu_akn_artifacts(eu_model, DATE, tmp_path)
    assert art["validation"].valid
    for name in ("document_akn.xml", "akn_validation_report.json", "akn_traceability.json", "akn_text_preservation.json"):
        assert (tmp_path / name).stat().st_size > 0
    rep = json.loads((tmp_path / "akn_validation_report.json").read_text(encoding="utf-8"))
    assert rep["valid"] is True and rep["errors"] == [] and rep["profile"] == "eu_legislation"
    assert rep["text_preservation_summary"]["same_order_and_text"] is True
    tr = json.loads((tmp_path / "akn_traceability.json").read_text(encoding="utf-8"))
    assert tr["excluded_counts"]["unmapped"] == 0 and len(tr["uncertain"]) == 3
    again = tmp_path / "again"
    build_eu_akn_artifacts(eu_model, DATE, again)
    for name in ("document_akn.xml", "akn_traceability.json", "akn_text_preservation.json"):
        assert (tmp_path / name).read_bytes() == (again / name).read_bytes()
