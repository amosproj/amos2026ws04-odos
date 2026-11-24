"""Schema-aware repair of model-proposed Rule JSON records: only repairs whose result is unambiguous.

The model sometimes writes a record that is right in substance but breaks the schema in form: a `description` on a
predicate (which has none), `"3"` for the number 3, `"Obligation"` for the enum value `obligation`, `"years"` for the
duration unit `year`, `m²` for the unit `m2`. Rejecting such a record loses a valid rule. `repair_rule` walks the
record along the Rule JSON schema itself (no hard-coded paths, so it follows schema changes) and applies only these
repairs:

* a property the schema does not allow at that place is removed if it is a pure annotation (`ANNOTATION_KEYS`, string
  value): it carries no logic. Its text is kept in the repair log, which is written to `review.ambiguities`;
* a string where the schema wants a number/integer/boolean is converted if it is exactly a number (`"3"`, `"0.4"`) or
  `true`/`false`;
* an enum value is mapped to the one enum value that equals it after case/space/hyphen folding, or (for plurals) after
  removing a final `s` (`"For at least"` -> `for_at_least`, `"years"` -> `year`);
* a unit with superscripts or a degree sign is rewritten (`m²` -> `m2`, `°` -> `deg`);
* a comparison without `valueType` gets the type of its value if that type is unique (bool, int, float, str, or a
  homogeneous list of them).

Everything else (missing required fields, a property that is not an annotation, a choice between several schema
branches) is left alone: the record is then rejected and kept as a candidate for review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ANNOTATION_KEYS = frozenset({"description", "note", "notes", "comment", "comments", "explanation", "rationale", "remark"})
SUPERSCRIPTS = (("²", "2"), ("³", "3"))
UNIT_NAMES = {"°": "deg", "grad": "deg", "degree": "deg", "degrees": "deg", "°c": "Cel", "° c": "Cel"}
NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")


@dataclass(frozen=True)
class Repair:
    path: str
    detail: str

    def __str__(self) -> str:
        return f"{self.path or '(record)'}: {self.detail}"


class _Walker:
    def __init__(self, schema: dict):
        self.defs = schema.get("$defs", {})
        self.root = schema
        self.repairs: list[Repair] = []

    def resolve(self, sub: dict) -> dict:
        seen = 0
        while isinstance(sub, dict) and "$ref" in sub and seen < 20:
            name = sub["$ref"].rsplit("/", 1)[-1]
            sub = self.defs.get(name, {}) if sub["$ref"].startswith("#/$defs/") else self.root
            seen += 1
        return sub if isinstance(sub, dict) else {}

    def _branch_for(self, node, branches: list[dict]) -> dict | None:
        """The one branch of a oneOf/anyOf whose `kind` matches the node's `kind`; None if not exactly one."""
        if not isinstance(node, dict) or not isinstance(node.get("kind"), str):
            return None
        matches = []
        for branch in (self.resolve(b) for b in branches):
            kind = branch.get("properties", {}).get("kind", {})
            if kind.get("const") == node["kind"] or node["kind"] in kind.get("enum", ()):
                matches.append(branch)
        return matches[0] if len(matches) == 1 else None

    def walk(self, node, sub: dict, path: str):
        """Returns the (possibly replaced) node."""
        sub = self.resolve(sub)
        for key in ("oneOf", "anyOf"):
            if key in sub:
                branch = self._branch_for(node, sub[key])
                if branch is not None:
                    node = self.walk(node, branch, path)
        for part in sub.get("allOf", []):
            part = self.resolve(part)
            if any(k in part for k in ("properties", "oneOf", "anyOf", "items", "type", "enum")) and "if" not in part:
                node = self.walk(node, part, path)
        node = self._scalar(node, sub, path)
        if isinstance(node, dict) and isinstance(sub.get("properties"), dict):
            self._object(node, sub, path)
        elif isinstance(node, list) and isinstance(sub.get("items"), dict):
            for i, item in enumerate(node):
                node[i] = self.walk(item, sub["items"], f"{path}/{i}")
        return node

    def _object(self, node: dict, sub: dict, path: str) -> None:
        properties = sub["properties"]
        if sub.get("additionalProperties") is False:
            for key in [k for k in node if k not in properties]:
                value = node[key]
                if key in ANNOTATION_KEYS and (isinstance(value, str) or (isinstance(value, list) and all(isinstance(v, str) for v in value))):
                    text = value if isinstance(value, str) else " / ".join(value)
                    del node[key]
                    self.repairs.append(Repair(path, f"removed {key!r} (not allowed here): {text[:200]!r}"))
        if "valueType" in properties and "valueType" not in node and "value" in node:
            inferred = _value_type(node["value"])
            if inferred:
                node["valueType"] = inferred
                self.repairs.append(Repair(path, f"added valueType {inferred!r} from the value"))
        value_type, value = node.get("valueType"), node.get("value")
        if "valueType" in properties and isinstance(value, str):  # the value's type is fixed by valueType (if/then)
            scalar = {"integer": {"type": "integer"}, "number": {"type": "number"}, "boolean": {"type": "boolean"}}.get(value_type)
            if scalar:
                node["value"] = self._scalar(value, scalar, f"{path}/value")
        for key in list(node):
            if key in properties:
                node[key] = self.walk(node[key], properties[key], f"{path}/{key}" if path else key)

    def _scalar(self, node, sub: dict, path: str):
        if not isinstance(node, str):
            return node
        wanted = sub.get("type")
        if wanted in ("number", "integer") and NUMBER.match(node.strip()):
            value = float(node) if "." in node else int(node)
            if wanted == "number" or isinstance(value, int):
                self.repairs.append(Repair(path, f"converted the string {node!r} to a number"))
                return value
        if wanted == "boolean" and node.strip().lower() in ("true", "false"):
            self.repairs.append(Repair(path, f"converted the string {node!r} to a boolean"))
            return node.strip().lower() == "true"
        enum = sub.get("enum")
        if isinstance(enum, list) and node not in enum:
            folded = re.sub(r"[\s\-]+", "_", node.strip().lower())
            matches = [e for e in enum if isinstance(e, str) and e in (folded, folded.removesuffix("s"))]
            if len(matches) == 1:
                self.repairs.append(Repair(path, f"mapped {node!r} to the schema value {matches[0]!r}"))
                return matches[0]
        if path.endswith("/unit") and sub.get("pattern"):
            fixed = UNIT_NAMES.get(node.strip().lower())
            if fixed is None and any(a in node for a, _ in SUPERSCRIPTS):
                fixed = node.strip()
                for old, new in SUPERSCRIPTS:
                    fixed = fixed.replace(old, new)
            if fixed and fixed != node and re.fullmatch(r"\S+", fixed):
                self.repairs.append(Repair(path, f"rewrote the unit {node!r} as {fixed!r}"))
                return fixed
        return node


def _value_type(value) -> str | None:
    def scalar(v):
        if isinstance(v, bool):
            return "boolean"
        if isinstance(v, int):
            return "integer"
        if isinstance(v, float):
            return "number"
        if isinstance(v, str):
            return "string"
        return None
    if isinstance(value, list):
        types = {scalar(v) for v in value}
        if types == {"integer", "number"}:
            types = {"number"}
        return f"{types.pop()}_array" if value and len(types) == 1 and None not in types else None
    return scalar(value)


def repair_rule(rule: dict, schema: dict) -> list[Repair]:
    """Repair `rule` in place along the schema's `Rule` definition; returns what was repaired."""
    walker = _Walker(schema)
    walker.walk(rule, schema, "")
    return walker.repairs
