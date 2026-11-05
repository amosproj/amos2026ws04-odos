"""The API with persistence disabled (the original in-memory mode) and its database error handling; no PostgreSQL."""

from pathlib import Path
from unittest.mock import patch

import psycopg
import pytest
from conftest import fake_pipeline, upload, wait_for
from fastapi.testclient import TestClient

import odos.api
from odos.api import DATABASE_UNAVAILABLE, app
from odos.artifact_names import LEGAL_JSON
from odos.database import connect

REPOSITORY_CALLS = ("create_document", "delete_document", "finish_document", "list_documents",
                    "mark_interrupted_jobs", "update_document_status")


@pytest.fixture
def no_database(monkeypatch):
    """Persistence off; any repository call fails the test."""
    monkeypatch.delenv("ODOS_DATABASE_ENABLED", raising=False)
    monkeypatch.delenv("ODOS_STORAGE_DIR", raising=False)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("the database was used although persistence is disabled")

    for name in REPOSITORY_CALLS:
        monkeypatch.setattr(odos.api, name, forbidden)


def test_in_memory_mode_works_without_database(no_database):
    with patch("odos.api.run_pipeline", side_effect=fake_pipeline()):
        with TestClient(app) as client:
            storage = odos.api._storage
            job = wait_for(client, upload(client).json()["id"])
            assert (job["status"], job["persistent"]) == ("completed", False)  # the frontend deletes it when done
            assert client.get(f"/api/jobs/{job['id']}/files/{LEGAL_JSON}").status_code == 200
            assert not (storage / job["id"] / "source.pdf").exists()  # the upload is not kept
            assert client.delete(f"/api/jobs/{job['id']}").status_code == 204
            assert client.get(f"/api/jobs/{job['id']}").status_code == 404
    assert not Path(storage).exists()  # the temporary storage is removed at shutdown


def test_in_memory_jobs_do_not_survive_a_restart(no_database):
    with patch("odos.api.run_pipeline", side_effect=fake_pipeline()):
        with TestClient(app) as client:
            job_id = wait_for(client, upload(client).json()["id"])["id"]
        with TestClient(app) as client:
            assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_upload_validation_is_unchanged(no_database):
    with TestClient(app) as client:
        assert upload(client, b"not a pdf").status_code == 415
        assert upload(client, b"").status_code == 415


def test_persistence_requires_a_storage_dir(monkeypatch):
    monkeypatch.setenv("ODOS_DATABASE_ENABLED", "1")
    monkeypatch.delenv("ODOS_STORAGE_DIR", raising=False)
    with pytest.raises(RuntimeError, match="ODOS_STORAGE_DIR"):
        with TestClient(app):
            pass


def test_connect_reports_missing_settings(monkeypatch):
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="POSTGRES_PASSWORD"):
        connect()


def test_upload_while_database_is_down_answers_503(monkeypatch, tmp_path):
    monkeypatch.setenv("ODOS_DATABASE_ENABLED", "1")
    monkeypatch.setenv("ODOS_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(odos.api, "mark_interrupted_jobs", lambda: None)
    monkeypatch.setattr(odos.api, "list_documents", lambda: [])

    def down(*_args):
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(odos.api, "create_document", down)
    with TestClient(app) as client:
        response = upload(client)
    assert (response.status_code, response.json()["detail"]) == (503, DATABASE_UNAVAILABLE)
    assert list(tmp_path.iterdir()) == []  # the stored PDF was removed again


def test_delete_while_database_is_down_keeps_the_job(monkeypatch, tmp_path):
    monkeypatch.setenv("ODOS_DATABASE_ENABLED", "1")
    monkeypatch.setenv("ODOS_STORAGE_DIR", str(tmp_path))
    (tmp_path / "done").mkdir()
    monkeypatch.setattr(odos.api, "mark_interrupted_jobs", lambda: None)
    monkeypatch.setattr(odos.api, "list_documents", lambda: [{"id": "done", "filename": "a.pdf", "status": "completed",
                                                               "stage": None, "message": None, "summary": {}}])

    def down(*_args):
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(odos.api, "delete_document", down)
    with TestClient(app) as client:
        assert client.delete("/api/jobs/done").status_code == 503
        assert client.get("/api/jobs/done").json()["status"] == "completed"
    assert (tmp_path / "done").is_dir()


def test_database_unreachable_at_startup_fails_fast(monkeypatch, tmp_path):
    monkeypatch.setenv("ODOS_DATABASE_ENABLED", "1")
    monkeypatch.setenv("ODOS_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("POSTGRES_USER", "odos")
    monkeypatch.setenv("POSTGRES_PASSWORD", "unused")
    monkeypatch.setenv("POSTGRES_PORT", "1")  # nothing listens there
    with pytest.raises(psycopg.OperationalError):
        with TestClient(app):
            pass
