"""AKN4EU artifacts: act + annex XML files, a ZIP package, validation report, traceability, text check.

Validation is reported in separate layers, never merged into one "valid":

1. ``oasis_akn_3_1_xsd`` -- each file against the unmodified OASIS AKN 3.1 schema (the base of AKN4EU 5.x,
   and the only schema ODOS validates against);
2. ``akn4eu_sample_checks`` -- the rules every official AKN4EU 5.0.1.0 sample satisfies (akn4eu_checks);
3. ``akn4eu_5_0_1_0_rules`` -- the rules of the AKN4EU 5.0.1.0 specification implemented by ODOS
   (akn4eu_validate): package, metadata, completeness against the model, the reviewed model;
4. ``official_akn4eu_validation`` -- not performed: no official AKN4EU schema/Schematron was available.

An export succeeds (``ok``) only if no layer fails: every file XSD-valid, every sample rule and every
mandatory specification rule met (rules that need information the source does not provide are reported
as ``missing_input``, not passed), the text and order identical to the model, and nothing unmapped.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path

from lxml import etree

from odos.akn.akn4eu import XID, Akn4EuResult, generate_akn4eu, node_text
from odos.akn.akn4eu_checks import check_package
from odos.akn.akn4eu_validate import validate_akn4eu
from odos.akn.validate import validate_xml
from odos.akn.verify import collapse_ws
from odos.document_model import DocumentModel, ElementType as T

PACKAGE_NAME = "akn4eu_package.zip"
REPORT_NAME = "akn4eu_validation_report.json"
STATUS_OK = "sample-compatible AKN4EU (not officially verified AKN4EU conformance)"
STATUS_FAILED = "NOT sample-compatible: see the failing layer(s)"
OFFICIAL = {
    "performed": False,
    "reason": "no official AKN4EU schema or Schematron available: the AKN4EU 5.0.1.0 sample package contains none, and the "
              "Publications Office download page could not be retrieved automatically",
}  # fmt: skip


def verify_akn4eu(model: DocumentModel, result: Akn4EuResult) -> dict:
    """Text and order of the AKN4EU files compared with the Internal Document Model."""
    trees = {name: etree.fromstring(xml) for name, xml in result.files.items()}
    index = {(name, n.get(XID)): n for name, t in trees.items() for n in t.iter() if isinstance(n.tag, str) and n.get(XID)}  # fmt: skip
    notes = {e["xml_id"]: e["footnote"]["reference_text"] for e in result.entries
             if e.get("footnote") and e["footnote"]["placed"] == "at_reference"}  # fmt: skip
    by_id = model.by_id()
    mismatches, atoms, chars, missing_nodes = [], 0, 0, []

    def check(e: dict, kind: str, ids: list[str], expected: str, joined: str | None = None) -> None:
        nonlocal atoms, chars
        nodes = [index.get((e["file"], i)) for i in ids]
        if any(n is None for n in nodes):
            missing_nodes.append({"model_id": e["model_id"], "kind": kind, "ids": ids})
            return
        actual = " ".join(node_text(n, notes) for n in nodes) if joined is None else joined
        atoms += 1
        chars += len(expected)
        if actual != expected:
            mismatches.append({"model_id": e["model_id"], "kind": kind, "expected": expected[:200], "actual": actual[:200]})  # fmt: skip

    for e in result.entries:
        el = by_id[e["model_id"]]
        if e["num_id"]:
            check(e, "num", [e["num_id"]], el.marker or "")
        if e["heading_id"]:
            check(e, "heading", [e["heading_id"]], el.title or "")
        if e.get("footnote"):
            p = index.get((e["file"], e["text_ids"][0]))
            check(e, "footnote", e["text_ids"], el.content_text, e["footnote"]["stripped_prefix"] + (node_text(p, notes) if p is not None else ""))  # fmt: skip
        elif el.table is not None:  # tables, and signature blocks Docling detected as tables
            cells = [c for row in el.table.rows for c in row if c]
            check(e, "table", e.get("cell_ids", []), " ".join(cells))
        elif e["text_ids"]:
            check(e, "text", e["text_ids"], el.content_text)

    # document order: the first XML node of each element, files in package order (act, annexes)
    owner = {}
    for e in result.entries:
        for i in [e["xml_id"], e["num_id"], e["heading_id"], *e["text_ids"], *e.get("cell_ids", [])]:
            if i:
                owner.setdefault((e["file"], i), e["model_id"])
    shells = {e["model_id"] for e in result.entries if e.get("role") == "container_shell"}
    seen: list[str] = []
    for name, t in trees.items():
        for n in t.iter():
            mid = owner.get((name, n.get(XID))) if isinstance(n.tag, str) else None
            if mid and mid not in seen:
                seen.append(mid)
    note_ids = {e["model_id"] for e in result.entries if e.get("footnote")}
    inc = set(result.included_ids)
    model_order = [e.id for e in model.elements if e.id in inc]
    pick = lambda seq, notes_: [i for i in seq if i not in shells and (i in note_ids) == notes_]  # noqa: E731
    orig_diffs = []
    for e in result.entries:
        el = by_id[e["model_id"]]
        if e["model_type"] in ("table", "footnote", "front_matter") or el.reviewed:  # reviewed text is listed separately
            continue
        rebuilt = " ".join(x for x in (el.marker, el.title if el.title else el.content_text) if x)
        if collapse_ws(rebuilt) != collapse_ws(el.original_text):
            orig_diffs.append({"model_id": el.id, "rebuilt": rebuilt[:80], "original": el.original_text[:80]})
    fn = [e["footnote"] for e in result.entries if e.get("footnote")]
    count = lambda t: sum(1 for i in result.included_ids if by_id[i].type == t)  # noqa: E731
    return {
        "same_order_and_text": not mismatches and not missing_nodes and pick(seen, False) == pick(model_order, False)
                               and pick(seen, True) == pick(model_order, True),
        "text_mismatches": mismatches,
        "missing_nodes": missing_nodes,
        "atoms_compared": atoms,
        "characters_compared": chars,
        "document_order_preserved": pick(seen, False) == pick(model_order, False),
        "footnote_order_preserved": pick(seen, True) == pick(model_order, True),
        "order_note": "container shells (preamble, conclusions) are not compared: the binding clause moves from the "
                      "conclusions to body/clause, i.e. before the conclusions shell, as in the AKN4EU samples",
        "original_text_reconstruction_diffs": orig_diffs,
        "reviewed_elements": [e["model_id"] for e in result.entries if e.get("reviewed")],
        "footnotes": {"total": len(fn), "at_reference": sum(f["placed"] == "at_reference" for f in fn),
                      "end_of_text": sum(f["placed"] == "end_of_text" for f in fn)},
        "elements_in_xml": len(result.included_ids),
        "elements_not_in_xml": {k: len(v) for k, v in result.excluded.items()},
        "unmapped": result.unmapped,
        "counts": {"recitals": count(T.RECITAL), "chapters": count(T.CHAPTER), "articles": count(T.ARTICLE),
                   "annexes": count(T.ANNEX), "files": len(result.files)},
    }  # fmt: skip


def atomic_write(path: Path, data: bytes) -> None:
    """Write next to the target and move it into place: a reader sees the old file or the new one, never half of it."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_package(files: dict[str, bytes], path: Path) -> None:
    """Deterministic ZIP (fixed timestamps, file order as generated), replaced atomically."""
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for name, xml in files.items():
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                z.writestr(info, xml)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


GENERATED_NAME = re.compile(r"^(main|act|ANNEX)-[^/\\]+\.xml$")


def remove_stale_files(out: Path, current: set[str]) -> dict:
    """Remove XML files of an earlier export of this folder that the new export no longer produces.

    Only files the previous report lists as generated are candidates, only if their name has the generated
    form and their bytes still equal what was generated (a file someone edited or replaced is kept), and never
    anything the new export wrote. Everything else in the folder is left alone."""
    removed, kept = [], []
    try:
        previous = json.loads((out / REPORT_NAME).read_text(encoding="utf-8")).get("files", {})
    except (OSError, ValueError, AttributeError):
        return {"removed": removed, "kept": kept}
    for name, info in previous.items():
        p = out / name
        if name in current or not GENERATED_NAME.match(name) or not isinstance(info, dict):
            continue
        if p.is_symlink() or not p.is_file():
            continue
        if hashlib.sha256(p.read_bytes()).hexdigest() != info.get("file_sha256"):
            kept.append({"name": name, "reason": "differs from what the earlier export generated: left in place"})
            continue
        p.unlink()
        removed.append(name)
    return {"removed": removed, "kept": kept}


def model_source_of(model: DocumentModel) -> dict:
    """Which model an export was built from, when the caller does not say (CLI: the model file given)."""
    review = model.review or {}
    return {"kind": "effective_reviewed_model" if review else "document_model", "model_revision": review.get("model_revision"),
            "corrected_elements": [e.id for e in model.elements if e.reviewed]}  # fmt: skip


def build_akn4eu_artifacts(model: DocumentModel, retrieval_date: str, out: Path, eli: str | None = None, oj_uri: str | None = None,
                           model_source: dict | None = None) -> dict:  # fmt: skip
    out.mkdir(parents=True, exist_ok=True)
    result = generate_akn4eu(model, retrieval_date, eli=eli, oj_uri=oj_uri)
    for name, xml in result.files.items():
        atomic_write(out / name, xml)  # written even if invalid: it is the diagnostic output
    xsd = {name: validate_xml(xml) for name, xml in result.files.items()}
    checks = check_package(result.files)
    text = verify_akn4eu(model, result)
    source = model_source or model_source_of(model)
    spec = validate_akn4eu(result.files, model, result, text, source)
    write_package(result.files, out / PACKAGE_NAME)
    xsd_ok = all(v.valid for v in xsd.values())
    complete = not result.unmapped and not result.excluded["unmapped"]  # nothing of the model silently left out
    layers = {"oasis_akn_3_1_xsd": xsd_ok, "akn4eu_sample_checks": checks["passed"], "akn4eu_5_0_1_0_rules": spec["passed"],
              "text_and_order_against_model": text["same_order_and_text"], "model_completeness": complete}  # fmt: skip
    ok = all(layers.values())
    export_warnings = []
    if source.get("kind") == "effective_reviewed_model" and source.get("review_state") != "approved":
        state = source.get("review_state")
        export_warnings.append({
            "code": "UNAPPROVED_REVIEW",
            "detail": f"built from the reviewed model of revision {source.get('model_revision')}, but the review is "
                      + (f"'{state}', not approved" if state else "of unknown approval state") + ": the corrections are not signed off",  # fmt: skip
        })
    report = {
        "profile": "akn4eu",
        "status": STATUS_OK if ok else STATUS_FAILED,
        "export_warnings": export_warnings,
        "failing_layers": [k for k, v in layers.items() if not v],
        "conformance": {
            "oasis_akn_3_1_xsd": {"valid": xsd_ok, "schema_version": next(iter(xsd.values())).schema_version,
                                  "schema_files": next(iter(xsd.values())).schema_files},
            "akn4eu_sample_checks": {"passed": checks["passed"], "rules": len(checks["rules"]), "meaning": checks["meaning"]},
            "akn4eu_5_0_1_0_rules": {k: spec[k] for k in ("passed", "complete", "verdict", "counts", "failed", "missing_input", "deviations", "warnings", "meaning")},
            "official_akn4eu_validation": OFFICIAL,
            "text_and_order_against_model": text["same_order_and_text"],
            "model_completeness": {"complete": complete, "unmapped": result.excluded["unmapped"]},
        },
        "files": {
            name: {"bytes": len(xml), "xml_sha256": xsd[name].xml_sha256, "file_sha256": hashlib.sha256(xml).hexdigest(), "valid_akn_3_1": xsd[name].valid,
                   "errors": [e.model_dump() for e in xsd[name].errors], "warnings": [e.model_dump() for e in xsd[name].warnings],
                   "sample_checks": checks["files"][name]}
            for name, xml in result.files.items()
        },
        "act_file": result.act_file,
        "main_file": result.main_file,
        "package": PACKAGE_NAME,
        "model_source": source,
        "identifiers": result.identifiers,
        "scope": result.scope,
        "generator_warnings": result.warnings,
        "unmapped": result.unmapped,
        "text_preservation_summary": {k: text[k] for k in ("same_order_and_text", "document_order_preserved", "footnote_order_preserved",
                                                           "atoms_compared", "characters_compared", "footnotes")},
        "validator": next(iter(xsd.values())).validator,
        "akn4eu_5_0_1_0": spec,
    }  # fmt: skip
    stale = remove_stale_files(out, set(result.files))  # reads the previous report, so before it is replaced
    report["stale_files"] = stale
    atomic_write(out / REPORT_NAME, json.dumps(report, indent=2, ensure_ascii=False).encode("utf-8"))
    atomic_write(out / "akn4eu_text_preservation.json", json.dumps(text, indent=2, ensure_ascii=False).encode("utf-8"))
    trace = {
        "profile": "akn4eu",
        "files": {name: xsd[name].xml_sha256 for name in result.files},
        "source": model.source.model_dump(),
        "nodes": result.entries,
        "included_model_elements": result.included_ids,
        "excluded_model_elements": result.excluded,
        "excluded_counts": {k: len(v) for k, v in result.excluded.items()},
        "uncertain": [{k: e[k] for k in ("model_id", "file", "xml_id", "uncertainty_reasons", "original_text", "source_spans")}
                      for e in result.entries if e["uncertain"]],
        "unmapped": result.unmapped,
    }  # fmt: skip
    atomic_write(out / "akn4eu_traceability.json", json.dumps(trace, indent=2, ensure_ascii=False).encode("utf-8"))
    return {"result": result, "xsd": xsd, "checks": checks, "spec": spec, "text": text, "report": report, "ok": ok}
