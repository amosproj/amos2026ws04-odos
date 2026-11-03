"""Basic public tests: the web API, the German and EU parsers, the DocumentModel and Custom Legal JSON 2.0.

They use only the synthetic documents (tests/synthetic_*.py) and replace the slow Docling conversion with their
prepared Docling JSON, so they run anywhere in a few seconds."""

import json
import shutil
import time

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

import odos.api as api
from odos.document_model import ElementType as T
from odos.legal_json.artifacts import SCHEMA_PATH, build_legal_json_artifacts, published_schema
from odos.legal_json.view import json_schema
from odos.parsing.profiles import PROFILES
from odos.pipeline import _run_structured


# ---- web API ---------------------------------------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path, monkeypatch, synthetic_german_raw_json):
    """The API with the synthetic German law's Docling JSON in place of the Docling conversion; the rest is real."""

    def run(pdf, out_dir, progress):
        for name in ("docling_raw.json", "pdf_text_lines.json"):
            shutil.copy(synthetic_german_raw_json.parent / name, out_dir / name)
        return _run_structured(list(PROFILES.values()), out_dir, {"pages": 3}, progress)

    monkeypatch.setattr(api, "run_pipeline", run)
    monkeypatch.setenv("ODOS_STORAGE_DIR", str(tmp_path))
    with TestClient(api.app) as c:
        yield c


def upload(client, data=b"%PDF-1.4 test"):
    return client.post("/api/jobs", files={"file": ("Gesetz.pdf", data, "application/pdf")})


def test_uploaded_pdf_is_processed_into_legal_json(client):
    job_id = upload(client).json()["id"]
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] not in ("queued", "processing"):
            break
        time.sleep(0.1)
    assert job["status"] == "completed"

    legal = client.get(f"/api/jobs/{job_id}/files/document.json").json()
    assert legal["schemaVersion"] == "2.0" and legal["legalSystem"] == "de"
    assert client.get(f"/api/jobs/{job_id}/files/document_model.json").status_code == 200
    download = client.get(f"/api/jobs/{job_id}/files/document.json?download=true")
    assert download.headers["content-disposition"] == 'attachment; filename="Gesetz.legal.json"'


def test_invalid_requests_are_rejected(client):
    assert upload(client, data=b"<html>").status_code == 415  # not a PDF
    assert client.get("/api/jobs/unknown").status_code == 404


# ---- parsers and DocumentModel ---------------------------------------------------------------------------------------
def test_german_law_is_parsed(synthetic_german_model):
    idx = synthetic_german_model.by_id()
    assert synthetic_german_model.metadata.short_title == "BspG"
    assert idx["doc/teil-1/kapitel-1/par-2"].marker == "§ 2" and idx["doc/teil-1/kapitel-1/par-2"].type == T.PARAGRAPH
    assert idx["doc/teil-1/kapitel-1/par-1/abs-2"].type == T.ABSATZ
    assert idx["doc/teil-1/kapitel-1/par-2/abs-1/nr-3/lit-b"].type == T.BUCHSTABE


def test_eu_regulation_is_parsed(synthetic_eu_model):
    idx = synthetic_eu_model.by_id()
    assert synthetic_eu_model.metadata.document_number == "2099/1"
    assert idx["doc/preamble/rec-2"].type == T.RECITAL
    assert idx["doc/chp-1/art-1"].type == T.ARTICLE
    assert idx["doc/chp-2/sec-1/art-3/para-2"].type == T.ARTICLE_PARAGRAPH


def test_document_model_keeps_ids_hierarchy_and_pdf_sources(synthetic_german_model):
    elements = synthetic_german_model.elements
    idx = synthetic_german_model.by_id()
    assert len(idx) == len(elements)  # unique ids
    for e in elements:
        assert all(idx[c].parent_id == e.id for c in e.children_ids)  # a consistent tree
        if e.source_refs:  # every element read from the PDF can be highlighted there
            assert e.pages and all(p.bbox for p in e.provenance), e.id


# ---- Custom Legal JSON 2.0 -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["synthetic_german", "synthetic_eu"])
def test_legal_json_is_valid_against_the_schema(request, name, tmp_path):
    model = request.getfixturevalue(f"{name}_model")
    raw = request.getfixturevalue(f"{name}_raw_json")
    report = build_legal_json_artifacts(model, raw, tmp_path)["report"]
    assert report["valid"] and report["text_preservation"]["identical_to_model"]
    data = json.loads((tmp_path / "document.json").read_text())
    assert not list(Draft202012Validator(published_schema()).iter_errors(data))


def test_published_schema_matches_the_exporter():
    assert json.loads(SCHEMA_PATH.read_text(encoding="utf-8")) == json_schema()
