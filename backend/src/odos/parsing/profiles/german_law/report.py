"""Validation report for a parsed DocumentModel."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from pydantic import BaseModel

from odos.document_model import DocumentModel, ElementType as T
from odos.normalization.docling_reader import read_docling_json
from odos.parsing.accounting import content_accounting, render_tree, text_repair_check, write_validation_outputs


class ValidationReport(BaseModel):
    document: str | None
    pages: int
    docling_items_total: int
    docling_items_in_model: int
    docling_items_missing: list[str]
    docling_items_duplicated: list[str]
    text_mismatches: list[str]
    element_counts: dict[str, int]
    structure: dict[str, int]
    unrecognized: list[dict]
    uncertain: list[dict]
    warning_counts: dict[str, int]
    warnings: list[dict]
    provenance_coverage: dict
    toc_vs_body: dict
    hierarchy_examples: dict[str, str]
    segmented_items: list[dict] = []  # Docling items split by the extraction-hygiene layer
    source_text_repairs: dict = {}  # characters restored from the PDF text layer (text_repair_check)


def build_report(model: DocumentModel, docling_json: Path) -> ValidationReport:
    _, items = read_docling_json(docling_json)
    src = {i.ref: i for i in items}
    acc = content_accounting(model, items)
    missing, duplicated, mismatches, segmented = acc["missing"], acc["duplicated"], acc["text_mismatches"], acc["segmented"]

    counts = Counter(e.type.value for e in model.elements)
    body = [e for e in model.elements if e.region == "body"]
    structural = {T.TEIL, T.KAPITEL, T.ABSCHNITT, T.UNTERABSCHNITT, T.PARAGRAPH, T.ABSATZ, T.NUMMER, T.BUCHSTABE, T.DOPPELBUCHSTABE}  # fmt: skip

    traced = [e for e in [*model.elements, *model.furniture] if e.source_refs]
    with_prov = [e for e in traced if e.provenance and e.pages]
    with_bbox = [e for e in traced if e.provenance and all(p.bbox for p in e.provenance)]
    prov = {
        "elements_with_source": len(traced),
        "with_page_provenance": len(with_prov),
        "with_bbox": len(with_bbox),
        "page_coverage_pct": round(100 * len(with_prov) / max(len(traced), 1), 2),
        "bbox_coverage_pct": round(100 * len(with_bbox) / max(len(traced), 1), 2),
        "without_provenance": [e.id for e in traced if e not in with_prov][:50],
    }

    toc_paras = set()
    for e in model.elements:
        if e.region == "toc":
            toc_paras |= set(re.findall(r"§\s*(\d+[a-z]?)\b", e.original_text))
            if e.table:
                for row in e.table.rows:
                    for cell in row:
                        toc_paras |= set(re.findall(r"§\s*(\d+[a-z]?)\b", cell))
    body_paras = {e.number for e in body if e.type == T.PARAGRAPH}
    toc_info = {
        "toc_elements": sum(1 for e in model.elements if e.region == "toc"),
        "toc_paragraph_numbers": len(toc_paras),
        "body_paragraph_numbers": len(body_paras),
        "in_toc_not_in_body": sorted(toc_paras - body_paras, key=lambda x: (len(x), x)),
        "in_body_not_in_toc": sorted(body_paras - toc_paras, key=lambda x: (len(x), x)),
        "note": "TOC § numbers are collected with a regex over letter-spaced Docling text and tables; differences indicate TOC extraction gaps, not necessarily body errors.",  # fmt: skip
    }

    ex: dict[str, str] = {}
    by_id = model.by_id()
    first_pars = [e for e in body if e.type == T.PARAGRAPH][:2]
    for par in first_pars:
        ex[par.id] = render_tree(model, par.id, max_depth=3)
    first_nr = next((e for e in model.elements if e.type == T.BUCHSTABE), None)
    if first_nr:
        par = next((p for p in model.path(first_nr.id) if p.type == T.PARAGRAPH), None)
    if first_nr and par:
        ex[f"{par.id} (contains Buchstabe lists)"] = render_tree(model, par.id, max_depth=4)
    top = next((e for e in body if e.type in (T.TEIL, T.ANLAGE) and e.children_ids), None)
    if top:
        ex[f"{top.id} (one level)"] = render_tree(model, top.id, max_depth=1)
    if "doc/toc" in by_id:
        ex["toc (first entries)"] = "\n".join(render_tree(model, "doc/toc", 1).splitlines()[:8])

    unrec = [
        {"id": e.id, "type": e.type.value, "label": e.docling_label, "ref": e.source_refs[:1], "text": e.original_text[:100]}  # fmt: skip
        for e in model.elements if e.type in (T.UNRECOGNIZED, T.UNMARKED_LIST_ITEM) and e.region == "body"  # fmt: skip
    ]
    uncertain = [
        {"id": e.id, "type": e.type.value, "reasons": e.uncertainty_reasons, "text": e.original_text[:80]}  # fmt: skip
        for e in model.elements if e.uncertain
    ]
    return ValidationReport(
        document=model.metadata.title,
        pages=model.source.num_pages,
        docling_items_total=len(src),
        docling_items_in_model=len(src) - len(missing),
        docling_items_missing=missing,
        docling_items_duplicated=duplicated,
        text_mismatches=mismatches,
        element_counts=dict(sorted(counts.items())),
        structure={t.value: sum(1 for e in body if e.type == t) for t in structural},
        unrecognized=unrec,
        uncertain=uncertain,
        warning_counts=dict(Counter(w.code for w in model.warnings)),
        warnings=[w.model_dump() for w in model.warnings],
        provenance_coverage=prov,
        toc_vs_body=toc_info,
        hierarchy_examples=ex,
        segmented_items=segmented,
        source_text_repairs=text_repair_check(model, items),
    )


def report_to_markdown(r: ValidationReport) -> str:
    L = [f"# Validation report: {r.document}", ""]
    L += ["## Content accounting", "",
          f"- Docling items (body + furniture): {r.docling_items_total}",
          f"- Represented in model: {r.docling_items_in_model}",
          f"- Missing: {len(r.docling_items_missing)} {r.docling_items_missing[:10]}",
          f"- Mapped more than once: {len(r.docling_items_duplicated)}",
          f"- Text differing from Docling `orig`: {len(r.text_mismatches)}",
          f"- Docling items split into segments (merged paragraphs): {len(r.segmented_items)}"
          + (f", all tiled exactly: {all(s['tiles_item_exactly'] for s in r.segmented_items)}" if r.segmented_items else ""),
          ""]  # fmt: skip
    L += ["## Recognized structure (body)", ""] + [f"- {k}: {v}" for k, v in r.structure.items()]
    L += ["", "## All element types", ""] + [f"- {k}: {v}" for k, v in r.element_counts.items()]
    L += ["", f"## Unrecognized / unmarked body elements ({len(r.unrecognized)})", ""]
    L += [f"- `{u['id']}` ({u['label']}): {u['text']}" for u in r.unrecognized] or ["- none"]
    L += ["", f"## Uncertain elements ({len(r.uncertain)})", ""]
    L += [f"- `{u['id']}`: {', '.join(u['reasons'])}" for u in r.uncertain] or ["- none"]
    L += ["", f"## Warnings ({len(r.warnings)})", ""]
    L += [f"- {k}: {v}" for k, v in r.warning_counts.items()] or ["- none"]
    L += ["", "<details><summary>All warnings</summary>", ""]
    L += [f"- [{w['severity']}] {w['code']} {w['element_id'] or ''} {w['source_ref'] or ''}: {w['message']}" for w in r.warnings]  # fmt: skip
    L += ["", "</details>", "", "## Provenance coverage", ""]
    L += [f"- {k}: {v}" for k, v in r.provenance_coverage.items() if k != "without_provenance"]
    L += ["", "## Table of contents vs. body (§ numbers)", ""]
    L += [f"- {k}: {v}" for k, v in r.toc_vs_body.items()]
    L += ["", "## Hierarchy examples", ""]
    for k, v in r.hierarchy_examples.items():
        L += [f"### {k}", "", "```", v, "```", ""]
    return "\n".join(L)


def write_outputs(model: DocumentModel, docling_json: Path, out_dir: Path) -> tuple[Path, Path, Path]:
    return write_validation_outputs(model, docling_json, out_dir, build_report, report_to_markdown)
