"""Whole-document rule extraction when applicability filtering removes parts of the document.

Regression: the Musterbauordnung's procedural sections (here § 52) are filtered out before anything is sent. Each such
part became an empty chunk that raised "The selected element IDs are not part of this document" and rejected the whole
document, although no element IDs were selected. No request reaches AWS (FakeBedrock).
"""

import json
from unittest.mock import patch

import pytest
from conftest import fake_pipeline, upload, wait_for
from fastapi.testclient import TestClient
from test_rule_extraction_api import FakeBedrock, answer, start, use, wait_for_extraction

import odos.api
from odos.api import app
from odos.llm.bedrock import BedrockConfig
from odos.llm.document_extraction import check_document_request
from odos.llm.rule_extraction import InvalidScopeError, NotApplicableError

MBO = {
    "schemaVersion": "2.0", "id": "mbo", "title": "Musterbauordnung (MBO)", "documentType": "de_legislation", "language": "de",
    "structure": [
        {"id": "mbo/par-6", "type": "section", "number": "6", "pages": [10], "children": [
            {"id": "mbo/par-6/abs-1", "type": "subsection", "pages": [10], "text": "Gebäude halten mindestens 3 m Abstand."}]},
        {"id": "mbo/par-52", "type": "section", "number": "52", "pages": [40], "children": [
            {"id": "mbo/par-52/abs-1", "type": "subsection", "pages": [40], "text": "Die am Bau Beteiligten sind verantwortlich."}]},
    ],
    "sentences": [
        {"id": "mbo/par-6/abs-1/satz-1", "ranges": [{"elementId": "mbo/par-6/abs-1", "start": 0, "end": 38}]},
        {"id": "mbo/par-52/abs-1/satz-1", "ranges": [{"elementId": "mbo/par-52/abs-1", "start": 0, "end": 43}]},
    ],
}
ONLY_EXCLUDED = {**MBO, "structure": [MBO["structure"][1]], "sentences": [MBO["sentences"][1]]}
RULE = {"schemaVersion": "2.0", "id": "par-6-abs-1",
        "source": {"elements": [{"elementId": "mbo/par-6/abs-1", "sentenceId": "mbo/par-6/abs-1/satz-1", "role": "primary"}]},
        "classification": {"type": "obligation", "summary": "Gebäude halten mindestens 3 m Abstand."},
        "requirements": [{"kind": "numeric", "fact": "distance_to_boundary", "operator": ">=", "value": 3, "unit": "m"}],
        "review": {"status": "draft"}}


# ── pre-flight (no request, no API) ────────────────────────────────────────────────────────────────────────────────────


def test_a_whole_document_with_a_filtered_out_section_passes_the_preflight():
    check_document_request(MBO, BedrockConfig(), None)  # raised InvalidScopeError before the fix


def test_a_document_with_nothing_applicable_is_not_applicable_not_an_id_error():
    with pytest.raises(NotApplicableError):
        check_document_request(ONLY_EXCLUDED, BedrockConfig(), None)


def test_a_selected_but_filtered_out_section_is_not_applicable():
    with pytest.raises(NotApplicableError):
        check_document_request(MBO, BedrockConfig(), ["mbo/par-52"])


def test_unknown_element_ids_are_still_refused_strictly():
    with pytest.raises(InvalidScopeError) as caught:
        check_document_request(MBO, BedrockConfig(), ["mbo/par-6", "mbo/par-999"])
    assert not isinstance(caught.value, NotApplicableError)


# ── through the API ────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mbo_api(monkeypatch):
    monkeypatch.delenv("ODOS_DATABASE_ENABLED", raising=False)
    monkeypatch.delenv("ODOS_STORAGE_DIR", raising=False)
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-key-not-real")

    def open_job(legal):
        with patch("odos.api.run_pipeline", side_effect=fake_pipeline(legal=legal)):
            job = wait_for(client, upload(client).json()["id"])
        assert job["status"] == "completed"
        return job["id"]

    with TestClient(app) as client:
        yield client, open_job


def test_whole_document_extraction_runs_and_sends_only_the_applicable_section(mbo_api, monkeypatch):
    client, open_job = mbo_api
    job_id = open_job(MBO)
    fake = use(monkeypatch, FakeBedrock(answer(RULE), answer(RULE)))
    response = start(client, job_id)
    assert response.status_code == 202, response.text
    done = wait_for_extraction(client, job_id)
    assert done["status"] == "completed", done
    assert fake.calls == 1  # § 6 only; nothing was sent for the filtered-out § 52
    report = json.loads((odos.api._storage / job_id / done["reportFile"]).read_text(encoding="utf-8"))
    assert report["integration"]["notApplicableChunks"] == ["mbo/par-52"]
    assert report["integration"]["failedChunks"] == []
    assert report["partial"] is False
    rules = client.get(f"/api/jobs/{job_id}/files/rules.json").json()
    assert [r["source"]["elements"][0]["elementId"] for r in rules["rules"]] == ["mbo/par-6/abs-1"]


def test_a_document_with_nothing_applicable_is_refused_before_anything_is_paid(mbo_api, monkeypatch):
    client, open_job = mbo_api
    job_id = open_job(ONLY_EXCLUDED)
    fake = use(monkeypatch, FakeBedrock(answer(RULE)))
    response = start(client, job_id)
    assert response.status_code == 422
    assert response.headers["X-ODOS-Error"] == "nothing_to_extract"
    assert "element ID" not in response.json()["detail"]
    assert fake.calls == 0


def test_unknown_selected_ids_are_refused_with_a_code_and_the_details_only_in_the_log(mbo_api, monkeypatch, caplog):
    client, open_job = mbo_api
    job_id = open_job(MBO)
    fake = use(monkeypatch, FakeBedrock(answer(RULE)))
    response = start(client, job_id, {"elementIds": ["mbo/par-999"]})
    assert response.status_code == 422
    assert response.headers["X-ODOS-Error"] == "invalid_scope"
    assert "mbo/par-999" not in response.json()["detail"]
    assert "mbo/par-999" in caplog.text
    assert fake.calls == 0


def test_retrying_after_a_refusal_works_once_the_request_is_valid(mbo_api, monkeypatch):
    client, open_job = mbo_api
    job_id = open_job(MBO)
    fake = use(monkeypatch, FakeBedrock(answer(RULE)))
    assert start(client, job_id, {"elementIds": ["mbo/par-999"]}).status_code == 422
    assert start(client, job_id).status_code == 202  # the refusal left nothing queued or locked
    assert wait_for_extraction(client, job_id)["status"] == "completed"
    assert fake.calls == 1


def test_completed_is_published_only_after_rules_json_is_written(mbo_api, monkeypatch):
    """Clients poll the status and then load rules.json: 'completed' must never be visible before the file exists."""
    import odos.rule_extraction_jobs as rx

    client, open_job = mbo_api
    job_id = open_job(MBO)
    use(monkeypatch, FakeBedrock(answer(RULE)))
    seen = []
    original = rx.save_rules

    def observing_save(result, directory):
        seen.append(odos.api.get_rule_extraction(job_id).status)  # what a poll would return right now
        original(result, directory)

    monkeypatch.setattr(rx, "save_rules", observing_save)
    assert start(client, job_id).status_code == 202
    assert wait_for_extraction(client, job_id)["status"] == "completed"
    assert seen == ["running"]
