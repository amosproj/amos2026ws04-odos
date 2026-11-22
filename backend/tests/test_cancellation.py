"""Cancellation of document processing and rule extraction.

There is no chunked extraction: document jobs run one at a time, and rule extraction sends one model request.
Cancelling a document job that has not started drops it. A document call that has already entered the pipeline runs
until that call returns; the answer is then discarded. Cancelling rule extraction closes the model connection instead,
so the request does not keep running, and a new extraction can start. These tests use a fake pipeline and a fake model.
Nothing reaches AWS and the real `odos` database is never used.
"""

import json
import threading
import time
from unittest.mock import patch

import psycopg
import pytest
from conftest import LEGAL_DOCUMENT, MINIMAL_PDF, fake_pipeline, upload, wait_for
from fastapi.testclient import TestClient
from test_rule_extraction_api import LEGAL, RULE, FakeBedrock, answer, start, use, wait_for_extraction

import odos.api
import odos.rule_extraction_jobs as rx
from odos.api import app
from odos.artifact_names import DOCUMENT_MODEL, LEGAL_JSON, RULE_JSON
from odos.database import connect
from odos.llm.bedrock import BedrockResponse
from odos.pipeline import Outcome, PipelineResult

ID1 = "demo-bo-par-6-abs-1"


@pytest.fixture
def api(monkeypatch):
    """The API without a database, one completed job, and a fake Bedrock key. No request leaves the process."""
    monkeypatch.delenv("ODOS_DATABASE_ENABLED", raising=False)
    monkeypatch.delenv("ODOS_STORAGE_DIR", raising=False)
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-key-not-real")
    with patch("odos.api.run_pipeline", side_effect=fake_pipeline(legal=LEGAL)):
        with TestClient(app) as client:
            job = wait_for(client, upload(client).json()["id"])
            assert job["status"] == "completed"
            yield client, job["id"]


def _client(monkeypatch):
    monkeypatch.delenv("ODOS_DATABASE_ENABLED", raising=False)
    monkeypatch.delenv("ODOS_STORAGE_DIR", raising=False)
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-key-not-real")


def _holding_pipeline(release: threading.Event, seen: list[str], *, write_before_return: bool):
    """The first job waits on `release` after `extracting`. Later jobs do not. Writes only if asked, and only after the wait."""
    entered = threading.Event()

    def run(pdf, out_dir, progress):
        seen.append(pdf.parent.name)
        progress("extracting")
        if len(seen) == 1:
            entered.set()
            assert release.wait(5), "the test never released the pipeline"
        if write_before_return:
            (out_dir / LEGAL_JSON).write_text(json.dumps(LEGAL_DOCUMENT), encoding="utf-8")
            (out_dir / DOCUMENT_MODEL).write_text("{}", encoding="utf-8")
            return PipelineResult(outcome=Outcome.COMPLETED, summary={"pages": 1}, message=None)
        progress("normalizing")
        (out_dir / LEGAL_JSON).write_text(json.dumps(LEGAL_DOCUMENT), encoding="utf-8")
        return PipelineResult(outcome=Outcome.COMPLETED, summary={"pages": 1}, message=None)

    return run, entered


def _until(event: threading.Event):
    assert event.wait(5), "the background job never reached the expected point"


# ── documents ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_queued_document_is_cancelled_before_it_starts_and_the_running_one_is_left_alone(monkeypatch):
    _client(monkeypatch)
    release, seen = threading.Event(), []
    run, entered = _holding_pipeline(release, seen, write_before_return=True)
    with patch("odos.api.run_pipeline", side_effect=run), TestClient(app) as client:
        try:
            first = upload(client).json()["id"]
            _until(entered)
            second = upload(client, name="queued.pdf").json()["id"]
            assert client.get(f"/api/jobs/{second}").json()["status"] == "queued"
            cancelled = client.post(f"/api/jobs/{second}/cancel")
            assert cancelled.status_code == 200
            assert cancelled.json()["status"] == "cancelled"
            assert cancelled.json()["message"] == "Processing was cancelled."
            assert second not in seen  # it was never scheduled
            assert client.get(f"/api/jobs/{first}").json()["status"] == "processing"
        finally:
            release.set()
        done = wait_for(client, first)
        assert done["status"] == "completed" and seen == [first]
        assert client.get(f"/api/jobs/{second}").json()["status"] == "cancelled"
        assert client.post(f"/api/jobs/{second}/cancel").status_code == 409


def test_cancelling_during_processing_discards_the_late_result(monkeypatch):
    _client(monkeypatch)
    release, seen = threading.Event(), []
    run, entered = _holding_pipeline(release, seen, write_before_return=True)
    with patch("odos.api.run_pipeline", side_effect=run), TestClient(app) as client:
        try:
            job_id = upload(client).json()["id"]
            _until(entered)
            stopping = client.post(f"/api/jobs/{job_id}/cancel")
            assert stopping.status_code == 200
            assert stopping.json()["status"] == "processing" and stopping.json()["stage"] == "cancelling"
            assert stopping.json()["cancelRequested"] is True
        finally:
            release.set()
        done = wait_for(client, job_id)
        assert done["status"] == "cancelled" and done["message"] == "Processing was cancelled."
        assert done["summary"] == {}
        directory = odos.api._storage / job_id
        assert not (directory / LEGAL_JSON).exists()  # the file the pipeline wrote after the cancel is gone
        assert not (directory / "source.pdf").exists()  # a non-persistent upload is not kept
        assert client.get(f"/api/jobs/{job_id}/files/{LEGAL_JSON}").status_code == 409


def test_a_cancel_between_stages_stops_before_the_next_stage_writes(monkeypatch):
    _client(monkeypatch)
    release, seen = threading.Event(), []
    run, entered = _holding_pipeline(release, seen, write_before_return=False)
    with patch("odos.api.run_pipeline", side_effect=run), TestClient(app) as client:
        try:
            job_id = upload(client).json()["id"]
            _until(entered)
            assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 200
        finally:
            release.set()
        assert wait_for(client, job_id)["status"] == "cancelled"
        assert not (odos.api._storage / job_id / LEGAL_JSON).exists()


def test_cancelling_one_document_does_not_cancel_the_one_waiting_behind_it(monkeypatch):
    _client(monkeypatch)
    release, seen = threading.Event(), []
    run, entered = _holding_pipeline(release, seen, write_before_return=False)
    with patch("odos.api.run_pipeline", side_effect=run), TestClient(app) as client:
        try:
            first = upload(client, name="first.pdf").json()["id"]
            _until(entered)
            second = upload(client, name="second.pdf").json()["id"]
            assert client.post(f"/api/jobs/{first}/cancel").json()["status"] == "processing"
        finally:
            release.set()
        assert wait_for(client, first)["status"] == "cancelled"
        second_done = wait_for(client, second)
        assert second_done["status"] == "completed" and seen == [first, second]
        assert client.get(f"/api/jobs/{second}/files/{LEGAL_JSON}").status_code == 200


def test_cancel_of_an_unknown_or_finished_document_is_refused(monkeypatch):
    _client(monkeypatch)
    with patch("odos.api.run_pipeline", side_effect=fake_pipeline()), TestClient(app) as client:
        assert client.post("/api/jobs/missing/cancel").status_code == 404
        job_id = wait_for(client, upload(client).json()["id"])["id"]
        assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 409
        assert client.post(f"/api/jobs/{job_id}/rule-extraction/cancel").status_code == 409


def test_an_unmigrated_database_keeps_the_cancellation_as_failed_without_a_result(db, tmp_path, monkeypatch):
    """`cancelled` needs backend/db/003_cancelled_status.sql. Until then the row is failed, with the same message."""
    monkeypatch.setenv("ODOS_DATABASE_ENABLED", "1")
    monkeypatch.setenv("ODOS_STORAGE_DIR", str(tmp_path))
    release, seen = threading.Event(), []
    run, entered = _holding_pipeline(release, seen, write_before_return=True)
    real = odos.api.finish_document

    def finish(document_id, status, summary, legal_json, message):
        if status == "cancelled":
            raise psycopg.errors.CheckViolation("documents_status_check")
        return real(document_id, status, summary, legal_json, message)

    with patch("odos.api.run_pipeline", side_effect=run), patch("odos.api.finish_document", finish), TestClient(app) as client:
        try:
            job_id = upload(client).json()["id"]
            _until(entered)
            assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 200
        finally:
            release.set()
        assert wait_for(client, job_id)["status"] == "cancelled"
    with connect() as conn:
        status, message, summary = conn.execute("SELECT status, message, summary FROM documents WHERE id = %s", (job_id,)).fetchone()
    assert status == "failed" and message == "Processing was cancelled." and summary["cancelled"] is True
    assert not (tmp_path / job_id / LEGAL_JSON).exists()
    assert (tmp_path / job_id / "source.pdf").read_bytes() == MINIMAL_PDF  # the original file stays


# ── rule extraction (one request; a second job waits, it is not a parallel chunk) ─────────────────────────────────────


def _wait_until_called(fake):
    for _ in range(250):
        if fake.calls:
            return
        time.sleep(0.02)
    raise AssertionError("the model was never called")


def test_a_queued_extraction_is_cancelled_before_the_model_is_called(api, monkeypatch):
    client, job_id = api
    gate = threading.Event()
    fake = use(monkeypatch, FakeBedrock(answer(RULE), answer(RULE), gate=gate))
    try:
        assert start(client, job_id).status_code == 202
        _wait_until_called(fake)
        other = wait_for(client, upload(client, name="other.pdf").json()["id"])["id"]
        assert start(client, other).status_code == 202
        cancelled = client.post(f"/api/jobs/{other}/rule-extraction/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert cancelled.json()["externalRequestStarted"] is False
        assert "charged" not in cancelled.json()["message"]
    finally:
        gate.set()
    assert wait_for_extraction(client, job_id)["status"] == "completed"
    assert fake.calls == 1  # the cancelled job never called the model
    assert client.get(f"/api/jobs/{other}/rule-extraction").json()["status"] == "cancelled"
    assert client.get(f"/api/jobs/{job_id}/files/{RULE_JSON}").status_code == 200


def test_cancelling_stops_the_model_request_and_a_new_extraction_can_start(api, monkeypatch):
    client, job_id = api
    use(monkeypatch, FakeBedrock(answer(RULE)))
    start(client, job_id)
    assert wait_for_extraction(client, job_id)["status"] == "completed"
    before = client.get(f"/api/jobs/{job_id}/files/{RULE_JSON}").content
    gate = threading.Event()
    replacement = dict(RULE, classification={**RULE["classification"], "summary": "replaced"})
    fake = use(monkeypatch, FakeBedrock(answer(RULE), answer(replacement), gate=gate))
    try:
        assert start(client, job_id).status_code == 202
        _wait_until_called(fake)
        running = client.get(f"/api/jobs/{job_id}/rule-extraction").json()
        assert running["status"] == "running" and running["stage"] == "finding"
        assert "progress" not in running  # this build has no section counts to report
        cancelled = client.post(f"/api/jobs/{job_id}/rule-extraction/cancel")
        # the connection is closed here: the run is cancelled without waiting for the model to finish
        assert cancelled.json()["status"] == "cancelled" and cancelled.json()["cancelRequested"] is True
        assert cancelled.json()["externalRequestStarted"] is True
        assert "may still be charged" in cancelled.json()["message"]
    finally:
        gate.set()
    done = wait_for_extraction(client, job_id)
    assert done["status"] == "cancelled" and done["rulesFile"] is None
    assert client.get(f"/api/jobs/{job_id}/files/{RULE_JSON}").content == before
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "completed"  # the document itself stays
    again = start(client, job_id)
    assert again.status_code == 202
    assert wait_for_extraction(client, job_id)["status"] == "completed"
    assert fake.calls == 2  # the cancelled call was not retried; the new extraction is the second call
    assert b"replaced" not in client.get(f"/api/jobs/{job_id}/files/{RULE_JSON}").content


def test_a_cancel_during_the_model_call_skips_the_correction_retry(api, monkeypatch):
    client, job_id = api

    class CancelDuring(FakeBedrock):
        def converse(self, system, user, **kwargs):
            self.calls += 1
            with odos.api._lock:
                odos.api._jobs[job_id].ruleExtraction.cancelRequested = True
            return BedrockResponse("not json", "end_turn", 1, 1, 1, "m")

    fake = use(monkeypatch, CancelDuring())
    assert start(client, job_id).status_code == 202
    done = wait_for_extraction(client, job_id)
    assert fake.calls == 1  # the retry was not sent
    assert done["status"] == "cancelled"
    assert "may still be charged" in done["message"]
    assert client.get(f"/api/jobs/{job_id}/files/{RULE_JSON}").status_code == 404


def test_cancelling_an_extraction_keeps_an_accepted_review_and_another_document(db, tmp_path, monkeypatch):
    monkeypatch.setenv("ODOS_DATABASE_ENABLED", "1")
    monkeypatch.setenv("ODOS_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-key-not-real")
    gate = threading.Event()
    with patch("odos.api.run_pipeline", side_effect=fake_pipeline(legal=LEGAL)), TestClient(app) as client:
        use(monkeypatch, FakeBedrock(answer(RULE)))
        job_id = wait_for(client, upload(client).json()["id"])["id"]
        start(client, job_id)
        assert wait_for_extraction(client, job_id)["status"] == "completed"
        rules_path = tmp_path / job_id / RULE_JSON
        before = rules_path.read_bytes()
        state = client.get(f"/api/jobs/{job_id}/rule-reviews").json()
        known = state["rules"][ID1]
        accepted = client.post(f"/api/jobs/{job_id}/rule-reviews", json={
            "ruleId": ID1, "extractionId": state["extractionId"], "expectedRuleSha256": known["ruleSha256"],
            "expectedLastEventId": known["lastEventId"], "action": "accept", "reviewer": "Dana Prüfer",
        })
        assert accepted.status_code == 201
        fake = use(monkeypatch, FakeBedrock(answer(RULE), gate=gate))
        try:
            assert start(client, job_id).status_code == 202
            _wait_until_called(fake)
            other = wait_for(client, upload(client, name="other.pdf").json()["id"])["id"]
            assert client.post(f"/api/jobs/{job_id}/rule-extraction/cancel").status_code == 200
        finally:
            gate.set()
        assert wait_for_extraction(client, job_id)["status"] == "cancelled"
        assert rules_path.read_bytes() == before
        again = client.get(f"/api/jobs/{job_id}/rule-reviews").json()
        assert again["rules"][ID1]["state"] == "accepted"
        assert client.get(f"/api/jobs/{job_id}").json()["status"] == "completed"
        assert client.get(f"/api/jobs/{other}").json()["status"] == "completed"


# ── status survives a restart ─────────────────────────────────────────────────────────────────────────────────────────


def test_restore_keeps_a_cancelled_extraction_and_does_not_call_it_interrupted(tmp_path):
    finished = rx.RuleExtraction.queued(rx.RuleExtractionRequest())
    finished.mark_cancelled()
    rx.save(tmp_path, finished)
    restored = rx.restore(tmp_path)
    assert restored is not None and restored.status == "cancelled" and restored.errorCode == "cancelled"
    assert restored.message == "Finding rules was cancelled."

    waiting = tmp_path / "waiting"
    waiting.mkdir()
    running = rx.RuleExtraction.queued(rx.RuleExtractionRequest())
    running.mark_running()
    running.cancelRequested = True
    running.externalRequestStarted = True
    rx.save(waiting, running)
    stopped = rx.restore(waiting)
    assert stopped.status == "cancelled" and stopped.errorCode == "cancelled"
    assert "may still be charged" in stopped.message
    assert stopped.message != rx.INTERRUPTED
