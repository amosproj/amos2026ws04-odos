"""AKN4EU export profile, checked against the official AKN4EU 5.0.1.0 samples and the OASIS AKN 3.1 XSD.

Two separate claims are tested, never mixed:
- *sample compatibility*: the output is built like the official samples (same rules, same skeletons) and
  is valid against the official OASIS AKN 3.1 schema that the samples themselves validate against;
- *official AKN4EU conformance*: NOT tested -- no official AKN4EU validation artefacts are available, and
  the report must say so.
"""

import hashlib
import io
import json
import re
import shutil
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from lxml import etree

import odos.pipeline as pl
from odos.akn.akn4eu import XID, generate_akn4eu
from odos.akn.akn4eu_artifacts import STATUS_OK, build_akn4eu_artifacts, verify_akn4eu
from odos.akn.akn4eu_checks import RULES, check_document, check_package
from odos.akn.eu_generator import generate_eu_akn
from odos.akn.validate import PINNED_SHA256, SCHEMA_DIR, SchemaIntegrityError, validate_xml
from odos.api.app import create_app
from odos.api.config import Settings
from odos.cli import main
from odos.extraction import ExtractionResult
from odos.document_model import ElementType as T
from odos.pipeline import run_pipeline
from odos.review.model import Correction
from odos.review.service import build_effective_model

BACKEND = Path(__file__).resolve().parents[1]
SAMPLES = BACKEND / "tests" / "fixtures" / "akn4eu-5.0.1.0-samples"
SAMPLE_FILES = sorted(SAMPLES.rglob("*.xml"))
REG_SAMPLE = SAMPLES / "OJ-L-202500864" / "AKN4EU" / "en" / "act-eli_reg_impl_2025_864-en.xml"
ANNEX_SAMPLE = SAMPLES / "OJ-L-202500864" / "AKN4EU" / "en" / "ANNEX-eli_reg_impl_2025_864_anx-en.xml"
NS = {"a": "http://docs.oasis-open.org/legaldocml/ns/akn/3.0", "akn4eu": "http://imfc.europa.eu/akn4eu"}
DATE = "2026-10-29"
ELI = "http://data.europa.eu/eli/reg/2023/1230/oj"


def q(node, path):
    return node.xpath(path, namespaces=NS)


def rel(p: Path) -> str:
    return str(p.relative_to(SAMPLES))


@pytest.fixture(scope="module")
def result(eu_model):
    return generate_akn4eu(eu_model, DATE)


@pytest.fixture(scope="module")
def trees(result):
    return {name: etree.fromstring(xml) for name, xml in result.files.items()}


@pytest.fixture(scope="module")
def act(result, trees):
    return trees[result.act_file]


# ==== the official samples as reference ==========================================================================
def test_sample_fixtures_are_the_unmodified_official_files():
    sums = dict(reversed(line.split("  ", 1)) for line in (SAMPLES / "SHA256SUMS").read_text().splitlines())
    assert len(SAMPLE_FILES) == len(sums) == 60
    for f in SAMPLE_FILES:
        assert hashlib.sha256(f.read_bytes()).hexdigest() == sums["./" + rel(f)], rel(f)


@pytest.mark.parametrize("sample", SAMPLE_FILES, ids=rel)
def test_every_official_sample_is_valid_against_akn_3_1(sample):
    v = validate_xml(sample.read_bytes())
    assert v.valid, [e.message for e in v.errors[:3]]


def test_the_active_schema_accepts_the_akn4eu_3_1_constructs_of_the_samples():
    """AKN 3.1 constructs used by the official samples (not in the former AKN 3.0 schema) are accepted."""
    text = b"".join(f.read_bytes() for f in SAMPLE_FILES)
    for construct in (b"<annex ", b"<thead", b"<tbody", b'<FRBRlanguage xml:id="FRBRlanguage" refersTo='):
        assert construct in text
    assert (SCHEMA_DIR.name, PINNED_SHA256["akomantoso30.xsd"][:8]) == ("akn-3.1-os", "8f1fe3e1")
    assert not (SCHEMA_DIR.parent / "akn-3.0-os").exists()  # legacy AKN 3.0 schema removed


@pytest.mark.parametrize("sample", SAMPLE_FILES, ids=rel)
def test_every_profile_rule_holds_for_every_official_sample(sample):
    assert check_document(sample.read_bytes()) == []


def test_official_sample_packages_resolve_their_document_refs():
    for folder in sorted({f.parent for f in SAMPLE_FILES}):
        files = {f.name: f.read_bytes() for f in sorted(folder.glob("*.xml"))}
        rep = check_package(files)
        assert rep["passed"], (rel(folder), {k: v["findings"] for k, v in rep["files"].items() if v["findings"]})


# ==== our output: OASIS AKN 3.1 XSD and the sample rules ===========================================================
def test_every_generated_file_is_valid_against_the_official_akn_3_1_xsd(result):
    assert len(result.files) == 13  # act + 12 annexes
    for name, xml in result.files.items():
        v = validate_xml(xml)
        assert v.valid and v.errors == [], (name, [e.message for e in v.errors[:3]])
        assert v.schema_version.startswith("OASIS Akoma Ntoso Version 2.0") and "AKN 3.1" in v.schema_version


def test_validator_still_rejects_broken_akn4eu_documents(result):
    xml = result.files[result.act_file]
    assert not validate_xml(xml.replace(b"<recitals ", b"<bogus/><recitals ", 1)).valid
    assert not validate_xml(xml.replace(b'xml:id="cit_2"', b'xml:id="cit_1"', 1)).valid  # xsd:ID
    assert not validate_xml(xml.replace(b"<attachments>", b'<attachments xml:id="x">', 1)).valid


def test_akn_3_1_schema_is_pinned_to_the_oasis_manifest(tmp_path):
    manifest = json.loads((SCHEMA_DIR / "manifest.json").read_text())
    published = {Path(i["path"]).name: i["sha256"] for i in manifest["items"] if i["path"].startswith("schemas/") and i["path"].endswith(".xsd")}  # fmt: skip
    assert published == PINNED_SHA256
    d = tmp_path / "akn31"
    shutil.copytree(SCHEMA_DIR, d)
    (d / "akomantoso30.xsd").write_bytes((d / "akomantoso30.xsd").read_bytes() + b"\n")
    with pytest.raises(SchemaIntegrityError):
        validate_xml(b"<akomaNtoso/>", schema_dir=d)


def test_generated_package_satisfies_every_sample_rule(result):
    rep = check_package(result.files)
    assert rep["passed"], {k: v["findings"][:3] for k, v in rep["files"].items() if v["findings"]}
    assert len(rep["rules"]) == len(RULES) == 16


@pytest.mark.parametrize(("mutation", "rule"), [
    (lambda x: x.replace(b"<p ", b'<p xmlns:odos="urn:x" odos:src="#/texts/1" ', 1), "FOREIGN_MARKUP"),
    (lambda x: x.replace(b"<meta>", b"<meta><notes><note/></notes>", 1), "NOTES_INLINE"),
    (lambda x: x.replace(b'refersTo="#REG"', b'refersTo="#NOPE"', 1), "REFERS_TO"),
    (lambda x: x.replace(b'eId="art_1"', b'eId="chp_1__art_1"', 1), "EID_PATTERN"),
    (lambda x: x.replace(b'<FRBRcountry value="EU"/>', b'<FRBRcountry value="eu"/>', 1), "FRBR_COUNTRY"),
    (lambda x: re.sub(rb'(<article) xml:id="art_2"', rb"\1", x, count=1), "XML_ID"),
])  # fmt: skip
def test_checker_detects_deviations_from_the_samples(result, mutation, rule):
    findings = check_document(mutation(result.files[result.act_file]))
    assert rule in {f["rule"] for f in findings}, findings


# ==== our output compared with the official published regulation (EU) 2025/864 ===========================================
def _seq(node, path=None, names=True):
    """Child sequence as tag[@name] (or just tag), consecutive repeats collapsed."""
    out = []
    for c in (q(node, path)[0] if path else node):
        if isinstance(c.tag, str):
            k = etree.QName(c).localname + (f"[{c.get('name')}]" if names and c.get("name") else "")
            if not out or out[-1] != k:
                out.append(k)
    return out


def test_act_skeleton_matches_the_official_regulation_sample(act):
    ref = etree.parse(str(REG_SAMPLE)).getroot()
    ours = [t for t in _seq(act[0]) if t != "coverPage"]  # coverPage: OJ section headings (documented ODOS addition)
    assert ours == _seq(ref[0]) == ["meta", "preface", "preamble", "body", "conclusions", "attachments"]
    for level in ("FRBRWork", "FRBRExpression", "FRBRManifestation"):
        assert _seq(act, f"//a:{level}", names=False) == _seq(ref, f"//a:{level}", names=False), level
    assert _seq(act, "//a:meta", names=False) == [t for t in _seq(ref, "//a:meta", names=False) if t != "analysis"]  # no modification analysis  # fmt: skip
    assert q(act, "string(/a:akomaNtoso/a:act/@name)") == "REG"


def test_meta_follows_the_akn4eu_conventions(act, eu_model):
    md = eu_model.metadata
    w = q(act, "//a:FRBRWork")[0]
    assert q(w, "string(a:FRBRcountry/@value)") == "EU"
    assert [(d.get("name"), d.get("date")) for d in q(w, "a:FRBRdate")] == [("adoption", md.adoption_date), ("publication", md.publication_date)]  # fmt: skip
    assert [a.get("href") for a in q(w, "a:FRBRauthor")] == ["#EP", "#CONSIL"]
    assert q(w, "string(a:FRBRnumber/@value)") == md.document_number and q(w, "string(a:FRBRsubtype/@value)") == "REG"
    e = q(act, "//a:FRBRExpression")[0]
    assert q(e, "string(a:FRBRdate/@date)") == "2999-01-01"  # AKN4EU placeholder, as in every sample
    assert (q(e, "string(a:FRBRlanguage/@language)"), q(e, "string(a:FRBRlanguage/@refersTo)")) == ("de", "~DEU")
    assert q(act, "string(//akn4eu:akn4euVersion/@value)") == "5.0.0.1"
    refs = {r.get(XID): r.get("href") for r in q(act, "//a:references/*")}
    auth = "http://publications.europa.eu/resource/authority/"
    assert refs["EP"] == auth + "corporate-body/EP" and refs["CONSIL"] == auth + "corporate-body/CONSIL"
    assert refs["DEU"] == auth + "language/DEU" and refs["REG"] == auth + "resource-type/REG" and refs["FRA_SXB"] == auth + "place/FRA_SXB"  # fmt: skip
    pub = q(act, "//a:meta/a:publication")[0]
    assert (pub.get("date"), pub.get("number"), pub.get("name")) == (md.publication_date, "L 165/1", "Amtsblatt der Europäischen Union")


def test_nothing_is_invented_without_an_eli(result, act):
    assert all(q(act, f"string(//a:{lvl}/a:FRBRthis/@value)") == "" for lvl in ("FRBRWork", "FRBRExpression", "FRBRManifestation"))
    assert all(b"data.europa.eu/eli" not in x and b"CELEX" not in x for x in result.files.values())
    assert any(w["code"] == "NO_ELI" for w in result.warnings) and result.identifiers["eli"] is None


def test_supplied_eli_is_checked_and_used_in_the_akn4eu_layout(eu_model):
    with pytest.raises(ValueError, match="does not match the printed act"):
        generate_akn4eu(eu_model, DATE, eli="http://data.europa.eu/eli/reg/2023/1231/oj")
    with pytest.raises(ValueError, match="does not match"):
        generate_akn4eu(eu_model, DATE, eli="http://data.europa.eu/eli/dir/2023/1230/oj")
    r = generate_akn4eu(eu_model, DATE, eli=ELI)
    a = etree.fromstring(r.files[r.act_file])
    assert [q(a, f"string(//a:{lvl}/a:FRBRthis/@value)") for lvl in ("FRBRWork", "FRBRExpression", "FRBRManifestation")] == [ELI, ELI + "/deu", ELI + "/deu/akn4eu"]  # fmt: skip
    assert q(a, "string(//a:FRBRWork/a:FRBRnumber[@refersTo='#ELI']/@value)") == "eli/reg/2023/1230"
    anx = etree.fromstring(r.files[next(n for n in r.files if n.startswith("ANNEX-"))])
    assert q(anx, "string(//a:FRBRWork/a:FRBRuri/@value)") == ELI  # as in the sample: annex FRBRuri = the act's
    assert q(anx, "string(//a:FRBRWork/a:FRBRthis/@value)") == ""  # 12 annexes: their ELIs are not known
    assert any(w["code"] == "ANNEX_ELI_UNKNOWN" for w in r.warnings)
    assert all(validate_xml(x).valid for x in r.files.values()) and check_package(r.files)["passed"]


def test_eids_only_where_the_samples_use_them(act, trees):
    sample_patterns = {re.sub(r"\d+", "N", n.get("eId")) for f in SAMPLE_FILES for n in etree.parse(str(f)).iter()
                       if isinstance(n.tag, str) and n.get("eId") and not q(n, "ancestor::a:meta")}  # fmt: skip
    ours = {re.sub(r"\d+", "N", n.get("eId")) for t in trees.values() for n in t.iter()
            if isinstance(n.tag, str) and n.get("eId") and not q(n, "ancestor::a:meta")}  # fmt: skip
    assert ours <= sample_patterns, ours - sample_patterns
    assert [r.get("eId") for r in q(act, "//a:recital")][:3] == ["rct_1", "rct_2", "rct_3"]
    assert q(act, "string(//a:article[@eId='art_3']/a:paragraph/@eId)") == "art_3/unp_1"


def test_structures_as_in_the_samples(act, trees, eu_model):
    assert len(q(act, "//a:recital")) == len(eu_model.of_type(T.RECITAL))
    assert len(q(act, "//a:article")) == len(eu_model.of_type(T.ARTICLE))
    assert len(q(act, "/a:akomaNtoso/a:act/a:body/a:chapter")) == len(eu_model.of_type(T.CHAPTER))
    assert [f.get("name") for f in q(act, "//a:preamble/a:formula")] == ["actingEntity", "enactingFormula"]
    # definitions: paragraph > list > (subparagraph[~INP], point...) as in the REG sample of DLV24-1.17
    lst = q(act, "//a:article[@eId='art_3']/a:paragraph/a:list")[0]
    assert q(lst, "string(a:subparagraph[1]/@refersTo)") == "~INP" and len(q(lst, "a:point")) == len([p for p in eu_model.of_type(T.NUMBERED_POINT) if p.parent_id == "doc/chp-1/art-3"])  # fmt: skip
    assert not q(act, "//a:point[not(parent::a:list)]")
    # the binding clause is body/clause, "Done at" and the signatories are structured as in 2025/864
    assert q(act, "string(//a:body/a:clause//a:p)").startswith("Diese Verordnung ist in allen ihren Teilen verbindlich")
    assert q(act, "string(//a:conclusions/a:p/a:location/@refersTo)") == "#FRA_SXB"
    assert q(act, "string(//a:conclusions/a:p/a:date/@date)") == eu_model.metadata.adoption_date
    sigs = q(act, "//a:conclusions/a:block[@name='signatory']/a:signature")
    assert [q(s, "string(a:organization/@refersTo)") for s in sigs] == ["#EP", "#CONSIL"]
    assert all(q(s, "a:role[@refersTo='#PRESID']") and q(s, "a:person") for s in sigs)
    # long title: docType with docNumber, date and docPurpose; EEA relevance container
    lt = q(act, "//a:preface/a:longTitle[@eId='tit_1']/a:p")[0]
    assert q(lt, "string(a:docType/a:docNumber)") == "(EU) 2023/1230" and q(lt, "string(a:date/@date)") == "2023-06-14"
    assert q(lt, "string(a:docPurpose)").startswith("über Maschinen")
    assert q(act, "string(//a:preface/a:container[@name='eeaRelevance'])").strip() == "(Text von Bedeutung für den EWR)"


def test_signature_block_as_table_or_as_text(eu_model, act):
    """Docling delivers the signature block as a table (verified extraction) or as one text item (other
    dependency versions); both become the same signatory structure, and the text check holds for both."""
    sig = next(e for e in eu_model.elements if e.type == T.SIGNATURE)
    assert sig.table is not None and len(sig.table.rows) == 3
    text = " ".join(f"{sig.table.rows[0][c]} {sig.table.rows[1][c]} {sig.table.rows[2][c]}" for c in range(len(sig.table.rows[0])))
    m = eu_model.model_copy(deep=True)
    el = m.by_id()[sig.id]
    el.table, el.type, el.content_text, el.original_text = None, T.TEXT, text, text
    r = generate_akn4eu(m, DATE)
    a2 = etree.fromstring(r.files[r.act_file])
    for a in (act, a2):
        sigs = q(a, "//a:conclusions/a:block[@name='signatory']/a:signature")
        assert [(q(s, "string(a:organization)"), q(s, "string(a:person)")) for s in sigs] == [
            ("Im Namen des Europäischen Parlaments", "R. METSOLA"), ("Im Namen des Rates", "J. ROSWALL")]
    assert verify_akn4eu(m, r)["same_order_and_text"] and not any(w["code"] == "SIGNATURE_NOT_STRUCTURED" for w in r.warnings)


def test_annexes_are_separate_documents_like_the_sample(result, trees, act):
    ref = etree.parse(str(ANNEX_SAMPLE)).getroot()
    hrefs = [r.get("href") for r in q(act, "//a:attachments/a:attachment/a:documentRef")]
    assert hrefs == [n for n in result.files if n.startswith("ANNEX-")] and len(hrefs) == 12
    for h in hrefs:
        t = trees[h]
        assert q(t, "string(/a:akomaNtoso/a:doc/@name)") == "ANNEX" == q(ref, "string(/a:akomaNtoso/a:doc/@name)")
        assert _seq(t[0]) == _seq(ref[0]) == ["meta", "mainBody"]
        assert q(t, "/a:akomaNtoso/a:doc/a:mainBody/a:annex/a:num")
    assert q(trees[hrefs[2]], "string(//a:annex/a:num)") == "ANHANG III"
    assert [q(p, "string(a:num)") for p in q(trees[hrefs[2]], "//a:annex/a:part")] == ["TEIL A", "TEIL B"]


def test_footnotes_are_inline_authorial_notes_at_their_reference(result, act, eu_model):
    fns = eu_model.of_type(T.FOOTNOTE)
    notes = [n for t in result.files.values() for n in q(etree.fromstring(t), "//a:authorialNote")]
    assert len(notes) == len(fns) and not any(b"<notes" in x for x in result.files.values())
    assert all(n.get("placement") == "bottom" and n.get("marker").isdigit() for n in notes)
    placed = [e["footnote"]["placed"] for e in result.entries if e.get("footnote")]
    assert placed == ["at_reference"] * len(fns)
    n1 = q(act, "//a:citation[@eId='cit_4']/a:p/a:authorialNote")[0]
    assert (n1.get("marker"), q(n1, "string(a:p)")) == ("1", "ABl. C 517 vom 22.12.2021, S. 67.")
    assert "( 1 )" not in q(act, "string(//a:citation[@eId='cit_4']/a:p/text()[1])")  # moved into @marker, recorded:
    e = next(e for e in result.entries if e["xml_id"] == n1.get(XID))
    assert e["footnote"]["reference_text"] == "( 1 )" and e["footnote"]["stripped_prefix"] == "( 1 ) "


# ==== text, order, accounting, provenance ---------------------------------------------------------------------------
def test_text_and_order_match_the_model_exactly(eu_model, result):
    t = verify_akn4eu(eu_model, result)
    assert t["same_order_and_text"] and t["text_mismatches"] == [] and t["missing_nodes"] == []
    assert t["document_order_preserved"] and t["footnote_order_preserved"] and t["original_text_reconstruction_diffs"] == []
    assert t["elements_not_in_xml"] == {"document_root": 1, "page_furniture": len(eu_model.furniture), "unmapped": 0}
    assert t["counts"] == {"recitals": len(eu_model.of_type(T.RECITAL)), "chapters": len(eu_model.of_type(T.CHAPTER)),
                           "articles": len(eu_model.of_type(T.ARTICLE)), "annexes": len(eu_model.of_type(T.ANNEX)), "files": 13}  # fmt: skip
    missing = [e.id for e in eu_model.elements if e.id not in set(result.included_ids) and e.type != T.DOCUMENT]
    assert missing == [] and result.unmapped == []


def test_text_check_detects_altered_text(eu_model, result):
    broken = result.model_copy(deep=True)
    broken.files[broken.act_file] = broken.files[broken.act_file].replace("Begriffsbestimmungen".encode(), b"Definitionen", 1)
    t = verify_akn4eu(eu_model, broken)
    assert not t["same_order_and_text"] and t["text_mismatches"]


def test_no_odos_markup_in_xml_but_full_provenance_in_traceability(eu_model, result):
    assert all(b"amos2026ws04-odos/ns" not in x and b"odos:" not in x for x in result.files.values())
    uncertain = {e.id for e in eu_model.elements if e.uncertain}
    assert {e["model_id"] for e in result.entries if e["uncertain"]} == uncertain
    para = next(e for e in result.entries if e["source_spans"])
    assert para["source_spans"][0]["bbox_scope"] == "docling_item" and para["xml_id"]
    assert all(e["source_refs"] == eu_model.by_id()[e["model_id"]].source_refs for e in result.entries)


def test_deterministic(eu_model, result, tmp_path):
    assert generate_akn4eu(eu_model, DATE).files == result.files
    build_akn4eu_artifacts(eu_model, DATE, tmp_path / "a")
    build_akn4eu_artifacts(eu_model, DATE, tmp_path / "b")
    for f in sorted((tmp_path / "a").iterdir()):
        assert f.read_bytes() == (tmp_path / "b" / f.name).read_bytes(), f.name


def test_reviewed_text_is_exported_and_traced_but_not_claimed_verbatim(eu_model):
    el = eu_model.by_id()["doc/chp-1/art-1"]
    corr = Correction(id="c1", element_id=el.id, field="title", original_value=el.title, previous_value=el.title,
                      corrected_value=el.title + " (geprüft)", timestamp=datetime.now(timezone.utc), review_revision=1, model_revision=1)  # fmt: skip
    m = build_effective_model(eu_model, [corr], 1)
    r = generate_akn4eu(m, DATE)
    a = etree.fromstring(r.files[r.act_file])
    assert q(a, "string(//a:article[@eId='art_1']/a:heading)") == el.title + " (geprüft)"
    t = verify_akn4eu(m, r)
    assert t["same_order_and_text"] and t["reviewed_elements"] == [el.id]
    e = next(e for e in r.entries if e["model_id"] == el.id)
    assert e["reviewed"]["verbatim_from_source"] is False and e["original_text"] == el.original_text


def test_refuses_unsupported_models(model, eu_model):
    with pytest.raises(ValueError, match="eu_legislation"):
        generate_akn4eu(model, DATE)  # BDSG: German law
    broken = eu_model.model_copy(deep=True)
    broken.metadata.adoption_date = None
    with pytest.raises(ValueError, match="refusing to invent"):
        generate_akn4eu(broken, DATE)
    broken = eu_model.model_copy(deep=True)
    broken.metadata.document_type = "EMPFEHLUNG"
    with pytest.raises(ValueError, match="no AKN4EU resource type"):
        generate_akn4eu(broken, DATE)


def test_generic_eu_export_is_independent_and_valid(eu_model):
    before = generate_eu_akn(eu_model, DATE).xml
    generate_akn4eu(eu_model, DATE)
    after = generate_eu_akn(eu_model, DATE)
    assert after.xml == before and validate_xml(after.xml).valid  # the eu_legislation export: unchanged, AKN 3.1 valid
    assert validate_xml(after.xml).schema_files[0]["sha256"] == "8f1fe3e187ee5e6f5bc9dfb013f7d9195de6516f077ce10726bedf6260f8b70a"


# ==== artifacts, report, CLI, API -----------------------------------------------------------------------------------------
def test_report_separates_sample_compatibility_from_official_conformance(eu_model, tmp_path):
    art = build_akn4eu_artifacts(eu_model, DATE, tmp_path)
    rep = json.loads((tmp_path / "akn4eu_validation_report.json").read_text(encoding="utf-8"))
    assert art["ok"] and rep["status"] == STATUS_OK and "not officially verified" in rep["status"]
    c = rep["conformance"]
    assert c["oasis_akn_3_1_xsd"]["valid"] is True and c["akn4eu_sample_checks"]["passed"] is True
    assert c["official_akn4eu_validation"]["performed"] is False and c["official_akn4eu_validation"]["reason"]
    assert all(f["valid_akn_3_1"] for f in rep["files"].values())
    with zipfile.ZipFile(tmp_path / "akn4eu_package.zip") as z:
        assert z.namelist() == list(art["result"].files) and z.read(rep["act_file"]) == art["result"].files[rep["act_file"]]
    tr = json.loads((tmp_path / "akn4eu_traceability.json").read_text(encoding="utf-8"))
    assert tr["excluded_counts"]["unmapped"] == 0 and len(tr["uncertain"]) == sum(e.uncertain for e in eu_model.elements)


def test_report_is_negative_when_a_layer_fails(eu_model, tmp_path, monkeypatch):
    import odos.akn.akn4eu_artifacts as art_mod

    monkeypatch.setattr(art_mod, "check_package", lambda files: {"passed": False, "rules": RULES, "meaning": "", "files": {n: {"passed": False, "findings": [{"rule": "X", "message": "x"}]} for n in files}})  # fmt: skip
    art = build_akn4eu_artifacts(eu_model, DATE, tmp_path)
    assert not art["ok"] and art["report"]["status"].startswith("NOT sample-compatible")


def test_cli(eu_model, tmp_path, capsys):
    mp = tmp_path / "document_model.json"
    mp.write_text(eu_model.model_dump_json(), encoding="utf-8")
    assert main(["akn4eu", str(mp), "--conversion-date", DATE]) == 0
    out = capsys.readouterr().out
    assert "AKN 3.1 XSD:       valid" in out and "not verified" in out and (tmp_path / "akn4eu" / "akn4eu_package.zip").is_file()
    assert main(["akn4eu", str(mp), "--eli", "http://data.europa.eu/eli/reg/2099/1/oj"]) == 1


@pytest.fixture()
def api(tmp_path, monkeypatch, raw_json):  # raw_json: the BDSG extraction must exist before the worker thread needs it
    def fake_extract(pdf, out_dir, do_ocr=False):  # Docling replaced by the stored extraction of the same PDF
        fn = json.loads((out_dir.parent / "meta.json").read_text())["filename"]
        src = BACKEND / "output" / ("bdsg" if fn == "BDSG.pdf" else "eu")
        if not (src / "docling_raw.json").exists():
            pytest.skip(f"{src} extraction not available")
        out_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(src / "docling_raw.json", out_dir / "docling_raw.json")
        (out_dir / "extracted.md").write_text("(extraction reused in tests)")
        return ExtractionResult(source=pdf, json_path=out_dir / "docling_raw.json", markdown_path=out_dir / "extracted.md",
                                status="success", pages=1, text_items=1, tables=0, warnings=[])  # fmt: skip

    monkeypatch.setattr(pl, "extract_pdf", fake_extract)
    s = Settings(storage_dir=tmp_path / "storage", max_upload_mb=50, max_queue=4, workers=1, cors_origins=())
    with TestClient(create_app(s, run_pipeline)) as c:
        yield c


def _processed(c, name: str, data: bytes, mode: str) -> str:
    doc = c.post("/api/documents", files={"file": (name, data, "application/pdf")}).json()["id"]
    c.post(f"/api/documents/{doc}/process", json={"mode": mode})
    for _ in range(600):
        s = c.get(f"/api/documents/{doc}/status").json()
        if s["status"] in ("completed", "failed"):
            break
        time.sleep(0.1)
    assert s["status"] == "completed", s
    return doc


def test_api_export(api, eu_raw_json):  # eu_raw_json: skips (with the reason) when the partner EU PDF is missing
    doc = _processed(api, "EuMaschinenbauverordnung.pdf", b"%PDF-1.4\n%stub\n", "eu_legislation")
    assert api.get(f"/api/documents/{doc}/exports/akn4eu/package").status_code == 404  # nothing exported yet
    assert api.get(f"/api/documents/{doc}/exports/akn4eu").json()["code"] == "no_akn4eu_export"
    r = api.post(f"/api/documents/{doc}/exports/akn4eu", json={})
    assert r.status_code == 200, r.text
    assert api.get(f"/api/documents/{doc}/exports/akn4eu").json() == r.json()  # the stored report
    act = r.json()["act_file"]
    x = api.get(f"/api/documents/{doc}/exports/akn4eu/files/{act}")
    assert x.status_code == 200 and x.headers["content-type"].startswith("application/xml") and b'<act name="REG">' in x.content
    assert api.get(f"/api/documents/{doc}/exports/akn4eu/files/akn4eu_traceability.json").status_code == 404  # only listed XML files
    assert api.get(f"/api/documents/{doc}/exports/akn4eu/files/..%2Fmeta.json").status_code == 404
    assert r.json()["status"] == STATUS_OK and r.json()["conformance"]["official_akn4eu_validation"]["performed"] is False
    z = zipfile.ZipFile(io.BytesIO(api.get(f"/api/documents/{doc}/exports/akn4eu/package").content))
    assert len(z.namelist()) == 13 and z.namelist()[0].startswith("act-reg_2023_1230")
    assert api.get(f"/api/documents/{doc}/exports/akn4eu/traceability").json()["profile"] == "akn4eu"
    assert api.post(f"/api/documents/{doc}/exports/akn4eu", json={"eli": "http://data.europa.eu/eli/reg/2023/9/oj"}).status_code == 422  # fmt: skip
    assert api.get(f"/api/documents/{doc}/exports/akn4eu/other").status_code == 404
    # the pipeline's own AKN artifact is untouched by the export
    assert api.get(f"/api/documents/{doc}/artifacts/akn_xml").status_code == 200


def test_api_export_refuses_german_law(api):
    doc = _processed(api, "BDSG.pdf", (BACKEND / "data" / "input" / "BDSG.pdf").read_bytes(), "german_law")
    r = api.post(f"/api/documents/{doc}/exports/akn4eu", json={})
    assert r.status_code == 409 and r.json()["code"] == "profile_not_supported"
