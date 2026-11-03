"""The web API (odos.api): upload, job lifecycle, result files, download, errors.

The fast tests replace only the Docling conversion: they run the real document type detection, parsing and export
(`_run_structured`) on the synthetic German law's and EU regulation's Docling JSON. The slow ones run the whole pipeline: the synthetic PDF through real Docling,
and the partner PDFs (MBO, Regulation (EU) 2023/1230), which skip with the reason when they are not available."""

import dataclasses
import json
import shutil
import time

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

import odos.api as api
from odos.legal_json.artifacts import published_schema
from odos.pipeline import _run_structured
from odos.parsing.profiles import PROFILES


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ODOS_STORAGE_DIR", str(tmp_path / "storage"))
    with TestClient(api.app) as c:
        yield c


@pytest.fixture
def without_docling(monkeypatch, synthetic_german_raw_json):
    """run_pipeline with a synthetic Docling JSON in place of the Docling conversion (the synthetic German law; a test
    may point the returned dict's "dir" at another one); the rest is real."""
    source = {"dir": synthetic_german_raw_json.parent}

    def run(pdf, out_dir, progress):
        progress("extracting")
        for f in ("docling_raw.json", "pdf_text_lines.json"):
            if (source["dir"] / f).exists():
                shutil.copy(source["dir"] / f, out_dir / f)
        return _run_structured(list(PROFILES.values()), out_dir, {"pages": 3, "docling_warnings": ["/private/path/x.pdf: note"]}, progress)

    monkeypatch.setattr(api, "run_pipeline", run)
    return source


def upload(client, data=b"%PDF-1.4 test", name="Gesetz.pdf"):
    return client.post("/api/jobs", files={"file": (name, data, "application/pdf")})


def wait(client, job_id, timeout=900):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] not in ("queued", "processing"):
            return job
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} did not finish")


def test_job_lifecycle_and_results(client, without_docling, tmp_path):
    res = upload(client)
    assert res.status_code == 202
    job = res.json()
    assert (job["status"], job["filename"]) == ("queued", "Gesetz.pdf")

    done = wait(client, job["id"])
    assert done["status"] == "completed" and done["stage"] is None
    assert done["summary"]["json_schema_valid"] and done["summary"]["paragraphs"] == 5
    assert done["summary"]["docling_warnings"] == 1  # counted, never quoted (it may name a server path)
    assert not (tmp_path / "storage" / job["id"] / "source.pdf").exists()  # the upload is not kept

    model = client.get(f"/api/jobs/{job['id']}/files/document_model.json").json()
    legal = client.get(f"/api/jobs/{job['id']}/files/document.json").json()
    assert not list(Draft202012Validator(published_schema()).iter_errors(legal))
    # every Legal JSON node is a model element with provenance the PDF viewer can highlight
    by_id = {e["id"]: e for e in model["elements"]}
    walk = lambda ns: [m for n in ns for m in [n, *walk(n.get("children", []))]]
    nodes = walk(legal["structure"])
    assert nodes and all(n["id"] in by_id and n.get("pages", []) == by_id[n["id"]]["pages"] for n in nodes)
    abs1 = by_id["doc/teil-1/kapitel-1/par-1/abs-1"]
    assert abs1["pages"] and abs1["provenance"][0]["bbox"]

    dl = client.get(f"/api/jobs/{job['id']}/files/document.json?download=true")
    assert dl.headers["content-disposition"] == 'attachment; filename="Gesetz.legal.json"'
    assert dl.json() == legal and "nativeType" in dl.text and "germanType" not in dl.text  # canonical field names

    assert client.delete(f"/api/jobs/{job['id']}").status_code == 204
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404
    assert not (tmp_path / "storage" / job["id"]).exists()


def test_eu_legislation_is_recognized_from_its_structure(client, without_docling, synthetic_eu_raw_json):
    without_docling["dir"] = synthetic_eu_raw_json.parent
    job = wait(client, upload(client).json()["id"])
    assert job["status"] == "completed" and job["summary"]["articles"] == 3 and "paragraphs" not in job["summary"]
    assert client.get(f"/api/jobs/{job['id']}/files/document.json").json()["legalSystem"] == "eu"


def test_unrecognized_document_is_refused(client, without_docling, tmp_path):
    raw = json.loads((without_docling["dir"] / "docling_raw.json").read_text())
    for t in raw["texts"]:  # the same items without any legal heading
        t["text"] = t["orig"] = "Lorem ipsum"
    (tmp_path / "plain").mkdir()
    (tmp_path / "plain" / "docling_raw.json").write_text(json.dumps(raw))
    without_docling["dir"] = tmp_path / "plain"
    job = wait(client, upload(client).json()["id"])
    assert job["status"] == "unsupported" and "could not be recognized" in job["message"]
    assert client.get(f"/api/jobs/{job['id']}/files/document.json").status_code == 409


def test_ambiguous_document_is_refused(client, without_docling, monkeypatch):
    for key, profile in PROFILES.items():  # both profiles claim the document
        monkeypatch.setitem(PROFILES, key, dataclasses.replace(profile, has_structure=lambda model: True))
    job = wait(client, upload(client).json()["id"])
    assert job["status"] == "unsupported" and "ambiguous" in job["message"]


def test_failure_is_reported_without_internals(client, monkeypatch):
    def boom(pdf, out_dir, progress):
        raise RuntimeError(f"cannot read {pdf}")

    monkeypatch.setattr(api, "run_pipeline", boom)
    job = wait(client, upload(client).json()["id"])
    assert job["status"] == "failed" and job["message"] == api.FAILED_MESSAGE
    assert "storage" not in json.dumps(job) and "Traceback" not in json.dumps(job)


def test_rejected_uploads(client, monkeypatch):
    assert upload(client, data=b"<html>").status_code == 415
    assert upload(client, data=b"").status_code == 415
    monkeypatch.setattr(api, "MAX_UPLOAD_BYTES", 10)
    res = upload(client, data=b"%PDF-1.4 " + b"x" * 20)
    assert res.status_code == 413 and "larger than" in res.json()["detail"]
    assert not api._jobs and not any((api._storage).iterdir())  # nothing is kept of a rejected upload


def test_unknown_jobs_and_files(client, without_docling):
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.get("/api/jobs/nope/files/document.json").status_code == 404
    job = wait(client, upload(client).json()["id"])
    for name in ("source.pdf", "extracted.md", "docling_raw.json", "validation_report.json", "..%2Fx"):  # only the two result files are served
        assert client.get(f"/api/jobs/{job['id']}/files/{name}").status_code == 404


def test_old_finished_jobs_are_removed(client, without_docling, monkeypatch):
    monkeypatch.setattr(api, "MAX_JOBS", 2)
    ids = [wait(client, upload(client).json()["id"])["id"] for _ in range(3)]
    assert list(api._jobs) == ids[1:]
    assert not (api._storage / ids[0]).exists()


@pytest.mark.slow
def test_real_docling_on_a_pdf_without_recognizable_structure(client, synthetic_german_raw_json):
    """The generated synthetic PDF through the whole pipeline: Docling joins its front matter, table of contents and
    first headings into one block, so no § heading is found and the job ends as unsupported (not failed)."""
    pdf = (synthetic_german_raw_json.parent / "original.pdf").read_bytes()
    job = wait(client, upload(client, data=pdf).json()["id"])
    assert job["status"] == "unsupported" and job["summary"]["pages"] == 3 and "could not be recognized" in job["message"]


def _process(client, pdf):
    job = wait(client, upload(client, data=pdf.read_bytes(), name=pdf.name).json()["id"])
    assert job["status"] == "completed", job
    s = job["summary"]
    assert s["json_valid"] and s["json_schema_valid"] and s["json_text_identical"] and not s["extraction_reused"]
    files = lambda name: client.get(f"/api/jobs/{job['id']}/files/{name}").json()
    model, legal = files("document_model.json"), files("document.json")
    assert not list(Draft202012Validator(published_schema()).iter_errors(legal))
    return job, {e["id"]: e for e in model["elements"]}, legal


def _find(nodes, node_id):
    for n in nodes:
        if n["id"] == node_id:
            return n
        if hit := _find(n.get("children", []), node_id):
            return hit
    return None


@pytest.mark.slow
def test_mbo_end_to_end(client, mbo_pdf):
    job, by_id, legal = _process(client, mbo_pdf)
    assert job["summary"]["pages"] == 83 and legal["legalSystem"] == "de"
    abs1 = _find(legal["structure"], "doc/teil-2/par-6/abs-1")
    assert abs1["nativeType"] == "Absatz" and abs1["pages"] == [9, 10]
    assert [c["id"] for c in abs1["children"]] == ["doc/teil-2/par-6/abs-1/nr-1", "doc/teil-2/par-6/abs-1/nr-2"]
    assert abs1["text"].startswith("1 Vor den Außenwänden von Gebäuden sind Abstandsflächen")
    el = by_id["doc/teil-2/par-6/abs-1"]  # the highlight runs over both pages
    assert {p["page_no"] for p in el.get("highlight_boxes") or el["provenance"]} == {9, 10}


@pytest.mark.slow
def test_eu_regulation_end_to_end(client, eu_pdf):
    job, by_id, legal = _process(client, eu_pdf)
    assert job["summary"]["pages"] == 102 and legal["legalSystem"] == "eu" and legal["documentType"] == "eu_regulation"
    para = _find(legal["structure"], "doc/chp-2/art-10/para-1")
    assert para["nativeType"] == "Absatz" and para["pages"]
    el = by_id["doc/chp-2/art-10/para-1"]
    assert {p["page_no"] for p in el.get("highlight_boxes") or el["provenance"]} == set(para["pages"])
