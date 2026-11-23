"""Cancellation of document processing (Docling pipeline).

Cooperative cancellation: the cancel endpoint sets `cancelRequested = True` and
returns immediately; the background worker checks the flag between pipeline stages.
No database or Bedrock calls are made.
"""

import threading
import time
from unittest.mock import patch

import pytest
from conftest import fake_pipeline, upload, wait_for
from fastapi.testclient import TestClient

import odos.api
from odos.api import app
from odos.artifact_names import DOCUMENT_MODEL, LEGAL_JSON


# ── fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def api(monkeypatch):
    """The API without a database, in-memory only."""
    monkeypatch.delenv("ODOS_DATABASE_ENABLED", raising=False)
    monkeypatch.delenv("ODOS_STORAGE_DIR", raising=False)
    with TestClient(app) as client:
        yield client


# ── slow pipeline that blocks between stages ──────────────────────────────────


def slow_pipeline(gate: threading.Event, legal: dict | None = None):
    """A fake pipeline that blocks until `gate` is set before the second stage."""
    from odos.artifact_names import DOCUMENT_MODEL, LEGAL_JSON
    from odos.pipeline import Outcome, PipelineResult
    import json
    from conftest import LEGAL_DOCUMENT

    def run(pdf, out_dir, progress):
        progress("extracting")
        gate.wait()  # pause here — cancel can fire between extracting and normalizing
        progress("normalizing")
        (out_dir / LEGAL_JSON).write_text(json.dumps(legal or LEGAL_DOCUMENT), encoding="utf-8")
        (out_dir / DOCUMENT_MODEL).write_text("{}", encoding="utf-8")
        return PipelineResult(outcome=Outcome.COMPLETED, summary={"pages": 1, "docling_warnings": []}, message=None)

    return run


# ── cancel endpoint ────────────────────────────────────────────────────────────


def test_cancel_endpoint_sets_cancel_requested_and_returns_immediately(api):
    """The cancel endpoint marks cancelRequested=True but does not wait for the worker."""
    gate = threading.Event()
    with patch("odos.api.run_pipeline", side_effect=slow_pipeline(gate)):
        job_id = upload(api).json()["id"]
        # let the pipeline start and block at the gate
        for _ in range(200):
            job = api.get(f"/api/jobs/{job_id}").json()
            if job["status"] == "processing":
                break
            time.sleep(0.02)
        assert job["status"] == "processing"

        response = api.post(f"/api/jobs/{job_id}/cancel")
        assert response.status_code == 200
        body = response.json()
        # cancel endpoint returns before the worker finishes
        assert body["cancelRequested"] is True
        assert body["status"] == "processing"
        gate.set()

    done = wait_for(api, job_id)
    assert done["status"] == "cancelled"
    assert done["cancelRequested"] is False
    assert done["message"] == odos.api.CANCELLED_DOCUMENT


def test_cancel_endpoint_returns_409_when_job_already_finished(api):
    """Cancelling a completed job returns 409 Conflict."""
    with patch("odos.api.run_pipeline", side_effect=fake_pipeline()):
        job_id = upload(api).json()["id"]
        wait_for(api, job_id)
    assert api.post(f"/api/jobs/{job_id}/cancel").status_code == 409


def test_cancel_endpoint_is_idempotent_on_already_cancelled_job(api):
    """Calling cancel on a cancelled job returns 409 (already terminal, like completed)."""
    gate = threading.Event()
    with patch("odos.api.run_pipeline", side_effect=slow_pipeline(gate)):
        job_id = upload(api).json()["id"]
        for _ in range(200):
            if api.get(f"/api/jobs/{job_id}").json()["status"] == "processing":
                break
            time.sleep(0.02)
        api.post(f"/api/jobs/{job_id}/cancel")
        gate.set()
    wait_for(api, job_id)
    r = api.post(f"/api/jobs/{job_id}/cancel")
    assert r.status_code == 409


# ── no partial results published ──────────────────────────────────────────────


def test_cancelled_job_has_no_result_files(api):
    """A cancelled job returns 409 for file requests (not completed)."""
    gate = threading.Event()
    with patch("odos.api.run_pipeline", side_effect=slow_pipeline(gate)):
        job_id = upload(api).json()["id"]
        for _ in range(200):
            if api.get(f"/api/jobs/{job_id}").json()["status"] == "processing":
                break
            time.sleep(0.02)
        api.post(f"/api/jobs/{job_id}/cancel")
        gate.set()
    done = wait_for(api, job_id)
    assert done["status"] == "cancelled"
    assert api.get(f"/api/jobs/{job_id}/files/{DOCUMENT_MODEL}").status_code == 409
    assert api.get(f"/api/jobs/{job_id}/files/{LEGAL_JSON}").status_code == 409


def test_cancelled_job_does_not_publish_a_result_even_if_pipeline_finished(api):
    """If the pipeline finishes but cancelRequested is set, no result is published."""
    gate = threading.Event()
    with patch("odos.api.run_pipeline", side_effect=slow_pipeline(gate)):
        job_id = upload(api).json()["id"]
        for _ in range(200):
            if api.get(f"/api/jobs/{job_id}").json()["status"] == "processing":
                break
            time.sleep(0.02)
        # cancel and release the gate simultaneously — pipeline finishes but result must be discarded
        api.post(f"/api/jobs/{job_id}/cancel")
        gate.set()
    done = wait_for(api, job_id)
    assert done["status"] == "cancelled"
    assert api.get(f"/api/jobs/{job_id}/files/{DOCUMENT_MODEL}").status_code == 409


# ── job recovery ──────────────────────────────────────────────────────────────


def test_cancel_stage_shown_while_waiting_for_pipeline(api):
    """While cancelRequested is set and the pipeline hasn't finished, stage is 'cancelling'."""
    gate = threading.Event()
    with patch("odos.api.run_pipeline", side_effect=slow_pipeline(gate)):
        job_id = upload(api).json()["id"]
        for _ in range(200):
            if api.get(f"/api/jobs/{job_id}").json()["status"] == "processing":
                break
            time.sleep(0.02)
        response = api.post(f"/api/jobs/{job_id}/cancel")
        assert response.json()["stage"] == "cancelling"
        gate.set()
    assert wait_for(api, job_id)["status"] == "cancelled"


# ── persistent mode, repository faked (no database) ───────────────────────────────────────────────────────────────────


@pytest.fixture
def persistent_api(monkeypatch, tmp_path):
    """Database persistence on, with every repository function replaced by a recorder."""
    calls: list[tuple] = []
    monkeypatch.setenv("ODOS_DATABASE_ENABLED", "1")
    monkeypatch.setenv("ODOS_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(odos.api, "ensure_cancelled_status", lambda: calls.append(("ensure",)))
    monkeypatch.setattr(odos.api, "mark_interrupted_jobs", lambda: None)
    monkeypatch.setattr(odos.api, "list_documents", lambda: [])
    monkeypatch.setattr(odos.api, "create_document", lambda *a: calls.append(("create", a[0])))
    monkeypatch.setattr(odos.api, "update_document_status", lambda i, s, stage=None: calls.append(("status", s, stage)))
    monkeypatch.setattr(odos.api, "finish_document", lambda i, s, *a: calls.append(("finish", s)))
    with TestClient(app) as client:
        yield client, calls


def _started(client, job_id):
    for _ in range(200):
        if client.get(f"/api/jobs/{job_id}").json()["status"] == "processing":
            return
        time.sleep(0.02)
    raise AssertionError("job did not start")


def test_startup_applies_the_cancelled_status_migration(persistent_api):
    _, calls = persistent_api
    assert ("ensure",) in calls


def test_cancelled_document_is_stored_as_cancelled_and_never_finished(persistent_api):
    client, calls = persistent_api
    gate = threading.Event()
    with patch("odos.api.run_pipeline", side_effect=slow_pipeline(gate)):
        job_id = upload(client).json()["id"]
        _started(client, job_id)
        client.post(f"/api/jobs/{job_id}/cancel")
        gate.set()
    assert wait_for(client, job_id)["status"] == "cancelled"
    assert calls[-1] == ("status", "cancelled", None)  # the row ends as cancelled
    assert not [c for c in calls if c[0] == "finish"]  # no result was stored


def test_cancel_arriving_while_the_result_is_stored_cannot_overwrite_it(persistent_api, monkeypatch):
    """Decision, database write and publication happen under one lock: a late cancel gets 409 and the row stays completed."""
    client, calls = persistent_api
    late: dict = {}

    def finish(i, status, *a):
        calls.append(("finish", status))
        t = threading.Thread(target=lambda: late.update(r=client.post(f"/api/jobs/{i}/cancel")))
        late["t"] = t
        t.start()
        time.sleep(0.2)  # the cancel request is now waiting for the lock

    monkeypatch.setattr(odos.api, "finish_document", finish)
    with patch("odos.api.run_pipeline", side_effect=fake_pipeline()):
        job_id = upload(client).json()["id"]
        done = wait_for(client, job_id)
    late["t"].join(5)
    assert done["status"] == "completed"
    assert late["r"].status_code == 409
    assert calls[-1] == ("finish", "completed")  # nothing wrote 'processing/cancelling' over the stored result
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "completed"


def test_a_cancelled_document_does_not_block_the_next_one_from_being_cancelled_or_run(api):
    """One worker: a new upload waits behind the cancelled job's unfinished stage; it never runs alongside it."""
    gate = threading.Event()
    running = []
    peak = []

    def pipeline(pdf, out_dir, progress):
        running.append(1)
        peak.append(len(running))
        progress("extracting")
        gate.wait()
        running.pop()
        return fake_pipeline()(pdf, out_dir, lambda s: None)

    with patch("odos.api.run_pipeline", side_effect=pipeline):
        first = upload(api).json()["id"]
        _started(api, first)
        api.post(f"/api/jobs/{first}/cancel")
        second = upload(api).json()["id"]
        time.sleep(0.3)
        assert api.get(f"/api/jobs/{second}").json()["status"] == "queued"  # not started while the first still runs
        gate.set()
        assert wait_for(api, first)["status"] == "cancelled"
        assert wait_for(api, second)["status"] == "completed"
    assert max(peak) == 1


def test_migration_file_and_startup_statement_are_the_same():
    from pathlib import Path
    from odos.document_repository import ALLOW_CANCELLED_SQL

    sql = (Path(__file__).parent.parent / "db" / "003_cancelled_status.sql").read_text(encoding="utf-8")
    body = "\n".join(line for line in sql.splitlines() if not line.startswith("--")).strip()
    assert body == ALLOW_CANCELLED_SQL.strip()
    assert "'cancelled'" in body and "DROP CONSTRAINT IF EXISTS" in body
    assert "DELETE" not in body.upper() and "UPDATE" not in body.upper()  # never touches rows
