"""Deterministic outputs of one parsed document, for the golden equivalence checks (tests/test_golden_equivalence.py).

Everything is computed in memory; no paths, timestamps or runtime metadata enter the bytes.
`fingerprint` returns SHA-256 per output plus one short hash per element, so a difference can be located.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

# outputs the baselines were recorded with that ODOS no longer produces (Akoma Ntoso was removed; Legal JSON 1.1 and
# its 1.0 downgrade were replaced by 2.0, whose hashes are in legal_json_2_0_baseline.json); a baseline is never
# rewritten, so they are left out of the comparison and every other value must still match
RETIRED = {
    "outputs": {"akn_xml", "akn_xml_excerpt", "akn_xsd_valid", "legal_json_1_1", "legal_json_1_0", "legal_json_report"},
    "summary": {"akn_xsd_valid"},
}


def _sha(b: bytes | str) -> str:
    return hashlib.sha256(b.encode("utf-8") if isinstance(b, str) else b).hexdigest()


def outputs(model, raw: Path) -> dict[str, bytes]:
    from odos.legal_json.artifacts import build_legal_json_artifacts, serialize
    from odos.legal_json.exporter import to_legal_json

    out: dict[str, bytes] = {"model": model.model_dump_json(indent=2).encode("utf-8")}
    out["legal_json_2_0"] = serialize(to_legal_json(model))
    with tempfile.TemporaryDirectory() as t:
        rep = build_legal_json_artifacts(model, raw, Path(t))["report"]
    out["legal_json_2_0_report"] = json.dumps(rep, indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if model.profile == "eu_legislation":
        from odos.parsing.profiles.eu_legislation.report import build_eu_report

        out["validation_report"] = _canonical(build_eu_report(model, raw).model_dump())
    else:
        from odos.parsing.profiles.german_law.report import build_report

        out["validation_report"] = _canonical(build_report(model, raw).model_dump())
    return out


def _canonical(data) -> bytes:
    """Reports compared by content: key order is not content (the German report's `structure` counts come from
    iterating a set, so their order depends on the Python hash seed)."""
    return json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True).encode("utf-8")


def fingerprint(model, raw: Path) -> dict:
    from collections import Counter

    outs = outputs(model, raw)
    return {
        "outputs": {k: _sha(v) for k, v in sorted(outs.items())},
        "summary": {
            "elements": len(model.elements), "furniture": len(model.furniture),
            "warnings": dict(sorted(Counter(w.code for w in model.warnings).items())),
            "uncertain": sum(e.uncertain for e in model.elements),
            "sentences": len(model.sentences), "toc_entries": len(model.toc_entries),
            "toc_linked": sum(e.status == "linked" for e in model.toc_entries),
            "footnotes_anchored": sum(bool(e.anchor_ids) for e in model.elements),
            "highlight_elements": sum(bool(e.highlight_boxes) for e in model.elements),
        },
        "element_ids": _sha("\n".join(e.id for e in [*model.elements, *model.furniture])),
        "elements": {e.id: _sha(e.model_dump_json())[:16] for e in [*model.elements, *model.furniture]},
        "sentences": {s.id: _sha(s.model_dump_json())[:16] for s in model.sentences},
        "toc_entries": {t.id: _sha(t.model_dump_json())[:16] for t in model.toc_entries},
    }


def first_differences(expected: dict, actual: dict, limit: int = 10) -> list[str]:
    """Human-readable list of what differs (outputs, summary counts, then individual elements)."""
    diff = []
    for section in ("outputs", "summary"):
        for k in sorted((set(expected[section]) - RETIRED[section]) | set(actual[section])):
            if expected[section].get(k) != actual[section].get(k):
                diff.append(f"{section}.{k}: {expected[section].get(k)!r} -> {actual[section].get(k)!r}")
    if expected["element_ids"] != actual["element_ids"]:
        diff.append("element id list changed")
    for section in ("elements", "sentences", "toc_entries"):
        e, a = expected[section], actual[section]
        for k in [*[k for k in e if k not in a], *[k for k in a if k not in e], *[k for k in e if k in a and e[k] != a[k]]][:limit]:
            diff.append(f"{section}: {k} {'missing' if k not in a else 'new' if k not in e else 'changed'}")
    return diff


def record_baseline(path: Path, data: dict) -> None:
    """Write a new baseline file. An existing baseline is evidence and is never overwritten (a difference to it is
    investigated, not refreshed); a new fixture gets a new file."""
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"{path} exists: baselines are never overwritten")
    path.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
