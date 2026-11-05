"""Integration tests for PostgreSQL-backed ODOS jobs (need the `odos_test` database, see conftest.py)."""

import shutil
from unittest.mock import patch

import psycopg
import pytest
from conftest import LEGAL_DOCUMENT, MINIMAL_PDF, TEST_DATABASE, fake_pipeline, require_test_database, upload, wait_for
from fastapi.testclient import TestClient

from odos.api import NOT_STORED_MESSAGE, app
from odos.artifact_names import LEGAL_JSON
from odos.database import connect
from odos.document_repository import (
    create_document,
    delete_document,
    finish_document,
    get_document,
    list_documents,
    mark_interrupted_jobs,
    update_document_status,
)
from odos.pipeline import Outcome


@pytest.fixture
def persistent(db, tmp_path, monkeypatch):
    """The API in persistence mode, with its job files in a temporary ODOS_STORAGE_DIR."""
    monkeypatch.setenv("ODOS_DATABASE_ENABLED", "1")
    monkeypatch.setenv("ODOS_STORAGE_DIR", str(tmp_path))
    return tmp_path


# --- safety and connection ---


def test_refuses_databases_without_test_suffix():
    for name in ("odos", "postgres", "odos_test_backup", ""):
        with pytest.raises(RuntimeError, match="Refusing"):
            require_test_database(name)
    assert require_test_database("odos_test") == "odos_test"


def test_connects_to_the_test_database_only(db):
    with connect() as conn:
        name, version = conn.execute("SELECT current_database(), current_setting('server_version_num')::int").fetchone()
    assert name == TEST_DATABASE != "odos"
    assert version >= 170000  # PostgreSQL 17


# --- repository ---


def test_create_and_get_document(db):
    create_document("doc1", "Muster.pdf", "doc1/source.pdf")
    stored = get_document("doc1")
    assert stored["filename"] == "Muster.pdf"
    assert stored["status"] == "queued"
    assert stored["pdf_storage_key"] == "doc1/source.pdf"
    assert stored["summary"] == {} and stored["legal_json"] is None
    assert stored["created_at"] is not None
    assert get_document("missing") is None


def test_legal_json_round_trips_as_jsonb(db):
    create_document("doc1", "eu.pdf", "doc1/source.pdf")
    summary = {"pages": 83, "json_schema_valid": False, "parser_warnings": 17}
    finish_document("doc1", "completed", summary, LEGAL_DOCUMENT, None)

    stored = get_document("doc1")
    assert stored["legal_json"] == LEGAL_DOCUMENT  # nested lists, umlauts and € unchanged
    assert stored["summary"] == summary
    assert stored["document_type"] == "eu_regulation"
    with connect() as conn:
        kinds = conn.execute(
            "SELECT jsonb_typeof(legal_json), jsonb_typeof(summary), legal_json #>> '{structure,0,number}'"
            " FROM documents"
        ).fetchone()
    assert kinds == ("object", "object", "1")


def test_status_updates_and_finish(db):
    create_document("doc1", "a.pdf", "doc1/source.pdf")
    update_document_status("doc1", "processing", "extracting")
    stored = get_document("doc1")
    assert (stored["status"], stored["stage"]) == ("processing", "extracting")
    assert stored["updated_at"] >= stored["created_at"]

    finish_document("doc1", "unsupported", {"pages": 2}, None, "not recognized")
    stored = get_document("doc1")
    assert (stored["status"], stored["stage"], stored["message"]) == ("unsupported", None, "not recognized")
    assert stored["legal_json"] is None and stored["document_type"] is None


def test_invalid_status_and_duplicate_id_are_rejected(db):
    create_document("doc1", "a.pdf", "doc1/source.pdf")
    with pytest.raises(psycopg.errors.CheckViolation):
        update_document_status("doc1", "done")
    with pytest.raises(psycopg.errors.UniqueViolation):
        create_document("doc1", "b.pdf", "doc1/source.pdf")
    stored = get_document("doc1")  # the failed statements were rolled back
    assert (stored["status"], stored["filename"]) == ("queued", "a.pdf")


def test_values_are_parameters_not_sql(db):
    name = "x'); DROP TABLE documents; --.pdf"
    create_document("doc1", name, "doc1/source.pdf")
    assert get_document("doc1")["filename"] == name
    assert get_document("doc1' OR '1'='1") is None


def test_list_and_delete(db):
    for doc in ("a", "b", "c"):
        create_document(doc, f"{doc}.pdf", f"{doc}/source.pdf")
    assert [row["id"] for row in list_documents()] == ["a", "b", "c"]
    delete_document("b")
    delete_document("b")  # deleting twice is harmless
    assert [row["id"] for row in list_documents()] == ["a", "c"]
    assert get_document("b") is None


def test_mark_interrupted_jobs(db):
    for doc, status in (("q", "queued"), ("p", "processing"), ("c", "completed"), ("u", "unsupported")):
        create_document(doc, f"{doc}.pdf", f"{doc}/source.pdf")
        update_document_status(doc, status, "extracting" if status == "processing" else None)
    mark_interrupted_jobs()
    states = {row["id"]: (row["status"], row["stage"]) for row in list_documents()}
    assert states == {"q": ("failed", None), "p": ("failed", None),
                      "c": ("completed", None), "u": ("unsupported", None)}
    assert "interrupted" in get_document("p")["message"]


# --- API in persistence mode ---


def test_document_survives_api_restart(persistent):
    with patch("odos.api.run_pipeline", side_effect=fake_pipeline()):
        with TestClient(app) as client:
            response = upload(client, name="MusterBauVerordnung.pdf")
            assert response.status_code == 202
            assert response.json()["persistent"] is True  # the frontend keeps the job instead of deleting it
            job_id = response.json()["id"]
            assert get_document(job_id)["status"] in ("queued", "processing", "completed")
            assert wait_for(client, job_id)["status"] == "completed"

        stored = get_document(job_id)
        assert stored["status"] == "completed" and stored["stage"] is None
        assert stored["legal_json"] == LEGAL_DOCUMENT
        assert stored["summary"]["docling_warnings"] == 1  # only the number of Docling warnings is stored
        # the PDF is kept next to the results, under the stored key relative to ODOS_STORAGE_DIR
        assert (persistent / stored["pdf_storage_key"]).read_bytes() == MINIMAL_PDF

        # second API session: a restarted server restores the job from PostgreSQL
        with TestClient(app) as client:
            job = client.get(f"/api/jobs/{job_id}").json()
            assert (job["status"], job["filename"], job["persistent"]) == ("completed", "MusterBauVerordnung.pdf", True)
            response = client.get(f"/api/jobs/{job_id}/files/{LEGAL_JSON}")
            assert response.status_code == 200 and response.json() == LEGAL_DOCUMENT

            assert client.delete(f"/api/jobs/{job_id}").status_code == 204
            assert get_document(job_id) is None
            assert not (persistent / job_id).exists()
            assert client.get(f"/api/jobs/{job_id}").status_code == 404

        with TestClient(app) as client:  # and it stays deleted after another restart
            assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_unsupported_document_is_stored_without_legal_json(persistent):
    with patch("odos.api.run_pipeline", side_effect=fake_pipeline(Outcome.UNSUPPORTED)):
        with TestClient(app) as client:
            job = wait_for(client, upload(client).json()["id"])
    assert job["status"] == "unsupported"
    stored = get_document(job["id"])
    assert (stored["status"], stored["legal_json"], stored["message"]) == ("unsupported", None, "unsupported")


def test_pipeline_error_is_stored_as_failed(persistent):
    with patch("odos.api.run_pipeline", side_effect=ValueError("broken PDF")):
        with TestClient(app) as client:
            job = wait_for(client, upload(client).json()["id"])
    assert job["status"] == "failed"
    stored = get_document(job["id"])
    assert stored["status"] == "failed" and "could not be processed" in stored["message"]


def test_interrupted_job_is_restored_as_failed(persistent):
    create_document("running", "a.pdf", "running/source.pdf")
    update_document_status("running", "processing", "extracting")
    with TestClient(app) as client:
        job = client.get("/api/jobs/running").json()
    assert (job["status"], job["stage"]) == ("failed", None)
    assert "interrupted" in job["message"]


def test_running_job_cannot_be_deleted(persistent):
    create_document("waiting", "a.pdf", "waiting/source.pdf")
    with patch("odos.api.mark_interrupted_jobs"):  # keep it queued across the startup
        with TestClient(app) as client:
            assert client.delete("/api/jobs/waiting").status_code == 409
    assert get_document("waiting") is not None


def test_restored_job_without_files_answers_404(persistent):
    with patch("odos.api.run_pipeline", side_effect=fake_pipeline()):
        with TestClient(app) as client:
            job_id = wait_for(client, upload(client).json()["id"])["id"]
    shutil.rmtree(persistent / job_id)
    with TestClient(app) as client:
        assert client.get(f"/api/jobs/{job_id}").json()["status"] == "completed"
        response = client.get(f"/api/jobs/{job_id}/files/{LEGAL_JSON}")
    assert response.status_code == 404
    assert "no longer available" in response.json()["detail"]


def test_result_that_cannot_be_stored_is_reported_as_failed(persistent):
    real_finish = finish_document
    calls = []

    def finish_once_fails(*args):
        calls.append(args)
        if len(calls) == 1:
            raise psycopg.OperationalError("connection lost")
        real_finish(*args)

    with patch("odos.api.run_pipeline", side_effect=fake_pipeline()):
        with patch("odos.api.finish_document", finish_once_fails), TestClient(app) as client:
            job = wait_for(client, upload(client).json()["id"])
    assert (job["status"], job["message"]) == ("failed", NOT_STORED_MESSAGE)
    stored = get_document(job["id"])  # the API and the database agree, also after a restart
    assert (stored["status"], stored["legal_json"]) == ("failed", None)
