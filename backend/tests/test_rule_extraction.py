"""Legal JSON 2.0 -> Amazon Bedrock -> Rule JSON: prompt, scope, size limit, answer handling and provenance.

Bedrock is always mocked here: the model's answers are canned strings, so the tests check what ODOS does with an answer
(validation, provenance rewrite, rejection), not what a model would say.
"""

import copy
import glob
import json
import re
from pathlib import Path

import pytest

from odos import cli
from odos.artifact_names import RULE_JSON
from odos.llm.bedrock import BedrockConfig, BedrockResponse, BedrockThrottledError
from odos.llm.rule_extraction import (
    EXAMPLE_RULE,
    DocumentTooLargeError,
    InvalidScopeError,
    MalformedOutputError,
    OutputTruncatedError,
    build_system_prompt,
    extract_rules,
    parse_rules,
    prepare_request,
    rule_validator,
    scope_document,
    write_rules_json,
)

MODEL = "eu.anthropic.claude-sonnet-4-6"

LEGAL = {
    "schemaVersion": "2.0", "id": "demo", "title": "Demo-Bauordnung", "documentType": "de_legislation", "legalSystem": "de",
    "language": "de", "pageCount": 4,
    "tableOfContentsEntries": [{"id": "doc/toc/entry-1", "text": "§ 1 Abstand " * 50}],
    "frontMatter": [{"id": "doc/front-1", "type": "text", "text": "Fassung 2024", "pages": [1]}],
    "structure": [
        {"id": "doc/teil-1", "type": "part", "title": "Allgemeines", "pages": [1], "children": [
            {"id": "doc/teil-1/par-1", "type": "section", "germanType": "Paragraph", "marker": "§ 1", "title": "Abstand", "pages": [2], "children": [
                {"id": "doc/teil-1/par-1/abs-1", "type": "subsection", "germanType": "Absatz", "marker": "(1)",
                 "text": "Gebäude müssen mindestens 3 m von der Grenze entfernt sein. Das gilt nicht für Garagen.", "pages": [2, 3]},
                {"id": "doc/teil-1/par-1/abs-2", "type": "subsection", "germanType": "Absatz", "marker": "(2)",
                 "text": "Die Behörde kann Ausnahmen zulassen.", "pages": [3]},
            ]},
            {"id": "doc/teil-1/par-2", "type": "section", "marker": "§ 2", "title": "Anderes", "pages": [4], "children": [
                {"id": "doc/teil-1/par-2/abs-1", "type": "subsection", "marker": "(1)", "text": "Anderer Text.", "pages": [4]}]},
        ]},
    ],
    "footnotes": [{"id": "doc/fn-1", "marker": "*", "text": "Notifiziert.", "pages": [2], "anchorElementIds": ["doc/teil-1/par-1/abs-1"]},
                  {"id": "doc/fn-2", "marker": "**", "text": "Fern.", "pages": [4], "anchorElementIds": ["doc/teil-1/par-2/abs-1"]}],
    "sentences": [
        {"id": "doc/teil-1/par-1/abs-1/satz-1", "unitId": "doc/teil-1/par-1/abs-1", "number": "1",
         "ranges": [{"elementId": "doc/teil-1/par-1/abs-1", "start": 0, "end": 56}]},
        {"id": "doc/teil-1/par-2/abs-1/satz-1", "unitId": "doc/teil-1/par-2/abs-1", "number": "1",
         "ranges": [{"elementId": "doc/teil-1/par-2/abs-1", "start": 0, "end": 13}]},
    ],
}
ABS1 = "doc/teil-1/par-1/abs-1"
ABS2 = "doc/teil-1/par-1/abs-2"
SATZ1 = "doc/teil-1/par-1/abs-1/satz-1"


def model_rule(**overrides) -> dict:
    """What a model might answer for abs-1: valid, with deliberately wrong provenance details the code must correct."""
    rule = {
        "schemaVersion": "2.0",
        "id": "demo-par-1-abs-1",
        "source": {"documentId": "made-up", "documentTitle": "Wrong Title", "language": "en", "citation": "§ 1 Abs. 1 Satz 1",
                   "elements": [{"elementId": ABS1, "sentenceId": SATZ1, "pdfPages": [99], "role": "primary"}]},
        "classification": {"type": "obligation", "normativeCategory": "substantive",
                           "summary": "Gebäude müssen mindestens 3 m von der Grenze entfernt sein."},
        "applicability": {"targets": [{"entity": "Gebäude"}]},
        "requirements": [{"kind": "numeric", "fact": "distance_to_boundary", "operator": ">=", "value": 3, "unit": "m"}],
        "review": {"status": "approved", "machineCheckable": True},
    }
    rule.update(overrides)
    return rule


def answer(*rules, stop="end_turn") -> BedrockResponse:
    return BedrockResponse(json.dumps({"rules": list(rules)}), stop, 1200, 300, 900, MODEL)


class FakeClient:
    """A BedrockClient stand-in that records the prompt and returns `response` (or raises it)."""

    def __init__(self, response=None, **config):
        self.config = BedrockConfig(**config)
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def converse(self, system, user, **kwargs):
        self.calls.append((system, user))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.fixture(autouse=True)
def _no_real_env_file(monkeypatch, tmp_path):
    """The CLI commands read a .env; the tests must never pick up a developer's real one (and its key)."""
    monkeypatch.setenv("ODOS_ENV_FILE", str(tmp_path / "no-such.env"))


# ── prompt and input ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_v2_is_sent_without_modifying_the_original_legal_json():
    from odos.llm_input.artifacts import build_inputs
    original = copy.deepcopy(LEGAL)
    request = prepare_request(LEGAL, BedrockConfig())
    sent = json.loads(re.search(r"<legal_json>\n(.*)\n</legal_json>", request.user, re.DOTALL).group(1))
    assert sent == build_inputs(LEGAL)[1]
    assert LEGAL == original
    assert request.scope == "document"


def test_the_system_prompt_carries_the_one_rule_json_schema_and_the_provenance_rules():
    system = build_system_prompt(LEGAL)
    schema = json.loads(re.search(r"<schema>\n(.*)\n</schema>", system, re.DOTALL).group(1))
    assert schema == json.loads(Path(__file__).parents[1].joinpath("schemas/rule-json/rule.schema.json").read_text(encoding="utf-8"))
    assert "Never invent or alter an ID" in system
    assert '"draft"' in system


def test_the_prompt_example_is_a_valid_rule():
    assert list(rule_validator().iter_errors(EXAMPLE_RULE)) == []


def test_the_prompt_example_passes_the_quality_checks():
    from odos.llm.rule_checks import check_rule

    check = check_rule(copy.deepcopy(EXAMPLE_RULE))
    assert (check.errors, check.flags, check.renamed) == ([], [], {})


def test_a_document_without_structure_is_refused():
    with pytest.raises(InvalidScopeError):
        prepare_request({"id": "x", "structure": []}, BedrockConfig())


# ── scope ─────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_scope_keeps_the_subtree_and_its_ancestors_with_unchanged_ids_and_pages():
    scoped = scope_document(LEGAL, [ABS1])
    part = scoped["structure"][0]
    assert part["id"] == "doc/teil-1" and part["title"] == "Allgemeines"
    section = part["children"][0]
    assert [section["id"], section["marker"], section["title"]] == ["doc/teil-1/par-1", "§ 1", "Abstand"]
    assert [c["id"] for c in section["children"]] == [ABS1]  # the sibling Absatz and § 2 are not sent
    assert section["children"][0] == LEGAL["structure"][0]["children"][0]["children"][0]


def test_selecting_a_provision_keeps_its_whole_subtree():
    scoped = scope_document(LEGAL, ["doc/teil-1/par-1"])
    assert [c["id"] for c in scoped["structure"][0]["children"][0]["children"]] == [ABS1, ABS2]


def test_a_scope_keeps_the_sentences_and_footnotes_of_the_kept_nodes_only():
    scoped = scope_document(LEGAL, [ABS1])
    assert [s["id"] for s in scoped["sentences"]] == [SATZ1]
    assert [f["id"] for f in scoped["footnotes"]] == ["doc/fn-1"]


def test_a_scope_drops_bulky_document_level_parts_but_keeps_the_identity():
    scoped = scope_document(LEGAL, [ABS1])
    assert "tableOfContentsEntries" not in scoped and "frontMatter" not in scoped
    assert (scoped["id"], scoped["title"], scoped["language"], scoped["schemaVersion"]) == ("demo", "Demo-Bauordnung", "de", "2.0")


def test_an_unknown_element_id_is_refused_and_named():
    with pytest.raises(InvalidScopeError, match="doc/nope"):
        prepare_request(LEGAL, BedrockConfig(), ["doc/nope"])


def test_scoping_does_not_modify_the_input():
    before = copy.deepcopy(LEGAL)
    scope_document(LEGAL, [ABS1])
    assert LEGAL == before


# ── context window ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_request_beyond_the_context_window_is_reported_and_nothing_is_sent():
    client = FakeClient(answer(model_rule()), context_tokens=5000)
    with pytest.raises(DocumentTooLargeError, match="Nothing was sent or truncated"):
        extract_rules(LEGAL, client=client)
    assert client.calls == []


def test_the_size_error_for_the_whole_document_points_to_element_selection():
    with pytest.raises(DocumentTooLargeError, match="--element-id"):
        prepare_request(LEGAL, BedrockConfig(context_tokens=5000))


def test_the_output_limit_counts_towards_the_context_window():
    system_and_user = prepare_request(LEGAL, BedrockConfig()).estimated_input_tokens
    assert prepare_request(LEGAL, BedrockConfig(context_tokens=system_and_user + 100, max_tokens=100)).fits
    with pytest.raises(DocumentTooLargeError):
        prepare_request(LEGAL, BedrockConfig(context_tokens=system_and_user + 100, max_tokens=101))


# ── provenance ────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_provenance_comes_from_the_legal_json_not_from_the_model():
    result = extract_rules(LEGAL, client=FakeClient(answer(model_rule())))
    assert result.rejected == []
    rule = result.rules[0]
    assert rule["source"]["documentId"] == "demo"  # not "made-up"
    assert rule["source"]["documentTitle"] == "Demo-Bauordnung"
    assert rule["source"]["language"] == "de"
    assert rule["source"]["citation"] == "§ 1 Abs. 1 Satz 1"  # the model's citation is kept
    element = rule["source"]["elements"][0]
    assert element == {"elementId": ABS1, "sentenceId": SATZ1, "pdfPages": [2, 3], "role": "primary"}  # pages from the Legal JSON
    assert rule["schemaVersion"] == "2.0"
    assert rule["review"]["status"] == "draft"  # "approved" is not for a model to say
    assert rule["review"]["machineCheckable"] is True
    assert any(MODEL in note for note in rule["review"]["notes"])
    assert list(rule_validator().iter_errors(rule)) == []


def test_wrongly_typed_fields_in_an_answer_reject_the_record_instead_of_crashing():
    wrong_element = model_rule(source={"elements": [{"elementId": [ABS1]}]})
    wrong_elements = model_rule(source={"elements": ["doc/teil-1/par-1/abs-1"]})
    wrong_sentence = model_rule(source={"elements": [{"elementId": ABS1, "sentenceId": [SATZ1]}]})
    wrong_reference = model_rule(references=[{"citation": "§ 2", "elementId": {"id": "x"}, "resolution": "resolved"}])
    wrong_review = model_rule(review="draft")
    result = extract_rules(LEGAL, client=FakeClient(answer(wrong_element, wrong_elements, wrong_sentence, wrong_reference, wrong_review)))
    assert [r["index"] for r in result.rejected] == [0, 1]  # unusable provenance
    assert len(result.rules) == 3
    assert "sentenceId" not in result.rules[0]["source"]["elements"][0]  # a list is not a sentence ID
    assert result.rules[1]["references"] == [{"citation": "§ 2", "resolution": "unresolved"}]
    assert result.rules[2]["review"]["status"] == "draft"  # a review that is not an object is replaced


def test_the_legal_text_and_hierarchy_are_not_touched():
    before = copy.deepcopy(LEGAL)
    extract_rules(LEGAL, client=FakeClient(answer(model_rule())))
    assert LEGAL == before


def test_a_sentence_id_the_document_does_not_have_for_that_element_is_removed():
    source = {"elements": [{"elementId": ABS2, "sentenceId": SATZ1}, {"elementId": ABS1, "sentenceId": "doc/made/up"}]}
    result = extract_rules(LEGAL, client=FakeClient(answer(model_rule(source=source))))
    elements = result.rules[0]["source"]["elements"]
    assert all("sentenceId" not in e for e in elements)  # satz-1 belongs to abs-1, not abs-2; the other does not exist
    assert [e["pdfPages"] for e in elements] == [[3], [2, 3]]


def test_a_rule_citing_an_element_that_was_not_supplied_is_rejected():
    source = {"elements": [{"elementId": ABS1}, {"elementId": "doc/teil-9/par-99/abs-1"}]}
    result = extract_rules(LEGAL, client=FakeClient(answer(model_rule(source=source), model_rule(id="good"))))
    assert [r["id"] for r in result.rules] == ["demo-good"]
    assert result.rejected[0]["index"] == 0
    assert "doc/teil-9/par-99/abs-1" in result.rejected[0]["reasons"][0]


def test_with_a_scope_only_the_supplied_elements_may_be_cited():
    outside = model_rule(source={"elements": [{"elementId": "doc/teil-1/par-2/abs-1"}]})  # exists, but was not sent
    result = extract_rules(LEGAL, client=FakeClient(answer(outside, model_rule(id="inside"))), element_ids=[ABS1])
    assert [r["id"] for r in result.rules] == ["demo-inside"]
    assert len(result.rejected) == 1


def test_a_cross_reference_to_an_unknown_element_becomes_unresolved():
    refs = [{"citation": "§ 2 Abs. 1", "elementId": "doc/teil-1/par-2/abs-1", "resolution": "resolved"},
            {"citation": "§ 77", "elementId": "doc/teil-9/par-77", "resolution": "resolved"}]
    rule = extract_rules(LEGAL, client=FakeClient(answer(model_rule(references=refs)))).rules[0]
    assert rule["references"][0] == refs[0]  # a real element of the document stays
    assert rule["references"][1] == {"citation": "§ 77", "resolution": "unresolved"}


def test_duplicate_rule_ids_are_made_unique():
    def variant(n):
        rule = model_rule()
        rule["requirements"] = [{"kind": "numeric", "fact": "distance_to_boundary", "operator": ">=", "value": n, "unit": "m"}]
        return rule
    result = extract_rules(LEGAL, client=FakeClient(answer(variant(3), variant(4), variant(5))))
    assert [r["id"] for r in result.rules] == ["demo-par-1-abs-1", "demo-par-1-abs-1-2", "demo-par-1-abs-1-3"]


def test_identical_records_are_kept_once_and_the_copies_reported():
    result = extract_rules(LEGAL, client=FakeClient(answer(model_rule(), model_rule(id="copy"))))
    assert [r["id"] for r in result.rules] == ["demo-par-1-abs-1"]
    assert [{k: r[k] for k in ("index", "id", "reasons")} for r in result.rejected] == [
        {"index": 1, "id": "demo-copy", "reasons": ["duplicate of rule 'demo-par-1-abs-1'"]}]
    assert result.rejected[0]["candidate"] == model_rule(id="copy")  # kept as proposed, for review


def test_only_valid_rule_records_are_accepted():
    bad_operator = model_rule(requirements=[{"kind": "numeric", "fact": "d", "operator": "approximately", "value": 3, "unit": "m"}])
    no_source = model_rule()
    del no_source["source"]
    result = extract_rules(LEGAL, client=FakeClient(answer(bad_operator, no_source, "text", model_rule(id="ok"))))
    assert [r["id"] for r in result.rules] == ["demo-ok"]
    assert [r["index"] for r in result.rejected] == [0, 1, 2]
    assert "operator" in result.rejected[0]["reasons"][0]
    assert result.rejected[2]["reasons"] == ["the record is not a JSON object"]


def test_rejected_records_are_reported_in_the_generation_block():
    result = extract_rules(LEGAL, client=FakeClient(answer(model_rule(source={"elements": [{"elementId": "nope"}]}), model_rule(id="ok"))))
    data = result.to_json_dict()
    assert [r["id"] for r in data["rules"]] == ["demo-ok"]
    generation = data["_generation"]
    assert generation["rulesProposed"] == 2 and len(generation["rulesRejected"]) == 1
    assert (generation["provider"], generation["modelId"], generation["region"]) == ("aws-bedrock", MODEL, "eu-central-1")
    assert generation["documentId"] == "demo" and generation["scope"] == "document"
    assert (generation["inputTokens"], generation["outputTokens"], generation["stopReason"]) == (1200, 300, "end_turn")


# ── model answers ─────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text", [
    '{"rules": [1]}',
    '```json\n{"rules": [1]}\n```',
    'Here are the rules:\n{"rules": [1]}\nDone.',
    "[1]",
])
def test_the_rules_list_is_found_in_common_answer_shapes(text):
    assert parse_rules(text) == [1]


@pytest.mark.parametrize("text", ["", "no json here", '{"rules": "none"}', '{"other": []}', '{"rules": [1]', '"text"', "42"])
def test_an_answer_that_is_not_the_expected_json_is_a_malformed_output_error(text):
    with pytest.raises(MalformedOutputError):
        parse_rules(text)


def test_an_empty_rules_list_is_a_valid_result():
    result = extract_rules(LEGAL, client=FakeClient(answer()))
    assert result.rules == [] and result.rejected == []


def test_a_malformed_answer_raises_and_uses_nothing():
    client = FakeClient(BedrockResponse("I could not do this.", "end_turn", 10, 5, 100, MODEL))
    with pytest.raises(MalformedOutputError):
        extract_rules(LEGAL, client=client)


def test_an_answer_cut_off_at_the_token_limit_is_never_used():
    client = FakeClient(answer(model_rule(), stop="max_tokens"), max_tokens=500)
    with pytest.raises(OutputTruncatedError, match="500"):
        extract_rules(LEGAL, client=client)


def test_bedrock_errors_pass_through_unchanged():
    with pytest.raises(BedrockThrottledError):
        extract_rules(LEGAL, client=FakeClient(BedrockThrottledError("slow down", code="ThrottlingException")))


def test_the_request_sent_is_the_prepared_one():
    client = FakeClient(answer())
    extract_rules(LEGAL, client=client, element_ids=[ABS1])
    system, user = client.calls[0]
    assert system == build_system_prompt(LEGAL)
    assert "Anderer Text." not in user and "Gebäude müssen" in user


# ── rules.json ────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_rules_json_is_the_collection_the_viewer_reads(tmp_path):
    result = extract_rules(LEGAL, client=FakeClient(answer(model_rule())))
    path = write_rules_json(result, tmp_path / RULE_JSON)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert [r["id"] for r in data["rules"]] == ["demo-par-1-abs-1"]  # `{ "rules": [...] }`, accepted by frontend ruleEntries()
    assert data["rules"][0]["schemaVersion"] == "2.0" and data["rules"][0]["source"]["elements"]
    assert data["_generation"]["provider"] == "aws-bedrock"
    assert sorted(p.name for p in tmp_path.iterdir()) == [RULE_JSON]  # no temporary file left behind


def test_writing_rules_json_replaces_the_old_file_atomically(tmp_path):
    target = tmp_path / RULE_JSON
    target.write_text("old", encoding="utf-8")
    write_rules_json(extract_rules(LEGAL, client=FakeClient(answer())), target)
    assert json.loads(target.read_text(encoding="utf-8"))["rules"] == []


# ── command line ──────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def legal_file(tmp_path):
    path = tmp_path / "document.json"
    path.write_text(json.dumps(LEGAL, ensure_ascii=False), encoding="utf-8")
    return path


def test_the_dry_run_reports_the_size_and_calls_nothing(legal_file, capsys, monkeypatch):
    monkeypatch.setattr("odos.llm.bedrock.BedrockClient", lambda *a, **k: pytest.fail("a dry run must not create a client"))
    assert cli.main(["extract-rules", str(legal_file), "--dry-run", "--element-id", ABS1]) == 0
    out = capsys.readouterr().out
    assert "scope:      " + ABS1 in out and "nothing was sent" in out and MODEL in out
    assert not (legal_file.parent / RULE_JSON).exists()


def test_the_command_writes_rules_json_next_to_the_input(legal_file, capsys, monkeypatch):
    monkeypatch.setattr("odos.llm.bedrock.BedrockClient", lambda: FakeClient(answer(model_rule(), model_rule(source={"elements": [{"elementId": "x"}]}))))
    assert cli.main(["extract-rules", str(legal_file)]) == 0
    out = capsys.readouterr()
    assert "1 accepted (0 flagged for review, 0 repaired), 1 rejected" in out.out and "rejected:" in out.err
    assert "coverage:" in out.out
    assert [r["id"] for r in json.loads((legal_file.parent / RULE_JSON).read_text(encoding="utf-8"))["rules"]] == ["demo-par-1-abs-1"]


def test_the_command_reports_a_bedrock_error_and_writes_nothing(legal_file, capsys, monkeypatch):
    monkeypatch.setattr("odos.llm.bedrock.BedrockClient", lambda: FakeClient(BedrockThrottledError("Bedrock ThrottlingException: slow down")))
    assert cli.main(["extract-rules", str(legal_file)]) == 2
    assert "ThrottlingException" in capsys.readouterr().err
    assert not (legal_file.parent / RULE_JSON).exists()


def test_the_command_refuses_a_missing_file(tmp_path, capsys):
    assert cli.main(["extract-rules", str(tmp_path / "missing.json")]) == 1
    assert "file not found" in capsys.readouterr().err


def test_the_connectivity_check_names_the_missing_api_key(capsys, monkeypatch):
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    assert cli.main(["bedrock-check"]) == 2
    assert "AWS_BEARER_TOKEN_BEDROCK" in capsys.readouterr().err


# ── real parser output ────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_real_processed_document_round_trips_with_mocked_bedrock():
    """Uses a processed MBO document from the local job storage when there is one (storage/ is not part of the repository)."""
    storage = Path(__file__).parents[1] / "storage"
    for path in sorted(glob.glob(str(storage / "**/document.json"), recursive=True)):
        legal = json.loads(Path(path).read_text(encoding="utf-8"))
        if legal.get("id") == "mbo":
            break
    else:
        pytest.skip("no processed MBO document.json in backend/storage")
    target = "doc/teil-2/par-6/abs-5"
    node = next(n for n in _walk(legal["structure"]) if n["id"] == target)
    rule = model_rule(source={"elements": [{"elementId": target, "role": "primary"}]})
    result = extract_rules(legal, client=FakeClient(answer(rule)), element_ids=[target])
    assert result.rejected == []
    assert result.rules[0]["source"]["documentId"] == "mbo"
    assert result.rules[0]["source"]["elements"][0]["pdfPages"] == node["pages"]


def _walk(nodes):
    for n in nodes:
        yield n
        yield from _walk(n.get("children", []))


def test_model_payload_excludes_excel_articles_and_their_scope_cannot_be_requested():
    legal = {"id": "verordnung-2023-1230", "documentType": "eu_regulation", "title": "Machinery", "structure": [
        {"id": "art-10", "type": "article", "number": "10", "text": "Keep technical duty."},
        {"id": "art-50", "type": "article", "number": "50", "text": "Excluded penalties."},
    ]}
    request = prepare_request(legal, BedrockConfig())
    assert [n["id"] for n in request.document["structure"]] == ["art-10"]
    assert "Excluded penalties" not in request.user
    assert len(legal["structure"]) == 2
    with pytest.raises(InvalidScopeError):
        prepare_request(legal, BedrockConfig(), ["art-50"])
