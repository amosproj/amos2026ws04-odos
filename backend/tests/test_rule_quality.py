"""Extraction quality: layered instructions (general / language / document type) and the deterministic rule checks.

Regression baselines (read only, never rewritten by these tests):
* dev-fixtures/rule-json-examples/{mbo,eu-machinery}.rules.json: hand-modeled examples. They must stay acceptable.
* dev-fixtures/bedrock-extraction-results/mbo-paragraph-6.rules.json: the first real extraction (prompt version 1). The
  checks must detect the problems found in it.
Model answers are canned; no test calls Bedrock.
"""

import copy
import glob
import hashlib
import json
import re
from pathlib import Path

import pytest

from odos.llm.bedrock import BedrockConfig, BedrockResponse
from odos.llm.profiles import (
    EU_DIRECTIVE,
    EU_LEGISLATION,
    GENERAL_INSTRUCTIONS,
    GENERIC,
    GERMAN_LEGISLATION,
    LANGUAGE_GLOSSARIES,
    instructions_for,
    profile_for,
)
from odos.llm.rule_checks import FLAG_PREFIX, check_rule, check_rule_set, normalize_fact
from odos.llm.rule_extraction import build_system_prompt, extract_rules, rule_validator

ROOT = Path(__file__).parents[2]
MANUAL_MBO = ROOT / "dev-fixtures/rule-json-examples/mbo.rules.json"
MANUAL_EU = ROOT / "dev-fixtures/rule-json-examples/eu-machinery.rules.json"
BASELINE_MBO_6 = ROOT / "dev-fixtures/bedrock-extraction-results/mbo-paragraph-6.rules.json"
BASELINE_MBO_6_SHA256 = "1db8718601931dcfbd1dbef32042fc30e70dd7e03d30cd15085f195fccb9839e"
UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def rules_of(path: Path) -> list[dict]:
    return copy.deepcopy(json.loads(path.read_text(encoding="utf-8"))["rules"])


def doc(document_type=None, legal_system=None, language="de") -> dict:
    d = {"id": "x", "language": language, "structure": []}
    if document_type:
        d["documentType"] = document_type
    if legal_system:
        d["legalSystem"] = legal_system
    return d


# ── instructions: general / language / document type ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("document_type, legal_system, expected", [
    ("de_legislation", "de", GERMAN_LEGISLATION),
    ("eu_regulation", "eu", EU_LEGISLATION),
    ("eu_decision", "eu", EU_LEGISLATION),
    ("eu_legislation", "eu", EU_LEGISLATION),
    ("eu_directive", "eu", EU_DIRECTIVE),
    (None, "de", GERMAN_LEGISLATION),  # older documents without documentType fall back to the legal system
    (None, "eu", EU_LEGISLATION),
    ("technical_standard", None, GENERIC),  # no DIN/EN/ISO profile yet
    (None, None, GENERIC),
])
def test_the_profile_follows_the_document_type_then_the_legal_system(document_type, legal_system, expected):
    assert profile_for(doc(document_type, legal_system)) is expected


def test_the_general_instructions_name_no_particular_law_or_legal_system():
    for law_specific in ("MBO", "Musterbauordnung", "BauGB", "§", "Abstandsfl", "2023/1230", "Absatz", "Artikel"):
        assert law_specific not in GENERAL_INSTRUCTIONS


@pytest.mark.parametrize("legal", [doc("de_legislation", "de"), doc("eu_regulation", "eu"), doc("eu_directive", "eu"),
                                   doc("technical_standard", None, "en"), doc(None, None, "fr")])
def test_every_prompt_has_the_general_instructions(legal):
    text, _ = instructions_for(legal)
    assert text.startswith(GENERAL_INSTRUCTIONS)
    assert "English, ASCII, lower-case snake_case" in text and "== max(" in text


def test_a_german_law_gets_the_german_glossary_and_profile_but_no_eu_text():
    text, profile = instructions_for(doc("de_legislation", "de"))
    assert profile is GERMAN_LEGISLATION
    assert LANGUAGE_GLOSSARIES["de"] in text and "§ 6 Abs. 5 Satz 1" in text
    assert "Artikel" not in text and "Member States" not in text


def test_an_eu_regulation_in_german_gets_the_german_glossary_and_the_eu_profile():
    text, profile = instructions_for(doc("eu_regulation", "eu", "de"))
    assert profile is EU_LEGISLATION
    assert LANGUAGE_GLOSSARIES["de"] in text and "Artikel 10 Absatz 3 Unterabsatz 2" in text
    assert "Erwägungsgründe" in text and "§ 6 Abs." not in text
    assert "transposition" not in text  # directive-only


def test_an_eu_act_in_english_gets_the_english_glossary():
    text, _ = instructions_for(doc("eu_regulation", "eu", "en"))
    assert LANGUAGE_GLOSSARIES["en"] in text and LANGUAGE_GLOSSARIES["de"] not in text


def test_a_directive_adds_member_state_duties_to_the_eu_profile():
    text, profile = instructions_for(doc("eu_directive", "eu"))
    assert profile is EU_DIRECTIVE
    assert "EU directive" in text and "Member State is the `duty_holder`" in text and "transposition" in text
    assert "Artikel 10 Absatz 3 Unterabsatz 2" in text  # shares the EU structure and citation style


def test_an_unknown_language_gets_no_glossary_and_a_technical_standard_the_generic_profile():
    text, profile = instructions_for(doc("technical_standard", None, "fr"))
    assert profile is GENERIC
    assert all(glossary not in text for glossary in LANGUAGE_GLOSSARIES.values())


def test_the_system_prompt_carries_the_profile_of_the_document():
    assert "German legislation" in build_system_prompt(doc("de_legislation", "de"))
    assert "EU legal act" in build_system_prompt(doc("eu_regulation", "eu"))


@pytest.mark.parametrize("document_id, expected", [("mbo", GERMAN_LEGISLATION), ("verordnung-2023-1230", EU_LEGISLATION)])
def test_real_parser_output_selects_the_right_profile(document_id, expected):
    for path in sorted(glob.glob(str(ROOT / "backend/storage/**/document.json"), recursive=True)):
        legal = json.loads(Path(path).read_text(encoding="utf-8"))
        if legal.get("id") == document_id:
            assert profile_for(legal) is expected
            return
    pytest.skip(f"no processed {document_id} document.json in backend/storage")


# ── fact identifiers ──────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name, expected", [
    ("setback_depth", "setback_depth"),
    ("building.height", "building.height"),
    ("H", "h"),
    ("measureH", "measure_h"),
    ("controlSystem.withstandsIntendedExternalInfluences", "control_system.withstands_intended_external_influences"),
    ("sourceCodeNeededToVerifyAnnexIIIRequirements", "source_code_needed_to_verify_annex_iii_requirements"),
    ("Wall-Height", "wall_height"),
    ("roof pitch", "roof_pitch"),
])
def test_ascii_identifiers_are_normalized_to_snake_case(name, expected):
    assert normalize_fact(name) == expected


def fact_rule(*facts):
    return {"requirements": [{"kind": "numeric", "fact": f, "operator": ">=", "value": 1, "unit": "m"} for f in facts]}


@pytest.mark.parametrize("bad", ["abstandsfläche_tiefe", "größe", "höhe", "a+b", "1st_floor", "x..y", ""])
def test_identifiers_that_cannot_be_made_english_ascii_reject_the_record(bad):
    check = check_rule(fact_rule(bad))
    assert check.errors and repr(bad) in check.errors[0]


def test_normalization_renames_every_occurrence_of_a_fact_consistently():
    rule = {"requirements": [{"kind": "formula", "fact": "setbackDepth", "operator": "==", "unit": "m",
                              "expression": {"kind": "operation", "operator": "multiply", "operands": [
                                  {"kind": "literal", "value": 0.4}, {"kind": "fact", "name": "MeasureH", "unit": "m"}]}}],
            "applicability": {"conditions": {"kind": "comparison", "fact": "setbackDepth", "operator": ">", "value": 0, "valueType": "number", "unit": "m"}}}
    check = check_rule(rule)
    assert check.errors == [] and check.renamed == {"setbackDepth": "setback_depth", "MeasureH": "measure_h"}
    assert rule["requirements"][0]["fact"] == rule["applicability"]["conditions"]["fact"] == "setback_depth"
    assert rule["requirements"][0]["expression"]["operands"][1]["name"] == "measure_h"


# ── references ────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_reference_to_the_rules_own_primary_element_is_removed_others_stay():
    rule = {"source": {"elements": [{"elementId": "a", "role": "primary"}, {"elementId": "b", "role": "cross_reference"}]},
            "references": [{"citation": "Satz 2", "elementId": "a", "resolution": "resolved"},
                           {"citation": "§ 2", "elementId": "b", "resolution": "resolved"},
                           {"citation": "§ 9 BauGB", "resolution": "unresolved"}],
            "exceptions": [{"kind": "alternative", "description": "x", "references": [{"citation": "Satz 3", "elementId": "a", "resolution": "resolved"}]}]}
    check = check_rule(rule)
    assert check.self_references_removed == 2
    assert [r["citation"] for r in rule["references"]] == ["§ 2", "§ 9 BauGB"]
    assert "references" not in rule["exceptions"][0]


# ── units and formulas ────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("unit, flagged", [("1", True), ("m", True), ("deg", False), ("%", False), ("rad", False)])
def test_an_angle_needs_an_angle_unit(unit, flagged):
    rule = {"applicability": {"conditions": {"kind": "comparison", "fact": "roof.pitch", "operator": "<", "value": 70, "valueType": "number", "unit": unit}}}
    assert bool(check_rule(rule).flags) is flagged


def operation(op, *operands):
    return {"kind": "operation", "operator": op, "operands": list(operands)}


def fact(name, unit=None):
    return {"kind": "fact", "name": name, **({"unit": unit} if unit else {})}


def literal(value, unit=None):
    return {"kind": "literal", "value": value, **({"unit": unit} if unit else {})}


def formula(expression, unit="m"):
    return {"requirements": [{"kind": "formula", "fact": "result_value", "operator": "==", "unit": unit, "expression": expression}]}


def test_adding_quantities_in_different_units_is_flagged():
    assert check_rule(formula(operation("add", fact("wall_height", "m"), fact("roof_height", "cm")))).flags


def test_a_formula_whose_result_unit_differs_from_its_operands_is_flagged():
    assert check_rule(formula(operation("max", fact("depth", "m"), literal(3, "m")), unit="mm")).flags


@pytest.mark.parametrize("expression", [
    operation("max", operation("multiply", literal(0.4), fact("measure_h", "m")), literal(3, "m")),
    operation("add", fact("wall_height", "m"), operation("divide", fact("roof_height", "m"), literal(3))),
    operation("multiply", fact("area", "m2"), fact("load", "kN/m2")),  # multiplication changes the unit: not checked
])
def test_consistent_formulas_are_not_flagged(expression):
    unit = "kN" if expression["operator"] == "multiply" and expression["operands"][0].get("name") == "area" else "m"
    assert check_rule(formula(expression, unit)).flags == []


def bounds(*items):
    return {"requirementExpression": {"kind": "all", "requirements": [{"kind": "requirement", "requirement": i} for i in items]}}


def test_a_determined_value_split_into_several_minimums_is_flagged():
    rule = bounds({"kind": "formula", "fact": "setback_depth", "operator": ">=", "unit": "m",
                   "expression": operation("multiply", literal(0.4), fact("measure_h", "m"))},
                  {"kind": "numeric", "fact": "setback_depth", "operator": ">=", "value": 3, "unit": "m"})
    flags = check_rule(rule).flags
    assert len(flags) == 1 and "== max(...)" in flags[0]


def test_bounds_on_different_facts_or_a_range_are_not_flagged():
    a_range = bounds({"kind": "numeric", "fact": "width", "operator": ">=", "value": 1, "unit": "m"},
                     {"kind": "numeric", "fact": "width", "operator": "<=", "value": 2, "unit": "m"})
    two_facts = bounds({"kind": "numeric", "fact": "width", "operator": ">=", "value": 1, "unit": "m"},
                       {"kind": "numeric", "fact": "height", "operator": ">=", "value": 2, "unit": "m"})
    assert check_rule(a_range).flags == [] and check_rule(two_facts).flags == []


# ── across records ────────────────────────────────────────────────────────────────────────────────────────────────────


def record(rule_id, element="e", sentence="s1", **body):
    return {"id": rule_id, "source": {"elements": [{"elementId": element, "sentenceId": sentence, "role": "primary"}]}, **body}


ZONE = {"kind": "comparison", "fact": "zone_type", "operator": "in", "value": ["commercial", "industrial"], "valueType": "string_array"}
NUMERIC = {"kind": "numeric", "fact": "depth", "operator": ">=", "value": 3, "unit": "m"}


def test_a_record_that_repeats_an_exception_of_another_record_is_flagged():
    main = record("main", exceptions=[{"kind": "alternative", "effect": "modifies_rule", "description": "x", "condition": ZONE}])
    separate = record("separate", sentence="s2", applicability={"conditions": ZONE}, requirements=[NUMERIC])
    kept, duplicates, flags = check_rule_set([main, separate])
    assert len(kept) == 2 and duplicates == []
    assert "repeats an exception of rule 'main'" in flags["separate"][0] and "main" not in flags


def test_conditions_in_another_order_are_the_same_condition():
    a = {"kind": "comparison", "fact": "a", "operator": "==", "value": 1, "valueType": "integer"}
    b = {"kind": "comparison", "fact": "b", "operator": "==", "value": 2, "valueType": "integer"}
    main = record("main", exceptions=[{"kind": "alternative", "description": "x", "condition": {"kind": "all", "conditions": [a, b]}}])
    separate = record("separate", applicability={"conditions": {"kind": "all", "conditions": [b, a]}})
    assert "separate" in check_rule_set([main, separate])[2]


def test_the_same_condition_from_another_provision_is_not_a_repetition():
    main = record("main", element="art-1", exceptions=[{"kind": "alternative", "description": "x", "condition": ZONE}])
    other = record("other", element="art-9", applicability={"conditions": ZONE})
    assert check_rule_set([main, other])[2] == {}


def test_different_operators_on_one_fact_from_the_same_sentence_are_flagged():
    exact = record("exact", requirements=[{**NUMERIC, "operator": "=="}])
    minimum = record("minimum", requirements=[NUMERIC])
    flags = check_rule_set([exact, minimum])[2]
    assert "'depth' has operator ['=='] here and ['>='] in rule 'minimum'" in flags["exact"][0]


def test_identical_records_differing_only_in_id_review_and_descriptions_are_duplicates():
    a = record("a", requirements=[{**NUMERIC, "description": "one"}], review={"status": "draft"})
    b = record("b", requirements=[{**NUMERIC, "description": "two"}], review={"status": "draft", "notes": ["x"]})
    kept, duplicates, _ = check_rule_set([a, b])
    assert [r["id"] for r in kept] == ["a"] and duplicates == [(b, "duplicate of rule 'a'")]


# ── regression baselines ──────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", [MANUAL_MBO, MANUAL_EU], ids=["mbo", "eu-machinery"])
def test_the_hand_modeled_examples_pass_every_check(path):
    rules = rules_of(path)
    renamed = {}
    for rule in rules:
        check = check_rule(rule)
        assert check.errors == [] and check.flags == [], rule["id"]
        renamed.update(check.renamed)
        assert list(rule_validator().iter_errors(rule)) == []  # still schema-valid after normalization
    kept, duplicates, flags = check_rule_set(rules)
    assert duplicates == [] and flags == {}
    if path == MANUAL_MBO:
        assert renamed == {}  # already snake_case
    else:  # camelCase in the EU example is converted, not rejected
        assert renamed["controlSystem.withstandsIntendedExternalInfluences"] == "control_system.withstands_intended_external_influences"
        assert all(re.fullmatch(r"[a-z0-9_.]+", new) for new in renamed.values())


def test_the_first_real_extraction_is_kept_unchanged_as_the_baseline():
    assert hashlib.sha256(BASELINE_MBO_6.read_bytes()).hexdigest() == BASELINE_MBO_6_SHA256


def test_the_checks_find_the_problems_of_the_first_real_extraction():
    rules = rules_of(BASELINE_MBO_6)
    checks = {r["id"]: check_rule(r) for r in rules}
    rejected = {rid for rid, c in checks.items() if c.errors}
    assert len(rejected) == 18  # German, non-ASCII fact identifiers (e.g. "abstandsfläche_tiefe")
    assert any("abstandsfläche_tiefe" in e for e in checks["mbo-par-6-abs-5-satz-1"].errors)
    assert {rid for rid, c in checks.items() if c.renamed == {"H": "h"}} >= {"mbo-par-6-abs-4-satz-3", "mbo-par-6-abs-4-satz-4"}


def test_with_ascii_facts_the_checks_find_the_semantic_problems_of_the_first_extraction():
    """The same baseline with umlauts transliterated, to reach the checks behind the identifier check."""
    rules = json.loads(json.dumps(rules_of(BASELINE_MBO_6), ensure_ascii=False).translate(UMLAUTS))
    checks = {r["id"]: check_rule(r) for r in rules}
    assert all(not c.errors for c in checks.values())
    # "beträgt 0,4 H, mindestens 3 m" was split into two minimums
    assert any("== max(...)" in f for f in checks["mbo-par-6-abs-5-satz-1"].flags)
    # the roof pitch (an angle) was given the dimensionless unit "1"
    assert not checks["mbo-par-6-abs-4-satz-3"].flags  # "dachneigung" is German, so no English angle word to detect
    # Satz 2 and 3 were emitted as records although they are exceptions of Satz 1
    _, _, flags = check_rule_set(rules)
    for rule_id in ("mbo-par-6-abs-5-satz-2", "mbo-par-6-abs-5-satz-3"):
        assert any("repeats an exception of rule 'mbo-par-6-abs-5-satz-1'" in f for f in flags[rule_id])


# ── end to end (canned model answers) ─────────────────────────────────────────────────────────────────────────────────

MBO_LIKE = {
    "schemaVersion": "2.0", "id": "demo-bo", "title": "Demo-Bauordnung", "documentType": "de_legislation", "legalSystem": "de",
    "language": "de", "structure": [{"id": "doc/par-6", "type": "section", "marker": "§ 6", "pages": [10], "children": [
        {"id": "doc/par-6/abs-5", "type": "subsection", "marker": "(5)", "pages": [10],
         "text": "Die Tiefe der Abstandsflächen beträgt 0,4 H, mindestens 3 m. In Gewerbegebieten genügt eine Tiefe von 0,2 H, mindestens 3 m."}]}],
    "sentences": [{"id": "doc/par-6/abs-5/satz-1", "ranges": [{"elementId": "doc/par-6/abs-5", "start": 0, "end": 59}]},
                  {"id": "doc/par-6/abs-5/satz-2", "ranges": [{"elementId": "doc/par-6/abs-5", "start": 60, "end": 125}]}],
}
EU_LIKE = {
    "schemaVersion": "2.0", "id": "verordnung-demo", "title": "Verordnung (EU) Demo", "documentType": "eu_regulation", "legalSystem": "eu",
    "language": "de", "structure": [{"id": "doc/art-10", "type": "article", "marker": "Artikel 10", "pages": [40], "children": [
        {"id": "doc/art-10/par-3", "type": "paragraph", "marker": "(3)", "pages": [41],
         "text": "Die Hersteller halten die technischen Unterlagen nach Anhang IV mindestens zehn Jahre lang bereit."}]},
        {"id": "doc/annex-4", "type": "annex", "marker": "ANHANG IV", "pages": [90], "text": "Technische Unterlagen"}],
    "sentences": [],
}


def answer(*rules):
    return BedrockResponse(json.dumps({"rules": list(rules)}, ensure_ascii=False), "end_turn", 100, 100, 100, "m")


class FakeClient:
    def __init__(self, response):
        self.config, self.response, self.system = BedrockConfig(), response, None

    def converse(self, system, user, **kwargs):
        self.system = system
        return self.response


def german_answer_with_known_problems():
    split = bounds({"kind": "formula", "fact": "setbackDepth", "operator": ">=", "unit": "m",
                    "expression": operation("multiply", literal(0.4), fact("H", "m"))},
                   {"kind": "numeric", "fact": "setbackDepth", "operator": ">=", "value": 3, "unit": "m"})
    return {"schemaVersion": "2.0", "id": "demo-6-5-1",
            "source": {"citation": "§ 6 Abs. 5 Satz 1", "elements": [
                {"elementId": "doc/par-6/abs-5", "sentenceId": "doc/par-6/abs-5/satz-1", "role": "primary"}]},
            "classification": {"type": "obligation", "summary": "Die Tiefe der Abstandsflächen beträgt 0,4 H, mindestens 3 m."},
            "references": [{"citation": "§ 6 Abs. 5 Satz 2", "elementId": "doc/par-6/abs-5", "resolution": "resolved"}],
            **split, "review": {"status": "draft"}}


def test_end_to_end_german_law_profile_normalization_and_flags():
    client = FakeClient(answer(german_answer_with_known_problems(),
                               {**german_answer_with_known_problems(), "id": "umlaut",
                                "requirements": [{"kind": "numeric", "fact": "fußbodenaufbau", "operator": "<=", "value": 7, "unit": "m"}],
                                "requirementExpression": None}))
    result = extract_rules(MBO_LIKE, client=client)
    assert "German legislation" in client.system and "GERMAN WORDING" in client.system
    gen = result.to_json_dict()["_generation"]
    assert (gen["profile"], gen["promptVersion"]) == ("german_legislation", "4")
    assert gen["factRenames"] == {"setbackDepth": "setback_depth", "H": "h"}
    assert gen["selfReferencesRemoved"] == 1 and gen["rulesFlagged"] == 1
    rule = result.rules[0]
    assert "references" not in rule
    assert rule["source"]["citation"] == "§ 6 Abs. 5 Satz 1"  # the document's citation style is kept
    assert any(a.startswith(FLAG_PREFIX) and "== max(...)" in a for a in rule["review"]["ambiguities"])
    assert [r["id"] for r in gen["rulesRejected"]] == ["umlaut"]
    assert list(rule_validator().iter_errors(rule)) == []


def test_end_to_end_eu_regulation_profile_and_provenance():
    eu_rule = {
        "schemaVersion": "2.0", "id": "eu-demo-10-3",
        "source": {"citation": "Artikel 10 Absatz 3", "elements": [
            {"elementId": "doc/art-10/par-3", "role": "primary"}, {"elementId": "doc/annex-4", "role": "context"}]},
        "classification": {"type": "obligation", "summary": "Die Hersteller halten die technischen Unterlagen zehn Jahre lang bereit."},
        "applicability": {"actors": [{"role": "duty_holder", "entity": "Hersteller"}]},
        "requirements": [{"kind": "temporal", "action": "technische Unterlagen bereithalten", "relation": "for_at_least",
                          "startEvent": "Inverkehrbringen", "duration": {"value": 10, "unit": "year"}},
                         {"kind": "boolean", "fact": "technicalDocumentation.keptAvailable", "value": True}],
        "references": [{"citation": "Anhang IV", "elementId": "doc/annex-4", "resolution": "resolved", "relationship": "depends_on"},
                       {"citation": "Artikel 21", "resolution": "unresolved"}],
        "review": {"status": "draft"},
    }
    client = FakeClient(answer(eu_rule))
    result = extract_rules(EU_LIKE, client=client)
    assert "EU legal act" in client.system and "GERMAN WORDING" in client.system and "German legislation" not in client.system
    assert result.rejected == [], result.rejected
    rule = result.rules[0]
    gen = result.to_json_dict()["_generation"]
    assert gen["profile"] == "eu_legislation"
    assert gen["factRenames"] == {"technicalDocumentation.keptAvailable": "technical_documentation.kept_available"}
    assert [e["pdfPages"] for e in rule["source"]["elements"]] == [[41], [90]]
    assert [r["citation"] for r in rule["references"]] == ["Anhang IV", "Artikel 21"]  # the annex is a context element, not a self-reference
    assert rule["source"]["citation"] == "Artikel 10 Absatz 3"
