import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker


SCHEMA_PATH = Path(__file__).parents[1] / "schemas/rule-json/2.0/rule.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())

EXAMPLES_DIR = Path(__file__).parents[2] / "dev-fixtures/rule-json-examples"


def make_rule(**overrides):
    rule = {
        "schemaVersion": "2.0",
        "id": "test-rule-1",
        "source": {
            "documentId": "test-document",
            "elements": [{"elementId": "doc/section-1/para-1"}],
        },
        "classification": {
            "type": "obligation",
            "summary": "A test requirement.",
        },
        "requirements": [
            {"kind": "numeric", "fact": "distance", "operator": ">=", "value": 3, "unit": "m"}
        ],
        "review": {"status": "draft"},
    }
    rule.update(overrides)
    return rule


# ── Schema validity ──────────────────────────────────────────────────


def test_schema_is_valid_draft_2020_12():
    Draft202012Validator.check_schema(SCHEMA)


# ── Positive: example files validate ─────────────────────────────────


def _load_example_rules():
    rules = []
    for path in sorted(EXAMPLES_DIR.glob("*.rules.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for rule in data.get("rules", []):
            rules.append(pytest.param(rule, id=rule["id"]))
    return rules


@pytest.mark.parametrize("rule", _load_example_rules())
def test_example_rules_validate(rule):
    errors = list(VALIDATOR.iter_errors(rule))
    assert errors == [], [e.message for e in errors]


# ── Positive: minimal valid rule ─────────────────────────────────────


def test_minimal_rule_validates():
    assert list(VALIDATOR.iter_errors(make_rule())) == []


def test_definition_rule_validates():
    rule = make_rule(
        classification={"type": "definition", "summary": "Defines a term."},
        requirements=None,
        definition={"term": "Gebäude", "text": "A building."},
    )
    rule.pop("requirements", None)
    assert list(VALIDATOR.iter_errors(rule)) == []


def test_rule_with_applicability_validates():
    rule = make_rule(
        applicability={
            "targets": [{"entity": "Fenster", "entityType": "window"}],
            "actors": [{"role": "duty_holder", "entity": "Bauherr"}],
            "conditions": {
                "kind": "comparison",
                "fact": "building.height",
                "operator": ">",
                "value": 7,
                "valueType": "number",
                "unit": "m",
            },
        }
    )
    assert list(VALIDATOR.iter_errors(rule)) == []


def test_rule_with_requirement_expression_validates():
    rule = make_rule(
        requirements=None,
        requirementExpression={
            "kind": "any",
            "requirements": [
                {"kind": "requirement", "requirement": {"kind": "numeric", "fact": "width", "operator": ">=", "value": 0.9, "unit": "m"}},
                {"kind": "requirement", "requirement": {"kind": "numeric", "fact": "step_distance", "operator": "<=", "value": 1.0, "unit": "m"}},
            ],
        },
    )
    rule.pop("requirements", None)
    assert list(VALIDATOR.iter_errors(rule)) == []


def test_rule_with_exceptions_validates():
    rule = make_rule(
        exceptions=[
            {
                "kind": "alternative",
                "description": "Reduced setback in commercial zones.",
                "condition": {"kind": "comparison", "fact": "zone", "operator": "==", "value": "commercial", "valueType": "string"},
                "effect": "modifies_rule",
            }
        ]
    )
    assert list(VALIDATOR.iter_errors(rule)) == []


def test_rule_with_review_details_validates():
    rule = make_rule(
        review={
            "status": "reviewed",
            "machineCheckable": True,
            "checkMethods": ["ids", "shacl"],
            "ambiguities": ["Calendar month calculation not specified."],
            "notes": ["Reviewed by legal team."],
        }
    )
    assert list(VALIDATOR.iter_errors(rule)) == []


def test_rule_with_external_mapping_validates():
    rule = make_rule(
        externalMappings=[
            {
                "standard": "IFC4",
                "entityClass": "IfcWindow",
                "propertySet": "Pset_WindowCommon",
                "propertyPath": "OverallWidth",
            }
        ]
    )
    assert list(VALIDATOR.iter_errors(rule)) == []


def test_rule_with_pdf_pages_validates():
    rule = make_rule(
        source={
            "documentId": "mbo",
            "citation": "§ 37 Abs. 5",
            "elements": [
                {"elementId": "doc/teil-3/par-37/abs-5", "pdfPages": [34], "role": "primary"}
            ],
        }
    )
    assert list(VALIDATOR.iter_errors(rule)) == []


def test_temporal_requirement_validates():
    rule = make_rule(
        requirements=[
            {
                "kind": "temporal",
                "action": "retain documentation",
                "startEvent": "placing on the market",
                "relation": "for_at_least",
                "duration": {"value": 10, "unit": "year"},
            }
        ]
    )
    assert list(VALIDATOR.iter_errors(rule)) == []


def test_unresolved_requirement_validates():
    rule = make_rule(
        requirements=[
            {
                "kind": "unresolved",
                "text": "General safety clause.",
                "reason": "Cannot be reduced to a numeric check.",
            }
        ]
    )
    assert list(VALIDATOR.iter_errors(rule)) == []


def test_cross_references_validate():
    rule = make_rule(
        references=[
            {
                "documentId": "mbo",
                "citation": "§ 67 Abs. 1",
                "elementId": "doc/teil-5/par-67/abs-1",
                "resolution": "resolved",
                "relationship": "subject_to",
            }
        ]
    )
    assert list(VALIDATOR.iter_errors(rule)) == []


# ── Negative: invalid rules are rejected ─────────────────────────────


def test_missing_schema_version_is_rejected():
    rule = make_rule()
    del rule["schemaVersion"]
    assert list(VALIDATOR.iter_errors(rule))


def test_wrong_schema_version_is_rejected():
    assert list(VALIDATOR.iter_errors(make_rule(schemaVersion="1.0")))


def test_missing_source_is_rejected():
    rule = make_rule()
    del rule["source"]
    assert list(VALIDATOR.iter_errors(rule))


def test_missing_classification_is_rejected():
    rule = make_rule()
    del rule["classification"]
    assert list(VALIDATOR.iter_errors(rule))


def test_missing_review_is_rejected():
    rule = make_rule()
    del rule["review"]
    assert list(VALIDATOR.iter_errors(rule))


def test_invalid_rule_type_is_rejected():
    assert list(VALIDATOR.iter_errors(
        make_rule(classification={"type": "numeric_comparison", "summary": "bad"})
    ))


def test_missing_elements_in_source_is_rejected():
    assert list(VALIDATOR.iter_errors(
        make_rule(source={"documentId": "test"})
    ))


def test_empty_elements_in_source_is_rejected():
    assert list(VALIDATOR.iter_errors(
        make_rule(source={"documentId": "test", "elements": []})
    ))


def test_invalid_comparison_operator_is_rejected():
    rule = make_rule(
        applicability={
            "conditions": {"kind": "comparison", "fact": "height", "operator": "approximately", "value": 3}
        }
    )
    assert list(VALIDATOR.iter_errors(rule))


def test_typed_numeric_comparison_rejects_string_value():
    rule = make_rule(
        applicability={
            "conditions": {"kind": "comparison", "fact": "storeys", "operator": "<=", "value": "3", "valueType": "integer"}
        }
    )
    assert list(VALIDATOR.iter_errors(rule))


def test_unsupported_extra_fields_are_rejected():
    assert list(VALIDATOR.iter_errors(make_rule(inventedField=True)))


def test_definition_cannot_have_requirements():
    rule = make_rule(
        classification={"type": "definition", "summary": "A term."},
        definition={"term": "x", "text": "meaning"},
    )
    assert list(VALIDATOR.iter_errors(rule))


def test_non_definition_must_have_requirements():
    rule = make_rule()
    del rule["requirements"]
    assert list(VALIDATOR.iter_errors(rule))


def test_cannot_have_both_requirements_and_expression():
    rule = make_rule(
        requirementExpression={
            "kind": "requirement",
            "requirement": {"kind": "boolean", "fact": "x", "value": True},
        }
    )
    assert list(VALIDATOR.iter_errors(rule))


def test_invalid_review_status_is_rejected():
    assert list(VALIDATOR.iter_errors(
        make_rule(review={"status": "pending"})
    ))


def test_invalid_check_method_is_rejected():
    assert list(VALIDATOR.iter_errors(
        make_rule(review={"status": "draft", "checkMethods": ["magic"]})
    ))


def test_temporal_requirement_without_start_event_is_rejected():
    rule = make_rule(
        requirements=[{
            "kind": "temporal",
            "action": "retain records",
            "relation": "for_at_least",
            "duration": {"value": 10, "unit": "year"},
        }]
    )
    assert list(VALIDATOR.iter_errors(rule))


def test_invalid_nested_logical_predicate_is_rejected():
    rule = make_rule(
        applicability={
            "conditions": {"kind": "all", "conditions": [{"kind": "not", "condition": {"kind": "all", "conditions": []}}]}
        }
    )
    assert list(VALIDATOR.iter_errors(rule))


def test_invalid_numeric_unit_is_rejected():
    rule = make_rule(
        requirements=[{"kind": "numeric", "fact": "distance", "operator": ">=", "value": 3, "unit": ""}]
    )
    assert list(VALIDATOR.iter_errors(rule))


def test_logical_expression_needs_at_least_two_items():
    rule = make_rule(
        requirements=None,
        requirementExpression={
            "kind": "any",
            "requirements": [
                {"kind": "requirement", "requirement": {"kind": "boolean", "fact": "a", "value": True}}
            ],
        },
    )
    rule.pop("requirements", None)
    assert list(VALIDATOR.iter_errors(rule))

# ── Structured formula validation ──────────────────────────

def test_structured_formula_validates():
    rule = make_rule(requirements=[{
        "kind": "formula",
        "fact": "setback_depth",
        "unit": "m",
        "expression": {
            "kind": "operation",
            "operator": "multiply",
            "operands": [
                {"kind": "literal", "value": 0.4},
                {"kind": "fact", "name": "wall_height", "unit": "m"}
            ]
        }
    }])
    assert list(VALIDATOR.iter_errors(rule)) == []


def test_string_formula_is_rejected():
    rule = make_rule(requirements=[{
        "kind": "formula",
        "fact": "setback_depth",
        "unit": "m",
        "expression": "0.4 * wall_height"
    }])
    assert list(VALIDATOR.iter_errors(rule))