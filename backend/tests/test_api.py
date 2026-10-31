import json
import threading
from collections import Counter
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from odos.api.app import create_app
from odos.api.config import Settings
from odos.api.schemas import DocumentStatus, JobStatus
from odos.document_model import DocumentModel
from odos.pipeline import Outcome, PipelineResult, run_pipeline

BACKEND = Path(__file__).resolve().parents[1]
BDSG = BACKEND / "data" / "input" / "BDSG.pdf"
MINI_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 200]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 56>>stream\nBT /F1 14 Tf 20 100 Td (Einkaufsliste: Brot und Milch) Tj ET\nendstream\nendobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\ntrailer<</Root 1 0 R/Size 6>>\n%%EOF\n"
)


def settings(tmp_path, **kw):
    return Settings(storage_dir=tmp_path / "storage", max_upload_mb=kw.pop("max_upload_mb", 5), max_queue=kw.pop("max_queue", 4), workers=1, cors_origins=())  # fmt: skip


def fake_pipeline(gate: threading.Event | None = None, outcome=Outcome.COMPLETED, fail=False):
    def run(pdf, out_dir, mode, retrieval_date, progress=lambda s: None):
        progress("extracting")
        if gate is not None:
            gate.wait(10)
        if fail:
            raise RuntimeError("boom")
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "docling_raw.json").write_text("{}")
        return PipelineResult(outcome=outcome, message="msg", summary={"pages": 1})

    return run


@pytest.fixture()
def client(tmp_path):
    with TestClient(create_app(settings(tmp_path), fake_pipeline())) as c:
        yield c


def upload(c, name="a.pdf", data=MINI_PDF):
    return c.post("/api/documents", files={"file": (name, data, "application/pdf")})


def wait(c, doc_id, states=("completed", "failed"), timeout=300):
    end = time.time() + timeout
    while time.time() < end:
        s = c.get(f"/api/documents/{doc_id}/status").json()
        if s["status"] in states:
            return s
        time.sleep(0.1)
    raise AssertionError(f"timeout, last: {s}")


# ---- upload and storage -------------------------------------------------------------------------
def test_upload_returns_uuid_and_stores_file(client, tmp_path):
    r = upload(client, "Mein Gesetz.pdf")
    assert r.status_code == 201
    body = r.json()
    DocumentStatus.model_validate(body)
    import uuid

    assert str(uuid.UUID(body["id"])) == body["id"]
    assert body["status"] == "uploaded" and body["size_bytes"] == len(MINI_PDF)
    assert (tmp_path / "storage" / "documents" / body["id"] / "original.pdf").read_bytes() == MINI_PDF
    assert client.get("/api/documents").json()[0]["id"] == body["id"]


@pytest.mark.parametrize("name,data,code", [
    ("a.txt", MINI_PDF, "unsupported_file_type"),
    ("a.pdf", b"not a pdf at all", "not_a_pdf"),
    ("a.pdf", b"", "not_a_pdf"),
])  # fmt: skip
def test_upload_rejects_wrong_type(client, name, data, code):
    r = upload(client, name, data)
    assert r.status_code == 415 and r.json()["code"] == code


def test_upload_size_limit_and_cleanup(tmp_path):
    with TestClient(create_app(settings(tmp_path, max_upload_mb=0.001), fake_pipeline())) as c:
        r = upload(c, data=b"%PDF-" + b"x" * 5000)
        assert r.status_code == 413 and r.json()["code"] == "file_too_large"
        assert list((tmp_path / "storage" / "documents").iterdir()) == []  # partial upload removed


def test_unsafe_filename_and_ids_cannot_escape_storage(client, tmp_path):
    r = upload(client, "../../../evil.pdf")
    assert r.status_code == 201 and "/" not in r.json()["filename"] and r.json()["filename"] == "evil.pdf"
    assert not (tmp_path / "evil.pdf").exists()
    doc = r.json()["id"]
    for bad in ["..", "..%2F..%2Fetc", "not-a-uuid", doc.upper(), "00000000-0000-0000-0000-000000000000"]:
        assert client.get(f"/api/documents/{bad}/status").status_code == 404
    for t in ["meta", "../meta.json", "original", "docling_raw"]:
        assert client.get(f"/api/documents/{doc}/artifacts/{t}").status_code == 404


def test_original_pdf_served_inline(client):
    doc = upload(client).json()["id"]
    r = client.get(f"/api/documents/{doc}/original")
    assert r.status_code == 200 and r.content == MINI_PDF and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("inline")


# ---- job lifecycle -----------------------------------------------------------------------------------------
def test_process_requires_explicit_mode(client):
    doc = upload(client).json()["id"]
    assert client.post(f"/api/documents/{doc}/process", json={}).status_code == 422
    assert client.post(f"/api/documents/{doc}/process", json={"mode": "magic"}).status_code == 422


def test_states_queued_processing_completed_and_conflict(tmp_path):
    gate = threading.Event()
    with TestClient(create_app(settings(tmp_path), fake_pipeline(gate))) as c:
        a, b = upload(c).json()["id"], upload(c).json()["id"]
        assert c.post(f"/api/documents/{a}/process", json={"mode": "german_law"}).status_code == 202
        wait(c, a, ("processing",))
        for _ in range(100):
            if c.get(f"/api/documents/{a}/status").json()["stage"] == "extracting":
                break
            time.sleep(0.05)
        else:
            raise AssertionError("never reached stage 'extracting'")
        assert c.post(f"/api/documents/{a}/process", json={"mode": "german_law"}).status_code == 409
        c.post(f"/api/documents/{b}/process", json={"mode": "extract_only"})
        assert c.get(f"/api/documents/{b}/status").json()["status"] == "queued"  # single worker is busy
        assert c.get(f"/api/documents/{a}/structure").json()["code"] == "not_ready"
        gate.set()
        done = wait(c, a)
        assert done["status"] == "completed" and done["outcome"] == "completed" and done["mode"] == "german_law"
        assert [x["type"] for x in done["artifacts"]] == ["docling_raw"]
        assert wait(c, b)["status"] == "completed"


def test_queue_is_bounded(tmp_path):
    gate = threading.Event()
    with TestClient(create_app(settings(tmp_path, max_queue=1), fake_pipeline(gate))) as c:
        a, b = upload(c).json()["id"], upload(c).json()["id"]
        assert c.post(f"/api/documents/{a}/process", json={"mode": "german_law"}).status_code == 202
        r = c.post(f"/api/documents/{b}/process", json={"mode": "german_law"})
        assert r.status_code == 429 and r.json()["code"] == "queue_full"
        gate.set()
        wait(c, a)


def test_failed_job_reports_error(tmp_path):
    with TestClient(create_app(settings(tmp_path), fake_pipeline(fail=True))) as c:
        doc = upload(c).json()["id"]
        c.post(f"/api/documents/{doc}/process", json={"mode": "german_law"})
        s = wait(c, doc)
        assert s["status"] == "failed" and "boom" in s["error"] and s["finished_at"]
        assert c.get(f"/api/documents/{doc}/structure").status_code == 409


def test_interrupted_jobs_are_marked_failed_on_restart(tmp_path):
    with TestClient(create_app(settings(tmp_path), fake_pipeline())) as c:
        doc = upload(c).json()["id"]
        c.app.state.store.update(doc, status=JobStatus.PROCESSING)
    with TestClient(create_app(settings(tmp_path), fake_pipeline())) as c2:
        s = c2.get(f"/api/documents/{doc}/status").json()
        assert s["status"] == "failed" and "restart" in s["error"]


def test_unsupported_outcome_gives_explanation_not_structure(tmp_path):
    with TestClient(create_app(settings(tmp_path), fake_pipeline(outcome=Outcome.UNSUPPORTED))) as c:
        doc = upload(c).json()["id"]
        c.post(f"/api/documents/{doc}/process", json={"mode": "german_law"})
        wait(c, doc)
        r = c.get(f"/api/documents/{doc}/structure")
        assert r.status_code == 409 and r.json()["code"] == "unsupported_document_type"


# ---- real pipeline ---------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def real_client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("real")
    with TestClient(create_app(settings(tmp, max_upload_mb=50), run_pipeline)) as c:
        yield c


def test_real_non_law_pdf_is_unsupported_in_german_law_mode(real_client):
    doc = upload(real_client, "einkauf.pdf", MINI_PDF).json()["id"]
    real_client.post(f"/api/documents/{doc}/process", json={"mode": "german_law"})
    s = wait(real_client, doc)
    assert s["status"] == "completed" and s["outcome"] == "unsupported"
    assert "German legislation" in s["message"]
    types = {a["type"] for a in s["artifacts"]}
    assert types == {"docling_raw", "extracted_md", "reading_order_evidence"}  # PDF text layer only: no model, no XML
    r = real_client.get(f"/api/documents/{doc}/structure")
    assert r.status_code == 409 and r.json()["code"] == "unsupported_document_type"
    assert real_client.get(f"/api/documents/{doc}/artifacts/akn_xml").status_code == 404


def test_real_extract_only_mode_makes_no_legal_claims(real_client):
    doc = upload(real_client, "einkauf.pdf", MINI_PDF).json()["id"]
    real_client.post(f"/api/documents/{doc}/process", json={"mode": "extract_only"})
    s = wait(real_client, doc)
    assert s["outcome"] == "completed" and {a["type"] for a in s["artifacts"]} == {"docling_raw", "extracted_md"}
    assert real_client.get(f"/api/documents/{doc}/structure").json()["code"] == "no_structure"
    assert "Einkaufsliste" in real_client.get(f"/api/documents/{doc}/artifacts/extracted_md").text


def test_end_to_end_with_real_bdsg(real_client):
    data = BDSG.read_bytes()
    doc = upload(real_client, "BDSG.pdf", data).json()["id"]
    assert real_client.post(f"/api/documents/{doc}/process", json={"mode": "german_law"}).status_code == 202
    s = wait(real_client, doc)
    assert s["status"] == "completed" and s["outcome"] == "completed", s
    assert s["summary"]["paragraphs"] == 86 and s["summary"]["akn_xsd_valid"] is True
    assert s["summary"]["akn_text_identical"] is True and s["summary"]["pages"] == 45

    model = DocumentModel.model_validate(real_client.get(f"/api/documents/{doc}/structure").json())
    assert len(model.of_type(__import__("odos.document_model", fromlist=["x"]).ElementType.PARAGRAPH)) == 86
    assert any(e.uncertain for e in model.elements) and model.warnings  # indicators preserved
    assert model.by_id()["doc/teil-1/kapitel-1/par-1"].pages == [5]

    assert real_client.get(f"/api/documents/{doc}/original").content == data
    types = {a["type"] for a in s["artifacts"]}
    assert types == {"docling_raw", "extracted_md", "document_model", "legal_json", "legal_json_validation_report",
                     "validation_report", "akn_xml", "akn_validation_report", "akn_traceability", "reading_order_evidence"}  # fmt: skip
    assert s["summary"]["json_valid"] is True and s["summary"]["json_text_identical"] is True
    xml = real_client.get(f"/api/documents/{doc}/artifacts/akn_xml")
    assert xml.headers["content-type"].startswith("application/xml") and "attachment" in xml.headers["content-disposition"]
    rep = real_client.get(f"/api/documents/{doc}/artifacts/akn_validation_report").json()
    assert rep["valid"] is True and rep["errors"] == []
    assert "all 86 §" in xml.text[:600]  # declared as a prototype body conversion, not an excerpt of §§ 1-2
    # the CLI's checked-in-by-test excerpt behaviour is untouched
    assert real_client.get(f"/api/documents/{doc}/artifacts/akn_traceability").json()["excerpt"]["scope"] == "all-paragraphs-of-body"


# ---- EU legislation mode ---------------------------------------------------------------------------------------------
def test_eu_mode_is_accepted_and_listed(client):
    assert "eu_legislation" in client.get("/api/health").json()["modes"]
    doc = upload(client).json()["id"]
    r = client.post(f"/api/documents/{doc}/process", json={"mode": "eu_legislation"})
    assert r.status_code == 202 and r.json()["mode"] == "eu_legislation"
    assert wait(client, doc)["mode"] == "eu_legislation"
    assert client.post(f"/api/documents/{doc}/process", json={"mode": "auto"}).status_code == 422


def test_real_non_eu_pdf_is_unsupported_in_eu_mode(real_client):
    doc = upload(real_client, "einkauf.pdf", MINI_PDF).json()["id"]
    real_client.post(f"/api/documents/{doc}/process", json={"mode": "eu_legislation"})
    s = wait(real_client, doc)
    assert s["outcome"] == "unsupported" and "EU article structure" in s["message"]
    assert {a["type"] for a in s["artifacts"]} == {"docling_raw", "extracted_md", "reading_order_evidence"}
    assert real_client.get(f"/api/documents/{doc}/structure").json()["code"] == "unsupported_document_type"


def test_end_to_end_eu_machinery_regulation(real_client, eu_pdf):
    data = eu_pdf.read_bytes()
    doc = upload(real_client, "EuMaschinenbauverordnung.pdf", data).json()["id"]
    assert real_client.post(f"/api/documents/{doc}/process", json={"mode": "eu_legislation"}).status_code == 202
    s = wait(real_client, doc, timeout=900)
    assert s["status"] == "completed" and s["outcome"] == "completed", s
    sm = s["summary"]
    assert (sm["recitals"], sm["chapters"], sm["articles"], sm["annexes"]) == (86, 9, 54, 12)
    assert sm["source_accounting_exact"] is True and sm["pages"] == 102
    assert sm["akn_generated"] is True and sm["akn_xsd_valid"] is True and sm["akn_xsd_errors"] == 0
    assert sm["akn_text_identical"] is True and sm["akn_document_order_preserved"] is True and sm["akn_unmapped"] == 0
    assert "valid against the official OASIS XSD" in s["message"]
    assert {a["type"] for a in s["artifacts"]} == {"docling_raw", "extracted_md", "document_model", "validation_report",
                                                  "legal_json", "legal_json_validation_report", "akn_xml", "akn_validation_report", "akn_traceability", "akn_text_report",
                                                  "reading_order_evidence"}  # fmt: skip  (pages with overlapping boxes or unproven split boundaries)
    ev = real_client.get(f"/api/documents/{doc}/artifacts/reading_order_evidence").json()
    assert list(ev["pages"]) == ["24", "36"] and ev["error"] is None and ev["extractor"].startswith("pypdfium2")
    xml = real_client.get(f"/api/documents/{doc}/artifacts/akn_xml")
    assert xml.status_code == 200 and b'<act name="regulation"' in xml.content
    assert b"festgelegten Bedingungen \xc3\xbcbertragen." in xml.content  # Art. 47(1), reading order repaired
    assert real_client.get(f"/api/documents/{doc}/artifacts/akn_validation_report").json()["valid"] is True
    assert real_client.get(f"/api/documents/{doc}/artifacts/akn_text_report").json()["same_order_and_text"] is True
    assert real_client.get(f"/api/documents/{doc}/original").content == data

    body = real_client.get(f"/api/documents/{doc}/structure").json()
    assert body["profile"] == "eu_legislation" and body["metadata"]["document_number"] == "2023/1230"
    model = DocumentModel.model_validate(body)  # response is the Internal Document Model
    assert model.metadata.adoption_date == "2023-06-14"
    types = Counter(e["type"] for e in body["elements"])
    assert (types["recital"], types["article"], types["chapter"], types["annex"]) == (86, 54, 9, 12)
    split = [e for e in body["elements"] if e.get("source_spans")]
    assert len(split) == 25 and all(e["source_spans"][0]["bbox_scope"] == "docling_item" for e in split)  # 22 + Art. 47(1)-(3) repaired
    repaired = [e["id"] for e in split if "reading_order_repaired_from_pdf_text_layer" in e["hygiene_flags"]]
    assert repaired == ["doc/chp-7/art-47/para-1", "doc/chp-7/art-47/para-2", "doc/chp-7/art-47/para-3"]
    assert all(e["pages"] and e["provenance"] for e in body["elements"] if e["source_refs"])
    assert any(e["uncertain"] and e["uncertainty_reasons"] for e in body["elements"])
    # no unresolved structural warning; the verified valid exceptions are exposed as structure notes
    assert {w["code"] for w in body["warnings"]} == {"SENTENCE_SEGMENTATION_UNRESOLVED"}  # undecidable sentence ends only
    assert {n["category"] for n in body["structure_notes"]} == {"valid_structure"}
    rep = real_client.get(f"/api/documents/{doc}/artifacts/validation_report").json()
    assert rep["profile"] == "eu_legislation" and rep["accounting"]["exact"] is True


# ---- classification and routing ---------------------------------------------------------------------------------------
def test_upload_classifies_without_running_docling(tmp_path, monkeypatch):
    import odos.pipeline as pl

    monkeypatch.setattr(pl, "extract_pdf", lambda *a, **k: pytest.fail("Docling must not run at upload"))
    with TestClient(create_app(settings(tmp_path), fake_pipeline())) as c:
        body = upload(c, "BDSG.pdf", BDSG.read_bytes()).json()
        cl = c.get(f"/api/documents/{body['id']}/classification").json()
        assert cl["document_type"] == "german_law" and cl["suggested_processing_mode"] == "german_law"
        assert cl["supported"] and cl["confidence_band"] == "high" and cl["input"]["source"] == "pdf_text_layer"
        assert cl["evidence"] and all(e["source_ref"].startswith("pdf_text_layer:") for e in cl["evidence"] if e["source_ref"])
        assert cl["pdf_sha256"] and "not a probability" in cl["confidence_note"]
        assert (tmp_path / "storage" / "documents" / body["id"] / "classification.json").exists()  # stored with the document


def test_stored_classification_is_reused_and_refresh_recomputes(tmp_path, monkeypatch):
    import odos.api.app as app_mod

    with TestClient(create_app(settings(tmp_path), fake_pipeline())) as c:
        doc = upload(c, "BDSG.pdf", BDSG.read_bytes()).json()["id"]
        calls = []
        orig = app_mod.lines_from_pdf
        monkeypatch.setattr(app_mod, "lines_from_pdf", lambda p: (calls.append(p), orig(p))[1])
        c.get(f"/api/documents/{doc}/classification")
        c.get(f"/api/documents/{doc}/classification")
        assert calls == []  # served from the stored result
        c.get(f"/api/documents/{doc}/classification?refresh=true")
        assert len(calls) == 1
        assert c.get("/api/documents/00000000-0000-0000-0000-000000000000/classification").status_code == 404


def test_classification_prefers_an_existing_docling_output(tmp_path):
    with TestClient(create_app(settings(tmp_path), fake_pipeline())) as c:
        doc = upload(c, "BDSG.pdf", BDSG.read_bytes()).json()["id"]
        art = tmp_path / "storage" / "documents" / doc / "artifacts"
        art.mkdir(exist_ok=True)
        (art / "docling_raw.json").write_bytes((BACKEND / "output" / "bdsg" / "docling_raw.json").read_bytes())
        cl = c.get(f"/api/documents/{doc}/classification?refresh=true").json()
        assert cl["input"]["source"] == "docling" and cl["document_type"] == "german_law"


def test_routing_records_suggestion_and_manual_override(tmp_path):
    with TestClient(create_app(settings(tmp_path), fake_pipeline())) as c:
        doc = upload(c, "BDSG.pdf", BDSG.read_bytes()).json()["id"]
        r = c.post(f"/api/documents/{doc}/process", json={"mode": "german_law"}).json()
        assert r["routing"] == {"document_type": "german_law", "suggested_mode": "german_law", "chosen_mode": "german_law",
                                "manual_override": False, "warnings": []}  # fmt: skip
        wait(c, doc)
        r = c.post(f"/api/documents/{doc}/process", json={"mode": "eu_legislation"}).json()  # explicit override is allowed
        assert r["mode"] == "eu_legislation" and r["routing"]["manual_override"] is True
        assert "classified as german_law" in r["routing"]["warnings"][0]
        assert wait(c, doc)["routing"]["chosen_mode"] == "eu_legislation"  # kept after the job finishes


def test_unknown_document_suggests_extraction_only(tmp_path):
    with TestClient(create_app(settings(tmp_path), fake_pipeline())) as c:
        doc = upload(c).json()["id"]  # MINI_PDF: a shopping list
        cl = c.get(f"/api/documents/{doc}/classification").json()
        assert cl["document_type"] == "unknown" and cl["suggested_processing_mode"] == "extract_only" and cl["supported"] is False
        assert cl["support_status"] == "unsupported"


def test_docling_runs_once_per_pdf_across_modes(tmp_path, monkeypatch):
    """Changing the processing mode reuses the stored extraction instead of converting the PDF again."""
    import odos.pipeline as pl
    from odos.extraction import ExtractionResult

    calls = []
    src = BACKEND / "output" / "bdsg"

    def fake_extract(pdf, out_dir, do_ocr=False):
        calls.append(pdf)
        out_dir.mkdir(parents=True, exist_ok=True)
        for n in ("docling_raw.json", "extracted.md"):
            (out_dir / n).write_bytes((src / n).read_bytes())
        return ExtractionResult(source=pdf, json_path=out_dir / "docling_raw.json", markdown_path=out_dir / "extracted.md",
                                status="success", pages=45, text_items=875, tables=5, warnings=[])  # fmt: skip

    monkeypatch.setattr(pl, "extract_pdf", fake_extract)
    with TestClient(create_app(settings(tmp_path), run_pipeline)) as c:
        doc = upload(c, "BDSG.pdf", BDSG.read_bytes()).json()["id"]
        c.post(f"/api/documents/{doc}/process", json={"mode": "german_law"})
        first = wait(c, doc)
        assert first["status"] == "completed" and first["summary"]["extraction_reused"] is False
        c.post(f"/api/documents/{doc}/process", json={"mode": "extract_only"})
        second = wait(c, doc)
        assert second["summary"]["extraction_reused"] is True and "akn_xml" not in {a["type"] for a in second["artifacts"]}
        assert {"docling_raw", "extracted_md"} <= {a["type"] for a in second["artifacts"]}  # kept
        c.post(f"/api/documents/{doc}/process", json={"mode": "german_law"})
        third = wait(c, doc)
        assert third["summary"]["extraction_reused"] is True and third["summary"]["akn_xsd_valid"] is True
        assert len(calls) == 1  # one Docling conversion for three runs
        # a different PDF with the same document directory content never reuses a stale extraction
        art = tmp_path / "storage" / "documents" / doc / "artifacts"
        meta = json.loads((art / "extraction.json").read_text())
        meta["pdf_sha256"] = "0" * 64
        (art / "extraction.json").write_text(json.dumps(meta))
        c.post(f"/api/documents/{doc}/process", json={"mode": "extract_only"})
        assert wait(c, doc)["summary"]["extraction_reused"] is False and len(calls) == 2
