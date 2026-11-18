"""Reliable handling of the model's answer: conservative parsing, at most one correction request, private diagnostics,
and document-scoped rule IDs. Model answers are canned; no test calls Bedrock."""

import json
import logging
import stat

import pytest

from odos.llm.bedrock import BedrockConfig, BedrockConfigError, BedrockResponse
from odos.llm.model_output import OutputParseError, parse_model_output, redact, save_diagnostic
from odos.llm.rule_extraction import (
    CORRECTION_PROMPT,
    MalformedOutputError,
    OutputTruncatedError,
    extract_rules,
    scoped_rule_id,
)

SECRET_WORD = "Abstandsflächengeheimnis"  # stands for document text: must never reach a message or the log

LEGAL = {
    "schemaVersion": "2.0", "id": "demo", "title": "Demo", "documentType": "de_legislation", "language": "de",
    "structure": [{"id": "doc/par-1", "type": "section", "pages": [3], "children": [
        {"id": "doc/par-1/abs-1", "type": "subsection", "pages": [3], "text": "Gebäude müssen 3 m Abstand halten."}]}],
    "sentences": [{"id": "doc/par-1/abs-1/satz-1", "ranges": [{"elementId": "doc/par-1/abs-1", "start": 0, "end": 34}]}],
}


def record(rule_id="par-1-abs-1", element="doc/par-1/abs-1", **extra):
    return {"schemaVersion": "2.0", "id": rule_id,
            "source": {"citation": "§ 1 Abs. 1", "elements": [{"elementId": element, "sentenceId": "doc/par-1/abs-1/satz-1"}]},
            "classification": {"type": "obligation", "summary": f"Gebäude halten 3 m Abstand. {SECRET_WORD}"},
            "requirements": [{"kind": "numeric", "fact": "distance_to_boundary", "operator": ">=", "value": 3, "unit": "m"}],
            "review": {"status": "approved"}, **extra}


VALID = json.dumps({"rules": [record()]}, ensure_ascii=False)
# a defect in the second record (an unescaped quote), after one complete record
BROKEN = '{"rules": [' + json.dumps(record(), ensure_ascii=False) + ', {"id": "x", "classification": {"summary": "a "quoted" ' + SECRET_WORD + '"}}]}'


def response(text, stop="end_turn"):
    return BedrockResponse(text, stop, 1000, 500, 10, "eu.anthropic.claude-sonnet-4-6")


class FakeClient:
    """Answers in order; records every request."""

    def __init__(self, *answers, retries=1):
        self.config = BedrockConfig(output_retries=retries)
        self.answers, self.calls = list(answers), []

    def converse(self, system, user, **kwargs):
        self.calls.append({"user": user, **kwargs})
        return self.answers.pop(0)


# ── parsing ───────────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text, mode", [
    (VALID, "exact"),
    ("```json\n" + VALID + "\n```", "exact"),
    ("Hier sind die Regeln:\n" + VALID + "\nIch hoffe, das hilft {sehr}.", "embedded"),
    (json.dumps([record()]), "exact"),  # a bare list is tolerated
])
def test_valid_json_is_used_as_is_and_surrounding_text_is_ignored(text, mode):
    parsed = parse_model_output(text)
    assert parsed.mode == mode and parsed.rules[0]["id"] == "par-1-abs-1"


def test_a_defect_is_located_without_quoting_the_answer_and_complete_records_are_offered():
    with pytest.raises(OutputParseError) as caught:
        parse_model_output(BROKEN)
    e = caught.value
    assert e.line == 1 and e.column > 0 and "delimiter" in e.reason
    assert SECRET_WORD not in str(e)
    assert [r["id"] for r in e.salvaged] == ["par-1-abs-1"]  # only the complete record before the defect


@pytest.mark.parametrize("text", ['{"result": []}', "keine Regeln", '{"rules": {"a": 1}}', ""])
def test_json_without_a_rules_list_is_not_usable(text):
    with pytest.raises(OutputParseError):
        parse_model_output(text)


# ── at most one correction request ────────────────────────────────────────────────────────────────────────────────────


def test_a_malformed_answer_is_kept_and_corrected_with_exactly_one_more_request(tmp_path):
    client = FakeClient(response(BROKEN), response(VALID))
    result = extract_rules(LEGAL, client=client, diagnostics_dir=tmp_path)
    assert [r["id"] for r in result.rules] == ["demo-par-1-abs-1"]
    assert len(client.calls) == 2
    second = client.calls[1]
    assert second["history"][0][0] == "user" and second["history"][1] == ("assistant", BROKEN)
    assert second["user"].startswith(CORRECTION_PROMPT.split("(")[0]) and SECRET_WORD not in second["user"]
    out = result.generation["modelOutput"]
    assert (out["requests"], out["parse"], out["partial"], len(out["diagnostics"])) == (2, "exact", False, 1)
    assert (result.generation["inputTokens"], result.generation["outputTokens"]) == (2000, 1000)  # both requests counted


def test_a_second_malformed_answer_fails_without_a_third_request(tmp_path):
    client = FakeClient(response(BROKEN), response(BROKEN), response(VALID))
    with pytest.raises(MalformedOutputError) as caught:
        extract_rules(LEGAL, client=client, diagnostics_dir=tmp_path)
    assert len(client.calls) == 2 and len(caught.value.diagnostic_ids) == 2
    assert SECRET_WORD not in str(caught.value)


def test_retries_can_be_switched_off(tmp_path):
    client = FakeClient(response(BROKEN), response(VALID), retries=0)
    with pytest.raises(MalformedOutputError):
        extract_rules(LEGAL, client=client, diagnostics_dir=tmp_path)
    assert len(client.calls) == 1


@pytest.mark.parametrize("value, expected", [(None, 1), ("0", 0), ("1", 1)])
def test_the_retry_setting_defaults_to_one_and_cannot_exceed_one(value, expected):
    env = {} if value is None else {"ODOS_BEDROCK_OUTPUT_RETRIES": value}
    assert BedrockConfig.from_env(env).output_retries == expected


@pytest.mark.parametrize("value", ["2", "10", "-1", "x"])
def test_more_than_one_retry_or_a_bad_value_is_refused(value):
    with pytest.raises(BedrockConfigError):
        BedrockConfig.from_env({"ODOS_BEDROCK_OUTPUT_RETRIES": value})


def test_a_truncated_answer_is_kept_but_not_retried(tmp_path):
    client = FakeClient(response(VALID[:40], stop="max_tokens"), response(VALID))
    with pytest.raises(OutputTruncatedError):
        extract_rules(LEGAL, client=client, diagnostics_dir=tmp_path)
    assert len(client.calls) == 1 and len(list(tmp_path.glob("*.json"))) == 1


def test_bedrocks_malformed_output_stop_reason_counts_as_malformed(tmp_path):
    client = FakeClient(response(VALID, stop="malformed_model_output"), response(VALID))
    assert len(extract_rules(LEGAL, client=client, diagnostics_dir=tmp_path).rules) == 1
    assert len(client.calls) == 2


def test_partial_records_are_used_only_on_request_and_still_validated(tmp_path):
    invented = record("invented", element="doc/par-99")  # complete JSON, but its source is not in the document
    broken = '{"rules": [' + json.dumps(record()) + ", " + json.dumps(invented) + ', {"id": "x" "y"}]}'
    with pytest.raises(MalformedOutputError):
        extract_rules(LEGAL, client=FakeClient(response(broken), retries=0), diagnostics_dir=tmp_path)
    result = extract_rules(LEGAL, client=FakeClient(response(broken), retries=0), diagnostics_dir=tmp_path, accept_partial=True)
    assert [r["id"] for r in result.rules] == ["demo-par-1-abs-1"]
    assert [r["id"] for r in result.rejected] == ["invented"]  # recovered JSON is never accepted unchecked
    assert result.generation["modelOutput"]["partial"] is True and result.generation["modelOutput"]["parse"] == "partial"
    assert all(r["review"]["status"] == "draft" for r in result.rules)


# ── diagnostics ───────────────────────────────────────────────────────────────────────────────────────────────────────


def test_diagnostics_are_private_files_and_the_log_names_only_their_id(tmp_path, caplog):
    folder = tmp_path / "diag"
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(MalformedOutputError):
            extract_rules(LEGAL, client=FakeClient(response(BROKEN), response(BROKEN)), diagnostics_dir=folder)
    files = sorted(folder.glob("*.json"))
    assert len(files) == 2
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700 and all(stat.S_IMODE(f.stat().st_mode) == 0o600 for f in files)
    kept = json.loads(files[0].read_text(encoding="utf-8"))
    assert kept["response"] == BROKEN and kept["attempt"] in (1, 2) and kept["documentId"] == "demo"
    assert {"error", "responseSha256", "responseChars", "modelId", "stopReason"} <= set(kept)
    assert SECRET_WORD not in caplog.text and kept["diagnosticId"] in caplog.text


def test_diagnostics_never_contain_keys_and_are_pruned(tmp_path):
    # Assembled at runtime so no complete credential-shaped literal appears in this source file.
    _bearer = "Bearer " + "abcdefghijklmnopqrstuvwx"           # matches bearer-token branch of _SECRETS
    _absk = "ABSK" + "QmVkcm9ja0FQSUtleS1leGFtcGxlMTIzNDU2"   # Bedrock key format; value decodes to "BedrockAPIKey-example123456"
    _akia = "AKIA" + "ABCDEFGHIJKLMNOP"                        # AWS access-key-ID format; clearly synthetic
    text = " ".join([_bearer, _absk, _akia, "my-own-secret-value"])
    assert redact(text, ("my-own-secret-value",)) == "*** *** *** ***"
    for n in range(4):
        save_diagnostic(tmp_path, text=text, error="e", metadata={"n": n}, secrets=("my-own-secret-value",), keep=2)
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 2
    assert all("ABSK" not in f.read_text() and "my-own-secret-value" not in f.read_text() for f in files)


# ── document-scoped rule IDs ──────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("document, proposed, expected", [
    ("mbo", "par-6-abs-5", "mbo-par-6-abs-5"),
    ("mbo", "mbo-par-6-abs-5", "mbo-par-6-abs-5"),  # already scoped: unchanged
    ("verordnung-2023-1230", "art-10-para-3-s1", "verordnung-2023-1230-art-10-para-3-s1"),
    ("verordnung-2023-1230", "Art 10 (3) Satz 1", "verordnung-2023-1230-art-10-3-satz-1"),
    ("mbo", None, "mbo-rule"), ("mbo", ["x"], "mbo-rule"), ("", "x", "document-x"),
    ("mbo", "mboverlap", "mbo-mboverlap"),  # a prefix of the word is not the document prefix
])
def test_rule_ids_are_prefixed_with_the_document_id(document, proposed, expected):
    assert scoped_rule_id(document, proposed) == expected


def test_the_same_local_ids_from_two_documents_do_not_collide_and_keep_their_document():
    other = {**LEGAL, "id": "other-law", "title": "Other"}
    a = extract_rules(LEGAL, client=FakeClient(response(VALID))).rules
    b = extract_rules(other, client=FakeClient(response(VALID))).rules
    assert a[0]["id"] == "demo-par-1-abs-1" and b[0]["id"] == "other-law-par-1-abs-1"
    assert (a[0]["source"]["documentId"], b[0]["source"]["documentId"]) == ("demo", "other-law")
    assert a[0]["source"]["elements"] == b[0]["source"]["elements"]  # provenance unchanged
    assert a[0]["review"]["status"] == "draft"  # the model's "approved" is never kept
