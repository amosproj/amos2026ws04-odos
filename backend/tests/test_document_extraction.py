"""Provision ownership, reference isolation, failure retention and merged audit reports."""

import copy
import json
import threading
from dataclasses import replace

import pytest

from odos.llm.bedrock import BedrockConfig, BedrockResponse, BedrockUnavailableError
from odos.llm.document_extraction import extract_document, plan_chunks, prepare_chunk
from odos.llm.rule_extraction import _walk, write_rules_json
from test_extraction_workflow import SequenceClient, broken_rule
from test_rule_extraction import ABS1, LEGAL, model_rule

PAR1 = "doc/teil-1/par-1"
PAR2 = "doc/teil-1/par-2"


@pytest.fixture(autouse=True)
def deterministic_sequence_clients(monkeypatch):
    """Canned answer sequences are serial; dedicated tests opt into real concurrency."""
    monkeypatch.setattr("odos.llm.document_extraction.MAX_PARALLEL_CHUNKS", 1)


def other_rule(**kwargs):
    rule = model_rule(**kwargs)
    rule["source"]["elements"] = [{"elementId": PAR2 + "/abs-1", "role": "primary"}]
    return rule


def test_plan_is_ordered_collapses_overlap_and_preserves_a_narrow_selection():
    _, chunks = plan_chunks(LEGAL, ["doc/teil-1", PAR1])
    assert [c.id for c in chunks] == [PAR1, PAR2]
    _, narrow = plan_chunks(LEGAL, [ABS1])
    assert [c.id for c in narrow] == [PAR1]
    assert ABS1 in {n["id"] for n in _walk(narrow[0].target["structure"])}
    assert PAR1 + "/abs-2" not in {n["id"] for n in _walk(narrow[0].target["structure"])}


def test_annex_and_container_text_are_not_silently_skipped():
    legal = copy.deepcopy(LEGAL)
    legal["structure"][0]["text"] = "Scope outside a provision."
    legal["structure"].append({"id": "doc/annex", "type": "annex", "text": "Annex text."})
    _, chunks = plan_chunks(legal)
    assert [c.id for c in chunks] == ["doc/teil-1", PAR1, PAR2, "doc/annex"]
    assert chunks[0].kind == chunks[-1].kind == "non_provision"
    assert len(list(_walk(chunks[0].target["structure"]))) == 1


def referenced_legal():
    legal = copy.deepcopy(LEGAL)
    legal["structure"][0]["children"][0]["children"][0]["text"] += " Siehe § 2 Abs. 1 und § 99."
    legal["structure"][0]["children"][1]["children"][0]["text"] += " Siehe § 88."
    return legal


def test_only_direct_references_are_context_not_extraction_targets():
    legal = referenced_legal()
    _, chunks = plan_chunks(legal, [PAR1])
    req, findings = prepare_chunk(legal, chunks[0], BedrockConfig())
    payload = json.loads(req.user.split("\n", 1)[1])
    refs = payload["context"]["referencedProvisions"]
    assert [r["elementId"] for r in refs] == [PAR2 + "/abs-1"]
    assert any(f["citation"] == "§ 99" and f["status"] == "unresolved" for f in findings)
    assert not any("88" in f.get("citation", "") for f in findings)
    assert "Do not extract standalone rules from context" in req.system
    assert PAR2 not in {n["id"] for n in _walk(req.target_document["structure"])}


def test_external_references_and_context_over_budget_are_reported(monkeypatch):
    legal = referenced_legal()
    legal["structure"][0]["children"][0]["children"][0]["text"] += " Nach § 2 BGB."
    _, chunks = plan_chunks(legal, [PAR1])
    monkeypatch.setattr("odos.llm.document_extraction.CONTEXT_TOKEN_BUDGET", 1)
    req, findings = prepare_chunk(legal, chunks[0], BedrockConfig())
    assert not json.loads(req.user.split("\n", 1)[1])["context"]["referencedProvisions"]
    assert any("budget" in f.get("reason", "") for f in findings)
    assert any("External" in f.get("reason", "") for f in findings)


def test_merge_retains_duplicate_ids_with_traceability_and_writes_chunk_artifacts(tmp_path, monkeypatch):
    monkeypatch.delenv("ODOS_RULE_EXTRACTION_ARCHIVE_DIR", raising=False)
    client = SequenceClient({"rules": [model_rule()]}, {"rules": [other_rule()]})
    result = extract_document(LEGAL, client=client, diagnostics_dir=tmp_path / "llm-diagnostics")
    assert len(client.calls) == 2
    assert len(result.rules) == 2
    assert len({r["id"] for r in result.rules}) == 2
    assert result.report["integration"]["idRenames"]
    assert [o["targetId"] for o in result.report["ruleOrigins"]] == [PAR1, PAR2]
    directory = tmp_path / result.report["runDirectory"]
    assert len(list(directory.glob("chunks/*/rules.json"))) == 2
    assert len(list(directory.glob("chunks/*/report.json"))) == 2
    assert (directory / "report.json").is_file()
    write_rules_json(result, tmp_path / "rules.json")
    saved = json.loads((tmp_path / "rule_extraction_report.json").read_text())
    assert len(saved["chunks"]) == 2 and saved["checks"]["schemaValid"]


def test_one_failed_chunk_does_not_prevent_later_chunks_from_running(tmp_path):
    client = SequenceClient(BedrockUnavailableError("offline"), {"rules": [other_rule()]})
    result = extract_document(LEGAL, client=client, diagnostics_dir=tmp_path / "llm-diagnostics")
    assert len(result.rules) == 1
    assert result.report["partial"]
    assert result.report["integration"]["failedChunks"] == [PAR1]
    assert result.report["chunks"][1]["status"] == "completed"


def test_all_transport_failures_raise_and_progress_remains_available(tmp_path):
    client = SequenceClient(BedrockUnavailableError("offline"), BedrockUnavailableError("offline"))
    with pytest.raises(BedrockUnavailableError):
        extract_document(LEGAL, client=client, diagnostics_dir=tmp_path / "llm-diagnostics")
    progress = json.loads(next(tmp_path.glob("extraction-runs/*/progress.json")).read_text())
    assert len(progress["chunks"]) == 2
    assert all(c["status"] == "failed" for c in progress["chunks"])


def test_each_chunk_has_its_own_schema_budget_and_invalid_content_survives():
    client = SequenceClient({"rules": [broken_rule()]}, {"replacements": [], "additions": []},
                            {"replacements": [], "additions": []}, {"rules": [other_rule()]})
    result = extract_document(LEGAL, client=client)
    assert len(client.calls) == 4
    assert len(result.rules) == 2
    assert result.report["chunks"][0]["report"]["modelCalls"] == 3
    assert not result.report["checks"]["schemaValid"]


def test_context_only_records_are_kept_but_reported_and_do_not_cover_the_target():
    legal = referenced_legal()
    result = extract_document(legal, client=SequenceClient({"rules": [other_rule()]}), element_ids=[PAR1])
    assert len(result.rules) == 1
    assert result.report["integration"]["contextOnlyRules"]
    assert result.report["chunks"][0]["report"]["checks"]["coverage"]["sentencesCited"] == 0


def test_truncated_valid_records_do_not_trigger_a_useless_schema_patch():
    class Truncated(SequenceClient):
        def converse(self, *args, **kwargs):
            return replace(super().converse(*args, **kwargs), stop_reason="max_tokens")
    client = Truncated({"rules": [model_rule()]})
    result = extract_document(LEGAL, client=client, element_ids=[PAR1])
    assert len(client.calls) == 1
    assert result.report["integration"]["partialChunks"] == [PAR1]
    assert "Split" in result.report["chunks"][0]["actionRequired"]


def test_empty_results_remain_explicit_in_the_integration_report():
    result = extract_document(LEGAL, client=SequenceClient({"rules": []}, {"rules": []}))
    assert result.report["integration"]["emptyChunks"] == [PAR1, PAR2]
    assert result.report["outcome"] == "completed_with_issues"


@pytest.mark.parametrize("source", [None, {"elements": None}, {"elements": "not a list"}])
def test_malformed_source_survives_chunk_and_merge_inspection(source):
    rule = model_rule(source=source)
    client = SequenceClient({"rules": [rule]}, {"replacements": [], "additions": []},
                            {"replacements": [], "additions": []})
    result = extract_document(LEGAL, client=client, element_ids=[PAR1])
    assert len(result.rules) == 1
    assert result.rules[0]["source"] == source
    assert not result.report["checks"]["schemaValid"]
    assert result.report["integration"]["contextOnlyRules"]


@pytest.mark.parametrize("failed_index", [None, 2])
def test_four_workers_overlap_wait_for_every_chunk_and_merge_in_source_order(tmp_path, monkeypatch, failed_index):
    legal = copy.deepcopy(LEGAL)
    legal["structure"] = [{"id": "doc/part", "type": "part", "children": [
        {"id": f"doc/part/par-{i+1}", "type": "section", "marker": f"§ {i+1}", "children": [
            {"id": f"doc/part/par-{i+1}/abs-1", "type": "subsection", "text": "Abstand mindestens 3 m."}]}
        for i in range(5)]}]
    legal["sentences"] = []
    legal["footnotes"] = []

    class ConcurrentClient:
        config = BedrockConfig()

        def __init__(self):
            self.barrier = threading.Barrier(4)
            self.fifth_finished = threading.Event()
            self.lock = threading.Lock()
            self.active = self.peak = 0
            self.finished = []

        def converse(self, system, user, **kwargs):
            payload = json.loads(user.split("\n", 1)[1])
            target = payload["context"]["chapterPath"][-1]["id"]
            index = int(target.rsplit("-", 1)[-1]) - 1
            with self.lock:
                self.active += 1
                self.peak = max(self.peak, self.active)
            try:
                if index < 4:
                    self.barrier.wait(timeout=5)  # A serial implementation cannot pass.
                if index == 0:
                    assert self.fifth_finished.wait(5)
                if index == failed_index:
                    raise BedrockUnavailableError("offline")
                rule = model_rule(id="same-local-id")
                rule["source"]["elements"] = [{"elementId": target + "/abs-1", "role": "primary"}]
                return BedrockResponse(json.dumps({"rules": [rule]}), "end_turn", 100, 50, 1, self.config.model_id)
            finally:
                with self.lock:
                    self.active -= 1
                    self.finished.append(index)
                if index == 4:
                    self.fifth_finished.set()

    client = ConcurrentClient()
    from odos.llm import document_extraction as module
    inspect = module.inspect_candidates

    def after_all_workers(*args, **kwargs):
        assert sorted(client.finished) == list(range(5)), "Merge started before every worker finished"
        return inspect(*args, **kwargs)

    monkeypatch.setattr(module, "inspect_candidates", after_all_workers)
    result = extract_document(legal, client=client, max_workers=4, diagnostics_dir=tmp_path / "llm-diagnostics")
    assert client.peak == 4
    assert client.finished[0] != 0
    assert [e["index"] for e in result.report["chunks"]] == list(range(5))
    expected = [f"doc/part/par-{i+1}" for i in range(5) if i != failed_index]
    assert [o["targetId"] for o in result.report["ruleOrigins"]] == expected
    assert len({r["id"] for r in result.rules}) == len(expected)
    assert result.report["maxWorkers"] == 4
    assert result.report["strategy"] == "parallel_provisions"
    assert all(e["elapsedSeconds"] >= 0 and e["queueSeconds"] >= 0 for e in result.report["chunks"])
    assert result.report["timing"]["sumChunkSeconds"] > 0
    if failed_index is not None:
        assert result.report["partial"]
        assert result.report["integration"]["failedChunks"] == [f"doc/part/par-{failed_index+1}"]
    assert len(list((tmp_path / result.report["runDirectory"]).glob("chunks/*/rules.json"))) == len(expected)
