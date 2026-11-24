
import json
from pathlib import Path


def load_generated_rules():
    path = Path(__file__).resolve().parents[1] / "fixtures" / "mbo-6-5.rules.json"

    with path.open(encoding="utf-8") as file:
        return json.load(file)


def test_one_rule_was_generated():
    data = load_generated_rules()

    assert len(data["rules"]) == 1


def test_generated_rule_has_correct_source():
    data = load_generated_rules()

    rule = data["rules"][0]

    assert rule["source"]["citation"] == "§ 6 Abs. 5 Satz 1"

    source_ids = {
        item["sentenceId"]
        for item in rule["source"]["elements"]
    }

    assert len(source_ids) == 4


def test_generated_rule_requires_human_review():
    data = load_generated_rules()

    assert data["_generation"]["review"]["status"] == "draft"
    assert data["_generation"]["review"]["humanReviewRequired"] is True


def test_main_formula_is_structured():
    data = load_generated_rules()

    rule = data["rules"][0]
    formula = rule["requirements"][0]["expression"]

    assert formula["kind"] == "operation"
    assert formula["operator"] == "max"

    operands = formula["operands"]

    assert operands[0]["operator"] == "multiply"
    assert operands[0]["operands"][0]["value"] == 0.4
    assert operands[1]["value"] == 3


def test_exceptions_are_preserved():
    data = load_generated_rules()

    rule = data["rules"][0]

    assert len(rule["exceptions"]) == 3

    assert any(
        "Gewerbe- und Industriegebieten" in item["description"]
        for item in rule["exceptions"]
    )
