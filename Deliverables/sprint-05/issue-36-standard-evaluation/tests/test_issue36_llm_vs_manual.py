
"""Issue #36: Compare LLM-generated MBO formulas with hand-written references.

This evaluates a limited, synthetic example of MBO §6(5).
It is not a legal compliance decision.
"""

import json
from pathlib import Path

import pytest


BACKEND = Path(__file__).resolve().parents[1]
SAMPLE = Path(__file__).resolve().parents[1] / "fixtures" / "mbo-6-5.rules.json"


def load_rule():
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    assert len(data["rules"]) == 1
    return data["rules"][0]


def evaluate_expression(expression, facts):
    """Evaluate supported arithmetic expressions from Rule JSON."""
    kind = expression["kind"]

    if kind == "literal":
        return expression["value"]

    if kind == "fact":
        return facts[expression["name"]]

    if kind != "operation":
        raise ValueError(f"Unsupported expression kind: {kind}")

    values = [
        evaluate_expression(item, facts)
        for item in expression["operands"]
    ]

    operator = expression["operator"]

    if operator == "max":
        return max(values)
    if operator == "multiply":
        result = 1
        for value in values:
            result *= value
        return result
    if operator == "add":
        return sum(values)
    if operator == "subtract" and len(values) == 2:
        return values[0] - values[1]
    if operator == "divide" and len(values) == 2:
        return values[0] / values[1]

    raise ValueError(f"Unsupported arithmetic operator: {operator}")


def manual_general(height):
    """Independent reference for the general case."""
    return max(0.4 * height, 3.0)


def manual_commercial(height):
    """Independent reference for the commercial/industrial case."""
    return max(0.2 * height, 3.0)


def llm_general(height):
    rule = load_rule()
    requirement = rule["requirements"][0]
    assert requirement["kind"] == "formula"

    return evaluate_expression(
        requirement["expression"],
        {"measure_h": height},
    )


def llm_commercial(height):
    rule = load_rule()

    exception = next(
        item for item in rule["exceptions"]
        if item.get("condition", {}).get("fact") == "building_zone"
    )

    requirement = exception["requirements"][0]

    return evaluate_expression(
        requirement["expression"],
        {"measure_h": height},
    )


@pytest.mark.parametrize("height", [2, 5, 10, 20, 30])
def test_general_formula_matches_manual_reference(height):
    assert llm_general(height) == pytest.approx(
        manual_general(height)
    )


@pytest.mark.parametrize("height", [2, 5, 10, 20, 30])
def test_commercial_formula_matches_manual_reference(height):
    assert llm_commercial(height) == pytest.approx(
        manual_commercial(height)
    )


def test_residential_exception_has_required_conditions():
    rule = load_rule()

    residential = next(
        item for item in rule["exceptions"]
        if item["kind"] == "alternative"
        and item["condition"].get("kind") == "all"
    )

    predicates = {
        item["fact"]: item
        for item in residential["condition"]["conditions"]
    }

    assert predicates["building.use_type"]["value"] == "residential_building"
    assert predicates["building.building_class"]["value"] == [1, 2]
    assert predicates["building.above_ground_storey_count"]["operator"] == "<="
    assert predicates["building.above_ground_storey_count"]["value"] == 3

    requirement = residential["requirements"][0]
    assert requirement["value"] == 3
    assert requirement["unit"] == "m"


def test_statutory_exception_is_preserved():
    rule = load_rule()

    exceptions = [
        item for item in rule["exceptions"]
        if item["effect"] == "disapplies_rule"
    ]

    assert len(exceptions) >= 1
    assert any(
        reference.get("resolution") == "unresolved"
        for item in exceptions
        for reference in item.get("references", [])
    )


def test_llm_output_stays_draft():
    rule = load_rule()
    assert rule["review"]["status"] == "draft"


def test_main_operator_semantics_are_recorded():
    """Document the semantic issue without rewriting the original output."""
    rule = load_rule()

    # '==' describes the calculated prescribed depth.
    # It must not automatically mean actual setback == prescribed depth.
    assert rule["requirements"][0]["operator"] == "=="
    assert rule["requirements"][0]["fact"] == "setback_area_depth"

def test_incorrect_llm_formula_is_detected():
    """An incorrect LLM coefficient must disagree with the reference."""
    import copy

    original = load_rule()
    incorrect = copy.deepcopy(original)

    # Change the LLM coefficient from 0.4 to 0.5.
    incorrect["requirements"][0]["expression"]["operands"][0][
        "operands"
    ][0]["value"] = 0.5

    calculated = evaluate_expression(
        incorrect["requirements"][0]["expression"],
        {"measure_h": 10},
    )

    reference = manual_general(10)

    assert calculated == pytest.approx(5.0)
    assert reference == pytest.approx(4.0)
    assert calculated != pytest.approx(reference)
