"""Deterministic outputs of one parsed document, for the golden equivalence checks (tests/test_golden_equivalence.py).

Everything is computed in memory with fixed dates; no paths, timestamps or runtime metadata enter the bytes.
`fingerprint` returns SHA-256 per output plus one short hash per element, so a difference can be located.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

DATE = "2026-10-27"  # fixed retrieval / processing date


def _sha(b: bytes | str) -> str:
    return hashlib.sha256(b.encode("utf-8") if isinstance(b, str) else b).hexdigest()


def outputs(model, raw: Path) -> dict[str, bytes]:
    from odos.akn.validate import validate_xml
    from odos.legal_json.artifacts import build_legal_json_artifacts, serialize
    from odos.legal_json.exporter import load_source_context, to_legal_json
    from odos.legal_json.legacy import downgrade_to_1_0
    from odos.document_model import ElementType as T

    out: dict[str, bytes] = {"model": model.model_dump_json(indent=2).encode("utf-8")}
    doc11 = serialize(to_legal_json(model, load_source_context(raw)))
    out["legal_json_1_1"] = doc11
    out["legal_json_1_0"] = json.dumps(downgrade_to_1_0(json.loads(doc11)), indent=2, ensure_ascii=False).encode("utf-8")
    with tempfile.TemporaryDirectory() as t:
        rep = build_legal_json_artifacts(model, raw, Path(t))["report"]
    # the one additive key of Phase 3 (step 7, approved): hashed without it, so every other byte of the report must
    # still equal the baseline; its content is checked in test_legal_json.test_downgrade_information_loss_is_reported
    rep.pop("downgrade_to_1_0_information_loss", None)
    out["legal_json_report"] = json.dumps(rep, indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if model.profile == "eu_legislation":
        from odos.akn.eu_generator import generate_eu_akn
        from odos.parsing.profiles.eu_legislation.report import build_eu_report

        out["akn_xml"] = generate_eu_akn(model, DATE).xml
        out["validation_report"] = _canonical(build_eu_report(model, raw).model_dump())
    else:
        from odos.akn.generator import generate_excerpt
        from odos.parsing.profiles.german_law.report import build_report

        pars = [p.number for p in model.of_type(T.PARAGRAPH)]
        out["akn_xml"] = generate_excerpt(model, pars, DATE, undated_policy="processing_date").xml
        if model.metadata.ausfertigungsdatum:
            out["akn_xml_excerpt"] = generate_excerpt(model, pars[:2], DATE).xml
        out["validation_report"] = _canonical(build_report(model, raw).model_dump())
    out["akn_xsd_valid"] = str(validate_xml(out["akn_xml"]).valid).encode()
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
            "akn_xsd_valid": outs["akn_xsd_valid"].decode(),
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
        for k in sorted(set(expected[section]) | set(actual[section])):
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
