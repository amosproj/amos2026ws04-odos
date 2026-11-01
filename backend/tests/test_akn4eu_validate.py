"""AKN4EU 5.0.1.0 specification rules (odos.akn.akn4eu_validate) and the export defects they guard against.

Every mandatory rule is tested both ways: the generated package meets it (or reports exactly which input is
missing), and a minimal mutation of that package makes it fail. The synthetic EU regulation always runs;
the full Regulation (EU) 2023/1230 (12 annexes) runs when its PDF is available (see conftest.py).
"""

import json
import re
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from lxml import etree

import odos.pipeline as pl
from odos.akn.akn4eu import AKN4EU_VERSION, generate_akn4eu
from odos.akn.akn4eu_artifacts import STATUS_FAILED, STATUS_OK, build_akn4eu_artifacts, verify_akn4eu
from odos.akn.akn4eu_validate import FAIL, PASS, RULES, TARGET_VERSION, validate_akn4eu
from odos.api.app import create_app
from odos.api.config import Settings
from odos.document_model import Element, ElementType as T
from odos.extraction import ExtractionResult
from odos.pipeline import run_pipeline
from odos.review.model import Correction
from odos.review.service import build_effective_model

BACKEND = Path(__file__).resolve().parents[1]
SAMPLE_OJ = BACKEND / "tests" / "fixtures" / "akn4eu-5.0.1.0-samples" / "OJ-L-202500864" / "AKN4EU" / "en"
NS = {"a": "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"}
DATE = "2026-10-29"
ELI = "http://data.europa.eu/eli/reg/2099/1/oj"  # the synthetic regulation (EU) 2099/1, OJ L 1/1 of 1.1.2099
OJ_URI = "http://publications.europa.eu/resource/oj/JOL_2099_1_R_0001"
MUSTS = {r for r, (_, level, _, _) in RULES.items() if level == "MUST"}


def statuses(report: dict) -> dict:
    return {x["rule"]: x["status"] for x in report["rules"]}


def check(files, model=None, result=None):
    text = verify_akn4eu(model, result) if model is not None and result is not None else None
    return validate_akn4eu(files, model, result, text)


@pytest.fixture(scope="module")
def full(synthetic_eu_model):
    """The synthetic act exported with its (checked) ELI and OJ URI: every identifier is known."""
    return generate_akn4eu(synthetic_eu_model, DATE, eli=ELI, oj_uri=OJ_URI)


@pytest.fixture(scope="module")
def bare(synthetic_eu_model):
    """The same act without ELI and OJ URI: what the PDF alone provides."""
    return generate_akn4eu(synthetic_eu_model, DATE)


# ==== positive: what is met, and what is reported as missing instead of invented ========================================
def test_package_structure_of_a_published_regulation(full):
    names = list(full.files)
    assert names == ["main-OJ_JOL_2099_1_R_0001-de.xml", "act-eli_reg_2099_1-de.xml", "ANNEX-eli_reg_2099_1_anx-de.xml"]
    main = etree.fromstring(full.files[full.main_file])
    assert main.xpath("string(/a:akomaNtoso/a:officialGazette/@name)", namespaces=NS) == "OJ-L"
    assert main.xpath("/a:akomaNtoso/a:officialGazette/a:collectionBody/a:component/a:documentRef/@href", namespaces=NS) == [full.act_file]  # fmt: skip
    act = etree.fromstring(full.files[full.act_file])
    assert act.xpath("string(/a:akomaNtoso/a:act/@name)", namespaces=NS) == "REG"
    assert act.xpath("string(//a:akn4euVersion/@value)", namespaces={"a": "http://imfc.europa.eu/akn4eu"}) == AKN4EU_VERSION == TARGET_VERSION == "5.0.1.0"  # fmt: skip


def test_complete_identifiers_meet_every_mandatory_rule(synthetic_eu_model, full):
    rep = check(full.files, synthetic_eu_model, full)
    st = statuses(rep)
    assert rep["passed"] and rep["failed"] == [], [x for x in rep["rules"] if x["status"] == FAIL]
    assert rep["missing_input"] == ["FRBR_SUBTYPE"]  # the procedure (TLCProcess) is not determined from the source
    assert rep["deviations"] == ["META_SOURCE"]  # ODOS is not an EU body and is not presented as one
    assert {r for r in MUSTS if st[r] == PASS} == MUSTS - {"FRBR_SUBTYPE", "META_SOURCE"}
    assert not rep["complete"] and rep["verdict"].startswith("NOT conformant")


def test_without_identifiers_nothing_is_invented_and_the_gap_is_reported(synthetic_eu_model, bare):
    assert all(b"data.europa.eu/eli" not in x and b"resource/oj/" not in x for x in bare.files.values())
    assert list(bare.files) == ["main-OJ_L_2099_1-de.xml", "act-reg_2099_1-de.xml", "ANNEX-reg_2099_1_anx_1-de.xml"]
    rep = check(bare.files, synthetic_eu_model, bare)
    assert rep["passed"] and set(rep["missing_input"]) == {"FILENAME_IDENTIFIER", "FRBR_SUBTYPE", "FRBR_NUMBER_OJ", "OJ_URI"}
    assert {w["code"] for w in bare.warnings} >= {"NO_ELI", "NO_OJ_URI"}


def test_supplied_oj_uri_is_checked_never_derived(synthetic_eu_model):
    for wrong in ("http://publications.europa.eu/resource/oj/JOL_2099_2_R_0001",  # other issue
                  "http://publications.europa.eu/resource/oj/JOL_2098_1_R_0001",  # other year
                  "http://publications.europa.eu/resource/oj/JOC_2099_1_R_0001",  # other series
                  "http://publications.europa.eu/resource/oj/L_209900001"):  # ABA form: not this publication  # fmt: skip
        with pytest.raises(ValueError, match="OJ URI"):
            generate_akn4eu(synthetic_eu_model, DATE, oj_uri=wrong)


def test_regulation_2023_1230_keeps_all_12_annexes_referenced(eu_model):
    r = generate_akn4eu(eu_model, DATE, eli="http://data.europa.eu/eli/reg/2023/1230/oj")
    annexes = [n for n in r.files if n.startswith("ANNEX-")]
    assert annexes == [f"ANNEX-eli_reg_2023_1230_anx_{i}-de.xml" for i in range(1, 13)] and r.act_file == "act-eli_reg_2023_1230-de.xml"
    act = etree.fromstring(r.files[r.act_file])
    assert act.xpath("//a:attachments/a:attachment/a:documentRef/@href", namespaces=NS) == annexes
    assert [etree.fromstring(r.files[n]).findtext(".//{*}annex/{*}num") for n in annexes] == [e.marker for e in eu_model.of_type(T.ANNEX)]
    rep = check(r.files, eu_model, r)
    st = statuses(rep)
    assert rep["failed"] == [], [x for x in rep["rules"] if x["status"] == FAIL]
    assert all(st[k] == PASS for k in ("ATTACHMENTS", "PKG_REFERENCES", "MODEL_ANNEXES", "MODEL_COMPLETE", "MODEL_TEXT_ORDER", "MODEL_ACT_TYPE", "DOC_TYPE_ACT"))  # fmt: skip
    # each of the 12 annexes would need its own ELI, and the OJ URI is not printed: reported, not invented
    assert set(rep["missing_input"]) == {"FILENAME_IDENTIFIER", "FRBR_SUBTYPE", "FRBR_NUMBER_OJ", "OJ_URI"}
    assert set(rep["deviations"]) == {"META_SOURCE", "ACT_STRUCTURE"}  # coverPage: the OJ headings printed above the title


def test_official_oj_package_meets_the_package_rules():
    """The rules are the specification's, not ODOS's: the official OJ package of 2025/864 meets the package and
    identification rules, and fails exactly where the 5.0.0.1 sample differs from the 5.0.1.0 text."""
    rep = validate_akn4eu({f.name: f.read_bytes() for f in sorted(SAMPLE_OJ.glob("*.xml"))})
    st = statuses(rep)
    for rule in ("XML_WELL_FORMED", "AKN_3_1_XSD", "PKG_MAIN_FILE", "PKG_MAIN_COVERPAGE", "PKG_REFERENCES", "FILENAME_PREFIX",
                 "FILENAME_LANGUAGE", "FILENAME_IDENTIFIER", "OJ_GAZETTE", "OJ_GAZETTE_STRUCTURE", "OJ_GAZETTE_META",
                 "OJ_COVERPAGE_REFERENCE", "DOC_TYPE_ACT", "DOC_ANNEX", "META_SOURCE", "FRBR_NUMBER_OJ", "FRBR_SUBTYPE",
                 "FRBR_LANGUAGE", "OJ_DATES", "OJ_AUTHOR", "OJ_PUBLICATION", "AKN4EU_DOCUMENTATION"):  # fmt: skip
        assert st[rule] == PASS, (rule, next(x["findings"] for x in rep["rules"] if x["rule"] == rule))
    assert {"AKN4EU_VERSION", "ELI_EIDS", "ATTACHMENTS"} <= set(rep["failed"])  # 5.0.0.1, body "ent_1", showAs "ANNEX"


# ==== negative: each mandatory rule fails on a minimal mutation ============================================================
def edit(files: dict, prefix: str, old: bytes, new: bytes) -> dict:
    name = next(n for n in files if n.startswith(prefix))
    assert old in files[name], (name, old)
    return {**files, name: files[name].replace(old, new, 1)}


def rename(files: dict, prefix: str, new: str) -> dict:
    old = next(n for n in files if n.startswith(prefix))
    return {(new if n == old else n): x.replace(old.encode(), new.encode()) for n, x in files.items()}


def drop(files: dict, prefix: str) -> dict:
    return {n: x for n, x in files.items() if not n.startswith(prefix)}


def cut(files: dict, prefix: str, pattern: bytes) -> dict:
    name = next(n for n in files if n.startswith(prefix))
    new, n = re.subn(pattern, b"", files[name], count=1, flags=re.S)
    assert n == 1, (name, pattern)
    return {**files, name: new}


MUTATIONS = [
    ("XML_WELL_FORMED", lambda f: {**f, "act-eli_reg_2099_1-de.xml": f["act-eli_reg_2099_1-de.xml"][:-40]}),
    ("AKN_ROOT", lambda f: {**f, "act-eli_reg_2099_1-de.xml": b'<akomaNtoso xmlns="http://docs.oasis-open.org/legaldocml/ns/akn/3.0"/>'}),
    ("AKN_3_1_XSD", lambda f: edit(f, "act-", b"<recitals ", b"<bogus/><recitals ")),
    ("PKG_MAIN_FILE", lambda f: drop(f, "main-")),
    ("PKG_MAIN_FILE", lambda f: {**f, "main-copy-de.xml": f["main-OJ_JOL_2099_1_R_0001-de.xml"]}),
    ("PKG_MAIN_COVERPAGE", lambda f: cut(f, "main-", rb"<coverPage .*?</coverPage>")),
    ("PKG_FLAT", lambda f: rename(f, "ANNEX-", "annexes/ANNEX-eli_reg_2099_1_anx-de.xml")),
    ("PKG_REFERENCES", lambda f: {**f, "ANNEX-eli_reg_2099_1_anx_9-de.xml": f["ANNEX-eli_reg_2099_1_anx-de.xml"]}),
    ("PKG_REFERENCES", lambda f: edit(f, "act-", b'href="ANNEX-eli_reg_2099_1_anx-de.xml"', b'href="ANNEX-missing-de.xml"')),
    ("FILENAME_CHARACTERS", lambda f: rename(f, "ANNEX-", "ANNEX-eli_reg_2099_1_anx?-de.xml")),
    ("FILENAME_PREFIX", lambda f: rename(f, "act-", "REG-eli_reg_2099_1-de.xml")),
    ("FILENAME_LANGUAGE", lambda f: rename(f, "act-", "act-eli_reg_2099_1-en.xml")),
    ("FILENAME_IDENTIFIER", lambda f: rename(f, "act-", "act-eli_reg_2099_2-de.xml")),
    ("OJ_GAZETTE", lambda f: edit(f, "main-", b'<officialGazette name="OJ-L">', b'<officialGazette name="OJ-Z">')),
    ("OJ_GAZETTE", lambda f: rename(drop(f, "main-"), "act-", "main-eli_reg_2099_1-de.xml")),  # the act itself as main
    ("OJ_GAZETTE_STRUCTURE", lambda f: edit(f, "main-", b"</collectionBody>", b'<component><documentRef href="act-eli_reg_2099_1-de.xml" showAs=""/></component></collectionBody>')),  # fmt: skip
    ("OJ_GAZETTE_STRUCTURE", lambda f: edit(f, "main-", b'href="act-eli_reg_2099_1-de.xml" showAs=""', b'href="act-eli_reg_2099_1-de.xml" showAs="act"')),  # fmt: skip
    ("OJ_GAZETTE_META", lambda f: edit(f, "main-", b'<FRBRauthor href="#EURUN"/>', b'<FRBRauthor href="#ODOS"/>')),
    ("OJ_COVERPAGE_REFERENCE", lambda f: cut(f, "main-", rb'<block name="reference".*?</block>')),
    ("ATTACHMENTS", lambda f: edit(f, "act-", b'href="ANNEX-eli_reg_2099_1_anx-de.xml" showAs=""', b'href="ANNEX-eli_reg_2099_1_anx-de.xml" showAs="ANNEX"')),  # fmt: skip
    ("ATTACHMENTS", lambda f: cut(f, "act-", rb"<attachments>.*?</attachments>")),
    ("DOC_TYPE_ACT", lambda f: edit(f, "act-", b'<act name="REG">', b'<act name="REGULATION">')),
    ("ACT_STRUCTURE", lambda f: cut(f, "act-", rb"<conclusions .*?</conclusions>")),
    ("DOC_ANNEX", lambda f: edit(f, "ANNEX-", b"resource-type/ANNEX", b"resource-type/DOC")),
    ("META_SOURCE", lambda f: edit(f, "act-", b'href="/ontology/organization/odos"', b'href="http://example.org/converter"')),
    ("FRBR_MANDATORY", lambda f: cut(f, "act-", rb'<FRBRuri value="http://data.europa.eu/eli/reg/2099/1/oj/deu"/>')),
    ("FRBR_COUNTRY", lambda f: edit(f, "act-", b'<FRBRcountry value="EU"/>', b'<FRBRcountry value="DE"/>')),
    ("FRBR_SUBTYPE", lambda f: edit(f, "act-", b'<FRBRsubtype value="REG"/>', b'<FRBRsubtype value="DIR"/>')),
    ("FRBR_NUMBER", lambda f: cut(f, "act-", rb"<FRBRnumber [^>]*/>")),
    ("FRBR_NUMBER_OJ", lambda f: edit(f, "act-", b'<FRBRnumber value="eli/reg/2099/1"', b'<FRBRnumber value="eli/reg/2099/2"')),
    ("FRBR_PRESCRIPTIVE", lambda f: edit(f, "act-", b'<FRBRprescriptive value="true"/>', b'<FRBRprescriptive value="false"/>')),
    ("FRBR_PRESCRIPTIVE", lambda f: edit(f, "main-", b'<FRBRcountry value="EU"/>', b'<FRBRcountry value="EU"/><FRBRprescriptive value="true"/>')),  # fmt: skip
    ("FRBR_LANGUAGE", lambda f: edit(f, "act-", b'showAs="de"', b'showAs="xx"')),
    ("FRBR_LANGUAGE", lambda f: edit(f, "act-", b'refersTo="~DEU" xml:id="FRBRlanguage"', b'refersTo="~EU" xml:id="FRBRlanguage"')),
    ("AKN4EU_VERSION", lambda f: edit(f, "act-", b'akn4euVersion value="5.0.1.0"', b'akn4euVersion value="5.0.0.1"')),  # the samples' value
    ("AKN4EU_VERSION", lambda f: cut(f, "act-", rb"<akn4eu:akn4euVersion [^>]*/>")),
    ("AKN4EU_DOCUMENTATION", lambda f: edit(f, "act-", b"resource/dataset/akn4eu", b"resource/dataset/other")),
    ("OJ_URI", lambda f: edit(f, "act-", b'<FRBRthis value="http://data.europa.eu/eli/reg/2099/1/oj"/>', b'<FRBRthis value="http://data.europa.eu/eli/dir/2099/1/oj"/>')),  # fmt: skip
    ("OJ_URI", lambda f: edit(f, "main-", b'<FRBRthis value="http://publications.europa.eu/resource/oj/JOL_2099_1_R_0001"/>', b'<FRBRthis value="http://data.europa.eu/eli/reg/2099/1/oj"/>')),  # fmt: skip
    ("OJ_DATES", lambda f: edit(f, "act-", b'<publication date="2099-01-01"', b'<publication date="2099-01-02"')),
    ("OJ_AUTHOR", lambda f: edit(f, "act-", b'<FRBRauthor href=""/>\n          <preservation', b'<FRBRauthor href="#EP"/>\n          <preservation')),  # fmt: skip
    ("OJ_PUBLICATION", lambda f: cut(f, "ANNEX-", rb"<publication [^>]*/>")),
    ("TLC_AUTHORITY", lambda f: edit(f, "act-", b'corporate-body/EP" showAs=""', b'corporate-body/EP" showAs="Europaeisches Parlament"')),  # fmt: skip
    ("TLC_AUTHORITY", lambda f: edit(f, "act-", b'xml:id="EP" eId="EP"', b'xml:id="EP" eId="PARL"')),
    ("ELI_EIDS", lambda f: edit(f, "act-", b'eId="enc_1"', b'eId="ent_1"')),  # the samples' value
    ("ANNEX_EIDS", lambda f: edit(f, "ANNEX-", b'<mainBody xml:id="mainBody">', b'<mainBody xml:id="mainBody" eId="mainBody">')),
]  # fmt: skip


def test_every_mandatory_package_and_metadata_rule_has_a_negative_test():
    model_rules = {r for r, (layer, *_ ) in RULES.items() if layer == "model"}
    assert {r for r, _ in MUTATIONS} == MUSTS - model_rules


@pytest.mark.parametrize(("rule", "mutation"), MUTATIONS, ids=[f"{r}-{i}" for i, (r, _) in enumerate(MUTATIONS)])
def test_mutation_fails_its_rule(full, rule, mutation):
    assert statuses(check(full.files))[rule] != FAIL  # unmutated: met (META_SOURCE: deviation, FRBR_SUBTYPE: missing input)
    rep = check(mutation(dict(full.files)))
    st = statuses(rep)
    assert st[rule] == FAIL, (rule, st[rule], next(x["findings"] for x in rep["rules"] if x["rule"] == rule))
    assert not rep["passed"] and rule in rep["failed"]


# ==== the model layer and the three defects =================================================================================
def _with_unmapped(model):
    """The model plus one element the AKN4EU mapping has no place for (a TOC entry inside an article)."""
    m = model.model_copy(deep=True)
    art = m.of_type(T.ARTICLE)[0]
    el = Element(id=art.id + "/toc-1", type=T.TOC_ENTRY, region="body", parent_id=art.id, original_text="Inhalt", content_text="Inhalt")
    art.children_ids.append(el.id)
    m.elements.append(el)
    return m, el


def test_defect_2_an_export_with_unmapped_content_is_rejected(synthetic_eu_model, tmp_path):
    m, el = _with_unmapped(synthetic_eu_model)
    art = build_akn4eu_artifacts(m, DATE, tmp_path, eli=ELI, oj_uri=OJ_URI)
    rep = art["report"]
    assert el.id in art["result"].excluded["unmapped"] and art["result"].scope["complete"] is False
    assert not art["ok"] and rep["status"] == STATUS_FAILED
    assert {"model_completeness", "akn4eu_5_0_1_0_rules"} <= set(rep["failing_layers"])
    assert rep["conformance"]["model_completeness"] == {"complete": False, "unmapped": [el.id]}
    assert "MODEL_COMPLETE" in rep["conformance"]["akn4eu_5_0_1_0_rules"]["failed"]
    clean = build_akn4eu_artifacts(synthetic_eu_model, DATE, tmp_path / "ok", eli=ELI, oj_uri=OJ_URI)
    assert clean["ok"] and clean["report"]["status"] == STATUS_OK and clean["result"].scope["complete"] is True


def test_defect_3_the_version_value_and_its_applicability_are_checked(full):
    for value, ok in (("5.0.1.0", True), ("5.0.0.1", False), ("4.1.1.0", False), ("", False)):
        rep = check(edit(dict(full.files), "act-", b'akn4euVersion value="5.0.1.0"', f'akn4euVersion value="{value}"'.encode()))
        assert (statuses(rep)["AKN4EU_VERSION"] == PASS) is ok, value
    from odos.akn.akn4eu_checks import check_document  # the sample-compatibility layer checks the value's form

    assert {f["rule"] for f in check_document(full.files[full.act_file].replace(b'akn4euVersion value="5.0.1.0"', b'akn4euVersion value="latest"'))} == {"AKN4EU_VERSION"}  # fmt: skip


@pytest.mark.parametrize("change", ["text", "type", "publication", "annexes"])
def test_model_layer_detects_disagreement_with_the_model(synthetic_eu_model, full, change):
    m, files, result = synthetic_eu_model, dict(full.files), full
    if change == "text":
        result = full.model_copy(deep=True)
        result.files[result.act_file] = result.files[result.act_file].replace("Gegenstand".encode(), b"Inhalt", 1)
        files, rule = result.files, "MODEL_TEXT_ORDER"
    elif change == "type":
        m = m.model_copy(deep=True)
        m.metadata.document_type, rule = "DURCHFÜHRUNGSVERORDNUNG", "MODEL_ACT_TYPE"
    elif change == "publication":
        m = m.model_copy(deep=True)
        m.metadata.publication_reference, rule = "L 2/1", "MODEL_PUBLICATION"
    else:
        files, rule = cut(files, "act-", rb"<attachments>.*?</attachments>"), "MODEL_ANNEXES"
    assert statuses(validate_akn4eu(files, m, result, verify_akn4eu(m, result)))[rule] == FAIL


def test_review_source_is_checked(synthetic_eu_model, full):
    text = verify_akn4eu(synthetic_eu_model, full)
    st = lambda src: statuses(validate_akn4eu(full.files, synthetic_eu_model, full, text, src))["MODEL_REVIEW"]  # noqa: E731
    assert st({"kind": "original_document_model", "review_corrections": 0}) == PASS
    assert st({"kind": "original_document_model", "review_corrections": 2}) == FAIL  # a review exists, its model was not used
    assert st({"kind": "effective_reviewed_model", "model_revision": 3}) == FAIL  # claimed, but the model has no review


def test_defect_1_review_corrections_reach_the_akn4eu_export(synthetic_eu_model, tmp_path):
    art = synthetic_eu_model.of_type(T.ARTICLE)[0]
    corr = Correction(id="c1", element_id=art.id, field="title", original_value=art.title, previous_value=art.title,
                      corrected_value=art.title + " (geprüft)", timestamp="2026-10-29T00:00:00Z", review_revision=1, model_revision=1)  # fmt: skip
    m = build_effective_model(synthetic_eu_model, [corr], 1)
    out = build_akn4eu_artifacts(m, DATE, tmp_path, eli=ELI, oj_uri=OJ_URI)
    act = etree.fromstring(out["result"].files[out["result"].act_file])
    assert act.xpath("string(//a:article[@eId='art_1']/a:heading)", namespaces=NS) == art.title + " (geprüft)"
    assert out["ok"] and out["report"]["model_source"] == {"kind": "effective_reviewed_model", "model_revision": 1, "corrected_elements": [art.id]}
    assert statuses(out["spec"])["MODEL_REVIEW"] == PASS


# ==== the API: the export uses the effective reviewed model ===================================================================
@pytest.fixture()
def api(tmp_path, monkeypatch, synthetic_eu_raw_json):
    def fake_extract(pdf, out_dir, do_ocr=False):  # Docling replaced by the synthetic regulation's Docling JSON
        out_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(synthetic_eu_raw_json, out_dir / "docling_raw.json")
        (out_dir / "extracted.md").write_text("(synthetic extraction)")
        return ExtractionResult(source=pdf, json_path=out_dir / "docling_raw.json", markdown_path=out_dir / "extracted.md",
                                status="success", pages=3, text_items=1, tables=1, warnings=[])  # fmt: skip

    monkeypatch.setattr(pl, "extract_pdf", fake_extract)
    s = Settings(storage_dir=tmp_path / "storage", max_upload_mb=50, max_queue=4, workers=1, cors_origins=())
    with TestClient(create_app(s, run_pipeline)) as c:
        doc = c.post("/api/documents", files={"file": ("synthetic_eu.pdf", b"%PDF-1.4\n%stub\n", "application/pdf")}).json()["id"]
        c.post(f"/api/documents/{doc}/process", json={"mode": "eu_legislation"})
        for _ in range(600):
            s = c.get(f"/api/documents/{doc}/status").json()
            if s["status"] in ("completed", "failed"):
                break
            time.sleep(0.1)
        assert s["status"] == "completed", s
        yield c, doc


def test_api_export_uses_the_effective_reviewed_model(api):
    c, doc = api
    body = {"eli": ELI, "oj_uri": OJ_URI}
    r = c.post(f"/api/documents/{doc}/exports/akn4eu", json=body).json()
    assert r["model_source"]["kind"] == "original_document_model" and r["status"] == STATUS_OK  # no review yet
    assert r["main_file"] == "main-OJ_JOL_2099_1_R_0001-de.xml" and r["identifiers"]["oj_uri"] == OJ_URI
    model = c.get(f"/api/documents/{doc}/structure").json()
    art = next(e for e in model["elements"] if e["type"] == "article")
    rev = c.get(f"/api/documents/{doc}/review").json()["review_revision"]
    ok = c.post(f"/api/documents/{doc}/review/corrections",
                json={"base_revision": rev, "element_id": art["id"], "field": "title", "value": art["title"] + " (geprüft)"})  # fmt: skip
    assert ok.status_code == 200, ok.text
    r = c.post(f"/api/documents/{doc}/exports/akn4eu", json=body).json()
    assert r["model_source"]["kind"] == "effective_reviewed_model" and r["model_source"]["model_revision"] == 1
    assert r["model_source"]["corrected_elements"] == [art["id"]] and r["status"] == STATUS_OK
    xml = c.get(f"/api/documents/{doc}/exports/akn4eu/files/{r['act_file']}").content
    assert (art["title"] + " (geprüft)").encode() in xml
    assert next(x for x in r["akn4eu_5_0_1_0"]["rules"] if x["rule"] == "MODEL_REVIEW")["status"] == PASS
    # the stored original model is untouched by the export
    assert c.get(f"/api/documents/{doc}/structure").json() == model
    bad = c.post(f"/api/documents/{doc}/exports/akn4eu", json={"oj_uri": "http://publications.europa.eu/resource/oj/JOL_2099_7_R_0001"})
    assert bad.status_code == 422 and bad.json()["code"] == "akn4eu_refused"


def test_report_keeps_the_existing_keys(synthetic_eu_model, tmp_path):
    """Backward compatibility: the keys the frontend and clients read are unchanged; the new layer is additive."""
    rep = build_akn4eu_artifacts(synthetic_eu_model, DATE, tmp_path)["report"]
    assert {"profile", "status", "conformance", "files", "act_file", "package", "identifiers", "scope", "generator_warnings",
            "unmapped", "text_preservation_summary", "validator"} <= set(rep)  # fmt: skip
    assert {"oasis_akn_3_1_xsd", "akn4eu_sample_checks", "official_akn4eu_validation", "text_and_order_against_model"} <= set(rep["conformance"])  # fmt: skip
    assert rep["conformance"]["official_akn4eu_validation"]["performed"] is False
    assert rep["status"].startswith("sample-compatible") and "not officially verified" in rep["status"]
    spec = rep["akn4eu_5_0_1_0"]
    assert spec["target_version"] == "5.0.1.0" and "is not official AKN4EU conformance" in spec["meaning"] and spec["not_checked"]
    assert rep["conformance"]["akn4eu_5_0_1_0_rules"]["missing_input"] == spec["missing_input"] != []  # reported, never hidden
    assert json.loads((tmp_path / "akn4eu_validation_report.json").read_text(encoding="utf-8")) == rep


# ==== stabilization pass: stale files (D1), consistent review read (D2), SHOULD warnings (D5), unapproved review ==============
import hashlib  # noqa: E402
import odos.akn.akn4eu_artifacts as art_mod  # noqa: E402
from odos.akn.akn4eu_validate import WARN  # noqa: E402


def _listing(d: Path) -> set[str]:
    return {p.name for p in d.iterdir()}


def test_d1_re_export_with_other_identifiers_leaves_no_stale_generated_xml(synthetic_eu_model, tmp_path):
    out = tmp_path / "akn4eu"
    build_akn4eu_artifacts(synthetic_eu_model, DATE, out)  # without identifiers
    first = {n for n in _listing(out) if n.endswith(".xml")}
    assert first == {"main-OJ_L_2099_1-de.xml", "act-reg_2099_1-de.xml", "ANNEX-reg_2099_1_anx_1-de.xml"}
    (out / "notes.txt").write_text("mine")  # not generated by ODOS
    (out / "ANNEX-handmade-de.xml").write_text("<x/>")  # generated-looking name, but never in a report
    rep = build_akn4eu_artifacts(synthetic_eu_model, DATE, out, eli=ELI, oj_uri=OJ_URI)["report"]
    now = {n for n in _listing(out) if n.endswith(".xml")}
    assert now == set(rep["files"]) | {"ANNEX-handmade-de.xml"}  # the three earlier files are gone, nothing else
    assert set(rep["stale_files"]["removed"]) == first and rep["stale_files"]["kept"] == []
    assert (out / "notes.txt").read_text() == "mine" and (out / "ANNEX-handmade-de.xml").read_text() == "<x/>"
    assert not [n for n in _listing(out) if n.endswith(".tmp")]
    # same export again: nothing to remove, byte-identical results
    before = {n: (out / n).read_bytes() for n in _listing(out) if n != "akn4eu_validation_report.json"}
    again = build_akn4eu_artifacts(synthetic_eu_model, DATE, out, eli=ELI, oj_uri=OJ_URI)["report"]
    assert again["stale_files"] == {"removed": [], "kept": []}
    assert all((out / n).read_bytes() == b for n, b in before.items())


def test_d1_a_stale_file_that_was_edited_is_kept_and_reported(synthetic_eu_model, tmp_path):
    out = tmp_path / "akn4eu"
    build_akn4eu_artifacts(synthetic_eu_model, DATE, out)
    (out / "act-reg_2099_1-de.xml").write_bytes(b"<!-- edited by a person -->")
    rep = build_akn4eu_artifacts(synthetic_eu_model, DATE, out, eli=ELI, oj_uri=OJ_URI)["report"]
    assert (out / "act-reg_2099_1-de.xml").read_bytes() == b"<!-- edited by a person -->"
    assert [k["name"] for k in rep["stale_files"]["kept"]] == ["act-reg_2099_1-de.xml"]
    assert "act-reg_2099_1-de.xml" not in rep["stale_files"]["removed"] and "act-reg_2099_1-de.xml" not in rep["files"]
    assert not (out / "main-OJ_L_2099_1-de.xml").exists()  # the unedited ones were removed


def test_d1_a_stale_symlink_is_never_followed_or_removed(synthetic_eu_model, tmp_path):
    out = tmp_path / "akn4eu"
    build_akn4eu_artifacts(synthetic_eu_model, DATE, out)
    target = tmp_path / "precious.xml"
    target.write_bytes((out / "act-reg_2099_1-de.xml").read_bytes())
    (out / "act-reg_2099_1-de.xml").unlink()
    (out / "act-reg_2099_1-de.xml").symlink_to(target)
    build_akn4eu_artifacts(synthetic_eu_model, DATE, out, eli=ELI, oj_uri=OJ_URI)
    assert target.is_file() and (out / "act-reg_2099_1-de.xml").is_symlink()


def test_d1_replacement_is_atomic(synthetic_eu_model, tmp_path, monkeypatch):
    out = tmp_path / "akn4eu"
    build_akn4eu_artifacts(synthetic_eu_model, DATE, out)
    old = {n: (out / n).read_bytes() for n in _listing(out)}

    def boom(src, dst):
        raise OSError("disk error")

    monkeypatch.setattr(art_mod.os, "replace", boom)
    with pytest.raises(OSError):
        build_akn4eu_artifacts(synthetic_eu_model, DATE, out, eli=ELI, oj_uri=OJ_URI)
    monkeypatch.undo()
    assert {n: (out / n).read_bytes() for n in _listing(out)} == old  # nothing half-written, no temp files, nothing removed
    art_mod.atomic_write(out / "x.json", b"1")
    assert (out / "x.json").read_bytes() == b"1" and not [n for n in _listing(out) if n.endswith(".tmp")]


def test_d5_failed_should_rules_are_warnings_not_mandatory_errors(synthetic_eu_model, full):
    rep = check(full.files, synthetic_eu_model, full)
    st = statuses(rep)
    assert st["OJ_CLASSIFICATION"] == WARN and st["OJ_COVERPAGE_INFO"] == "missing_input"
    assert {"OJ_CLASSIFICATION", "OJ_COVERPAGE_INFO"} <= set(rep["warnings"])
    assert not {"OJ_CLASSIFICATION", "OJ_COVERPAGE_INFO"} & set(rep["failed"]) and rep["passed"]
    assert RULES["OJ_CLASSIFICATION"][1] == "SHOULD" and "should_not_met" not in rep
    # a MUST violation still fails, whatever the warnings
    bad = check(edit(dict(full.files), "act-", b'<FRBRcountry value="EU"/>', b'<FRBRcountry value="DE"/>'))
    assert not bad["passed"] and "FRBR_COUNTRY" in bad["failed"] and "FRBR_COUNTRY" not in bad["warnings"]


def test_d5_warnings_do_not_make_the_export_fail(synthetic_eu_model, tmp_path):
    art = build_akn4eu_artifacts(synthetic_eu_model, DATE, tmp_path, eli=ELI, oj_uri=OJ_URI)
    c = art["report"]["conformance"]["akn4eu_5_0_1_0_rules"]
    assert art["ok"] and c["passed"] and "OJ_CLASSIFICATION" in c["warnings"] and "OJ_CLASSIFICATION" not in c["failed"]


def test_unapproved_review_is_reported_never_treated_as_approved(synthetic_eu_model, tmp_path):
    def run(source):
        return build_akn4eu_artifacts(synthetic_eu_model, DATE, tmp_path / "o", model_source=source)["report"]

    for state in ("pending_review", "in_review", "changes_requested", None):
        rep = run({"kind": "effective_reviewed_model", "model_revision": 0, "review_state": state, "approved": False})
        assert [w["code"] for w in rep["export_warnings"]] == ["UNAPPROVED_REVIEW"]
        assert "not approved" in rep["export_warnings"][0]["detail"] or "unknown approval state" in rep["export_warnings"][0]["detail"]
    assert run({"kind": "effective_reviewed_model", "model_revision": 0, "review_state": "approved", "approved": True})["export_warnings"] == []
    assert run({"kind": "original_document_model", "model_revision": None, "review_state": None})["export_warnings"] == []
    # a model that carries review data but no stated approval state (CLI) is not assumed approved
    m = synthetic_eu_model.model_copy(deep=True)
    m.review = {"model_revision": 2, "corrections": ["c1"]}
    assert [w["code"] for w in build_akn4eu_artifacts(m, DATE, tmp_path / "cli")["report"]["export_warnings"]] == ["UNAPPROVED_REVIEW"]


def _start_correction(c, doc):
    model = c.get(f"/api/documents/{doc}/structure").json()
    art = next(e for e in model["elements"] if e["type"] == "article")
    rev = c.get(f"/api/documents/{doc}/review").json()["review_revision"]
    r = c.post(f"/api/documents/{doc}/review/corrections", json={"base_revision": rev, "element_id": art["id"], "field": "title", "value": art["title"] + " Z"})  # fmt: skip
    assert r.status_code == 200, r.text
    return art, r.json()


def test_api_export_names_an_unapproved_review_and_not_an_approved_one(api):
    c, doc = api
    art, view = _start_correction(c, doc)
    r = c.post(f"/api/documents/{doc}/exports/akn4eu", json={}).json()
    assert r["model_source"]["approved"] is False and r["model_source"]["review_state"] != "approved"
    assert [w["code"] for w in r["export_warnings"]] == ["UNAPPROVED_REVIEW"]
    # approve (the synthetic act has no uncertain elements to confirm first)
    ok = c.post(f"/api/documents/{doc}/review/approve", json={"base_revision": view["review_revision"]})
    assert ok.status_code == 200, ok.text
    r = c.post(f"/api/documents/{doc}/exports/akn4eu", json={}).json()
    assert r["model_source"]["approved"] is True and r["model_source"]["review_state"] == "approved" and r["export_warnings"] == []


def test_d2_effective_model_and_revision_are_read_under_the_review_lock(api):
    c, doc = api
    art, view = _start_correction(c, doc)
    store = c.app.state.reviews.store
    lock, real_load, held = store.lock(doc), store.load, []

    def load(doc_id):  # every read of the review record by the export, and whether the review lock was held
        held.append(lock._is_owned())
        return real_load(doc_id)

    store.load = load
    try:
        r = c.post(f"/api/documents/{doc}/exports/akn4eu", json={})
    finally:
        store.load = real_load
    assert r.status_code == 200 and len(held) >= 2 and all(held), held  # the record is read twice, both times under the lock
    src = r.json()["model_source"]
    eff = c.get(f"/api/documents/{doc}/review/model").json()
    assert src["model_revision"] == eff["review"]["model_revision"] == 1  # the revision reported is the revision of the model used
    assert src["corrected_elements"] == [art["id"]]
    assert next(x for x in r.json()["akn4eu_5_0_1_0"]["rules"] if x["rule"] == "MODEL_REVIEW")["status"] == PASS
