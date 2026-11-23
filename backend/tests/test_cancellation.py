"""Cancellation of rule extraction (parallel chunked extraction).

Cooperative cancellation: the cancel endpoint sets `cancelRequested = True` and
returns immediately; the background worker checks the flag before submitting new
chunks and after each Bedrock call returns. No request reaches AWS and no .env
is read (conftest).
"""

import threading
import time
from unittest.mock import patch

import pytest
from conftest import fake_pipeline, upload, wait_for
from fastapi.testclient import TestClient
from test_rule_extraction_api import LEGAL, RULE, FakeBedrock, answer, start, use, wait_for_extraction

import odos.api
import odos.rule_extraction_jobs as rx
from odos.api import app
from odos.artifact_names import RULE_JSON
from odos.llm.bedrock import BedrockResponse


# ── helpers ────────────────────────────────────────────────────────────────────


def _wait_until_called(fake, count: int = 1):
    """Block until `fake.calls >= count` or raise after a timeout."""
    for _ in range(250):
        if fake.calls >= count:
            return
        time.sleep(0.02)
    raise AssertionError(f"model not called {count} time(s) (calls so far: {fake.calls})")


# ── fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def api(monkeypatch):
    """The API without a database, one completed job, and a fake Bedrock key."""
    monkeypatch.delenv("ODOS_DATABASE_ENABLED", raising=False)
    monkeypatch.delenv("ODOS_STORAGE_DIR", raising=False)
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-key-not-real")
    with patch("odos.api.run_pipeline", side_effect=fake_pipeline(legal=LEGAL)):
        with TestClient(app) as client:
            job = wait_for(client, upload(client).json()["id"])
            assert job["status"] == "completed"
            yield client, job["id"]


# ── cooperative cancellation endpoint ─────────────────────────────────────────


def test_cancel_endpoint_sets_cancel_requested_and_returns_immediately(api, monkeypatch):
    """The cancel endpoint marks cancelRequested=True but does not wait for the worker."""
    client, job_id = api
    gate = threading.Event()
    fake = use(monkeypatch, FakeBedrock(answer(RULE), answer(RULE), gate=gate))
    try:
        assert start(client, job_id).status_code == 202
        _wait_until_called(fake)
        response = client.post(f"/api/jobs/{job_id}/rule-extraction/cancel")
        assert response.status_code == 200
        body = response.json()
        # cancel endpoint returns before the worker finishes — status is still running
        assert body["cancelRequested"] is True
        assert body["status"] in ("queued", "running")
    finally:
        gate.set()
    done = wait_for_extraction(client, job_id)
    assert done["status"] == "cancelled"


def test_cancel_endpoint_returns_409_when_extraction_has_already_finished(api, monkeypatch):
    """Cancelling a completed extraction returns 409 Conflict."""
    client, job_id = api
    use(monkeypatch, FakeBedrock(answer(RULE), answer(RULE)))
    start(client, job_id)
    assert wait_for_extraction(client, job_id)["status"] == "completed"
    assert client.post(f"/api/jobs/{job_id}/rule-extraction/cancel").status_code == 409


def test_cancel_endpoint_returns_200_if_extraction_already_cancelled(api, monkeypatch):
    """Calling cancel on an already-cancelled extraction returns 200 (idempotent)."""
    client, job_id = api
    gate = threading.Event()
    fake = use(monkeypatch, FakeBedrock(answer(RULE), answer(RULE), gate=gate))
    try:
        start(client, job_id)
        _wait_until_called(fake)
        client.post(f"/api/jobs/{job_id}/rule-extraction/cancel")
    finally:
        gate.set()
    assert wait_for_extraction(client, job_id)["status"] == "cancelled"
    r = client.post(f"/api/jobs/{job_id}/rule-extraction/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


# ── no partial results published ───────────────────────────────────────────────


def test_cancelled_extraction_does_not_overwrite_previous_rules_json(api, monkeypatch):
    """A cancelled extraction does not replace a previous successful rules.json."""
    client, job_id = api
    # complete a first extraction so there is a rules.json
    use(monkeypatch, FakeBedrock(answer(RULE), answer(RULE)))
    start(client, job_id)
    assert wait_for_extraction(client, job_id)["status"] == "completed"
    before = client.get(f"/api/jobs/{job_id}/files/{RULE_JSON}").content

    gate = threading.Event()
    fake = use(monkeypatch, FakeBedrock(answer(RULE), answer(RULE), gate=gate))
    try:
        assert start(client, job_id).status_code == 202
        _wait_until_called(fake)
        client.post(f"/api/jobs/{job_id}/rule-extraction/cancel")
    finally:
        gate.set()

    done = wait_for_extraction(client, job_id)
    assert done["status"] == "cancelled" and done["rulesFile"] is None
    # the previous rules.json is intact
    assert client.get(f"/api/jobs/{job_id}/files/{RULE_JSON}").content == before
    # the document job itself is still completed
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "completed"


def test_cancellation_before_model_is_called_sets_no_external_request(api, monkeypatch):
    """Cancelling before any Bedrock call → externalRequestStarted stays False."""
    client, job_id = api
    gate = threading.Event()
    use(monkeypatch, FakeBedrock(answer(RULE), answer(RULE), gate=gate))
    try:
        assert start(client, job_id).status_code == 202
        # Upload a second job and cancel its extraction before the gate releases
        other = wait_for(client, upload(client, name="other.pdf").json()["id"])["id"]
        assert start(client, other).status_code == 202
        cancelled = client.post(f"/api/jobs/{other}/rule-extraction/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["externalRequestStarted"] is False
        assert "charged" not in (cancelled.json()["message"] or "")
    finally:
        gate.set()
    assert wait_for_extraction(client, job_id)["status"] == "completed"
    assert wait_for_extraction(client, other)["status"] == "cancelled"
    assert client.get(f"/api/jobs/{other}/rule-extraction").json()["rulesFile"] is None


def test_cancellation_after_model_called_reports_possible_charge(api, monkeypatch):
    """Cancelling after a Bedrock call started → externalRequestStarted=True + charge warning on final state."""
    client, job_id = api
    gate = threading.Event()
    fake = use(monkeypatch, FakeBedrock(answer(RULE), answer(RULE), gate=gate))
    try:
        assert start(client, job_id).status_code == 202
        _wait_until_called(fake)
        response = client.post(f"/api/jobs/{job_id}/rule-extraction/cancel")
        # Cancel endpoint returns at once with the current state; message is set only after the worker finishes.
        assert response.json()["externalRequestStarted"] is True
    finally:
        gate.set()
    done = wait_for_extraction(client, job_id)
    assert done["status"] == "cancelled"
    assert "may still be charged" in (done["message"] or "")


# ── cancellation of an in-flight Bedrock call ──────────────────────────────────


def test_cancel_during_model_call_does_not_trigger_retry(api, monkeypatch):
    """When cancellation fires after a Bedrock call returns (bad JSON), no correction retry is sent."""
    client, job_id = api

    class CancelAfterCall(FakeBedrock):
        def converse(self, system, user, **kwargs):
            self.calls += 1
            with odos.api._lock:
                job = odos.api._jobs.get(job_id)
                if job and job.ruleExtraction:
                    job.ruleExtraction.cancelRequested = True
            return BedrockResponse("not json", "end_turn", 1, 1, 1, "m")

    use(monkeypatch, CancelAfterCall())
    assert start(client, job_id).status_code == 202
    done = wait_for_extraction(client, job_id)
    assert done["status"] == "cancelled"
    assert done["externalRequestStarted"] is True
    assert "may still be charged" in (done["message"] or "")
    assert client.get(f"/api/jobs/{job_id}/files/{RULE_JSON}").status_code == 404


# ── cancelled extraction allows a new one ─────────────────────────────────────


def test_cancelled_extraction_allows_a_new_successful_extraction(api, monkeypatch):
    """After a cancellation, starting a fresh extraction succeeds and writes rules.json."""
    client, job_id = api
    gate = threading.Event()
    fake = use(monkeypatch, FakeBedrock(answer(RULE), answer(RULE), gate=gate))
    try:
        assert start(client, job_id).status_code == 202
        _wait_until_called(fake)
        client.post(f"/api/jobs/{job_id}/rule-extraction/cancel")
    finally:
        gate.set()
    assert wait_for_extraction(client, job_id)["status"] == "cancelled"

    fake2 = use(monkeypatch, FakeBedrock(answer(RULE), answer(RULE)))
    assert start(client, job_id).status_code == 202
    done = wait_for_extraction(client, job_id)
    assert done["status"] == "completed"
    assert fake2.calls >= 1
    assert client.get(f"/api/jobs/{job_id}/files/{RULE_JSON}").status_code == 200


# ── cooperative cancellation via should_stop ───────────────────────────────────


def test_cancellation_via_should_stop_callback_stops_extraction(api, monkeypatch):
    """The should_stop callback raised through cooperative cancellation stops the extraction."""
    client, job_id = api
    entered = threading.Event()
    original = rx.extract_rules  # the patched-in name from the import alias

    def slow_extract(legal, *, should_stop=None, **kwargs):
        entered.set()
        for _ in range(250):
            if should_stop and should_stop():
                from odos.llm.rule_extraction import ExtractionCancelled
                raise ExtractionCancelled()
            time.sleep(0.02)
        return original(legal, should_stop=should_stop, **kwargs)

    with patch.object(rx, "extract_rules", side_effect=slow_extract):
        assert start(client, job_id).status_code == 202
        assert entered.wait(5), "extract_rules was never entered"
        assert client.post(f"/api/jobs/{job_id}/rule-extraction/cancel").status_code == 200

    done = wait_for_extraction(client, job_id)
    assert done["status"] == "cancelled"
    assert done["rulesFile"] is None
    assert client.get(f"/api/jobs/{job_id}/files/{RULE_JSON}").status_code == 404


# ── job-state recovery across server restart ───────────────────────────────────


def test_restore_keeps_a_cancelled_extraction():
    """A cleanly cancelled extraction survives a restart unchanged."""
    finished = rx.RuleExtraction.queued(rx.RuleExtractionRequest())
    finished.mark_cancelled()
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        from pathlib import Path
        p = Path(d)
        rx.save(p, finished)
        restored = rx.restore(p)
    assert restored is not None
    assert restored.status == "cancelled" and restored.errorCode == "cancelled"
    assert restored.message == rx.CANCELLED
    assert restored.message != rx.INTERRUPTED


def test_restore_marks_cancel_requested_on_restart_as_cancelled_with_charge_warning():
    """Running extraction with cancelRequested=True at restart → cancelled + charge warning."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        from pathlib import Path
        p = Path(d)
        running = rx.RuleExtraction.queued(rx.RuleExtractionRequest())
        running.mark_running()
        running.cancelRequested = True
        running.externalRequestStarted = True
        rx.save(p, running)
        stopped = rx.restore(p)
    assert stopped.status == "cancelled" and stopped.errorCode == "cancelled"
    assert "may still be charged" in stopped.message
    assert stopped.message != rx.INTERRUPTED


def test_restore_marks_cancel_requested_without_external_request_as_cancelled_no_charge():
    """cancelRequested=True with no external request → cancelled message without charge warning."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        from pathlib import Path
        p = Path(d)
        running = rx.RuleExtraction.queued(rx.RuleExtractionRequest())
        running.mark_running()
        running.cancelRequested = True
        running.externalRequestStarted = False
        rx.save(p, running)
        stopped = rx.restore(p)
    assert stopped.status == "cancelled"
    assert "charged" not in stopped.message


def test_new_extraction_is_refused_until_the_cancelled_one_has_really_stopped(api, monkeypatch):
    """A model call cannot be interrupted: while it is still in flight a new start gets 409 and no second paid call is made."""
    client, job_id = api
    gate = threading.Event()
    fake = use(monkeypatch, FakeBedrock(answer(RULE), answer(RULE), gate=gate))
    try:
        assert start(client, job_id).status_code == 202
        _wait_until_called(fake)
        assert client.post(f"/api/jobs/{job_id}/rule-extraction/cancel").status_code == 200
        again = start(client, job_id)
        assert again.status_code == 409
        time.sleep(0.2)
        assert fake.calls == 1
    finally:
        gate.set()
    assert wait_for_extraction(client, job_id)["status"] == "cancelled"
    assert start(client, job_id).status_code == 202  # allowed once the worker has stopped
    wait_for_extraction(client, job_id)
