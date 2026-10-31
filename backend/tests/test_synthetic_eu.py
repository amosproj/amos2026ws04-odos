"""The EU profile end to end on the synthetic regulation (tests/synthetic_eu.py): always runs, needs no private file.

Parsing through the shared lifecycle, metadata, every EU structural unit, footnote anchoring, page furniture,
sentences, document.json 1.1 (schema, nesting, text) with its 1.0 downgrade, and Akoma Ntoso (XSD, text, order)."""

import json

from odos.akn.eu_artifacts import build_eu_akn_artifacts
from odos.legal_json.artifacts import build_legal_json_artifacts
from odos.parsing import engine
from odos.document_model import ElementType as T
from odos.parsing.profiles import EU_LEGISLATION


def test_parsed_through_the_shared_lifecycle(synthetic_eu_raw_json, synthetic_eu_model):
    trace: list[str] = []
    m = engine.parse(synthetic_eu_raw_json, EU_LEGISLATION, trace)
    assert trace == [name for name, _ in engine.STAGES]
    assert m.model_dump_json() == synthetic_eu_model.model_dump_json()  # deterministic
    assert m.profile == "eu_legislation" and not m.warnings and not any(e.uncertain for e in m.elements)


def test_metadata_is_read_from_the_printed_front_matter(synthetic_eu_model):
    md = synthetic_eu_model.metadata
    assert (md.document_type, md.document_number, md.adoption_date, md.subject) == (
        "VERORDNUNG", "2099/1", "2099-01-01", "über synthetische Prüfmaschinen")  # fmt: skip
    assert (md.publication_reference, md.publication_date, md.eea_relevance) == ("L 1/1", "2099-01-01", True)


def test_every_eu_unit_is_recognised(synthetic_eu_model):
    idx = synthetic_eu_model.by_id()
    expected = {
        "doc/preamble/citation-2": T.CITATION, "doc/preamble/rec-2": T.RECITAL, "doc/preamble/enacting-formula": T.ENACTING_FORMULA,
        "doc/chp-1/art-1": T.ARTICLE, "doc/chp-1/art-2/pt-b": T.POINT, "doc/chp-2/sec-1": T.SECTION,
        "doc/chp-2/sec-1/art-3/para-2": T.ARTICLE_PARAGRAPH, "doc/conclusions/signature-1": T.SIGNATURE,
        "doc/annex-1/part-a": T.ANNEX_PART, "doc/annex-1/part-a/h-1/h-1.2": T.ANNEX_HEADING,
    }  # fmt: skip
    assert {i: idx[i].type for i in expected} == expected
    assert (idx["doc/chp-2"].number, idx["doc/chp-2"].title) == ("II", "PFLICHTEN")  # printed numbers are kept


def test_footnote_and_page_furniture(synthetic_eu_model):
    idx = synthetic_eu_model.by_id()
    fn = idx["doc/preamble/citation-2/fn-1"]  # anchored to the citation that prints "( 1 )"
    assert fn.type == T.FOOTNOTE and fn.parent_id == "doc/preamble/citation-2"
    furniture = synthetic_eu_model.furniture
    assert len(furniture) == 12 and all(f.region == "furniture" for f in furniture)
    leaked = [f for f in furniture if "furniture_labelled_as_body_by_docling" in f.hygiene_flags]
    assert [f.original_text for f in leaked] == ["DE", "DE", "DE"]  # the running "DE" Docling labelled as body text


def test_sentences(synthetic_eu_model):
    assert [s.id for s in synthetic_eu_model.sentences] == [
        "doc/preamble/rec-1/s1", "doc/preamble/rec-2/s1", "doc/preamble/rec-2/s2", "doc/chp-1/art-1/s1",
        "doc/chp-1/art-2/s1", "doc/chp-2/sec-1/art-3/para-1/s1", "doc/chp-2/sec-1/art-3/para-2/s1",
        "doc/chp-2/sec-1/art-3/para-2/s2",
    ]  # fmt: skip


def test_legal_json_1_1_and_its_1_0_downgrade(synthetic_eu_model, synthetic_eu_raw_json, tmp_path):
    rep = build_legal_json_artifacts(synthetic_eu_model, synthetic_eu_raw_json, tmp_path)["report"]
    assert rep["valid"] and rep["schema_valid"] and rep["structure_valid"] and rep["downgrade_to_1_0_valid"]
    assert rep["text_preservation"]["identical_to_model"]
    doc = json.loads((tmp_path / "document.json").read_text())
    assert (doc["schemaVersion"], doc["legalSystem"], doc["documentType"], doc["id"]) == ("1.1", "eu", "eu_regulation", "verordnung-2099-1")
    assert rep["downgrade_to_1_0_information_loss"]["dropped"]["sentences"]["values"] == 8


def test_akoma_ntoso_is_valid_and_complete(synthetic_eu_model, tmp_path):
    art = build_eu_akn_artifacts(synthetic_eu_model, "2099-01-02", tmp_path)
    assert art["validation"].valid, art["validation"].errors
    assert art["text"]["same_order_and_text"] and art["text"]["document_order_preserved"] and not art["text"]["unmapped"]
