"""Prompt version 4 (exclusive requirement forms, every exception sentence cited by its record) and the separate,
unverified coverage category `coveredByExceptionText`. Model answers are canned; no test calls Bedrock."""

import copy
import json

from odos.llm.bedrock import BedrockConfig, BedrockResponse
from odos.llm.profiles import GENERAL_INSTRUCTIONS, PROMPT_VERSION, instructions_for
from odos.llm.rule_extraction import EXAMPLE_RULE, build_system_prompt, extract_rules, rule_validator
from odos.llm.source_checks import SourceText, coverage

MAIN = "Die Tiefe der Abstandsflächen beträgt 0,4 H, mindestens 3 m."
ALTERNATIVE = "In Gewerbe- und Industriegebieten genügt eine Tiefe von 0,2 H, mindestens 3 m."
SHORT = "Es gilt nicht."
TEXT = f"{MAIN} {ALTERNATIVE} {SHORT}"

LEGAL = {
    "schemaVersion": "2.0", "id": "demo", "title": "Demo", "documentType": "de_legislation", "language": "de",
    "structure": [{"id": "doc/par-5", "type": "section", "pages": [3], "children": [
        {"id": "doc/par-5/abs-1", "type": "subsection", "pages": [3], "text": TEXT}]}],
    "sentences": [
        {"id": "doc/par-5/abs-1/satz-1", "ranges": [{"elementId": "doc/par-5/abs-1", "start": 0, "end": len(MAIN)}]},
        {"id": "doc/par-5/abs-1/satz-2", "ranges": [{"elementId": "doc/par-5/abs-1", "start": len(MAIN) + 1,
                                                       "end": len(MAIN) + 1 + len(ALTERNATIVE)}]},
        {"id": "doc/par-5/abs-1/satz-3", "ranges": [{"elementId": "doc/par-5/abs-1", "start": len(TEXT) - len(SHORT), "end": len(TEXT)}]},
    ],
}


def formula(factor):
    return {"kind": "formula", "fact": "setback_area_depth", "operator": "==", "unit": "m", "expression": {
        "kind": "operation", "operator": "max", "operands": [
            {"kind": "operation", "operator": "multiply", "operands": [{"kind": "literal", "value": factor},
                                                                       {"kind": "fact", "name": "measure_h", "unit": "m"}]},
            {"kind": "literal", "value": 3, "unit": "m"}]}}


def rule(*sentences, exception_text=ALTERNATIVE, **extra):
    return {"schemaVersion": "2.0", "id": "par-5-abs-1",
            "source": {"citation": "§ 5 Abs. 1", "elements": [{"elementId": "doc/par-5/abs-1", "sentenceId": f"doc/par-5/abs-1/satz-{n}",
                                                                 "role": "primary"} for n in sentences]},
            "classification": {"type": "obligation", "summary": "Tiefe 0,4 H, mindestens 3 m."},
            "requirements": [formula(0.4)],
            "exceptions": [{"kind": "alternative", "description": exception_text,
                            "condition": {"kind": "comparison", "fact": "zone_type", "operator": "==", "value": "commercial", "valueType": "string"},
                            "requirements": [formula(0.2)]}],
            "review": {"status": "draft"}, **extra}


class FakeClient:
    def __init__(self, *rules):
        self.config = BedrockConfig()
        self.answer = BedrockResponse(json.dumps({"rules": list(rules)}), "end_turn", 100, 100, 10, "m")

    def converse(self, system, user, **kwargs):
        return self.answer


# ── prompt version 4 ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_prompt_version_is_4_and_is_recorded():
    assert PROMPT_VERSION == "4"
    assert extract_rules(LEGAL, client=FakeClient(rule(1, 2))).generation["promptVersion"] == "4"


def test_the_instructions_state_that_the_requirement_forms_are_exclusive_and_when_to_use_each():
    text, _ = instructions_for(LEGAL)
    for phrase in ("`requirements` and `requirementExpression` are mutually exclusive", "never both",
                   "Use `requirements`, a list in which every item must hold", "Use `requirementExpression` only when",
                   "never an `any` of their requirements", "each further case as an entry of `exceptions` with its own `condition`"):
        assert phrase in text
    assert "requirementExpression" in build_system_prompt(LEGAL)


def test_the_instructions_require_every_exception_sentence_to_be_cited_by_its_record():
    for phrase in ("has no source of its own", "cited ONLY in the `source.elements` of the record it belongs to",
                   "EVERY sentence that contributes", "is reported as not covered"):
        assert phrase in GENERAL_INSTRUCTIONS
    for law_specific in ("MBO", "BauGB", "§", "Abstandsfläche"):
        assert law_specific not in GENERAL_INSTRUCTIONS  # still document-neutral


def test_the_example_is_valid_cites_every_sentence_and_uses_one_requirement_form():
    assert list(rule_validator().iter_errors(EXAMPLE_RULE)) == []
    cited = {e["sentenceId"] for e in EXAMPLE_RULE["source"]["elements"]}
    assert len(cited) == 1 + len(EXAMPLE_RULE["exceptions"])  # the main requirement and each exception, one sentence each
    assert ("requirements" in EXAMPLE_RULE) != ("requirementExpression" in EXAMPLE_RULE)
    assert {e["kind"] for e in EXAMPLE_RULE["exceptions"]} == {"alternative", "exception"}


def test_a_record_with_both_requirement_forms_is_still_rejected_and_not_repaired():
    both = rule(1, 2, requirementExpression={"kind": "requirement", "requirement": formula(0.4)})
    result = extract_rules(LEGAL, client=FakeClient(both))
    assert result.rules == [] and len(result.rejected) == 1
    assert "'requirementExpression' is not allowed here" in result.rejected[0]["reasons"][0]
    assert set(result.rejected[0]["candidate"]) >= {"requirements", "requirementExpression"}  # nothing was removed


# ── coverage: coveredByExceptionText ──────────────────────────────────────────────────────────────────────────────────


def test_a_sentence_quoted_by_an_exception_is_reported_separately_and_not_as_cited():
    report = coverage([rule(1)], SourceText.of(LEGAL))
    assert [m["id"] for m in report["coveredByExceptionText"]] == ["doc/par-5/abs-1/satz-2"]
    match = report["coveredByExceptionText"][0]
    assert match["verified"] is False and match["matchedBy"] == [{"ruleId": "par-5-abs-1", "exception": 0}]
    # the existing metrics are unchanged: the sentence is still uncited and is not counted as cited
    assert (report["sentences"], report["sentencesCited"]) == (3, 1)
    assert [u["id"] for u in report["uncitedSentences"]] == ["doc/par-5/abs-1/satz-2", "doc/par-5/abs-1/satz-3"]


def test_an_explicitly_cited_sentence_is_not_in_the_text_matched_category():
    report = coverage([rule(1, 2)], SourceText.of(LEGAL))
    assert report["coveredByExceptionText"] == [] and report["sentencesCited"] == 2


def test_matching_ignores_numbers_case_and_punctuation_but_not_different_content():
    source = SourceText.of(LEGAL)
    reworded = rule(1, exception_text="2 in gewerbe- und industriegebieten GENÜGT eine Tiefe von 0,2 H; mindestens 3 m")
    assert [m["id"] for m in coverage([reworded], source)["coveredByExceptionText"]] == ["doc/par-5/abs-1/satz-2"]
    other = rule(1, exception_text="In Kerngebieten genügt eine Tiefe von 0,25 H, mindestens 4 m bei Hochhäusern.")
    assert coverage([other], source)["coveredByExceptionText"] == []


def test_a_description_that_contains_the_sentence_among_others_matches_but_a_short_sentence_never_does():
    source = SourceText.of(LEGAL)
    both = rule(1, exception_text=f"{ALTERNATIVE} Es gilt nicht.")
    ids = [m["id"] for m in coverage([both], source)["coveredByExceptionText"]]
    assert ids == ["doc/par-5/abs-1/satz-2"]  # "Es gilt nicht." is too short to prove a quote


def test_the_new_category_adds_a_key_and_changes_no_existing_one():
    source = SourceText.of(LEGAL)
    report = coverage([rule(1)], source)
    assert set(report) == {"sentences", "sentencesCited", "uncitedSentences", "elements", "elementsCited", "uncitedElements",
                           "citedOnlyByRejected", "coveredByExceptionText"}
    assert coverage([], source)["coveredByExceptionText"] == []


def test_extraction_neither_completes_the_sources_nor_changes_the_rule():
    proposed = rule(1)
    result = extract_rules(LEGAL, client=FakeClient(copy.deepcopy(proposed)))
    (accepted,) = result.rules
    assert [e["sentenceId"] for e in accepted["source"]["elements"]] == ["doc/par-5/abs-1/satz-1"]  # satz-2 was NOT added
    assert accepted["exceptions"] == proposed["exceptions"]
    cov = result.generation["coverage"]
    assert [m["id"] for m in cov["coveredByExceptionText"]] == ["doc/par-5/abs-1/satz-2"]
    assert "doc/par-5/abs-1/satz-2" in [u["id"] for u in cov["uncitedSentences"]]
