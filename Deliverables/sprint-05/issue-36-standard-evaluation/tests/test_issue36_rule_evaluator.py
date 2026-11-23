
"""Tests for the Issue #36 prototype evaluator."""

import json
from pathlib import Path

import pytest

from odos.llm.rule_evaluator import evaluate_building


SAMPLE = SAMPLE = Path(__file__).resolve().parent / "fixtures" / "mbo-6-5.rules.json"


@pytest.fixture
def rule():
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    return data["rules"][0]


def building(**overrides):
    facts = {
        "actual_setback_m": 4.5,
        "measure_h_m": 10,
        "zone": "general",
        "residential": False,
        "building_class": 3,
        "storeys": 4,
        "statutory_override": False,
    }
    facts.update(overrides)
    return facts


@pytest.mark.parametrize(
    "facts, expected_depth, expected_result",
    [
        ({}, 4.0, "PASS"),
        ({"actual_setback_m": 3.5}, 4.0, "FAIL"),
        ({"actual_setback_m": 4.0}, 4.0, "PASS"),
        (
            {"zone": "industrial", "measure_h_m": 20,
             "actual_setback_m": 4.5},
            4.0, "PASS",
        ),
        (
            {"zone": "commercial", "measure_h_m": 20,
             "actual_setback_m": 3.5},
            4.0, "FAIL",
        ),
        (
            {"residential": True, "building_class": 2,
             "storeys": 3, "actual_setback_m": 3.0},
            3.0, "PASS",
        ),
        (
            {"residential": True, "building_class": 2,
             "storeys": 4, "actual_setback_m": 3.0},
            4.0, "FAIL",
        ),
    ],
)
def test_scenario_calculation(rule, facts, expected_depth, expected_result):
    result = evaluate_building(rule, building(**facts))

    assert result["requiredDepthM"] == pytest.approx(expected_depth)
    assert result["technicalResult"] == expected_result

    # Draft LLM rules are never final compliance decisions.
    assert result["status"] == "NEEDS_REVIEW"


def test_unknown_statutory_applicability(rule):
    result = evaluate_building(
        rule, building(statutory_override=None)
    )

    assert result["status"] == "NEEDS_REVIEW"
    assert result["technicalResult"] is None


def test_statutory_override(rule):
    result = evaluate_building(
        rule, building(statutory_override=True)
    )

    assert result["status"] == "NEEDS_REVIEW"
    assert result["technicalResult"] is None


def test_missing_information(rule):
    facts = building()
    del facts["measure_h_m"]

    result = evaluate_building(rule, facts)

    assert result["status"] == "NEEDS_REVIEW"
    assert "measure_h_m" in result["reason"]


def test_overlapping_special_cases_require_review(rule):
    result = evaluate_building(
        rule,
        building(
            zone="industrial",
            residential=True,
            building_class=2,
            storeys=2,
        ),
    )

    assert result["technicalResult"] is None
    assert result["status"] == "NEEDS_REVIEW"
