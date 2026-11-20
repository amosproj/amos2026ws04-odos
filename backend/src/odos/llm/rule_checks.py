"""Deterministic quality checks for model-proposed Rule JSON records, independent of the document type.

They complement the JSON Schema (which checks shape) with checks the schema cannot express:

* fact identifiers: English ASCII snake_case with an optional dotted entity prefix. camelCase and upper case are
  converted losslessly (`controlSystem.withstandsX` -> `control_system.withstands_x`); anything else (umlauts, spaces,
  symbols) cannot be translated mechanically and rejects the record;
* references to the record's own primary source element are removed (a provision does not cross-reference itself);
* units: angle facts need an angle unit; operands of add/subtract/min/max and a formula's result share one unit;
* several lower (or upper) bounds on the same fact inside one `all` are flagged: usually a determined value
  ("0.4 H, at least 3 m" is `== max(...)`) that was split into bounds;
* with the document language (`odos.llm.terminology`): identifiers whose words are all known terms are translated
  (`gebaeudeklasse` -> `building_class`); identifiers that still contain words of that language are flagged;
* a period in days/weeks/months/years written as a number is flagged (it is a `temporal` requirement with a start event);
  so is an exception that changes the operator of the fact it modifies, and numbers compared as strings;
* across records: exact duplicates are rejected; a record that repeats an exception of another record, two records
  that put different operators on the same fact from the same sentence, one fact with several value types or units,
  identifiers that differ only in underscores, and one actor written in several ways are flagged.

A flag is written to `review.ambiguities` (prefix `FLAG_PREFIX`) so a reviewer sees it next to the rule; the record
stays a schema-valid draft.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from odos.llm.terminology import foreign_words, translate_fact

FLAG_PREFIX = "ODOS check: "
FACT_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*(?:\.[a-z][a-z0-9]*(?:_[a-z0-9]+)*)*$")
ANGLE_WORDS = re.compile(r"(?:^|[._])(angle|slope|pitch|inclination|tilt)(?:$|[._])")
ANGLE_UNITS = {"deg", "rad", "%", "'", "''"}
SAME_UNIT_OPERATORS = {"add", "subtract", "min", "max"}
LOWER, UPPER = {">=", ">"}, {"<=", "<"}
PERIOD_UNITS = {"a", "year", "years", "mo", "month", "months", "wk", "week", "weeks", "d", "day", "days"}


@dataclass
class RuleCheck:
    errors: list[str] = field(default_factory=list)  # reject the record
    flags: list[str] = field(default_factory=list)  # keep the record, flag it for review
    renamed: dict[str, str] = field(default_factory=dict)  # fact identifier -> normalized identifier
    translated: dict[str, str] = field(default_factory=dict)  # fact identifier -> English translation (subset of renamed)
    self_references_removed: int = 0


# ── fact identifiers ──────────────────────────────────────────────────────────────────────────────────────────────────


def _fact_slots(node) -> Iterator[tuple[dict, str]]:
    """Every (dict, key) that holds a fact identifier: `fact` of predicates/requirements/mappings, `name` of
    arithmetic fact nodes."""
    if isinstance(node, dict):
        if isinstance(node.get("fact"), str):
            yield node, "fact"
        if node.get("kind") == "fact" and isinstance(node.get("name"), str):
            yield node, "name"
        for value in node.values():
            yield from _fact_slots(value)
    elif isinstance(node, list):
        for item in node:
            yield from _fact_slots(item)


def normalize_fact(name: str) -> str:
    """camelCase/PascalCase/kebab-case/spaces -> snake_case per dotted segment; already valid names are unchanged."""
    segments = []
    for segment in name.strip().split("."):
        s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", segment)
        s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
        s = re.sub(r"[\s\-]+", "_", s).lower()
        segments.append(re.sub(r"_+", "_", s).strip("_"))
    return ".".join(segments)


def facts_of(rule: dict) -> list[str]:
    return [slot[key] for slot, key in _fact_slots(rule)]


def check_fact_identifiers(rule: dict, result: RuleCheck, language: str | None = None) -> None:
    """Normalize the identifiers in place; an identifier that is still not valid is an error.

    With the document's `language`: an identifier whose words are all known terms of that language is translated
    (`gebaeudeklasse` -> `building_class`, `höhe` -> `height`); one that still contains recognisably foreign words
    (a transliteration such as `abweichende_..._zulaessig`) is flagged, not translated halfway."""
    flagged: set[str] = set()
    for slot, key in _fact_slots(rule):
        original = slot[key]
        normalized = normalize_fact(original) if original.isascii() else original
        translated = translate_fact(normalized, language)
        if translated:
            result.translated[original] = translated
            normalized = translated
        if not FACT_PATTERN.match(normalized):
            result.errors.append(f"fact {original!r} is not an English ASCII snake_case identifier")
            continue
        if normalized != original:
            slot[key] = normalized
            result.renamed[original] = normalized
        foreign = foreign_words(normalized, language)
        if foreign and normalized not in flagged:
            flagged.add(normalized)
            result.flags.append(f"fact {normalized!r} is not English (words {foreign}); translate the meaning, a "
                                "transliteration is not an English identifier.")


# ── references ────────────────────────────────────────────────────────────────────────────────────────────────────────


def remove_self_references(rule: dict) -> int:
    """Drop references whose `elementId` is one of the record's own primary source elements (an element listed with
    role `cross_reference`, `context` or `definition` may legitimately be referenced too). Returns how many were removed."""
    own = {e.get("elementId") for e in rule.get("source", {}).get("elements", [])
           if isinstance(e, dict) and e.get("role", "primary") == "primary"}
    removed = 0
    holders = [rule, *[e for e in rule.get("exceptions", []) if isinstance(e, dict)]]
    for holder in holders:
        refs = holder.get("references")
        if not isinstance(refs, list):
            continue
        kept = [r for r in refs if not (isinstance(r, dict) and r.get("elementId") in own)]
        removed += len(refs) - len(kept)
        if kept:
            holder["references"] = kept
        else:
            holder.pop("references", None)
    return removed


# ── units and formulas ────────────────────────────────────────────────────────────────────────────────────────────────


def _walk(node) -> Iterator[dict]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _operand_units(operation: dict) -> set[str]:
    """The explicit units of an operation's direct operands (nested operations count with their common unit)."""
    units = set()
    for operand in operation.get("operands", []):
        if not isinstance(operand, dict):
            continue
        if operand.get("kind") in ("fact", "literal") and operand.get("unit"):
            units.add(operand["unit"])
        elif operand.get("kind") == "operation" and operand.get("operator") in SAME_UNIT_OPERATORS:
            inner = _operand_units(operand)
            if len(inner) == 1:
                units |= inner
    return units


def check_units(rule: dict, result: RuleCheck) -> None:
    for node in _walk(rule):
        fact = node.get("fact") if isinstance(node.get("fact"), str) else node.get("name") if node.get("kind") == "fact" else None
        unit = node.get("unit")
        if isinstance(fact, str) and unit and ANGLE_WORDS.search(fact) and unit not in ANGLE_UNITS:
            result.flags.append(f"{fact!r} looks like an angle but has unit {unit!r} (expected 'deg', 'rad' or '%').")
        if node.get("kind") == "operation" and node.get("operator") in SAME_UNIT_OPERATORS:
            units = _operand_units(node)
            if len(units) > 1:
                result.flags.append(f"'{node['operator']}' combines different units {sorted(units)}; check the formula.")
        if node.get("kind") == "formula" and isinstance(node.get("expression"), dict):
            expression = node["expression"]
            if expression.get("kind") == "operation" and expression.get("operator") in SAME_UNIT_OPERATORS:
                units = _operand_units(expression)
                if len(units) == 1 and unit and unit not in units:
                    result.flags.append(f"formula for {node.get('fact')!r} has unit {unit!r} but its operands are in {units.pop()!r}.")


def check_split_bounds(rule: dict, result: RuleCheck) -> None:
    """Several lower (or upper) bounds on one fact inside an `all`: usually a determined value split into bounds."""
    for node in _walk(rule):
        if node.get("kind") != "all" or not isinstance(node.get("requirements"), list):
            continue
        bounds: dict[tuple[str, str], int] = {}
        for item in node["requirements"]:
            req = item.get("requirement") if isinstance(item, dict) and item.get("kind") == "requirement" else None
            if not isinstance(req, dict) or not isinstance(req.get("fact"), str):
                continue
            side = "lower" if req.get("operator") in LOWER else "upper" if req.get("operator") in UPPER else None
            if side:
                bounds[(req["fact"], side)] = bounds.get((req["fact"], side), 0) + 1
        for (fact, side), count in bounds.items():
            if count > 1:
                fn = "max" if side == "lower" else "min"
                result.flags.append(
                    f"{count} {side} bounds on {fact!r} in one 'all'. If the text states a determined value "
                    f"(e.g. 'X, at least Y'), it is one formula '== {fn}(...)', not several bounds.")


def check_periods_as_numbers(rule: dict, result: RuleCheck) -> None:
    """A period in days, weeks, months or years as a plain number (`retention_period >= 10 year`) loses its start
    event; it is a `temporal` requirement. Short technical durations (s, min, h) are often properties and pass."""
    for node in _walk(rule):
        if node.get("kind") in ("numeric", "comparison") and node.get("unit") in PERIOD_UNITS and isinstance(node.get("fact"), str):
            result.flags.append(
                f"{node['fact']!r} is a period of {node.get('value')} {node['unit']} written as a number: the event it is "
                "counted from (or the deadline) is lost. Use a 'temporal' requirement (relation, duration, startEvent/endEvent or deadline).")


def check_alternative_operators(rule: dict, result: RuleCheck) -> None:
    """An alternative or exception that sets a value for a fact of the rule keeps the rule's operator unless the text
    says otherwise (a determined value `==` relaxed to `>=` changes the meaning, not only the value)."""
    main = _operators_by_fact(rule)
    for exception in rule.get("exceptions", []) if isinstance(rule.get("exceptions"), list) else []:
        if not isinstance(exception, dict):
            continue
        for node in _walk(exception.get("requirements")):
            fact, operator = node.get("fact"), node.get("operator")
            if node.get("kind") in ("numeric", "formula") and fact in main and operator and operator not in main[fact]:
                result.flags.append(
                    f"the {exception.get('kind', 'exception')} sets {fact!r} with operator {operator!r} but the rule uses "
                    f"{sorted(main[fact])}; keep the operator of the rule it changes unless the text states another one.")


def check_numeric_strings(rule: dict, result: RuleCheck) -> None:
    """Numbers compared as strings (`["1", "2"]` for building classes 1 and 2) are not numbers to a checker."""
    for node in _walk(rule):
        if node.get("kind") == "comparison" and node.get("valueType") in ("string", "string_array"):
            values = node.get("value") if isinstance(node.get("value"), list) else [node.get("value")]
            if values and all(isinstance(v, str) and re.fullmatch(r"-?\d+(?:\.\d+)?", v) for v in values):
                result.flags.append(f"{node.get('fact')!r} compares numbers as strings {values}; use 'integer'/'number' values.")


def check_rule(rule: dict, language: str | None = None) -> RuleCheck:
    """All single-record checks; normalizes (and, with the document `language`, translates) fact identifiers and removes
    self-references in place."""
    result = RuleCheck()
    check_fact_identifiers(rule, result, language)
    result.self_references_removed = remove_self_references(rule)
    check_units(rule, result)
    check_split_bounds(rule, result)
    check_periods_as_numbers(rule, result)
    check_alternative_operators(rule, result)
    check_numeric_strings(rule, result)
    return result


def add_flags(rule: dict, flags: list[str]) -> None:
    if not flags:
        return
    review = rule.setdefault("review", {"status": "draft"})
    existing = review.get("ambiguities") if isinstance(review.get("ambiguities"), list) else []
    review["ambiguities"] = existing + [FLAG_PREFIX + f for f in flags if FLAG_PREFIX + f not in existing]


# ── across records ────────────────────────────────────────────────────────────────────────────────────────────────────

_VOLATILE = ("id", "review")


def _content_key(rule: dict) -> str:
    """The record without id and review notes, with descriptions removed: two records with the same key say the same."""
    body = copy.deepcopy({k: v for k, v in rule.items() if k not in _VOLATILE})
    for node in _walk(body):
        node.pop("description", None)
    return json.dumps(_unordered(body), sort_keys=True, ensure_ascii=False)


def _sentences(rule: dict) -> set[tuple[str, str | None]]:
    return {(e["elementId"], e.get("sentenceId")) for e in rule.get("source", {}).get("elements", [])
            if isinstance(e, dict) and isinstance(e.get("elementId"), str)}


def _elements(rule: dict) -> set[str]:
    return {element for element, _ in _sentences(rule)}


def _unordered(node):
    """The node with the members of `all`/`any` sorted: their order carries no meaning."""
    if isinstance(node, list):
        return [_unordered(item) for item in node]
    if not isinstance(node, dict):
        return node
    out = {k: _unordered(v) for k, v in node.items()}
    if out.get("kind") in ("all", "any"):
        for key in ("conditions", "requirements"):
            if isinstance(out.get(key), list):
                out[key] = sorted(out[key], key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False))
    return out


def _canonical(node) -> str | None:
    return json.dumps(_unordered(node), sort_keys=True, ensure_ascii=False) if node else None


def _operators_by_fact(rule: dict) -> dict[str, set[str]]:
    """Operators of the rule's own requirements (not of exceptions) per fact."""
    out: dict[str, set[str]] = {}
    parts = [rule.get("requirements"), rule.get("requirementExpression")]
    for node in _walk(parts):
        if node.get("kind") in ("numeric", "formula", "text") and isinstance(node.get("fact"), str) and node.get("operator"):
            out.setdefault(node["fact"], set()).add(node["operator"])
    return out


def check_rule_set(rules: list[dict]) -> tuple[list[dict], list[tuple[dict, str]], dict[str, list[str]]]:
    """(kept records, [(duplicate record, reason)], {rule id: flags}). The first of identical records is kept."""
    kept: list[dict] = []
    duplicates: list[tuple[dict, str]] = []
    seen: dict[str, str] = {}
    for rule in rules:
        key = _content_key(rule)
        if key in seen:
            duplicates.append((rule, f"duplicate of rule {seen[key]!r}"))
            continue
        seen[key] = rule["id"]
        kept.append(rule)

    flags: dict[str, list[str]] = {}
    for rule in kept:
        conditions = _canonical(rule.get("applicability", {}).get("conditions"))
        for other in kept:
            if other is rule or not (_elements(rule) & _elements(other)):
                continue
            for exception in other.get("exceptions", []):
                if conditions and isinstance(exception, dict) and _canonical(exception.get("condition")) == conditions:
                    flags.setdefault(rule["id"], []).append(
                        f"repeats an exception of rule {other['id']!r} (same condition, same source element); "
                        "keep it in one place.")
    for i, rule in enumerate(kept):
        for other in kept[i + 1:]:
            if not (_sentences(rule) & _sentences(other)):
                continue
            mine, theirs = _operators_by_fact(rule), _operators_by_fact(other)
            for fact in sorted(set(mine) & set(theirs)):
                if mine[fact] != theirs[fact] and not (rule.get("applicability", {}).get("conditions") or other.get("applicability", {}).get("conditions")):
                    note = (f"{fact!r} has operator {sorted(mine[fact])} here and {sorted(theirs[fact])} in rule "
                            f"{other['id']!r} from the same sentence; check which one the text states.")
                    flags.setdefault(rule["id"], []).append(note)
    for rule_id, notes in [*_fact_consistency(kept), *_actor_consistency(kept)]:
        flags.setdefault(rule_id, []).extend(n for n in notes if n not in flags.get(rule_id, []))
    return kept, duplicates, flags


# ── consistency across records: value types, units, actor names ───────────────────────────────────────────────────────

_BASE_TYPE = {"string": "string", "integer": "number", "number": "number", "boolean": "boolean"}
_REQUIREMENT_TYPE = {"numeric": "number", "formula": "number", "boolean": "boolean", "text": "string"}


def _fact_usage(rule: dict) -> Iterator[tuple[str, str | None, str | None]]:
    """(fact, base value type, unit) of every comparison and requirement in the record."""
    for node in _walk(rule):
        fact = node.get("fact")
        if not isinstance(fact, str):
            continue
        if node.get("kind") == "comparison":
            base = _BASE_TYPE.get(str(node.get("valueType", "")).removesuffix("_array"))
            yield fact, base, node.get("unit")
        elif node.get("kind") in _REQUIREMENT_TYPE:
            yield fact, _REQUIREMENT_TYPE[node["kind"]], node.get("unit")


def _fact_consistency(rules: list[dict]) -> list[tuple[str, list[str]]]:
    """The same fact with different value types or units in different places; two identifiers that differ only in
    underscores (`building_class` / `buildingclass`)."""
    types: dict[str, dict[str, set[str]]] = {}
    units: dict[str, dict[str, set[str]]] = {}
    spellings: dict[str, set[str]] = {}
    for rule in rules:
        for fact, base, unit in _fact_usage(rule):
            if base:
                types.setdefault(fact, {}).setdefault(base, set()).add(rule["id"])
            if unit:
                units.setdefault(fact, {}).setdefault(unit, set()).add(rule["id"])
            spellings.setdefault(fact.replace("_", ""), set()).add(fact)
    out: list[tuple[str, list[str]]] = []
    for fact, by_type in types.items():
        if len(by_type) > 1:
            note = f"{fact!r} is used with different value types {sorted(by_type)}; one fact has one type."
            out += [(rid, [note]) for rids in by_type.values() for rid in sorted(rids)]
    for fact, by_unit in units.items():
        if len(by_unit) > 1:
            note = f"{fact!r} is used with different units {sorted(by_unit)}; one fact has one unit."
            out += [(rid, [note]) for rids in by_unit.values() for rid in sorted(rids)]
    for names in spellings.values():
        if len(names) > 1:
            note = f"fact identifiers {sorted(names)} differ only in underscores; use one identifier for one concept."
            out += [(rule["id"], [note]) for rule in rules if names & set(facts_of(rule))]
    return out


_ARTICLES = {"der", "die", "das", "den", "dem", "des", "the", "a", "an", "le", "la", "les"}


def _actor_key(entity: str) -> tuple[str, ...]:
    """Case, articles and plural/case endings ignored: `Zuständige nationale Behörde` ~ `zuständige nationale Behörden`."""
    words = [w for w in re.findall(r"\w+", entity.casefold()) if w not in _ARTICLES]
    return tuple(re.sub(r"(?:en|n|e|s|er)$", "", w) if len(w) > 4 else w for w in words)


def _actor_consistency(rules: list[dict]) -> list[tuple[str, list[str]]]:
    """One actor written in several ways makes `actors` useless as a filter. Exact variants (case, articles, endings)
    are flagged with the most frequent spelling; a name that extends another (`... Behörden der Mitgliedstaaten`) is
    flagged as possibly the same actor."""
    uses: dict[str, list[str]] = {}
    for rule in rules:
        for actor in rule.get("applicability", {}).get("actors", []) if isinstance(rule.get("applicability"), dict) else []:
            if isinstance(actor, dict) and isinstance(actor.get("entity"), str):
                uses.setdefault(actor["entity"], []).append(rule["id"])
    by_key: dict[tuple[str, ...], list[str]] = {}
    for entity in uses:
        by_key.setdefault(_actor_key(entity), []).append(entity)
    out: list[tuple[str, list[str]]] = []
    for names in by_key.values():
        if len(names) > 1:
            preferred = max(names, key=lambda n: (len(uses[n]), n))
            for name in names:
                if name != preferred:
                    note = f"actor {name!r} is also written {preferred!r} in other records; name one actor the same way everywhere."
                    out += [(rid, [note]) for rid in uses[name]]
    keys = list(by_key)
    for short in keys:
        for long in keys:
            if short and len(long) > len(short) and long[:len(short)] == short:
                for name in by_key[long]:
                    note = (f"actor {name!r} extends {by_key[short][0]!r} used in other records; if it is the same actor, "
                            "name it the same way.")
                    out += [(rid, [note]) for rid in uses[name]]
    return out
