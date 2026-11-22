"""The asynchronous rule extraction of the web API (without the database; the status file is what survives a restart).

The Bedrock client is replaced by a fake in every test: no request reaches AWS, and no .env is read (conftest)."""

import json
import threading
import time
from unittest.mock import patch, MagicMock

import pytest
from conftest import fake_pipeline, upload, wait_for
from fastapi.testclient import TestClient

import odos.api
import odos.rule_extraction_jobs as rx
from odos.api import app
from odos.artifact_names import RULE_JSON
from odos.llm.bedrock import BedrockConfig, BedrockRequestError, BedrockResponse, BedrockThrottledError, BedrockUnavailableError
from odos.pipeline import Outcome

LEGAL = {
    "schemaVersion": "2.0", "id": "demo-bo", "title": "Demo-Bauordnung", "documentType": "de_legislation", "language": "de",
    "structure": [{"id": "doc/par-6", "type": "section", "pages": [10], "children": [
        {"id": "doc/par-6/abs-1", "type": "subsection", "pages": [10], "text": "Gebäude halten mindestens 3 m Abstand."},
        {"id": "doc/par-6/abs-2", "type": "subsection", "pages": [10], "text": "Garagen sind zulässig."}]}],
    "sentences": [{"id": "doc/par-6/abs-1/satz-1", "ranges": [{"elementId": "doc/par-6/abs-1", "start": 0, "end": 38}]},
                  {"id": "doc/par-6/abs-2/satz-1", "ranges": [{"elementId": "doc/par-6/abs-2", "start": 0, "end": 22}]}],
}
RULE = {"schemaVersion": "2.0", "id": "par-6-abs-1",
        "source": {"elements": [{"elementId": "doc/par-6/abs-1", "sentenceId": "doc/par-6/abs-1/satz-1", "role": "primary"}]},
        "classification": {"type": "obligation", "summary": "Gebäude halten mindestens 3 m Abstand."},
        "requirements": [{"kind": "numeric", "fact": "distance_to_boundary", "operator": ">=", "value": 3, "unit": "m"}],
        "review": {"status": "draft"}}
UNUSABLE = {"schemaVersion": "2.0", "id": "bad", "source": {"elements": [{"elementId": "doc/elsewhere"}]},
            "classification": {"type": "obligation", "summary": "x"}, "requirements": [], "review": {"status": "draft"}}


def answer(*rules, text=None):
    return BedrockResponse(text if text is not None else json.dumps({"rules": list(rules)}), "end_turn", 900, 400, 5, "m")


class FakeBedrock:
    """Answers in order. `gate` holds the answer back until the test releases it (the request must not wait for it)."""

    def __init__(self, *answers, gate: threading.Event | None = None):
        self.config, self.answers, self.gate, self.calls = BedrockConfig(), list(answers), gate, 0

    def converse(self, system, user, **kwargs):
        self.calls += 1
        if self.gate is not None:
            assert self.gate.wait(5), "the test never released the model answer"
        if "REVISION MODE:" in system:
            return answer(text='{"replacements": [], "additions": []}')
        item = self.answers.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def api(monkeypatch):
    """The API without database, a completed job with the demo Legal JSON, and a configured (fake) Bedrock key."""
    monkeypatch.delenv("ODOS_DATABASE_ENABLED", raising=False)
    monkeypatch.delenv("ODOS_STORAGE_DIR", raising=False)
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-key-not-real")
    with patch("odos.api.run_pipeline", side_effect=fake_pipeline(legal=LEGAL)):
        with TestClient(app) as client:
            job = wait_for(client, upload(client).json()["id"])
            assert job["status"] == "completed" and job["ruleExtraction"] is None
            yield client, job["id"]


def use(monkeypatch, fake):
    monkeypatch.setattr(rx, "bedrock_client", lambda: fake)
    return fake


def wait_for_extraction(client, job_id) -> dict:
    for _ in range(250):
        state = client.get(f"/api/jobs/{job_id}/rule-extraction").json()
        if state["status"] not in ("queued", "running"):
            return state
        time.sleep(0.02)
    raise AssertionError(f"rule extraction of {job_id} did not finish: {state}")


def start(client, job_id, body=None):
    return client.post(f"/api/jobs/{job_id}/rule-extraction", json=body)


# ── workflow ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_extraction_returns_at_once_runs_in_the_background_and_saves_the_rules_artifact(api, monkeypatch):
    client, job_id = api
    gate = threading.Event()
    fake = use(monkeypatch, FakeBedrock(answer(RULE, UNUSABLE), gate=gate))
    response = start(client, job_id)
    assert response.status_code == 202
    queued = response.json()
    assert queued["status"] in ("queued", "running") and queued["scope"] == "document" and queued["rulesFile"] is None
    assert queued["review"]["humanReviewRequired"] is True
    assert client.get(f"/api/jobs/{job_id}").json()["ruleExtraction"]["status"] in ("queued", "running")
    gate.set()  # the model answers only after the request has returned
    done = wait_for_extraction(client, job_id)
    assert fake.calls == 3
    assert done["status"] == "completed" and done["rulesFile"] == RULE_JSON and done["errorCode"] is None
    assert done["counts"] == {"proposed": 2, "accepted": 1, "retained": 2, "invalid": 1,
                              "rejected": 0, "repaired": 0, "flagged": 0}
    assert done["coverage"]["sentences"] == 2 and done["coverage"]["sentencesCited"] == 1
    assert done["coverage"]["uncitedSentenceIds"] == ["doc/par-6/abs-2/satz-1"]
    assert done["coverage"]["coveredByExceptionTextIds"] == []
    assert done["modelOutput"] == {"requests": 3, "parse": "workflow", "partial": False, "diagnostics": 0}
    assert done["review"]["status"] == "draft" and done["review"]["rulesWithIssues"] == 1
    assert done["startedAt"] and done["finishedAt"] and done["promptVersion"] == "4"
    rules = client.get(f"/api/jobs/{job_id}/files/{RULE_JSON}").json()
    assert [r["id"] for r in rules["rules"]] == ["demo-bo-par-6-abs-1", "demo-bo-bad"]
    assert rules["rules"][0]["source"]["documentId"] == "demo-bo" and rules["rules"][0]["review"]["status"] == "draft"
    assert rules["_generation"]["rulesRejected"] == []
    report = client.get(f"/api/jobs/{job_id}/files/{done['reportFile']}").json()
    assert report["runId"] == rules["_generation"]["runId"]
    assert report["chunks"][0]["report"]["rounds"][0]["candidatesAfter"][1] == UNUSABLE
    assert client.get(f"/api/jobs/{job_id}").json()["ruleExtraction"] == done


def test_a_selected_scope_is_sent_and_reported(api, monkeypatch):
    client, job_id = api
    use(monkeypatch, FakeBedrock(answer(RULE)))
    assert start(client, job_id, {"elementIds": ["doc/par-6/abs-1"]}).status_code == 202
    done = wait_for_extraction(client, job_id)
    assert done["scope"] == ["doc/par-6/abs-1"] and done["coverage"]["sentences"] == 1


def test_a_second_extraction_while_one_runs_and_deleting_the_job_are_refused(api, monkeypatch):
    client, job_id = api
    gate = threading.Event()
    use(monkeypatch, FakeBedrock(answer(RULE), gate=gate))
    assert start(client, job_id).status_code == 202
    assert start(client, job_id).status_code == 409
    assert client.delete(f"/api/jobs/{job_id}").status_code == 409
    gate.set()
    assert wait_for_extraction(client, job_id)["status"] == "completed"
    assert client.delete(f"/api/jobs/{job_id}").status_code == 204


def test_paid_extractions_waiting_at_once_are_limited(api, monkeypatch):
    client, job_id = api
    monkeypatch.setattr(rx, "MAX_QUEUED_RULE_EXTRACTIONS", 1)
    with patch("odos.api.run_pipeline", side_effect=fake_pipeline(legal=LEGAL)):
        other = wait_for(client, upload(client).json()["id"])["id"]
    gate = threading.Event()
    use(monkeypatch, FakeBedrock(answer(RULE), answer(RULE), gate=gate))
    assert start(client, job_id).status_code == 202
    response = start(client, other)
    assert response.status_code == 429 and "Too many" in response.json()["detail"]
    gate.set()
    wait_for_extraction(client, job_id)
    assert start(client, other).status_code == 202
    assert wait_for_extraction(client, other)["status"] == "completed"


# ── failures ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_bedrock_failure_is_a_failed_status_with_a_fixed_message_and_the_old_rules_stay(api, monkeypatch):
    client, job_id = api
    use(monkeypatch, FakeBedrock(answer(RULE)))
    start(client, job_id)
    first = wait_for_extraction(client, job_id)
    before = client.get(f"/api/jobs/{job_id}/files/{RULE_JSON}").json()
    use(monkeypatch, FakeBedrock(BedrockThrottledError("Bedrock ThrottlingException: rate exceeded for account 123")))
    assert start(client, job_id).status_code == 202
    failed = wait_for_extraction(client, job_id)
    assert (failed["status"], failed["errorCode"]) == ("failed", "bedrock_throttled")
    assert failed["message"] == "Amazon Bedrock is busy. Try again later." and "123" not in json.dumps(failed)
    assert failed["counts"] == {} and failed["rulesFile"] is None and first["status"] == "completed"
    assert client.get(f"/api/jobs/{job_id}/files/{RULE_JSON}").json() == before  # a failed run never replaces the result


def test_a_failed_extraction_reports_the_aws_facts_in_status_and_log_but_no_content(api, monkeypatch, caplog):
    client, job_id = api
    error = BedrockRequestError("Bedrock ValidationException: text of the document 4711", code="ValidationException",
                                http_status=400, retry_attempts=1)
    use(monkeypatch, FakeBedrock(error))
    with caplog.at_level("WARNING"):
        start(client, job_id)
        failed = wait_for_extraction(client, job_id)
    assert failed["errorCode"] == "bedrock_request"
    detail = failed["errorDetail"]
    assert (detail["awsCode"], detail["httpStatus"], detail["retryAttempts"]) == ("ValidationException", 400, 1)
    assert isinstance(detail["elapsedSeconds"], int)
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "awsCode=ValidationException" in logged and "httpStatus=400" in logged
    assert "4711" not in logged and "4711" not in json.dumps(failed)


def test_a_failure_without_a_response_reports_the_client_side_cause(api, monkeypatch):
    client, job_id = api
    use(monkeypatch, FakeBedrock(BedrockUnavailableError("The connection to Bedrock failed.", cause="ConnectionClosedError")))
    start(client, job_id)
    failed = wait_for_extraction(client, job_id)
    assert (failed["errorCode"], failed["errorDetail"]["cause"]) == ("bedrock_unavailable", "ConnectionClosedError")


def test_malformed_answers_are_preserved_after_the_three_call_budget(api, monkeypatch):
    client, job_id = api
    fake = use(monkeypatch, FakeBedrock(answer(text='{"rules": [{"id": "x" "y"}]}'),
                                       answer(text="still not JSON {"), answer(text="not JSON")))
    start(client, job_id)
    failed = wait_for_extraction(client, job_id)
    assert fake.calls == 3
    assert failed["status"] == "completed" and failed["workflow"]["outcome"] == "completed_with_issues"
    assert failed["modelOutput"]["partial"] is True
    report = client.get(f"/api/jobs/{job_id}/files/{failed['reportFile']}").json()
    rounds = report["chunks"][0]["report"]["rounds"]
    assert len(rounds) == 3 and all(r["rawResponse"] for r in rounds)
    assert client.get(f"/api/jobs/{job_id}/files/{rx.DIAGNOSTICS_DIR}").status_code == 404  # never served
    assert client.get(f"/api/jobs/{job_id}/files/{RULE_JSON}").json()["rules"] == []


def test_a_malformed_first_answer_and_a_valid_correction_complete(api, monkeypatch):
    client, job_id = api
    use(monkeypatch, FakeBedrock(answer(text="Here: {not json"), answer(RULE)))
    start(client, job_id)
    done = wait_for_extraction(client, job_id)
    assert done["status"] == "completed" and done["modelOutput"] == {"requests": 2, "parse": "workflow", "partial": False, "diagnostics": 0}


# ── request validation (nothing is queued or paid for) ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("body, status", [
    ({"elementIds": ["doc/nowhere"]}, 422),
    ({"elementIds": []}, 422),
    ({"elementIds": "doc/par-6"}, 422),
    ({"elementIds": [""]}, 422),
    ({"elementIds": ["doc/par-6"], "model": "other"}, 422),  # unknown fields are refused
])
def test_invalid_requests_are_refused_before_anything_is_queued(api, monkeypatch, body, status):
    client, job_id = api
    fake = use(monkeypatch, FakeBedrock(answer(RULE)))
    assert start(client, job_id, body).status_code == status
    assert fake.calls == 0 and client.get(f"/api/jobs/{job_id}").json()["ruleExtraction"] is None


def test_unknown_job_and_unknown_extraction_are_404(api):
    client, job_id = api
    assert start(client, "unknown").status_code == 404
    assert client.get(f"/api/jobs/{job_id}/rule-extraction").status_code == 404


def test_without_a_bedrock_key_the_extraction_is_refused(api, monkeypatch):
    client, job_id = api
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK")
    response = start(client, job_id)
    assert response.status_code == 503 and "not configured" in response.json()["detail"]


def test_a_text_too_large_for_the_context_window_is_refused(api, monkeypatch):
    client, job_id = api
    monkeypatch.setenv("ODOS_BEDROCK_CONTEXT_TOKENS", "1000")
    assert start(client, job_id).status_code == 413


def test_a_retry_setting_above_one_is_a_configuration_error(api, monkeypatch):
    client, job_id = api
    monkeypatch.setenv("ODOS_BEDROCK_OUTPUT_RETRIES", "5")
    assert start(client, job_id).status_code == 503


def test_an_unsupported_job_has_no_legal_json_to_extract_from(monkeypatch):
    monkeypatch.delenv("ODOS_DATABASE_ENABLED", raising=False)
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-key-not-real")
    with patch("odos.api.run_pipeline", side_effect=fake_pipeline(Outcome.UNSUPPORTED)):
        with TestClient(app) as client:
            job_id = wait_for(client, upload(client).json()["id"])["id"]
            assert start(client, job_id).status_code == 409


def test_a_missing_legal_json_artifact_is_reported(api, monkeypatch):
    client, job_id = api
    (odos.api._storage / job_id / "document.json").unlink()
    assert start(client, job_id).status_code == 404


# ── status file: survives a restart ───────────────────────────────────────────────────────────────────────────────────


def test_the_status_file_is_restored_and_an_interrupted_run_is_failed(tmp_path):
    running = rx.RuleExtraction.queued(rx.RuleExtractionRequest())
    running.mark_running()
    rx.save(tmp_path, running)
    restored = rx.restore(tmp_path)
    assert (restored.status, restored.errorCode, restored.message) == ("failed", "interrupted", rx.INTERRUPTED)
    assert rx.restore(tmp_path) == restored  # written back
    completed = restored.model_copy(update={"status": "completed", "errorCode": None})
    rx.save(tmp_path, completed)
    assert rx.restore(tmp_path).status == "completed"
    (tmp_path / rx.RULE_EXTRACTION_STATUS).write_text("{broken", encoding="utf-8")
    assert rx.restore(tmp_path) is None
    assert rx.restore(tmp_path / "none") is None


# ── with the database: the extraction is restored with its job after a restart ───────────────────────────────────────


def test_with_the_database_the_extraction_survives_a_restart_and_a_cut_off_run_is_failed(db, tmp_path, monkeypatch):
    monkeypatch.setenv("ODOS_DATABASE_ENABLED", "1")
    monkeypatch.setenv("ODOS_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-key-not-real")
    use(monkeypatch, FakeBedrock(answer(RULE)))
    with patch("odos.api.run_pipeline", side_effect=fake_pipeline(legal=LEGAL)):
        with TestClient(app) as client:
            job_id = wait_for(client, upload(client).json()["id"])["id"]
            other_id = wait_for(client, upload(client).json()["id"])["id"]
            start(client, job_id)
            done = wait_for_extraction(client, job_id)
    running = rx.RuleExtraction.queued(rx.RuleExtractionRequest())
    running.mark_running()
    rx.save(tmp_path / other_id, running)  # as if the server stopped during the model call
    with TestClient(app) as client:
        assert client.get(f"/api/jobs/{job_id}/rule-extraction").json() == done
        assert client.get(f"/api/jobs/{job_id}/files/{RULE_JSON}").json()["rules"][0]["id"] == "demo-bo-par-6-abs-1"
        cut_off = client.get(f"/api/jobs/{other_id}").json()["ruleExtraction"]
        assert (cut_off["status"], cut_off["errorCode"]) == ("failed", "interrupted")
        assert client.delete(f"/api/jobs/{other_id}").status_code == 204


# ── interaction: parallel extraction ↔ human review ──────────────────────────────────────────────────────────────────


def test_posting_a_review_while_extraction_is_running_is_refused_with_409(api, monkeypatch):
    """The Human Review POST endpoint must return 409 while a rule extraction is active (queued or running).

    After extraction completes, the guard no longer fires. This test mocks require_storage so it runs without a
    PostgreSQL database; the guard in api.py fires before any database call is made."""
    import odos.rule_reviews as rv

    client, job_id = api
    gate = threading.Event()
    use(monkeypatch, FakeBedrock(answer(RULE), gate=gate))
    # bypass the database requirement so the extraction-active guard is reached
    monkeypatch.setattr(rv, "require_storage", MagicMock())

    start(client, job_id)
    # extraction is queued/running while gate is closed
    state = client.get(f"/api/jobs/{job_id}").json()
    assert state["ruleExtraction"]["status"] in ("queued", "running")

    review_body = {
        "ruleId": "demo-bo-par-6-abs-1",
        "extractionId": "x",  # a placeholder; the guard fires before the value is validated against the DB
        "expectedRuleSha256": "0" * 64,
        "expectedLastEventId": 0,
        "action": "accept",
        "reviewer": "Test Reviewer",
    }
    response = client.post(f"/api/jobs/{job_id}/rule-reviews", json=review_body)
    assert response.status_code == 409
    assert "running" in response.json()["detail"].lower()

    gate.set()
    done = wait_for_extraction(client, job_id)
    assert done["status"] == "completed"
    # Guard no longer fires: the extraction-active message is absent from the response.
    # The call now reaches rv.record_review which rejects the placeholder hash — different 409 or 503.
    response2 = client.post(f"/api/jobs/{job_id}/rule-reviews", json=review_body)
    assert "running" not in response2.json().get("detail", "").lower()
