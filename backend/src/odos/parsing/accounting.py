"""Validation shared by every profile's report: every Docling item is accounted for, split items are tiled exactly,
the text is verbatim (Docling text plus the recorded PDF repairs), and the writer of document_model.json plus the
profile's validation report (JSON and Markdown)."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from odos.artifact_names import DOCUMENT_MODEL, VALIDATION_REPORT, VALIDATION_REPORT_MD
from odos.document_model import DocumentModel, Element


def render_tree(model: DocumentModel, element_id: str, max_depth: int = 3, width: int = 70) -> str:
    index = model.by_id()
    lines: list[str] = []

    def rec(el: Element, depth: int) -> None:
        label = f"{el.marker or ''} {el.title or el.content_text}".strip()
        label = re.sub(r"\s+", " ", label)
        label = label if len(label) <= width else label[: width - 1] + "…"
        flag = "  [uncertain]" if el.uncertain else ""
        lines.append(f"{'  ' * depth}{el.type.value} <{el.id}> {label}{flag}")
        if depth < max_depth:
            for c in el.children_ids:
                rec(index[c], depth + 1)

    rec(index[element_id], 0)
    return "\n".join(lines)

def canonical_sources(model: DocumentModel, items) -> dict:
    """The Docling items with the model's recorded source-text repairs applied (Docling text otherwise).

    The model's text is compared against these: a repaired character must be a recorded, evidenced repair,
    and undoing the repairs must give back Docling's exact text (checked in `text_repair_check`)."""
    by_ref: dict[str, dict] = {}
    for e in [*model.elements, *model.furniture]:
        for r in e.text_repairs:
            by_ref.setdefault(r.ref, {})[(r.start, r.end, r.rule)] = r
    out = {}
    for it in items:
        reps = sorted(by_ref.get(it.ref, {}).values(), key=lambda r: r.start)
        if not reps:
            out[it.ref] = it
            continue
        text, pos, shift = [], 0, 0  # repair positions are in the canonical text; walk Docling's text forwards
        for r in reps:
            d_start = r.start - shift
            text.append(it.orig[pos:d_start])
            text.append(r.restored)
            pos = d_start + len(r.docling)
            shift += len(r.restored) - len(r.docling)
        text.append(it.orig[pos:])
        out[it.ref] = it.model_copy(update={"orig": "".join(text)})
    return out

def text_repair_check(model: DocumentModel, items) -> dict:
    """Undoing every recorded repair reproduces Docling's text exactly; every repair has evidence."""
    src = {i.ref: i for i in items}
    canon = canonical_sources(model, items)
    repairs = [r for e in [*model.elements, *model.furniture] for r in e.text_repairs]
    unique = {(r.ref, r.start, r.end, r.rule): r for r in repairs}.values()
    from odos.normalization.source_text import revert

    inconsistent = [ref for ref, it in canon.items() if it.orig != src[ref].orig and revert(it.orig, [r for r in unique if r.ref == ref]) != src[ref].orig]  # fmt: skip
    return {
        "repairs": len(unique),
        "verified_text_changes": sum(1 for r in unique if r.status == "verified" and r.restored != r.docling),
        "verified_docling_kept": sum(1 for r in unique if r.status == "verified" and r.restored == r.docling),
        "unresolved": sum(1 for r in unique if r.status == "unresolved"),
        "items_changed": sum(1 for ref, it in canon.items() if it.orig != src[ref].orig),
        "reverts_to_docling_exactly": not inconsistent,
        "inconsistent_items": inconsistent,
        "without_evidence": sum(1 for r in unique if not r.evidence),
    }

def content_accounting(model: DocumentModel, items) -> dict:
    """Every Docling item is represented; split items are tiled exactly; text is verbatim.

    Shared by the German and the EU report."""
    all_el = [*model.elements, *model.furniture]
    src = canonical_sources(model, items)
    seen = Counter(r for e in all_el for r in e.source_refs)
    missing = sorted(set(src) - set(seen))
    # a ref may back several elements only if each of them holds a span of it (hygiene segments)
    spans_by_ref: dict[str, list[tuple[int, int]]] = {}
    for e in all_el:
        for sp in e.source_spans:
            spans_by_ref.setdefault(sp.ref, []).append((sp.start, sp.end))
    duplicated = sorted(r for r, n in seen.items() if n > 1 and r not in spans_by_ref)

    def expected_text(e) -> str:
        if e.source_spans:
            return "\n".join(src[sp.ref].orig[sp.start : sp.end] for sp in e.source_spans if sp.ref in src)
        return "\n".join(src[x].orig for x in e.source_refs if x in src)  # merged heading = refs joined

    mismatches = [e.id for e in all_el if e.source_refs and e.original_text != expected_text(e)]
    segmented = []
    for ref, spans in sorted(spans_by_ref.items(), key=lambda kv: int(kv[0].rsplit("/", 1)[1])):
        orig, pos, ok = src[ref].orig, 0, True
        for s, e in sorted(spans):
            ok = ok and s >= pos and not orig[pos:s].strip()
            pos = e
        ok = ok and not orig[pos:].strip()
        segmented.append({"ref": ref, "segments": len(spans), "tiles_item_exactly": ok})

    def nonws(x: str) -> int:
        return sum(1 for c in x if not c.isspace())

    source_chars = sum(nonws(i.orig) for i in src.values())
    accounted = 0
    for e in all_el:
        if e.source_spans:
            accounted += sum(nonws(src[sp.ref].orig[sp.start : sp.end]) for sp in e.source_spans if sp.ref in src)
        else:
            accounted += sum(nonws(src[r].orig) for r in e.source_refs if r in src)
    return {"missing": missing, "duplicated": duplicated, "text_mismatches": mismatches, "segmented": segmented,
            "source_non_whitespace_chars": source_chars, "accounted_non_whitespace_chars": accounted}  # fmt: skip

def write_validation_outputs(model: DocumentModel, docling_json: Path, out_dir: Path, build, to_markdown) -> tuple[Path, Path, Path]:  # fmt: skip
    """document_model.json plus the profile's validation report (`build`) as JSON and Markdown (`to_markdown`)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / DOCUMENT_MODEL
    model_path.write_text(model.model_dump_json(indent=2), encoding="utf-8")
    report = build(model, docling_json)
    rj = out_dir / VALIDATION_REPORT
    rj.write_text(json.dumps(report.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
    rm = out_dir / VALIDATION_REPORT_MD
    rm.write_text(to_markdown(report), encoding="utf-8")
    return model_path, rj, rm
