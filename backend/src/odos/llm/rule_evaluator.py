
"""Issue #36: Prototype evaluation of MBO §6(5) setback rules.

Educational, narrowly scoped evaluator. It is NOT a legal compliance
engine. An LLM-generated draft cannot produce a final compliance decision.
"""

import math


def evaluate_expression(expression: dict, facts: dict) -> float:
    """Evaluate the arithmetic expression tree in Rule JSON."""
    kind = expression["kind"]

    if kind == "literal":
        return float(expression["value"])

    if kind == "fact":
        return float(facts[expression["name"]])

    if kind != "operation":
        raise ValueError(f"Unsupported expression kind: {kind}")

    values = [
        evaluate_expression(item, facts)
        for item in expression["operands"]
    ]

    op = expression["operator"]

    if op == "max":
        return max(values)
    if op == "multiply":
        return math.prod(values)
    if op == "add":
        return sum(values)
    if op == "subtract" and len(values) == 2:
        return values[0] - values[1]
    if op == "divide" and len(values) == 2:
        return values[0] / values[1]

    raise ValueError(f"Unsupported operator: {op}")


def evaluate_building(rule: dict, building: dict) -> dict:
    """Compare a synthetic building with the extracted MBO rule.

    Required building facts:
        actual_setback_m: numeric
        measure_h_m: numeric
        zone: general | commercial | industrial
        residential: boolean
        building_class: integer
        storeys: integer
        statutory_override: True | False | None

    statutory_override=False must mean a human has checked that no
    relevant local statute overrides the ordinary reference rule.
    """

    source = rule.get("source", {})
    base = {
        "ruleId": rule.get("id"),
        "source": source.get("citation"),
        "reviewStatus": rule.get("review", {}).get("status", "unknown"),
        "status": "NEEDS_REVIEW",
        "technicalResult": None,
        "requiredDepthM": None,
    }

    required_fields = (
        "actual_setback_m", "measure_h_m", "zone",
        "residential", "building_class", "storeys",
        "statutory_override",
    )

    missing = [name for name in required_fields if name not in building]
    if missing:
        return {**base, "reason": f"Missing facts: {', '.join(missing)}"}

    if building["statutory_override"] is not False:
        return {
            **base,
            "reason": "Statutory applicability is unresolved or overrides the rule.",
        }

    if (type(building["residential"]) is not bool
            or type(building["building_class"]) is not int
            or type(building["storeys"]) is not int):
        return {**base, "reason": "Invalid building classification facts."}

    if building["zone"] not in ("general", "commercial", "industrial"):
        return {**base, "reason": "Unsupported zone."}

    try:
        h = float(building["measure_h_m"])
        actual = float(building["actual_setback_m"])
    except (TypeError, ValueError):
        return {**base, "reason": "Invalid numeric values."}

    if not all(math.isfinite(v) for v in (h, actual)) or h < 0 or actual < 0:
        return {**base, "reason": "Height and setback must be finite and nonnegative."}

    # This limited example does not resolve overlap between special
    # residential conditions and commercial/industrial zoning.
    residential_case = (
        building["residential"]
        and building["building_class"] in (1, 2)
        and 0 <= building["storeys"] <= 3
    )

    if residential_case and building["zone"] != "general":
        return {**base, "reason": "Overlapping special-case rules require review."}

    try:
        if residential_case:
            # Find the residential alternative in the generated draft.
            candidates = [
                exception for exception in rule.get("exceptions", [])
                if exception.get("kind") == "alternative"
                and exception.get("condition", {}).get("kind") == "all"
            ]
            if len(candidates) != 1:
                raise ValueError("Residential alternative is missing or ambiguous")
            requirement = candidates[0]["requirements"][0]
            required = float(requirement["value"])
            scenario = "residential"

        elif building["zone"] in ("commercial", "industrial"):
            candidates = [
                exception for exception in rule.get("exceptions", [])
                if exception.get("kind") == "alternative"
                and exception.get("condition", {}).get("fact") == "building_zone"
            ]
            if len(candidates) != 1:
                raise ValueError("Commercial alternative is missing or ambiguous")
            requirement = candidates[0]["requirements"][0]
            required = evaluate_expression(
                requirement["expression"], {"measure_h": h}
            )
            scenario = "commercial_industrial"

        else:
            requirement = rule["requirements"][0]
            required = evaluate_expression(
                requirement["expression"], {"measure_h": h}
            )
            scenario = "general"

        if not math.isfinite(required) or required < 0:
            raise ValueError("Invalid calculated depth")

    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError) as exc:
        return {**base, "reason": f"Cannot evaluate extracted rule: {exc}"}

    technical = "PASS" if actual + 1e-9 >= required else "FAIL"

    return {
        **base,
        "scenario": scenario,
        "requiredDepthM": required,
        "actualDepthM": actual,
        "technicalResult": technical,
        "reason": (
            "Technical comparison only. The LLM rule remains a draft; "
            "its applicability and legal interpretation require approval."
        ),
    }
