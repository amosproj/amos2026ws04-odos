"""Human review workflow: corrections as versioned patches, regeneration, XSD validation, approval gating."""

import hashlib
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from lxml import etree

import odos.pipeline as pl
from odos.api.app import create_app
from odos.api.config import Settings
from odos.extraction import ExtractionResult
from odos.document_model import DocumentModel
from odos.pipeline import run_pipeline
from odos.review.store import FileReviewStore

BACKEND = Path(__file__).resolve().parents[1]
AKN = "{http://docs.oasis-open.org/legaldocml/ns/akn/3.0}"
ODOS = "{https://github.com/amosproj/amos2026ws04-odos/ns/akn-extension/1.0}"
PAR2 = "doc/teil-1/kapitel-1/par-1/abs-2"  # BDSG § 1 (2), not uncertain


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def settings(tmp: Path) -> Settings:
    return Settings(storage_dir=tmp / "storage", max_upload_mb=50, max_queue=4, workers=1, cors_origins=())


@pytest.fixture()
def fake_docling(monkeypatch, raw_json):  # raw_json: the BDSG extraction (MBO/EU tests request theirs)
    """Docling replaced by the stored extraction of the same PDF (the pipeline after it is real)."""
    sources = {"BDSG.pdf": "bdsg", "MusterBauVerordnung.pdf": "mbo", "original.pdf": "eu"}

    def fake_extract(pdf, out_dir, do_ocr=False):
        name = (out_dir.parent / "meta.json")
        fn = json.loads(name.read_text())["filename"]
        src = BACKEND / "output" / {"BDSG.pdf": "bdsg", "MusterBauVerordnung.pdf": "mbo"}.get(fn, "eu")
        if not (src / "docling_raw.json").exists():
            pytest.skip(f"{src} extraction not available")
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "docling_raw.json").write_bytes((src / "docling_raw.json").read_bytes())
        (out_dir / "extracted.md").write_text("(extraction reused in tests)")
        return ExtractionResult(source=pdf, json_path=out_dir / "docling_raw.json", markdown_path=out_dir / "extracted.md",
                                status="success", pages=1, text_items=1, tables=0, warnings=[])  # fmt: skip

    monkeypatch.setattr(pl, "extract_pdf", fake_extract)
    return sources


def wait(c, doc):
    for _ in range(600):
        s = c.get(f"/api/documents/{doc}/status").json()
        if s["status"] in ("completed", "failed"):
            return s
        time.sleep(0.1)
    raise AssertionError(s)


def processed(c, pdf: Path, mode: str, name: str | None = None) -> str:
    doc = c.post("/api/documents", files={"file": (name or pdf.name, pdf.read_bytes(), "application/pdf")}).json()["id"]
    c.post(f"/api/documents/{doc}/process", json={"mode": mode})
    s = wait(c, doc)
    assert s["status"] == "completed", s
    return doc


@pytest.fixture()
def bdsg(tmp_path, fake_docling):
    app = create_app(settings(tmp_path), run_pipeline)
    with TestClient(app) as c:
        doc = processed(c, BACKEND / "data" / "input" / "BDSG.pdf", "german_law")
        yield c, doc, tmp_path / "storage" / "documents" / doc


def correct(c, doc, base, element, field, value, note=None):
    return c.post(f"/api/documents/{doc}/review/corrections",
                  json={"base_revision": base, "element_id": element, "field": field, "value": value, "note": note})  # fmt: skip


# ---- initial state ----------------------------------------------------------------------------------------------
def test_initial_review_state_and_revision_zero(bdsg):
    c, doc, d = bdsg
    r = c.get(f"/api/documents/{doc}/review").json()
    assert (r["state"], r["review_revision"], r["model_revision"]) == ("pending_review", 0, 0)
    assert r["validation"]["xsd_valid"] is True and r["validation"]["blocking_errors"] == []
    assert len(r["uncertain_element_ids"]) == 19 and r["unresolved_uncertain_ids"] == r["uncertain_element_ids"]
    assert r["can_approve"] is False and r["structural_editing_supported"] is False
    rev0 = c.get(f"/api/documents/{doc}/review/revisions/0/xml").content
    assert rev0 == c.get(f"/api/documents/{doc}/artifacts/akn_xml").content  # regenerated revision 0 == pipeline export
    assert c.get(f"/api/documents/{doc}/status").json()["status"] == "completed"  # job state is separate


def test_json_and_xml_are_regenerated_from_the_same_reviewed_model(bdsg):
    c, doc, d = bdsg
    assert c.get(f"/api/documents/{doc}/review").json()["validation"]["json_valid"] is True  # creates revision 0
    r0 = c.get(f"/api/documents/{doc}/review/revisions/0/json").content
    assert r0 == c.get(f"/api/documents/{doc}/artifacts/legal_json").content  # review data never enters document.json
    r = correct(c, doc, 0, PAR2, "content_text", "korrigierter Text").json()
    assert r["validation"]["json_valid"] is True and r["validation"]["blocking_errors"] == []
    js = json.loads(c.get(f"/api/documents/{doc}/review/revisions/1/json").content)
    stack = list(js["structure"])
    while stack:
        n = stack.pop()
        if n["id"] == PAR2:
            assert n["text"] == "korrigierter Text"
        stack.extend(n.get("children", []))
    rep = c.get(f"/api/documents/{doc}/review/revisions/1/json_validation").json()
    v = c.get(f"/api/documents/{doc}/review/revisions/1/review_validation").json()
    assert rep["model_sha256"] == v["model_sha256"] == sha(d / "review" / "revisions" / "1" / "effective_model.json")  # one model state
    assert rep["json_sha256"] == v["json_sha256"] and rep["valid"]


# ---- corrections ------------------------------------------------------------------------------------------------------
def test_correction_creates_new_revision_and_preserves_originals(bdsg):
    c, doc, d = bdsg
    originals = {p: sha(p) for p in (d / "original.pdf", d / "artifacts" / "docling_raw.json", d / "artifacts" / "document_model.json",
                                     d / "artifacts" / "document_akn.xml")}  # fmt: skip
    before = DocumentModel.model_validate(c.get(f"/api/documents/{doc}/review/model").json())
    new = "Andere Rechtsvorschriften des Bundes über den Datenschutz gehen vor. [korrigiert]"
    r = correct(c, doc, 0, PAR2, "content_text", new, "OCR-Fehler").json()
    assert (r["state"], r["review_revision"], r["model_revision"]) == ("in_review", 1, 1)
    corr = r["corrections"][0]
    assert corr["element_id"] == PAR2 and corr["field"] == "content_text" and corr["corrected_value"] == new
    assert corr["original_value"] == before.by_id()[PAR2].content_text and corr["note"] == "OCR-Fehler"
    assert corr["timestamp"] and corr["review_revision"] == 1 and corr["model_revision"] == 1
    assert all(sha(p) == h for p, h in originals.items())  # PDF, Docling, original model and original XML untouched

    after = DocumentModel.model_validate(c.get(f"/api/documents/{doc}/review/model").json())
    el = after.by_id()[PAR2]
    assert el.content_text == new and el.original_text == before.by_id()[PAR2].original_text  # source text kept
    assert el.reviewed["fields"]["content_text"] == {"original": before.by_id()[PAR2].content_text, "corrected": new}
    assert el.reviewed["verbatim_from_source"] is False
    changed = [e.id for e in after.elements if e.model_dump(exclude={"content_text", "reviewed"}) != before.by_id()[e.id].model_dump(exclude={"content_text", "reviewed"}) or (e.id != PAR2 and e.content_text != before.by_id()[e.id].content_text)]  # fmt: skip
    assert changed == []  # nothing else changed
    assert after.review["model_revision"] == 1
    old0 = DocumentModel.model_validate(c.get(f"/api/documents/{doc}/review/model?revision=0").json())
    assert old0.by_id()[PAR2].content_text == before.by_id()[PAR2].content_text  # earlier revisions stay readable


def test_regenerated_xml_is_valid_and_traceable(bdsg):
    c, doc, d = bdsg
    new = "Text nach Prüfung durch die Fachabteilung."
    r = correct(c, doc, 0, PAR2, "content_text", new).json()
    v = r["validation"]
    assert v["model_revision"] == 1 and v["generated"] and v["xsd_valid"] and v["text_identical_to_reviewed_model"]
    assert v["corrected_elements"] == [PAR2] and v["uncorrected_text_differences"] == [] and v["blocking_errors"] == []
    xml = c.get(f"/api/documents/{doc}/review/revisions/1/xml").content
    root = etree.fromstring(xml)
    node = root.xpath(f"//*[@{ODOS.strip('{}') and 'odos:reviewed'}]", namespaces={"odos": ODOS.strip("{}")})
    assert len(node) == 2  # the paragraph and its text node
    p = next(n for n in node if n.tag == AKN + "p")
    assert p.text == new and p.get(ODOS + "reviewed") == "c1" and p.get(ODOS + "src") == "#/texts/97"
    rep = c.get(f"/api/documents/{doc}/review/revisions/1/validation").json()
    assert rep["valid"] is True and rep["errors"] == []
    tr = c.get(f"/api/documents/{doc}/review/revisions/1/traceability").json()
    entry = next(n for n in tr["nodes"] if n["model_id"] == PAR2)
    assert entry["reviewed"]["fields"]["content_text"]["corrected"] == new
    assert entry["original_text"].startswith("(2) Andere Rechtsvorschriften")  # source text, not the correction
    assert entry["content_text"] == new
    plain = next(n for n in tr["nodes"] if n["model_id"] == "doc/teil-1/kapitel-1/par-1/abs-3")
    assert "reviewed" not in plain
    exports = c.get(f"/api/documents/{doc}/review").json()["exports"]
    assert [(e["model_revision"], e["status"]) for e in exports] == [(0, "superseded"), (1, "current")]
    assert c.get(f"/api/documents/{doc}/review").json()["original_export_superseded"] is True


def test_title_and_marker_edits_change_only_display_not_ids(bdsg):
    c, doc, d = bdsg
    p1 = "doc/teil-1/kapitel-1/par-1"
    correct(c, doc, 0, p1, "title", "Anwendungsbereich dieses Gesetzes")
    r = correct(c, doc, 1, p1, "marker", "§ 1 (korr.)").json()
    root = etree.fromstring(c.get(f"/api/documents/{doc}/review/revisions/{r['model_revision']}/xml").content)
    art = root.xpath("//*[@eId='part_1__chp_1__art_1']")[0]  # same eId as before the edit
    assert art.find(AKN + "num").text == "§ 1 (korr.)" and art.find(AKN + "heading").text == "Anwendungsbereich dieses Gesetzes"
    assert r["validation"]["xsd_valid"] and r["validation"]["blocking_errors"] == []


def test_reverting_to_the_original_value_removes_the_annotation(bdsg):
    c, doc, d = bdsg
    orig = c.get(f"/api/documents/{doc}/review/model").json()
    original_text = next(e for e in orig["elements"] if e["id"] == PAR2)["content_text"]
    correct(c, doc, 0, PAR2, "content_text", "geändert")
    r = correct(c, doc, 1, PAR2, "content_text", original_text).json()
    assert r["model_revision"] == 2 and r["corrected_element_ids"] == [] and len(r["corrections"]) == 2
    el = next(e for e in c.get(f"/api/documents/{doc}/review/model").json()["elements"] if e["id"] == PAR2)
    assert "reviewed" not in el


# ---- conflicts and invalid edits ---------------------------------------------------------------------------------------
def test_stale_revision_is_rejected(bdsg):
    c, doc, d = bdsg
    assert correct(c, doc, 0, PAR2, "content_text", "erste Änderung").status_code == 200
    r = correct(c, doc, 0, "doc/teil-1/kapitel-1/par-1/abs-3", "content_text", "zweite Änderung (veraltet)")
    assert r.status_code == 409 and r.json()["code"] == "stale_revision" and r.json()["current_revision"] == 1
    assert c.post(f"/api/documents/{doc}/review/approve", json={"base_revision": 0}).json()["code"] == "stale_revision"
    assert len(c.get(f"/api/documents/{doc}/review").json()["corrections"]) == 1  # nothing was overwritten


@pytest.mark.parametrize("element,field,value,status,code", [
    (PAR2, "original_text", "x", 422, "original_text_immutable"),
    (PAR2, "parent_id", "doc", 422, "unsupported_structural_edit"),
    (PAR2, "children_ids", "[]", 422, "unsupported_structural_edit"),
    (PAR2, "type", "text", 422, "unsupported_structural_edit"),
    (PAR2, "number", "7", 422, "unsupported_structural_edit"),
    (PAR2, "colour", "red", 422, "invalid_field"),
    ("doc/does-not-exist", "content_text", "x", 404, "element_not_found"),
    ("doc", "content_text", "x", 422, "element_not_editable"),
    ("doc/toc/entry-2", "content_text", "x", 422, "element_not_editable"),  # a table
    (PAR2, "title", "x", 422, "field_not_applicable"),
    ("doc/teil-1/kapitel-1/par-1/abs-1/txt-1", "marker", "(9)", 422, "field_not_applicable"),
    ("doc/teil-1/kapitel-1/par-1", "content_text", "x", 422, "edit_title_instead"),
    ("doc/teil-1/kapitel-1/par-1", "title", "   ", 422, "empty_value"),
    (PAR2, "content_text", "", 422, "empty_value"),
    (PAR2, "marker", "(2)\\n(3)".replace("\\n", "\n"), 422, "invalid_marker"),
    (PAR2, "content_text", "bad \x0c char", 422, "invalid_characters"),
    (PAR2, "marker", "(2)", 422, "no_change"),
])  # fmt: skip
def test_invalid_and_structural_edits_are_rejected(bdsg, element, field, value, status, code):
    c, doc, d = bdsg
    r = correct(c, doc, 0, element, field, value)
    assert r.status_code == status and r.json()["code"] == code, r.json()
    assert c.get(f"/api/documents/{doc}/review").json()["review_revision"] == 0  # nothing stored


# ---- approval gating -----------------------------------------------------------------------------------------------------
def confirm_all(c, doc):
    r = c.get(f"/api/documents/{doc}/review").json()
    for el in r["unresolved_uncertain_ids"]:
        r = c.post(f"/api/documents/{doc}/review/confirmations", json={"base_revision": r["review_revision"], "element_id": el}).json()
    return r


def test_approval_requires_all_uncertain_elements_checked(bdsg):
    c, doc, d = bdsg
    r = correct(c, doc, 0, PAR2, "content_text", "korrigierter Text").json()
    a = c.post(f"/api/documents/{doc}/review/approve", json={"base_revision": r["review_revision"]})
    assert a.status_code == 409 and a.json()["code"] == "approval_blocked"
    assert any("19 uncertain" in b for b in a.json()["blockers"])
    assert c.post(f"/api/documents/{doc}/review/confirmations", json={"base_revision": 1, "element_id": PAR2}).json()["code"] == "not_uncertain"  # fmt: skip
    r = confirm_all(c, doc)
    assert r["unresolved_uncertain_ids"] == [] and r["can_approve"] is True and r["model_revision"] == 1
    dup = c.post(f"/api/documents/{doc}/review/confirmations", json={"base_revision": r["review_revision"], "element_id": r["uncertain_element_ids"][0]})  # fmt: skip
    assert dup.json()["code"] == "already_confirmed"
    ok = c.post(f"/api/documents/{doc}/review/approve", json={"base_revision": r["review_revision"], "note": "geprüft"}).json()
    ap = ok["approval"]
    assert ok["state"] == "approved" and ap["model_revision"] == 1 and ap["corrections"] == 1 and ap["confirmed_uncertain"] == 19
    assert ap["model_sha256"] == sha(d / "review" / "revisions" / "1" / "effective_model.json")
    assert ap["xml_sha256"] == hashlib.sha256(c.get(f"/api/documents/{doc}/review/revisions/1/xml").content).hexdigest()
    assert [e["status"] for e in ok["exports"]] == ["superseded", "approved"]
    # approved revision is locked
    locked = correct(c, doc, ok["review_revision"], PAR2, "content_text", "nach Freigabe")
    assert locked.status_code == 409 and locked.json()["code"] == "approved_locked"
    re_ = c.post(f"/api/documents/{doc}/review/reopen", json={"base_revision": ok["review_revision"]}).json()
    assert re_["state"] == "in_review" and re_["approval"] is None and re_["previous_approvals"][0]["model_revision"] == 1
    r2 = correct(c, doc, re_["review_revision"], PAR2, "content_text", "nach erneuter Prüfung").json()
    assert r2["model_revision"] == 2 and r2["can_approve"] is True  # confirmations persist across revisions


def test_failed_validation_blocks_approval(bdsg, monkeypatch):
    c, doc, d = bdsg
    import odos.akn.german_artifacts as cli
    from odos.akn.validate import validate_xml as real

    def broken(xml, *a, **k):
        v = real(xml, *a, **k)
        v.valid = False
        return v

    monkeypatch.setattr(cli, "validate_xml", broken)
    r = correct(c, doc, 0, PAR2, "content_text", "Text, dessen Export als ungültig simuliert wird").json()
    monkeypatch.undo()
    assert r["validation"]["xsd_valid"] is False and any("not valid against the official OASIS XSD" in b for b in r["validation"]["blocking_errors"])  # fmt: skip
    r = confirm_all(c, doc)
    assert r["can_approve"] is False
    a = c.post(f"/api/documents/{doc}/review/approve", json={"base_revision": r["review_revision"]})
    assert a.status_code == 409 and any("XSD" in b for b in a.json()["blockers"])


def test_request_changes(bdsg):
    c, doc, d = bdsg
    r = c.post(f"/api/documents/{doc}/review/request-changes", json={"base_revision": 0, "note": "§ 2 prüfen"}).json()
    assert r["state"] == "changes_requested" and r["history"][-1]["detail"] == "§ 2 prüfen"
    r = correct(c, doc, r["review_revision"], PAR2, "content_text", "nach Änderungswunsch").json()
    assert r["state"] == "in_review"


# ---- persistence and lifecycle ----------------------------------------------------------------------------------------------
def test_review_persists_across_api_restarts(tmp_path, fake_docling):
    with TestClient(create_app(settings(tmp_path), run_pipeline)) as c:
        doc = processed(c, BACKEND / "data" / "input" / "BDSG.pdf", "german_law")
        correct(c, doc, 0, PAR2, "content_text", "persistiert")
        r = confirm_all(c, doc)
        r = c.post(f"/api/documents/{doc}/review/approve", json={"base_revision": r["review_revision"]}).json()
    with TestClient(create_app(settings(tmp_path), run_pipeline)) as c2:  # a new API process
        r2 = c2.get(f"/api/documents/{doc}/review").json()
        assert r2["state"] == "approved" and r2["approval"] == r["approval"] and r2["corrections"] == r["corrections"]
        el = next(e for e in c2.get(f"/api/documents/{doc}/review/model").json()["elements"] if e["id"] == PAR2)
        assert el["content_text"] == "persistiert"


def test_reprocessing_archives_the_review(bdsg):
    c, doc, d = bdsg
    correct(c, doc, 0, PAR2, "content_text", "wird archiviert")
    c.post(f"/api/documents/{doc}/process", json={"mode": "german_law"})
    wait(c, doc)
    r = c.get(f"/api/documents/{doc}/review").json()
    assert r["review_revision"] == 0 and r["corrections"] == []
    archived = list((d / "review_archive").iterdir())
    assert len(archived) == 1 and json.loads((archived[0] / "corrections.json").read_text())[0]["corrected_value"] == "wird archiviert"


def test_revisions_are_write_once(tmp_path):
    store = FileReviewStore(lambda doc_id: tmp_path / doc_id)
    (tmp_path / "d1").mkdir()
    a = store.staging_dir("d1")
    (a / "x").write_text("1")
    store.publish_revision("d1", 1, a)
    b = store.staging_dir("d1")
    with pytest.raises(FileExistsError):
        store.publish_revision("d1", 1, b)


def test_review_requires_a_completed_structured_document(tmp_path, fake_docling):
    with TestClient(create_app(settings(tmp_path), run_pipeline)) as c:
        doc = processed(c, BACKEND / "data" / "input" / "BDSG.pdf", "extract_only")
        r = c.get(f"/api/documents/{doc}/review")
        assert r.status_code == 409 and r.json()["code"] == "no_structure"
        new = c.post("/api/documents", files={"file": ("BDSG.pdf", (BACKEND / "data" / "input" / "BDSG.pdf").read_bytes(), "application/pdf")}).json()["id"]  # fmt: skip
        assert c.get(f"/api/documents/{new}/review").json()["code"] == "not_ready"


# ---- MBO and EU ---------------------------------------------------------------------------------------------------------------
def test_mbo_marker_correction_validates(tmp_path, fake_docling, mbo_pdf, mbo_raw_json):
    with TestClient(create_app(settings(tmp_path), run_pipeline)) as c:
        doc = processed(c, mbo_pdf, "german_law")
        r = c.get(f"/api/documents/{doc}/review").json()
        assert r["validation"]["xsd_valid"] and len(r["uncertain_element_ids"]) == 36  # 35 footnote anchors proven, 2 page numbers out, +1 hyphen
        par23 = "doc/teil-3/abschnitt-3/par-23"  # printed without '§' in the source; a reviewer may add it
        r = correct(c, doc, 0, par23, "marker", "§ 23", "§-Zeichen fehlt im PDF").json()
        assert r["validation"]["xsd_valid"] and r["validation"]["corrected_elements"] == [par23]
        el = next(e for e in c.get(f"/api/documents/{doc}/review/model").json()["elements"] if e["id"] == par23)
        assert el["marker"] == "§ 23" and el["original_text"] == "23 Zertifizierung"  # source text unchanged


def test_eu_correction_keeps_spans_and_validates(tmp_path, fake_docling, eu_pdf, eu_raw_json):
    pdf = eu_pdf  # its Docling extraction (output/eu, eu_raw_json) is reused by fake_docling
    with TestClient(create_app(settings(tmp_path), run_pipeline)) as c:
        doc = processed(c, pdf, "eu_legislation", name="EuMaschinenbauverordnung.pdf")
        r = c.get(f"/api/documents/{doc}/review").json()
        assert r["validation"]["xsd_valid"] and len(r["uncertain_element_ids"]) == 3
        el_id = "doc/chp-2/art-11/para-3"  # a segment of a split Docling item
        r = correct(c, doc, 0, el_id, "content_text", "Korrigierter Absatztext. [geprüft]").json()
        v = r["validation"]
        assert v["xsd_valid"] and v["text_identical_to_reviewed_model"] and v["uncorrected_text_differences"] == []
        tr = c.get(f"/api/documents/{doc}/review/revisions/1/traceability").json()
        entry = next(n for n in tr["nodes"] if n["model_id"] == el_id)
        assert entry["source_spans"][0] == {**entry["source_spans"][0], "ref": "#/texts/373", "start": 659, "end": 1280}
        assert entry["reviewed"]["fields"]["content_text"]["corrected"].endswith("[geprüft]")
        assert entry["original_text"].startswith("(3) ") and "[geprüft]" not in entry["original_text"]  # the source text is untouched
        text = c.get(f"/api/documents/{doc}/review/revisions/1/text_report").json()
        assert text["same_order_and_text"] and text["document_order_preserved"]
