"""Extraction engine, prompt version 3: schema-aware repair, rejected candidates, thresholds and periods in the logic,
English fact naming, consistency of actors / operators / value types, and coverage of the cited text.

Regression cases come from the real Bedrock runs with prompt version 2 (read only, never rewritten here):
* dev-fixtures/bedrock-extraction-results/mbo-paragraph-6.v2.rules.json (MBO § 6)
* dev-fixtures/bedrock-extraction-results/eu-2023-1230-article-10.v2.rules.json (Verordnung (EU) 2023/1230, Artikel 10)
The defects found in their evaluation must be detected; the hand-modeled examples in dev-fixtures/rule-json-examples/
must stay free of findings. Model answers are canned; no test calls Bedrock.
"""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from odos.llm.bedrock import BedrockConfig, BedrockResponse
from odos.llm.profiles import GENERAL_INSTRUCTIONS, LANGUAGE_GLOSSARIES, PROMPT_VERSION, instructions_for
from odos.llm.rule_checks import FLAG_PREFIX, check_rule, check_rule_set, facts_of
from odos.llm.rule_extraction import describe_schema_error, extract_rules, rule_schema, rule_validator
from odos.llm.rule_repair import repair_rule
from odos.llm.source_checks import SourceText, check_quantities, coverage, dates, quantities
from odos.llm.terminology import foreign_words, translate_fact

ROOT = Path(__file__).parents[2]
RESULTS = ROOT / "dev-fixtures/bedrock-extraction-results"
MBO_V2 = RESULTS / "mbo-paragraph-6.v2.rules.json"
EU_V2 = RESULTS / "eu-2023-1230-article-10.v2.rules.json"
MANUAL = [ROOT / "dev-fixtures/rule-json-examples/mbo.rules.json", ROOT / "dev-fixtures/rule-json-examples/eu-machinery.rules.json"]
PINNED = {
    "mbo-paragraph-6.rules.json": "1db8718601931dcfbd1dbef32042fc30e70dd7e03d30cd15085f195fccb9839e",
    "mbo-paragraph-6.v2.rules.json": "f60d8a1b406e27a61e2049590779be28f263a73c7f84574f04c3e05e008698b5",
    "eu-2023-1230-article-10.v2.rules.json": "a4cc2138231f2cb6bc4a2be2b7e64e964d2952e845486069f077120d8ae39520",
}


def rules_of(path: Path) -> dict[str, dict]:
    return {r["id"]: r for r in copy.deepcopy(json.loads(path.read_text(encoding="utf-8"))["rules"])}


def flags_of(rule: dict) -> list[str]:
    return [a for a in rule.get("review", {}).get("ambiguities", []) if a.startswith(FLAG_PREFIX)]


# MBO § 6 Abs. 4 as in the parser output (sentence markers "1 ", "2 ", ... are part of the element text)
ABS_4 = ("1 Die Tiefe der Abstandsfläche bemisst sich nach der Wandhöhe; sie wird senkrecht zur Wand gemessen. 2 Wandhöhe ist "
         "das Maß von der Geländeoberfläche bis zum Schnittpunkt der Wand mit der Dachhaut oder bis zum oberen Abschluss der "
         "Wand. 3 Die Höhe von Dächern mit einer Neigung von weniger als 70 Grad wird zu einem Drittel der Wandhöhe "
         "hinzugerechnet. 4 Andernfalls wird die Höhe des Daches voll hinzugerechnet. 5 Die Sätze 1 bis 4 gelten für "
         "Dachaufbauten entsprechend. 6 Das sich ergebende Maß ist H.")


def mbo_abs_4() -> dict:
    bounds = [(0, 100), (101, 236), (237, 352), (353, 412), (413, 471), (472, 503)]
    abs_4 = "doc/teil-2/par-6/abs-4"
    return {"id": "mbo", "language": "de", "documentType": "de_legislation", "legalSystem": "de",
            "structure": [{"id": "doc/teil-2/par-6", "type": "section", "children": [
                {"id": abs_4, "type": "subsection", "pages": [10], "text": ABS_4}]}],
            "sentences": [{"id": f"{abs_4}/satz-{n}", "marker": {"elementId": abs_4, "start": s, "end": s + 1},
                           "ranges": [{"elementId": abs_4, "start": s, "end": e}]} for n, (s, e) in enumerate(bounds, 1)]}


# ── baselines stay untouched ──────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", sorted(PINNED))
def test_the_saved_real_extractions_are_never_rewritten(name):
    assert hashlib.sha256((RESULTS / name).read_bytes()).hexdigest() == PINNED[name]


@pytest.mark.parametrize("path", MANUAL, ids=["mbo", "eu-machinery"])
def test_the_hand_modeled_examples_need_no_repair_and_get_no_finding_with_the_document_language(path):
    rules = list(rules_of(path).values())
    for rule in rules:
        assert repair_rule(rule, rule_schema()) == [], rule["id"]
        check = check_rule(rule, "de")
        assert check.errors == [] and check.flags == [] and check.translated == {}, (rule["id"], check.flags)
    assert check_rule_set(rules)[2] == {}


# ── 1. schema-aware repair; rejected candidates are kept ──────────────────────────────────────────────────────────────

# reconstructed from the rejection of "mbo-par-6-abs-6-nr-2" in the V2 run: a `description` on a comparison predicate
NR_2_CONDITION = {"kind": "all", "conditions": [
    {"kind": "comparison", "fact": "projections.share_of_exterior_wall_width", "operator": "<=", "value": 0.333,
     "valueType": "number", "description": "Vorbauten nehmen insgesamt nicht mehr als ein Drittel der Breite der jeweiligen Außenwand in Anspruch"},
    {"kind": "comparison", "fact": "projections.depth", "operator": "<=", "value": 1.5, "valueType": "number", "unit": "m"}]}


def test_a_description_on_a_predicate_is_removed_and_logged_not_the_rule():
    rule = {"applicability": {"conditions": copy.deepcopy(NR_2_CONDITION)}}
    repairs = repair_rule(rule, rule_schema())
    assert [str(r) for r in repairs] == [
        "applicability/conditions/conditions/0: removed 'description' (not allowed here): "
        "'Vorbauten nehmen insgesamt nicht mehr als ein Drittel der Breite der jeweiligen Außenwand in Anspruch'"]
    assert "description" not in rule["applicability"]["conditions"]["conditions"][0]


@pytest.mark.parametrize("node, path, expected", [
    ({"classification": {"type": "Obligation", "summary": "x"}}, ("classification", "type"), "obligation"),
    ({"requirements": [{"kind": "numeric", "fact": "f", "operator": ">=", "value": "3", "unit": "m"}]}, ("requirements", 0, "value"), 3),
    ({"requirements": [{"kind": "numeric", "fact": "f", "operator": ">=", "value": 3, "unit": "m²"}]}, ("requirements", 0, "unit"), "m2"),
    ({"requirements": [{"kind": "numeric", "fact": "f", "operator": "<", "value": 70, "unit": "°"}]}, ("requirements", 0, "unit"), "deg"),
    ({"requirements": [{"kind": "temporal", "action": "a", "relation": "for_at_least", "startEvent": "e",
                        "duration": {"value": 10, "unit": "years"}}]}, ("requirements", 0, "duration", "unit"), "year"),
    ({"requirements": [{"kind": "temporal", "action": "a", "relation": "For at least", "startEvent": "e",
                        "duration": {"value": 10, "unit": "year"}}]}, ("requirements", 0, "relation"), "for_at_least"),
    ({"applicability": {"conditions": {"kind": "comparison", "fact": "c", "operator": "in", "value": [1, 2]}}},
     ("applicability", "conditions", "valueType"), "integer_array"),
    ({"applicability": {"conditions": {"kind": "comparison", "fact": "c", "operator": "==", "value": "true", "valueType": "boolean"}}},
     ("applicability", "conditions", "value"), True),
])
def test_unambiguous_form_errors_are_repaired(node, path, expected):
    repairs = repair_rule(node, rule_schema())
    value = node
    for key in path:
        value = value[key]
    assert value == expected and len(repairs) == 1


@pytest.mark.parametrize("node", [
    {"requirements": [{"kind": "numeric", "fact": "f", "operator": ">=", "value": 3, "unit": "m", "threshold": 3}]},  # not an annotation
    {"applicability": {"conditions": {"kind": "comparison", "fact": "c", "operator": "in", "value": [1, "a"]}}},  # mixed list
    {"classification": {"type": "duty", "summary": "x"}},  # no enum value matches
    {"requirements": [{"kind": "numeric", "fact": "f", "operator": ">=", "value": "drei", "unit": "m"}]},  # not a number
    {"requirements": [{"kind": "numeric", "fact": "f", "operator": ">=", "value": 3, "unit": "m", "description": {"de": "x"}}]},
])
def test_ambiguous_form_errors_are_not_repaired(node):
    before = copy.deepcopy(node)
    assert repair_rule(node, rule_schema()) == [] and node == before


def test_a_one_of_error_names_the_offending_property_not_the_whole_subtree():
    rule = {"schemaVersion": "2.0", "id": "x", "source": {"documentId": "d", "elements": [{"elementId": "e"}]},
            "classification": {"type": "obligation", "summary": "s"}, "review": {"status": "draft"},
            "requirements": [{"kind": "numeric", "fact": "f", "operator": ">=", "value": 3, "unit": "m", "threshold": 3}]}
    message = describe_schema_error(next(rule_validator().iter_errors(rule)))
    assert message.startswith("requirements/0") and "'threshold'" in message


SECRET = "Abstandsflächengeheimnis"  # stands for document text: no reason may quote it


def sample_rule(**extra):
    return {"schemaVersion": "2.0", "id": "x", "source": {"documentId": "d", "elements": [{"elementId": "e"}]},
            "classification": {"type": "obligation", "summary": f"{SECRET} " * 120},  # a record far longer than any limit
            "review": {"status": "draft"}, **extra}


def reasons(rule):
    return [describe_schema_error(e) for e in rule_validator().iter_errors(rule)]


def test_requirements_and_a_requirement_expression_together_name_the_conflict_not_the_record():
    numeric = {"kind": "numeric", "fact": "f", "operator": ">=", "value": 3, "unit": "m"}
    both = sample_rule(requirements=[numeric], requirementExpression={"kind": "requirement", "requirement": numeric})
    (reason,) = reasons(both)
    assert reason.startswith("(record): property 'requirementExpression' is not allowed here")
    assert "mutually exclusive" in reason and SECRET not in reason and len(reason) < 400


def test_reasons_never_quote_the_record_or_a_wrong_value():
    wrong = sample_rule(requirements=[{"kind": "numeric", "fact": "f", "operator": SECRET, "value": 3, "unit": "m"}])
    missing = sample_rule()  # neither requirements nor requirementExpression
    odd = sample_rule(requirements=[{"kind": SECRET}], **{"Eigenschaft mit Leerzeichen": 1})
    for rule in (wrong, missing, odd):
        found = reasons(rule)
        assert found and all(SECRET not in r and len(r) <= 400 for r in found), found


def test_common_schema_errors_are_described_from_the_schema():
    bad_enum = sample_rule(requirements=[{"kind": "numeric", "fact": "f", "operator": ">=", "value": 3, "unit": "m"}])
    bad_enum["classification"]["type"] = "Pflicht-xyz"
    assert any(r.startswith("classification/type: not one of [") and "Pflicht-xyz" not in r for r in reasons(bad_enum))
    unexpected = sample_rule(requirements=[{"kind": "numeric", "fact": "f", "operator": ">=", "value": 3, "unit": "m"}],
                             x_y=1, **{"zusätzlich ohne gültigen namen": 1})
    found = reasons(unexpected)
    assert any("unexpected property 'x_y'" in r for r in found)
    assert any("<name omitted>" in r and "zusätzlich" not in r for r in found)
    assert any("missing required property" in r or "expected type" in r or "not allowed" in r for r in reasons(sample_rule()))


# ── end to end: German law (MBO-like) and EU regulation (Artikel 10-like), canned answers ─────────────────────────────


def answer(*rules):
    return BedrockResponse(json.dumps({"rules": list(rules)}, ensure_ascii=False), "end_turn", 100, 100, 100, "m")


class FakeClient:
    def __init__(self, response):
        self.config, self.response, self.system = BedrockConfig(), response, None

    def converse(self, system, user, **kwargs):
        self.system = system
        return self.response


def mbo_record(rule_id, sentences, **body):
    return {"schemaVersion": "2.0", "id": rule_id,
            "source": {"citation": "§ 6 Abs. 4", "elements": [
                {"elementId": "doc/teil-2/par-6/abs-4", "sentenceId": f"doc/teil-2/par-6/abs-4/satz-{n}", "role": "primary"} for n in sentences]},
            "classification": {"type": "procedural_requirement", "summary": "Die Höhe von Dächern wird hinzugerechnet."},
            "review": {"status": "draft"}, **body}


ROOF = {"kind": "comparison", "fact": "roof_pitch", "operator": "<", "value": 70, "valueType": "number", "unit": "deg"}
THIRD = {"kind": "formula", "fact": "measure_h", "operator": "==", "unit": "m", "expression": {"kind": "operation", "operator": "add", "operands": [
    {"kind": "fact", "name": "wall_height", "unit": "m"},
    {"kind": "operation", "operator": "divide", "operands": [{"kind": "fact", "name": "roof_height", "unit": "m"}, {"kind": "literal", "value": 3}]}]}}
FULL = {"kind": "formula", "fact": "measure_h", "operator": "==", "unit": "m", "expression": {"kind": "operation", "operator": "add", "operands": [
    {"kind": "fact", "name": "wall_height", "unit": "m"}, {"kind": "fact", "name": "roof_height", "unit": "m"}]}}


def test_end_to_end_a_repairable_record_is_accepted_and_an_unrepairable_one_kept_as_candidate():
    repairable = mbo_record("repairable", [3, 4], applicability={"conditions": {**ROOF, "description": "Neigung unter 70 Grad"}},
                            requirements=[THIRD],
                            exceptions=[{"kind": "alternative", "effect": "modifies_rule", "description": "Andernfalls voll.",
                                         "condition": {"kind": "not", "condition": ROOF}, "requirements": [FULL]}])
    broken = mbo_record("broken", [1], requirements=[{**THIRD, "threshold": 1}])
    result = extract_rules(mbo_abs_4(), client=FakeClient(answer(repairable, broken)))
    assert [r["id"] for r in result.rules] == ["mbo-repairable"]
    assert any("schema repair" in f and "Neigung unter 70 Grad" in f for f in flags_of(result.rules[0]))
    gen = result.to_json_dict()["_generation"]
    assert gen["promptVersion"] == PROMPT_VERSION == "4"
    assert gen["schemaRepairs"] == [{"id": "mbo-repairable", "repairs": [
        "applicability/conditions: removed 'description' (not allowed here): 'Neigung unter 70 Grad'"]}]
    [rejected] = gen["rulesRejected"]
    assert rejected["id"] == "broken" and rejected["candidate"] == broken and "'threshold'" in rejected["reasons"][0]
    assert list(rule_validator().iter_errors(result.rules[0])) == []


# ── 2. thresholds in the logic, not only in descriptions ──────────────────────────────────────────────────────────────


def test_the_v2_roof_pitch_rule_is_flagged_because_70_degrees_is_only_in_its_descriptions():
    rule = rules_of(MBO_V2)["mbo-par-6-abs-4-satz-3-4"]  # 'any' of the two formulas, the pitch condition lost
    flags = check_quantities([rule], SourceText.of(mbo_abs_4()))
    assert any("'70 Grad'" in f and "abs-4/satz-3" in f for f in flags[rule["id"]])
    assert not any("Drittel" in f for f in flags[rule["id"]])  # the third is in the logic (divide by 3)


def test_a_rule_and_exception_with_the_threshold_predicate_is_not_flagged():
    rule = mbo_record("ok", [3, 4], applicability={"conditions": ROOF}, requirements=[THIRD],
                      exceptions=[{"kind": "alternative", "description": "Andernfalls wird die Höhe voll hinzugerechnet.",
                                   "condition": {"kind": "not", "condition": ROOF}, "requirements": [FULL]}])
    assert check_quantities([rule], SourceText.of(mbo_abs_4())) == {}


def test_a_number_only_in_the_summary_is_flagged_even_without_source_sentences():
    rule = {"id": "r", "classification": {"summary": "Der Abstand beträgt mindestens 2,5 m."},
            "requirements": [{"kind": "boolean", "fact": "distance_kept", "value": True}]}
    [flag] = check_quantities([rule], SourceText.of({"language": "de", "structure": []}))["r"]
    assert "'2,5 m'" in flag


@pytest.mark.parametrize("text, language, expected", [
    ("mindestens zehn Jahre lang aufbewahren", "de", [10]),
    ("innerhalb eines Monats", "de", [1]),
    ("beträgt 0,4 H, mindestens 3 m", "de", [0.4, 3]),
    ("nicht mehr als 1,50 m vor die Außenwand", "de", [1.5]),
    ("zu einem Drittel der Wandhöhe", "de", [1 / 3]),
    ("mit einer Neigung von weniger als 70 Grad", "de", [70]),
    ("within one month after the request", "en", [1]),
    ("for at least ten years", "en", [10]),
    ("Die Sätze 1 bis 4 gelten nach Artikel 21 und Anhang III Abschnitt 1.2.1", "de", []),  # citations are not quantities
    ("Gebäudeklassen 1 und 2", "de", []),
])
def test_quantities_are_read_from_german_and_english_text(text, language, expected):
    assert [round(q.value, 4) for q in quantities(text, language)] == [round(v, 4) for v in expected]


def test_dates_are_read_but_the_date_of_another_act_is_not_a_deadline():
    text = "Richtlinie 2006/42/EG vom 17. Mai 2006 gilt bis zum 20. Januar 2027."
    assert dates(text, "de") == [("2027-01-20", "20. Januar 2027")]


# ── 3. English fact naming ────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name, expected", [
    ("gebaeudeklasse", "building_class"), ("gebäudeklasse", "building_class"), ("wandhoehe", "wall_height"),
    ("abstandsflaeche_tiefe", "setback_area_depth"), ("abstandsflächen", "setback_area"), ("höhe", "height"),
    ("hersteller.betriebsanleitung", "manufacturer.instructions"),
    ("setback_depth", None),  # English already: nothing to translate
    ("abweichende_gebaeudeabstaende_nach_bau_gb_34_zulaessig", None),  # partly unknown: never half-translated
])
def test_german_identifiers_are_translated_only_when_every_word_is_known(name, expected):
    assert translate_fact(name, "de") == expected


def test_identifiers_are_not_translated_for_other_languages():
    assert translate_fact("gebaeudeklasse", "en") is None and foreign_words("gebaeudeklasse", "en") == []


def test_the_v2_mbo_facts_are_translated_or_flagged_and_none_passes_as_english():
    rules = rules_of(MBO_V2)
    rule = rules["mbo-par-6-abs-5-satz-1"]
    check = check_rule(rule, "de")
    assert check.translated == {"abstandsflaeche_tiefe": "setback_area_depth", "gebaeudeklasse": "building_class"}
    assert any("'satzung_ordnet_geltung_saetze_1_bis_3_an' is not English" in f for f in check.flags)
    for r in rules.values():  # after the check, every identifier is English or carries a finding
        flags = " ".join(check_rule(r, "de").flags)
        for name in facts_of(r):
            assert not foreign_words(name, "de") or f"{name!r} is not English" in flags, (r["id"], name)


def test_the_eu_v2_facts_are_english_and_get_no_naming_finding():
    for rule in rules_of(EU_V2).values():
        check = check_rule(rule, "de")
        assert check.translated == {} and not any("not English" in f for f in check.flags), rule["id"]


# ── 4. temporal semantics ─────────────────────────────────────────────────────────────────────────────────────────────


def test_the_v2_retention_period_written_as_a_number_is_flagged():
    flags = check_rule(rules_of(EU_V2)["verordnung-2023-1230-art-10-abs-3-s1"], "de").flags
    assert any("'documentation_retention_period' is a period of 10 year" in f and "temporal" in f for f in flags)


@pytest.mark.parametrize("requirement", [
    {"kind": "temporal", "action": "aufbewahren", "relation": "for_at_least", "startEvent": "Inverkehrbringen",
     "duration": {"value": 10, "unit": "year"}},
    {"kind": "numeric", "fact": "fire_resistance_duration", "operator": ">=", "value": 30, "unit": "min"},  # a property
])
def test_a_temporal_requirement_and_a_short_technical_duration_are_not_flagged(requirement):
    assert check_rule({"requirements": [requirement]}, "de").flags == []


def test_the_period_in_the_eu_text_is_satisfied_by_a_duration():
    eu = {"id": "eu", "language": "de", "structure": [{"id": "p3", "type": "paragraph", "text": "Die Hersteller bewahren die Unterlagen mindestens zehn Jahre lang auf."}],
          "sentences": [{"id": "p3/s1", "ranges": [{"elementId": "p3", "start": 0, "end": 70}]}]}
    temporal = {"id": "t", "source": {"elements": [{"elementId": "p3", "sentenceId": "p3/s1"}]},
                "requirements": [{"kind": "temporal", "action": "aufbewahren", "relation": "for_at_least", "startEvent": "Inverkehrbringen",
                                  "duration": {"value": 10, "unit": "year"}}]}
    assert check_quantities([temporal], SourceText.of(eu)) == {}


# ── 5. operators, value types, actors, coverage ───────────────────────────────────────────────────────────────────────


def test_the_v2_alternative_that_turns_a_determined_value_into_a_minimum_is_flagged():
    flags = check_rule(rules_of(MBO_V2)["mbo-par-6-abs-5-satz-1"], "de").flags
    assert any("sets 'setback_area_depth' with operator '>='" in f and "['==']" in f for f in flags)
    assert any("'building_class' compares numbers as strings ['1', '2']" in f for f in flags)


def test_one_fact_with_two_value_types_or_units_and_near_identical_spellings_are_flagged():
    a = {"id": "a", "applicability": {"conditions": {"kind": "comparison", "fact": "building_class", "operator": "in", "value": [1, 2], "valueType": "integer_array"}},
         "requirements": [{"kind": "numeric", "fact": "depth", "operator": ">=", "value": 3, "unit": "m"}]}
    b = {"id": "b", "applicability": {"conditions": {"kind": "comparison", "fact": "building_class", "operator": "==", "value": "1", "valueType": "string"}},
         "requirements": [{"kind": "numeric", "fact": "depth", "operator": ">=", "value": 300, "unit": "cm"},
                          {"kind": "boolean", "fact": "buildingclass", "value": True}]}
    flags = check_rule_set([a, b])[2]
    assert any("different value types ['number', 'string']" in f for f in flags["a"])
    assert any("different units ['cm', 'm']" in f for f in flags["b"])
    assert any("differ only in underscores" in f for f in flags["b"])


def test_the_v2_eu_actor_spellings_are_flagged():
    _, _, flags = check_rule_set(list(rules_of(EU_V2).values()))
    assert any("'Zuständige nationale Behörden' is also written 'Zuständige nationale Behörde'" in f
               for f in flags["verordnung-2023-1230-art-10-abs-3-s2"])
    assert any("extends 'Zuständige nationale Behörden'" in f for f in flags["verordnung-2023-1230-art-10-abs-9-s2"])


def test_coverage_reports_uncited_sentences_and_those_only_a_rejected_candidate_cites():
    source = SourceText.of(mbo_abs_4())
    accepted = [mbo_record("a", [1, 2, 6]), mbo_record("b", [3, 4])]
    report = coverage(accepted, source, rejected=[mbo_record("rejected", [5])])
    assert (report["sentences"], report["sentencesCited"]) == (6, 5)
    assert [u["id"] for u in report["uncitedSentences"]] == ["doc/teil-2/par-6/abs-4/satz-5"]
    assert report["uncitedSentences"][0]["text"].startswith("Die Sätze 1 bis 4 gelten für Dachaufbauten")  # marker removed
    assert report["citedOnlyByRejected"] == ["doc/teil-2/par-6/abs-4/satz-5"]


def test_end_to_end_the_generation_block_carries_coverage():
    result = extract_rules(mbo_abs_4(), client=FakeClient(answer(mbo_record("a", [6], definition={"term": "H", "text": "Das sich ergebende Maß"},
                                                                            classification={"type": "definition", "summary": "Das Maß ist H."}))))
    cov = result.to_json_dict()["_generation"]["coverage"]
    assert (cov["sentences"], cov["sentencesCited"], cov["elements"], cov["elementsCited"]) == (6, 1, 1, 1)


# ── prompt version 3 ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_v3_instructions_cover_thresholds_time_translation_value_types_actors_and_schema_form():
    for phrase in ("never only into a `description`", "7. TIME.", "TRANSLATE the meaning into English", "6. VALUE TYPES.",
                   "9. ACTORS.", "10. SCHEMA FORM.", "cited ONLY in the `source.elements` of the record it belongs to"):
        assert phrase in GENERAL_INSTRUCTIONS
    for law_specific in ("MBO", "BauGB", "§", "2023/1230", "Absatz", "Artikel"):
        assert law_specific not in GENERAL_INSTRUCTIONS


def test_the_german_glossary_lists_english_terms_and_temporal_wording():
    text, _ = instructions_for({"language": "de", "documentType": "de_legislation"})
    assert "Gebäudeklasse -> building_class" in LANGUAGE_GLOSSARIES["de"] and "Hersteller -> manufacturer" in text
    assert "innerhalb von" in text and "no_later_than" in LANGUAGE_GLOSSARIES["en"]
