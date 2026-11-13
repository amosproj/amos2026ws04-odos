import json
import os
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker


SCHEMA_PATH = Path(__file__).parents[1] / "schemas/rule-json/1.0/rule.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def make_rule(**overrides):
    rule = {
        "schemaVersion": "1.0",
        "id": "fixture-rule-1",
        "type": "conditional_requirement",
        "documentReference": {"documentId": "fixture-law"},
        "source": [{"elementId": "source/provision-1", "sentenceNumber": 1}],
        "status": "draft",
        "summary": "A fixture requirement.",
        "requirements": [{"kind": "numeric", "property": "distance", "operator": "gte", "value": 3, "unit": "m"}],
    }
    rule.update(overrides)
    return rule


MBO_FIXTURES = [
    make_rule(
        id="mbo-definition",
        type="definition",
        documentReference={"documentId": "mbo"},
        source=[{"elementId": "doc/teil-1/par-2/abs-2"}],
        requirements=None,
        definition={"term": "Gebäude", "text": "A source-language legal definition."},
    ),
    make_rule(
        id="mbo-procedural-deadline",
        documentReference={"documentId": "mbo"},
        source=[{"elementId": "doc/teil-5/abschnitt-2/par-62/abs-3", "sentenceNumber": 2}],
        actors=[{"role": "duty_holder", "entity": "Bauherr"}, {"role": "authority", "entity": "Gemeinde"}],
        requirements=None,
        requirementExpression={
            "kind": "requirement",
            "requirement": {
                "kind": "temporal",
                "action": "wait before commencing the building project",
                "startEvent": "receipt of the required documents by the municipality",
                "relation": "within",
                "duration": {"value": 1, "unit": "month"},
            },
        },
    ),
    make_rule(
        id="mbo-alternative-access",
        type="permission",
        documentReference={"documentId": "mbo"},
        source=[{"elementId": "doc/teil-2/par-4/abs-1"}],
        requirements=None,
        requirementExpression={
            "kind": "any",
            "requirements": [
                {"kind": "requirement", "requirement": {"kind": "boolean", "property": "site.adjoinsAccessiblePublicTrafficAreaAtAdequateWidth", "value": True}},
                {"kind": "requirement", "requirement": {"kind": "boolean", "property": "site.hasSecuredAccessibleAccessToPublicTrafficArea", "value": True}},
            ],
        },
    ),
    make_rule(
        id="mbo-general-safety-unresolved",
        documentReference={"documentId": "mbo"},
        source=[{"elementId": "doc/teil-1/par-3/txt-1"}],
        requirements=[{"kind": "unresolved", "text": "Avoid danger to public safety and order, especially life, health and natural resources.", "reason": "The provision is purpose-oriented and requires contextual legal and technical evaluation."}],
    ),
]

EU_FIXTURES = [
    make_rule(
        id="eu-conditional-definition",
        type="definition",
        documentReference={"documentId": "verordnung-2023-1230"},
        source=[{"elementId": "doc/chp-1/art-3/pt-18"}],
        requirements=None,
        definition={
            "term": "Hersteller",
            "text": "The person or entity meeting either of the alternatives in the cited definition.",
            "condition": {
                "kind": "any",
                "conditions": [
                    {
                        "kind": "all",
                        "conditions": [
                            {"kind": "comparison", "property": "manufacturesOrHasManufactured", "operator": "eq", "value": True, "valueType": "boolean"},
                            {"kind": "comparison", "property": "marketsUnderOwnNameOrTrademark", "operator": "eq", "value": True, "valueType": "boolean"},
                        ],
                    },
                    {
                        "kind": "all",
                        "conditions": [
                            {"kind": "comparison", "property": "manufactures", "operator": "eq", "value": True, "valueType": "boolean"},
                            {"kind": "comparison", "property": "putsProductIntoServiceForOwnUse", "operator": "eq", "value": True, "valueType": "boolean"},
                        ],
                    },
                ],
            },
        },
    ),
    make_rule(
        id="eu-actor-document-retention",
        documentReference={"documentId": "verordnung-2023-1230"},
        source=[
            {"elementId": "doc/chp-2/art-10/para-3", "role": "primary_normative_text"},
            {"elementId": "doc/preamble/rec-58", "role": "context"},
        ],
        actors=[
            {
                "role": "duty_holder",
                "entity": "manufacturer",
                "reference": {"documentId": "verordnung-2023-1230", "citation": "Article 3 point 18", "elementId": "doc/chp-1/art-3/pt-18", "resolution": "resolved", "relationship": "defined_by"},
            },
            {"role": "authority", "entity": "market surveillance authority"},
        ],
        requirements=None,
        requirementExpression={
            "kind": "requirement",
            "requirement": {
                "kind": "temporal",
                "action": "retain technical documentation and the EU declaration of conformity",
                "startEvent": "placing the machine or related product on the market or putting it into service",
                "relation": "for_at_least",
                "duration": {"value": 10, "unit": "year"},
            },
        },
        references=[{"documentId": "verordnung-2023-1230", "citation": "Annex IV", "elementId": "doc/annex-4", "resolution": "resolved", "relationship": "depends_on"}],
    ),
    make_rule(
        id="eu-annex-combined-requirements",
        documentReference={"documentId": "verordnung-2023-1230"},
        source=[{"elementId": "doc/annex-3/part-b/h-1/h-1.2/h-1.2.1/pt-a"}],
        requirements=None,
        requirementExpression={
            "kind": "all",
            "requirements": [
                {"kind": "requirement", "requirement": {"kind": "boolean", "property": "controlSystem.toleratesExpectedOperatingStress", "value": True}},
                {"kind": "requirement", "requirement": {"kind": "boolean", "property": "controlSystem.resistsIntendedExternalInfluences", "value": True}},
                {"kind": "requirement", "requirement": {"kind": "boolean", "property": "controlSystem.resistsUnintendedExternalInfluences", "value": True}},
            ],
        },
        references=[{"documentId": "verordnung-2023-1230", "citation": "Annex III", "elementId": "doc/annex-3", "resolution": "resolved", "relationship": "implements"}],
    ),
    make_rule(
        id="eu-scope-exclusion",
        documentReference={"documentId": "verordnung-2023-1230"},
        source=[{"elementId": "doc/chp-1/art-2/para-2/pt-a"}],
        scopeExclusions=[{"kind": "comparison", "property": "isReplacementSafetyComponentFromOriginalManufacturer", "operator": "eq", "value": True, "valueType": "boolean"}],
    ),
    make_rule(
        id="eu-transitional-application-date",
        documentReference={"documentId": "verordnung-2023-1230"},
        source=[{"elementId": "doc/chp-9/art-54/pt-a"}],
        requirements=[{"kind": "temporal", "action": "Articles 26 to 42 apply", "relation": "by", "deadline": "2024-01-14"}],
    ),
]


def test_schema_is_valid_draft_2020_12():
    Draft202012Validator.check_schema(SCHEMA)


@pytest.mark.parametrize("rule", MBO_FIXTURES + EU_FIXTURES, ids=lambda item: item["id"])
def test_manually_modeled_reference_fixtures_validate(rule):
    rule = {key: value for key, value in rule.items() if value is not None}
    assert list(VALIDATOR.iter_errors(rule)) == []


def test_legacy_untyped_comparison_remains_valid():
    rule = make_rule(applicability={"kind": "comparison", "property": "category", "operator": "eq", "value": {"legacy": "value"}})
    assert list(VALIDATOR.iter_errors(rule)) == []


def test_typed_numeric_comparison_rejects_a_string_value():
    rule = make_rule(applicability={"kind": "comparison", "property": "storeys", "operator": "lte", "value": "3", "valueType": "integer"})
    assert list(VALIDATOR.iter_errors(rule))


def test_typed_membership_requires_an_array():
    rule = make_rule(applicability={"kind": "comparison", "property": "class", "operator": "in", "value": "A", "valueType": "string"})
    assert list(VALIDATOR.iter_errors(rule))


def test_typed_array_values_are_limited_to_membership_operators():
    rule = make_rule(applicability={"kind": "comparison", "property": "classes", "operator": "eq", "value": [1, 2], "valueType": "integer_array"})
    assert list(VALIDATOR.iter_errors(rule))


def test_temporal_requirement_requires_event_and_duration_for_relative_period():
    rule = make_rule(requirements=[{"kind": "temporal", "action": "retain records", "relation": "for_at_least", "duration": {"value": 10, "unit": "year"}}])
    assert list(VALIDATOR.iter_errors(rule))


def test_temporal_deadline_must_be_an_iso_date():
    rule = make_rule(requirements=[{"kind": "temporal", "action": "apply provision", "relation": "by", "deadline": "next January"}])
    assert list(VALIDATOR.iter_errors(rule))


def test_invalid_logical_requirement_expression_is_rejected():
    rule = make_rule(requirements=None, requirementExpression={"kind": "any", "requirements": [{"kind": "requirement", "requirement": {"kind": "boolean", "property": "a", "value": True}}]})
    assert list(VALIDATOR.iter_errors(rule))


def test_missing_mandatory_fields_are_rejected():
    rule = make_rule()
    del rule["status"]
    assert list(VALIDATOR.iter_errors(rule))


def test_invalid_rule_type_is_rejected():
    assert list(VALIDATOR.iter_errors(make_rule(type="numeric_comparison")))


def test_invalid_comparison_operator_is_rejected():
    rule = make_rule(applicability={"kind": "comparison", "property": "height", "operator": "approximately", "value": 3})
    assert list(VALIDATOR.iter_errors(rule))


def test_invalid_nested_logical_predicate_is_rejected():
    rule = make_rule(applicability={"kind": "all", "conditions": [{"kind": "not", "condition": {"kind": "all", "conditions": []}}]})
    assert list(VALIDATOR.iter_errors(rule))


@pytest.mark.parametrize("unit", ["", None])
def test_invalid_numeric_unit_is_rejected(unit):
    rule = make_rule(requirements=[{"kind": "numeric", "property": "distance", "operator": "gte", "value": 3, "unit": unit}])
    assert list(VALIDATOR.iter_errors(rule))


def test_unsupported_extra_fields_are_rejected():
    assert list(VALIDATOR.iter_errors(make_rule(inventedField=True)))


def test_definition_cannot_include_requirement_fields():
    rule = make_rule(type="definition", definition={"term": "x", "text": "meaning"})
    assert list(VALIDATOR.iter_errors(rule))


def test_non_definition_requires_exactly_one_requirement_representation():
    rule = make_rule(requirementExpression={"kind": "requirement", "requirement": {"kind": "boolean", "property": "x", "value": True}})
    assert list(VALIDATOR.iter_errors(rule))


def _source_ids(document):
    ids = set()

    def visit(nodes):
        for node in nodes or []:
            if isinstance(node, dict):
                if isinstance(node.get("id"), str):
                    ids.add(node["id"])
                visit(node.get("children"))

    visit(document.get("structure"))
    return ids


def _assert_fixture_references_exist(document_path: str, fixtures: list[dict]):
    document = json.loads(Path(document_path).read_text(encoding="utf-8"))
    ids = _source_ids(document)
    referenced = set()

    def collect(value):
        if isinstance(value, dict):
            if value.get("resolution") != "unresolved" and isinstance(value.get("elementId"), str):
                referenced.add(value["elementId"])
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    for fixture in fixtures:
        collect(fixture)
    missing = sorted(referenced - ids)
    assert not missing, f"Fixture references missing Legal JSON element IDs: {missing}"


def test_mbo_source_references_exist():
    path = os.environ.get("ODOS_MBO_LEGAL_JSON_PATH") or os.environ.get("ODOS_LEGAL_JSON_PATH")
    if not path:
        pytest.skip("Set ODOS_MBO_LEGAL_JSON_PATH to a Legal JSON 2.0 MBO document")
    _assert_fixture_references_exist(path, MBO_FIXTURES)


def test_eu_source_references_exist():
    path = os.environ.get("ODOS_EU_LEGAL_JSON_PATH")
    if not path:
        pytest.skip("Set ODOS_EU_LEGAL_JSON_PATH to a Legal JSON 2.0 EU document")
    _assert_fixture_references_exist(path, EU_FIXTURES)



def test_labeled_eu_demo_fixture_validates_against_1_0():
    fixture = json.loads((Path(__file__).parent / "fixtures/rule-json/1.0/eu-machinery-demo.rules.json").read_text(encoding="utf-8"))
    assert "SIMULATED" in fixture["demoLabel"]
    for rule in fixture["rules"]:
        assert list(VALIDATOR.iter_errors(rule)) == [], rule["id"]
