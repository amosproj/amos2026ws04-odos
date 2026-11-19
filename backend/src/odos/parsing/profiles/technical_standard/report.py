"""Validation report for technical standards parsed with the ``technical_standard`` profile."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from pydantic import BaseModel

from odos.document_model import DocumentModel, ElementType as T
from odos.normalization.docling_reader import read_docling_json
from odos.parsing.accounting import content_accounting, render_tree, text_repair_check, write_validation_outputs


class TsValidationReport(BaseModel):
    profile: str
    document: str | None
    pages: int
    metadata: dict
    accounting: dict
    element_counts: dict[str, int]
    clauses_per_level: dict[str, int]
    definitions: int
    annexes: list[dict]
    uncertain: list[dict]
    uncertainty_reason_counts: dict[str, int]
    warning_counts: dict[str, int]
    warnings: list[dict]
    warning_category_counts: dict[str, int] = {}
    structure_note_counts: dict[str, int] = {}
    structure_notes: list[dict] = []
    provenance_coverage: dict
    duplicate_ids: list[str]
    hierarchy_examples: dict[str, str]


def _clause_level(n: str) -> int:
    return len(n.split("."))


def build_ts_report(model: DocumentModel, docling_json: Path) -> TsValidationReport:
    _, items = read_docling_json(docling_json, include_nested=True)
    acc = content_accounting(model, items)
    traced = [e for e in [*model.elements, *model.furniture] if e.source_refs]
    with_prov = [e for e in traced if e.provenance and e.pages]
    with_bbox = [e for e in traced if e.provenance and all(p.bbox for p in e.provenance)]
    ids = [e.id for e in [*model.elements, *model.furniture]]
    by_id = model.by_id()

    clauses_per_level = Counter(f"L{_clause_level(c.number or '')}" for c in model.of_type(T.CLAUSE))
    annexes = [
        {"id": a.id, "letter": a.number, "title": a.title,
         "normativity": next((f.split(":", 1)[1] for f in a.hygiene_flags if f.startswith("annex_normativity:")), None),
         "children": len(a.children_ids)}
        for a in model.of_type(T.STANDARD_ANNEX)
    ]  # fmt: skip
    ex = {eid: render_tree(model, eid, max_depth=3) for eid in ("doc/c-1", "doc/c-3") if eid in by_id}

    return TsValidationReport(
        profile=model.profile or "",
        document=model.metadata.title,
        pages=model.source.num_pages,
        metadata=model.metadata.model_dump(exclude_defaults=True),
        accounting={
            "docling_items_total": len(items),
            "missing": acc["missing"],
            "duplicated": acc["duplicated"],
            "text_mismatches": acc["text_mismatches"],
            "segmented_items": acc["segmented"],
            "source_non_whitespace_chars": acc["source_non_whitespace_chars"],
            "accounted_non_whitespace_chars": acc["accounted_non_whitespace_chars"],
            "source_text_repairs": text_repair_check(model, items),
            "exact": not acc["missing"] and not acc["duplicated"] and not acc["text_mismatches"]
            and acc["source_non_whitespace_chars"] == acc["accounted_non_whitespace_chars"]
            and all(s["tiles_item_exactly"] for s in acc["segmented"]),
        },  # fmt: skip
        element_counts=dict(sorted(Counter(e.type.value for e in model.elements).items())),
        clauses_per_level=dict(sorted(clauses_per_level.items())),
        definitions=len(model.of_type(T.DEFINITION)),
        annexes=annexes,
        uncertain=[{"id": e.id, "type": e.type.value, "reasons": e.uncertainty_reasons, "pages": e.pages,
                    "text": e.original_text[:90]} for e in model.elements if e.uncertain],  # fmt: skip
        uncertainty_reason_counts=dict(Counter(r for e in model.elements for r in e.uncertainty_reasons).most_common()),
        warning_counts=dict(Counter(w.code for w in model.warnings)),
        warnings=[w.model_dump() for w in model.warnings],
        warning_category_counts=dict(Counter(w.category or "needs_review" for w in model.warnings)),
        structure_note_counts=dict(Counter(n.code for n in model.structure_notes)),
        structure_notes=[n.model_dump() for n in model.structure_notes],
        provenance_coverage={
            "elements_with_source": len(traced),
            "with_page_provenance": len(with_prov),
            "with_bbox": len(with_bbox),
            "with_partial_item_spans": sum(1 for e in traced if e.source_spans),
        },
        duplicate_ids=sorted({i for i in ids if ids.count(i) > 1}),
        hierarchy_examples=ex,
    )


def ts_report_to_markdown(r: TsValidationReport) -> str:
    L = [f"# Technical-standard validation report: {r.document}", "", f"Profile: `{r.profile}` · pages: {r.pages}", "", "## Metadata", ""]
    L += [f"- {k}: {v}" for k, v in r.metadata.items() if k != "metadata_provenance"]
    L += ["", "## Accounting", ""] + [f"- {k}: {v}" for k, v in r.accounting.items() if k != "segmented_items"]
    L += ["", "## Element counts", ""] + [f"- {k}: {v}" for k, v in r.element_counts.items()]
    L += ["", f"- clauses per level: {r.clauses_per_level}", f"- definitions: {r.definitions}", ""]
    L += ["## Annexes", ""] + [f"- {a['letter']} ({a['normativity']}): {a['title']}" for a in r.annexes]
    L += ["", f"## Uncertain elements ({len(r.uncertain)})", ""] + [f"- {k}: {v}" for k, v in r.uncertainty_reason_counts.items()]
    L += ["", f"## Warnings ({len(r.warnings)})", ""] + [f"- [{w['severity']}] {w['code']}: {w['message']}" for w in r.warnings]
    L += ["", "## Provenance", ""] + [f"- {k}: {v}" for k, v in r.provenance_coverage.items()]
    L += ["", "## Hierarchy examples", ""]
    for k, v in r.hierarchy_examples.items():
        L += [f"### {k}", "", "```", v, "```", ""]
    return "\n".join(L)


def write_ts_outputs(model: DocumentModel, docling_json: Path, out_dir: Path) -> tuple[Path, Path, Path]:
    return write_validation_outputs(model, docling_json, out_dir, build_ts_report, ts_report_to_markdown)
