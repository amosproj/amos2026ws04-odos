import json
import os
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker


SCHEMA_PATH = Path(__file__).parents[1] / "schemas/rule-json/rule.schema.json"
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


def test_rule_json_has_a_single_schema_for_schema_version_2_0():
    assert [p.relative_to(SCHEMA_PATH.parent).as_posix() for p in SCHEMA_PATH.parent.rglob("*.json")] == ["rule.schema.json"]
    assert SCHEMA["$defs"]["Rule"]["properties"]["schemaVersion"] == {"const": "2.0"}


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
        "operator": "==",
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
        "operator": "==",
        "unit": "m",
        "expression": "0.4 * wall_height"
    }])
    assert list(VALIDATOR.iter_errors(rule))


# ── Operator and datatype compatibility ──────────────────────────────


def comparison(operator, value, value_type=None, **extra):
    condition = {"kind": "comparison", "fact": "f", "operator": operator, "value": value, **extra}
    if value_type is not None:
        condition["valueType"] = value_type
    return condition


def condition_rule(condition):
    return make_rule(applicability={"conditions": condition})


@pytest.mark.parametrize("condition", [
    comparison("==", "commercial", "string"),
    comparison("!=", True, "boolean"),
    comparison("==", 2, "integer"),
    comparison(">", 7, "number", unit="m"),
    comparison(">=", 3, "integer"),
    comparison("<", 0.5, "number", unit="m"),
    comparison("<=", 3, "integer"),
    comparison("in", ["core", "mixed"], "string_array"),
    comparison("not_in", [1, 2], "integer_array"),
    comparison("in", [0.9, 1.2], "number_array", unit="m"),
    comparison("in", [True], "boolean_array"),
    comparison("contains", "fire_door", "string"),
    comparison("contains", 3, "integer"),
    comparison("==", 2, "integer", unit="1"),
], ids=lambda c: f"{c['operator']}-{c['valueType']}")
def test_compatible_comparison_validates(condition):
    errors = list(VALIDATOR.iter_errors(condition_rule(condition)))
    assert errors == [], [e.message for e in errors]


@pytest.mark.parametrize("condition", [
    pytest.param(comparison(">", 3), id="missing-valueType"),
    pytest.param(comparison("==", {"a": 1}), id="missing-valueType-object-value"),
    pytest.param(comparison(">", "b", "string"), id="ordering-string"),
    pytest.param(comparison("<=", True, "boolean"), id="ordering-boolean"),
    pytest.param(comparison(">=", [1], "number_array"), id="ordering-array"),
    pytest.param(comparison(">", True, "number"), id="number-given-boolean"),
    pytest.param(comparison("==", 2.5, "integer"), id="integer-given-fraction"),
    pytest.param(comparison("==", None, "string"), id="null-value"),
    pytest.param(comparison("==", ["a"], "string_array"), id="equality-array"),
    pytest.param(comparison("in", "a", "string"), id="in-scalar-type"),
    pytest.param(comparison("not_in", 1, "integer"), id="not_in-scalar-type"),
    pytest.param(comparison("in", "a", "string_array"), id="in-non-array-value"),
    pytest.param(comparison("in", [], "string_array"), id="in-empty-array"),
    pytest.param(comparison("in", ["a", "a"], "string_array"), id="in-duplicate-items"),
    pytest.param(comparison("in", ["a", 1], "string_array"), id="in-mixed-items"),
    pytest.param(comparison("contains", True, "boolean"), id="contains-boolean"),
    pytest.param(comparison("contains", ["a"], "string_array"), id="contains-array"),
    pytest.param(comparison("==", "x", "string", unit="m"), id="unit-on-string"),
    pytest.param(comparison("==", True, "boolean", unit="m"), id="unit-on-boolean"),
    pytest.param(comparison("in", ["a"], "string_array", unit="m"), id="unit-on-string-array"),
    pytest.param(comparison(">", 3, "number", unit=""), id="empty-unit"),
    pytest.param(comparison(">", 3, "number", unit="3 m"), id="unit-with-whitespace"),
])
def test_incompatible_comparison_is_rejected(condition):
    assert list(VALIDATOR.iter_errors(condition_rule(condition)))


def test_incompatible_comparison_is_rejected_when_nested():
    nested = {"kind": "any", "conditions": [
        comparison("==", True, "boolean"),
        {"kind": "not", "condition": comparison(">", "tall", "string")},
    ]}
    rule = make_rule(exceptions=[{"kind": "exception", "description": "Nested.", "condition": nested}])
    assert list(VALIDATOR.iter_errors(rule))


@pytest.mark.parametrize("requirement", [
    {"kind": "numeric", "fact": "exits", "operator": ">=", "value": 2, "unit": "1"},
    {"kind": "text", "fact": "material", "operator": "==", "value": "Holz"},
    {"kind": "text", "fact": "fire_class", "operator": "in", "value": ["A1", "A2"]},
    {"kind": "text", "fact": "label", "operator": "contains", "value": "nichtbrennbar"},
], ids=lambda r: f"{r['kind']}-{r['operator']}")
def test_compatible_requirement_validates(requirement):
    errors = list(VALIDATOR.iter_errors(make_rule(requirements=[requirement])))
    assert errors == [], [e.message for e in errors]


@pytest.mark.parametrize("requirement", [
    pytest.param({"kind": "numeric", "fact": "d", "operator": "in", "value": 3, "unit": "m"}, id="numeric-membership-operator"),
    pytest.param({"kind": "numeric", "fact": "d", "operator": ">=", "value": "3", "unit": "m"}, id="numeric-string-value"),
    pytest.param({"kind": "numeric", "fact": "d", "operator": ">=", "value": 3, "unit": " m"}, id="numeric-unit-whitespace"),
    pytest.param({"kind": "text", "fact": "t", "operator": "==", "value": ["a"]}, id="text-equality-array"),
    pytest.param({"kind": "text", "fact": "t", "operator": "==", "value": ""}, id="text-equality-empty"),
    pytest.param({"kind": "text", "fact": "t", "operator": "in", "value": "a"}, id="text-in-string"),
    pytest.param({"kind": "text", "fact": "t", "operator": "in", "value": []}, id="text-in-empty"),
    pytest.param({"kind": "text", "fact": "t", "operator": "in", "value": ["a", "a"]}, id="text-in-duplicates"),
    pytest.param({"kind": "text", "fact": "t", "operator": "in", "value": ["a", 1]}, id="text-in-non-string"),
    pytest.param({"kind": "text", "fact": "t", "operator": "contains", "value": ["a"]}, id="text-contains-array"),
    pytest.param({"kind": "text", "fact": "t", "operator": "equals", "value": "a"}, id="text-legacy-equals"),
    pytest.param({"kind": "text", "fact": "t", "operator": "one_of", "value": ["a"]}, id="text-legacy-one_of"),
])
def test_incompatible_requirement_is_rejected(requirement):
    assert list(VALIDATOR.iter_errors(make_rule(requirements=[requirement])))


# ── Arithmetic expressions and formula semantics ─────────────────────


def literal(value, **extra):
    return {"kind": "literal", "value": value, **extra}


def fact(name, **extra):
    return {"kind": "fact", "name": name, **extra}


def operation(operator, *operands):
    return {"kind": "operation", "operator": operator, "operands": list(operands)}


def formula(expression, operator=">=", unit="m"):
    return {"kind": "formula", "fact": "setback_depth", "operator": operator, "expression": expression, "unit": unit}


@pytest.mark.parametrize("requirement", [
    pytest.param(formula(operation("max", operation("multiply", literal(0.4), fact("wall_height", unit="m")), literal(3, unit="m")), "=="), id="calculated-value"),
    pytest.param(formula(operation("multiply", literal(0.4), fact("wall_height", unit="m")), ">="), id="minimum"),
    pytest.param(formula(operation("multiply", literal(0.5), fact("wall_height", unit="m")), "<="), id="maximum"),
    pytest.param(formula(fact("corridor_width", unit="m"), ">="), id="fact-against-fact"),
    pytest.param(formula(operation("add", fact("a", unit="m"), fact("b", unit="m"), literal(0.5, unit="m"))), id="add-three-operands"),
    pytest.param(formula(operation("subtract", fact("a", unit="m"), literal(1, unit="m"))), id="subtract-two-operands"),
    pytest.param(formula(operation("divide", fact("area", unit="m2"), fact("length", unit="m"))), id="divide-by-fact"),
    pytest.param(formula(operation("divide", fact("h", unit="m"), literal(3))), id="divide-by-nonzero-literal"),
    pytest.param(formula(operation("min", fact("a", unit="m"), fact("b", unit="m"), literal(6, unit="m"))), id="min-three-operands"),
    pytest.param(formula(operation("divide", fact("persons"), literal(60)), unit="1"), id="dimensionless"),
])
def test_valid_formula_validates(requirement):
    errors = list(VALIDATOR.iter_errors(make_rule(requirements=[requirement])))
    assert errors == [], [e.message for e in errors]


_H = fact("wall_height", unit="m")


@pytest.mark.parametrize("requirement", [
    pytest.param({k: v for k, v in formula(operation("multiply", literal(0.4), _H)).items() if k != "operator"}, id="missing-operator"),
    pytest.param({k: v for k, v in formula(operation("multiply", literal(0.4), _H)).items() if k != "unit"}, id="missing-result-unit"),
    pytest.param(formula(operation("multiply", literal(0.4), _H), "in"), id="non-numeric-operator"),
    pytest.param(formula(operation("multiply", literal(0.4), _H), unit="m m"), id="result-unit-whitespace"),
    pytest.param(formula(operation("subtract", _H, literal(1, unit="m"), literal(1, unit="m"))), id="subtract-three-operands"),
    pytest.param(formula(operation("divide", _H, literal(2), literal(2))), id="divide-three-operands"),
    pytest.param(formula(operation("max", _H)), id="single-operand"),
    pytest.param(formula(operation("add")), id="no-operands"),
    pytest.param(formula(operation("power", _H, literal(2))), id="unknown-operator"),
    pytest.param(formula(operation("multiply", literal("0.4"), _H)), id="string-literal"),
    pytest.param(formula(operation("multiply", literal(True), _H)), id="boolean-literal"),
    pytest.param(formula(operation("multiply", literal(0.4), {"kind": "fact"})), id="fact-without-name"),
    pytest.param(formula(operation("multiply", literal(0.4, note="x"), _H)), id="unknown-node-field"),
    pytest.param(formula(operation("multiply", literal(0.4), fact("wall_height", unit="m "))), id="operand-unit-whitespace"),
    pytest.param(formula(operation("divide", _H, literal(0))), id="divide-by-zero"),
    pytest.param(formula(operation("divide", _H, literal(0.0))), id="divide-by-zero-float"),
    pytest.param(formula(operation("max", literal(3, unit="m"), operation("divide", _H, literal(0)))), id="nested-divide-by-zero"),
    pytest.param(formula(literal(3, unit="m")), id="bare-constant"),
    pytest.param(formula(operation("max", literal(3, unit="m"), operation("multiply", literal(2), literal(1, unit="m")))), id="constants-only"),
])
def test_invalid_formula_is_rejected(requirement):
    assert list(VALIDATOR.iter_errors(make_rule(requirements=[requirement])))


def test_zero_divisor_computed_at_runtime_is_not_detected_by_the_schema():
    # Documents a limit: only a literal zero divisor is static. 3 m − 3 m needs a semantic evaluator.
    divisor = operation("subtract", literal(3, unit="m"), literal(3, unit="m"))
    requirement = formula(operation("divide", _H, divisor), unit="1")
    assert list(VALIDATOR.iter_errors(make_rule(requirements=[requirement]))) == []


# ── Temporal relations ───────────────────────────────────────────────


def temporal(relation, **anchors):
    return {"kind": "temporal", "action": "act", "relation": relation, **anchors}


MONTH = {"value": 1, "unit": "month"}


@pytest.mark.parametrize("requirement", [
    pytest.param(temporal("within", startEvent="request", duration=MONTH), id="within"),
    pytest.param(temporal("for_at_least", startEvent="placing on the market", duration={"value": 10, "unit": "year"}), id="for_at_least"),
    pytest.param(temporal("after", startEvent="receipt of documents", duration=MONTH), id="after-offset"),
    pytest.param(temporal("after", startEvent="notification"), id="after-event"),
    pytest.param(temporal("before", endEvent="start of construction"), id="before-event"),
    pytest.param(temporal("before", endEvent="start of construction", duration={"value": 1, "unit": "week"}), id="before-offset"),
    pytest.param(temporal("before", deadline="2027-01-20"), id="before-date"),
    pytest.param(temporal("no_later_than", deadline="2027-01-20"), id="no_later_than-date"),
    pytest.param(temporal("no_later_than", endEvent="hearing", duration={"value": 3, "unit": "day"}), id="no_later_than-offset"),
    pytest.param(temporal("until", endEvent="end of production"), id="until-event"),
    pytest.param(temporal("until", startEvent="placing on the market", endEvent="withdrawal"), id="until-from-event"),
    pytest.param(temporal("until", deadline="2027-01-20"), id="until-date"),
])
def test_valid_temporal_requirement_validates(requirement):
    errors = list(VALIDATOR.iter_errors(make_rule(requirements=[requirement])))
    assert errors == [], [e.message for e in errors]


@pytest.mark.parametrize("requirement", [
    pytest.param(temporal("within", startEvent="request"), id="within-without-duration"),
    pytest.param(temporal("within", startEvent="request", duration=MONTH, endEvent="e"), id="within-with-endEvent"),
    pytest.param(temporal("within", startEvent="request", duration=MONTH, deadline="2027-01-20"), id="within-with-deadline"),
    pytest.param(temporal("for_at_least", duration=MONTH), id="for_at_least-without-startEvent"),
    pytest.param(temporal("after", deadline="2027-01-20"), id="after-with-date-only"),
    pytest.param(temporal("after", startEvent="s", endEvent="e"), id="after-with-endEvent"),
    pytest.param(temporal("before", startEvent="s", duration=MONTH), id="before-counted-from-startEvent"),
    pytest.param(temporal("before", endEvent="e", deadline="2027-01-20"), id="before-two-anchors"),
    pytest.param(temporal("before", deadline="2027-01-20", duration=MONTH), id="before-date-with-duration"),
    pytest.param(temporal("no_later_than"), id="no_later_than-without-anchor"),
    pytest.param(temporal("no_later_than", startEvent="s", duration=MONTH), id="no_later_than-forward-is-within"),
    pytest.param(temporal("until", startEvent="s", duration=MONTH), id="until-with-duration"),
    pytest.param(temporal("until", startEvent="s"), id="until-without-end"),
    pytest.param(temporal("by", deadline="2027-01-20"), id="removed-by-relation"),
    pytest.param(temporal("no_later_than", deadline="2027-13-01"), id="invalid-date"),
    pytest.param(temporal("within", startEvent="s", duration={"value": 0, "unit": "day"}), id="zero-duration"),
    pytest.param(temporal("within", startEvent="s", duration={"value": 2, "unit": "fortnight"}), id="unknown-duration-unit"),
])
def test_invalid_temporal_requirement_is_rejected(requirement):
    assert list(VALIDATOR.iter_errors(make_rule(requirements=[requirement])))


# ── Permissions are not obligations ──────────────────────────────────


def permission_rule(role):
    return make_rule(
        classification={"type": "permission", "summary": "Construction may start one month after receipt."},
        applicability={"actors": [{"role": role, "entity": "Bauherr"}]},
        requirements=[temporal("after", startEvent="receipt of documents", duration=MONTH)],
    )


def test_permission_with_beneficiary_validates():
    assert list(VALIDATOR.iter_errors(permission_rule("beneficiary"))) == []


def test_permission_with_duty_holder_is_rejected():
    assert list(VALIDATOR.iter_errors(permission_rule("duty_holder")))


def _legal_index(document):
    nodes = {}

    def walk(items):
        for node in items or []:
            nodes[node["id"]] = node
            walk(node.get("children"))

    for key in ("frontMatter", "tableOfContents", "structure"):
        walk(document.get(key))
    return nodes, {s["id"]: s for s in document.get("sentences", [])}


def _source_reference_problems(rules, document):
    """Element IDs, pdfPages and sentence IDs of the rules that do not match the Legal JSON document."""
    nodes, sentences = _legal_index(document)
    problems = []

    def check_reference(rule_id, value):
        if isinstance(value, dict):
            if value.get("resolution") != "unresolved" and "elementId" in value and value["elementId"] not in nodes:
                problems.append(f"{rule_id}: unknown elementId {value['elementId']}")
            for child in value.values():
                check_reference(rule_id, child)
        elif isinstance(value, list):
            for child in value:
                check_reference(rule_id, child)

    for rule in rules:
        check_reference(rule["id"], rule)
        for element in rule["source"]["elements"]:
            node = nodes.get(element["elementId"])
            if node is None:
                continue
            if "pdfPages" in element and element["pdfPages"] != node.get("pages"):
                problems.append(f"{rule['id']}: pdfPages {element['pdfPages']} of {node['id']} are {node.get('pages')} in the Legal JSON")
            sentence_id = element.get("sentenceId")
            if sentence_id is None:
                continue
            sentence = sentences.get(sentence_id)
            if sentence is None:
                problems.append(f"{rule['id']}: unknown sentenceId {sentence_id}")
            elif not any(r["elementId"] == node["id"] or r["elementId"].startswith(node["id"] + "/") for r in sentence["ranges"]):
                problems.append(f"{rule['id']}: sentence {sentence_id} does not lie in {node['id']}")
    return problems


@pytest.mark.parametrize("examples, variable", [
    ("mbo.rules.json", "ODOS_MBO_LEGAL_JSON_PATH"),
    ("eu-machinery.rules.json", "ODOS_EU_LEGAL_JSON_PATH"),
])
def test_example_source_references_match_legal_json(examples, variable):
    path = os.environ.get(variable)
    if not path:
        pytest.skip(f"Set {variable} to the Legal JSON 2.0 document of {examples}")
    rules = json.loads((EXAMPLES_DIR / examples).read_text(encoding="utf-8"))["rules"]
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    assert _source_reference_problems(rules, document) == []


def test_source_reference_check_reports_wrong_pages_and_sentences():
    document = {
        "structure": [{"id": "doc/par-1", "pages": [3], "children": [{"id": "doc/par-1/abs-1", "pages": [3]}]}],
        "sentences": [{"id": "doc/par-2/satz-1", "unitId": "doc/par-2", "ranges": [{"elementId": "doc/par-2", "start": 0, "end": 5}]}],
    }
    rule = make_rule(source={"documentId": "d", "elements": [
        {"elementId": "doc/par-1/abs-1", "pdfPages": [4]},
        {"elementId": "doc/par-1", "sentenceId": "doc/par-2/satz-1"},
        {"elementId": "doc/par-9"},
    ]})
    problems = _source_reference_problems([rule], document)
    assert len(problems) == 3, problems


def test_mbo_construction_start_example_is_a_permission_with_earliest_start():
    rules = json.loads((EXAMPLES_DIR / "mbo.rules.json").read_text(encoding="utf-8"))["rules"]
    rule = next(r for r in rules if r["id"] == "mbo-62-3-construction-start-permission")
    assert rule["classification"]["type"] == "permission"
    assert rule["requirementExpression"]["requirement"]["relation"] == "after"