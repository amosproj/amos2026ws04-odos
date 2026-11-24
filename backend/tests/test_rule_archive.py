"""Local result archives never call a model or change the original API artifact."""

from odos.llm.rule_extraction import ExtractionResult, write_rules_json


def test_repeated_exports_keep_each_run_and_the_latest_job_artifact(tmp_path, monkeypatch):
    archive = tmp_path / "archives"
    monkeypatch.setenv("ODOS_RULE_EXTRACTION_ARCHIVE_DIR", str(archive))
    artifact = tmp_path / "rules.json"
    first = ExtractionResult(rules=[{"id": "first"}], generation={"documentId": "../mbo"})
    second = ExtractionResult(rules=[{"id": "second"}], generation={"documentId": "../mbo"})

    write_rules_json(first, artifact)
    first_bytes = artifact.read_bytes()
    write_rules_json(second, artifact)
    second_bytes = artifact.read_bytes()

    snapshots = list(archive.glob("mbo_*.rules.json"))
    assert len(snapshots) == 2
    assert {p.read_bytes() for p in snapshots} == {first_bytes, second_bytes}
    assert all(p.name.endswith("Z.rules.json") for p in snapshots)
    assert artifact.read_bytes() == second_bytes


def test_unwritable_archive_keeps_successful_job_artifact(tmp_path, monkeypatch):
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("occupied", encoding="utf-8")
    monkeypatch.setenv("ODOS_RULE_EXTRACTION_ARCHIVE_DIR", str(blocked))
    artifact = tmp_path / "rules.json"
    result = ExtractionResult(rules=[], generation={"documentId": "mbo"})

    assert write_rules_json(result, artifact) == artifact
    assert artifact.is_file()
