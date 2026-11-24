"""Feedback budgets, content retention and report linkage, without paid model calls."""

import copy
import json
from dataclasses import replace

import pytest

from odos.llm.bedrock import BedrockConfig, BedrockResponse, BedrockUnavailableError
from odos.llm.extraction_workflow import extract_rules_workflow
from odos.llm.rule_extraction import write_rules_json
from test_rule_extraction import ABS1, LEGAL, model_rule


class SequenceClient:
    def __init__(self, *answers):
        self.config = BedrockConfig()
        self.answers = list(answers)
        self.calls = []

    def converse(self, system, user, **kwargs):
        self.calls.append({"system": system, "user": user, **kwargs})
        assert self.answers, "The workflow exceeded its expected model-call budget"
        value = self.answers.pop(0)
        if isinstance(value, Exception):
            raise value
        text = value if isinstance(value, str) else json.dumps(value)
        return BedrockResponse(text, "end_turn", 100, 50, 1, self.config.model_id)


@pytest.fixture(autouse=True)
def no_live_archive(monkeypatch):
    monkeypatch.delenv("ODOS_RULE_EXTRACTION_ARCHIVE_DIR", raising=False)
    monkeypatch.delenv("ODOS_RULE_EXTRACTION_REPORT_DIR", raising=False)


def run(client):
    return extract_rules_workflow(copy.deepcopy(LEGAL), client=client, element_ids=[ABS1], max_model_calls=3)


def broken_rule():
    return model_rule(requirements=None, requirementExpression={
        "kind": "requirement", "requirement": {"kind": "all", "requirements": []}})


def test_schema_feedback_targets_the_actual_nested_error_and_can_finish_early():
    client = SequenceClient({"rules": [broken_rule()]},
                            {"replacements": [{"index": 0, "rule": model_rule()}], "additions": []})
    result = run(client)
    assert len(client.calls) == 2
    assert "not an atomic requirement kind" in client.calls[1]["user"]
    assert "REVISION MODE" in client.calls[1]["system"]
    assert result.generation["counts"]["invalid"] == 0
    assert result.report["outcome"] == "completed"
    assert result.report["rounds"][1]["changes"][0]["before"] == broken_rule()


def test_third_check_keeps_invalid_rules_in_the_main_result():
    bad = broken_rule()
    client = SequenceClient({"rules": [bad]}, {"replacements": [], "additions": []},
                            {"replacements": [], "additions": []})
    result = run(client)
    assert len(client.calls) == 3
    assert len(result.rules) == 1
    assert result.rules[0]["requirementExpression"] == bad["requirementExpression"]
    assert result.generation["counts"]["invalid"] == 1
    assert result.generation["counts"]["rejected"] == 0
    assert result.report["outcome"] == "completed_with_issues"
    assert len(result.report["rounds"]) == 3


def test_content_flags_do_not_retry_when_schema_passes():
    wrong = model_rule()
    wrong["requirements"][0]["value"] = 2
    client = SequenceClient({"rules": [wrong]})
    result = run(client)
    assert len(client.calls) == 1
    assert result.report["rounds"][0]["checks"]["records"][0]["flags"]
    assert result.rules[0]["requirements"][0]["value"] == 2
    assert result.report["outcome"] == "completed_with_issues"
    assert result.generation["workflow"]["schemaValid"] is True


def test_uncovered_source_units_do_not_retry_when_schema_passes():
    client = SequenceClient({"rules": [model_rule()]})
    result = extract_rules_workflow(copy.deepcopy(LEGAL), client=client)
    assert len(client.calls) == 1
    assert result.report["checks"]["coverage"]["uncitedSentences"]
    assert result.report["retryPolicy"] == "schema_only"


def test_unmentioned_rules_and_non_target_replacements_cannot_be_deleted():
    client = SequenceClient({"rules": [model_rule(), broken_rule()]},
                            {"replacements": [{"index": 0, "rule": {"requirements": []}}], "additions": []},
                            {"replacements": [], "additions": []})
    result = run(client)
    assert len(result.rules) == 2
    assert result.rules[0]["requirements"][0]["value"] == 3
    assert result.report["rounds"][1]["changes"][0]["action"] == "ignored"


def test_bad_json_uses_the_same_total_budget_and_survives_in_report():
    client = SequenceClient("not JSON", "still not JSON", "no JSON")
    result = run(client)
    assert len(client.calls) == 3
    assert result.generation["modelOutput"]["partial"] is True
    assert [r["rawResponse"] for r in result.report["rounds"]] == ["not JSON", "still not JSON", "no JSON"]


def test_failed_correction_retains_the_initial_extraction():
    client = SequenceClient({"rules": [broken_rule()]}, BedrockUnavailableError("Unavailable"))
    result = run(client)
    assert len(result.rules) == 1
    assert result.report["modelCalls"] == 2
    assert "failed" in result.report["stoppedBecause"]


def test_unparseable_correction_keeps_previous_rules_without_claiming_they_are_partial():
    client = SequenceClient({"rules": [broken_rule()]}, "bad patch", "bad patch again")
    result = run(client)
    assert len(result.rules) == 1
    assert result.generation["modelOutput"]["partial"] is False
    assert result.report["outcome"] == "completed_with_issues"
    assert len(result.report["rounds"]) == 3


def test_new_rules_are_appended_and_never_replace_untargeted_rules():
    added = model_rule(id="another-rule")
    added["source"]["elements"] = [{"elementId": ABS1, "role": "primary"}]
    added["requirements"][0]["fact"] = "another_distance"
    client = SequenceClient({"rules": [broken_rule()]},
                            {"replacements": [], "additions": [added]},
                            {"replacements": [], "additions": []})
    result = run(client)
    assert len(result.rules) == 2
    assert result.report["rounds"][1]["changes"][0]["action"] == "add"
    assert result.rules[1]["requirements"][0]["fact"] == "another_distance"


def test_truncated_output_is_preserved_and_never_claimed_complete():
    class TruncatedClient(SequenceClient):
        def converse(self, *args, **kwargs):
            response = super().converse(*args, **kwargs)
            return replace(response, stop_reason="max_tokens")

    client = TruncatedClient({"rules": [model_rule()]}, {"replacements": [], "additions": []},
                             {"replacements": [], "additions": []})
    result = run(client)
    assert len(result.rules) == 1
    assert result.report["partial"] is True
    assert result.report["outcome"] == "completed_with_issues"
    assert len(client.calls) == 1


def test_result_and_report_share_run_id_and_timestamped_basename(tmp_path, monkeypatch):
    archive = tmp_path / "bedrock-extraction-results"
    reports = tmp_path / "Reports_for_results"
    monkeypatch.setenv("ODOS_RULE_EXTRACTION_ARCHIVE_DIR", str(archive))
    monkeypatch.setenv("ODOS_RULE_EXTRACTION_REPORT_DIR", str(reports))
    result = run(SequenceClient({"rules": [model_rule()]}))
    artifact = tmp_path / "job" / "rules.json"
    artifact.parent.mkdir()
    write_rules_json(result, artifact)
    saved = next(archive.glob("*.rules.json"))
    report = next(reports.glob("*.report.json"))
    assert saved.name.removesuffix(".rules.json") == report.name.removesuffix(".report.json")
    data, audit = json.loads(saved.read_text()), json.loads(report.read_text())
    assert data["_generation"]["runId"] == audit["runId"]
    assert audit["resultFile"] == saved.name
    assert json.loads((artifact.parent / "rule_extraction_report.json").read_text())["runId"] == audit["runId"]
