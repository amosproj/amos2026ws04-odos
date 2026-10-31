"""Validation report for documents parsed with the EU legislation profile."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from pydantic import BaseModel

from odos.normalization.docling_reader import read_docling_json
from odos.parsing.profiles.eu_legislation.recognizer import _key
from odos.document_model import DocumentModel, ElementType as T
from odos.parsing.accounting import content_accounting, render_tree, text_repair_check, write_validation_outputs


class EuValidationReport(BaseModel):
    profile: str
    document: str | None
    pages: int
    metadata: dict
    accounting: dict
    element_counts: dict[str, int]
    sequences: dict[str, dict]
    paragraphs_per_article: dict[str, list[str]]
    uncertain: list[dict]
    uncertainty_reason_counts: dict[str, int]
    warning_counts: dict[str, int]
    warnings: list[dict]
    # what kind of problem each remaining finding is (Phase-6 classification): parser_error |
    # extraction_uncertainty | needs_review for warnings and uncertain elements; valid source structures that
    # are not problems are listed apart as structure notes
    warning_category_counts: dict[str, int] = {}
    uncertainty_category_counts: dict[str, int] = {}
    structure_note_counts: dict[str, int] = {}
    structure_notes: list[dict] = []
    provenance_coverage: dict
    duplicate_ids: list[str]
    hierarchy_examples: dict[str, str]


def _sequence(model: DocumentModel, t: T) -> dict:
    els = model.of_type(t)
    keys = [_key(e) for e in els]
    return {
        "count": len(els),
        "markers": [e.marker for e in els][:3] + (["…"] if len(els) > 6 else []) + [e.marker for e in els][-3:],
        "consecutive_from_1": keys == list(range(1, len(keys) + 1)),
    }


def uncertainty_category(reason: str) -> str:
    """Uncertainty caused by the extraction (layout/text layer) rather than by the legal structure itself."""
    return "extraction_uncertainty" if reason.startswith(("reading_order_", "segment_boundary_")) else "needs_review"


def build_eu_report(model: DocumentModel, docling_json: Path) -> EuValidationReport:
    _, items = read_docling_json(docling_json)
    acc = content_accounting(model, items)
    traced = [e for e in [*model.elements, *model.furniture] if e.source_refs]
    with_prov = [e for e in traced if e.provenance and e.pages]
    with_bbox = [e for e in traced if e.provenance and all(p.bbox for p in e.provenance)]
    ids = [e.id for e in [*model.elements, *model.furniture]]
    by_id = model.by_id()
    paras = {
        a.marker: [by_id[c].marker for c in a.children_ids if by_id[c].type == T.ARTICLE_PARAGRAPH]
        for a in model.of_type(T.ARTICLE)
    }
    ex = {}
    for eid in ("doc/chp-1/art-1", "doc/chp-1/art-2", "doc/chp-2/art-17", "doc/annex-3/part-b/h-1/h-1.1"):
        if eid in by_id:
            ex[eid] = render_tree(model, eid, max_depth=3)
    ex["doc/preamble (first lines)"] = "\n".join(render_tree(model, "doc/preamble", 1).splitlines()[:10])
    md = model.metadata.model_dump(exclude_defaults=True)
    return EuValidationReport(
        profile=model.profile or "",
        document=model.metadata.title,
        pages=model.source.num_pages,
        metadata=md,
        accounting={
            "docling_items_total": len(items),
            "docling_items_missing": acc["missing"],
            "docling_items_duplicated": acc["duplicated"],
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
        sequences={t.value: _sequence(model, t) for t in (T.RECITAL, T.CHAPTER, T.ARTICLE, T.ANNEX)},
        paragraphs_per_article=paras,
        uncertain=[{"id": e.id, "type": e.type.value, "reasons": e.uncertainty_reasons, "pages": e.pages,
                    "text": e.original_text[:90]} for e in model.elements if e.uncertain],  # fmt: skip
        uncertainty_reason_counts=dict(Counter(r for e in model.elements for r in e.uncertainty_reasons).most_common()),
        warning_counts=dict(Counter(w.code for w in model.warnings)),
        warnings=[w.model_dump() for w in model.warnings],
        warning_category_counts=dict(Counter(w.category or "needs_review" for w in model.warnings)),
        uncertainty_category_counts=dict(Counter(
            "extraction_uncertainty" if any(uncertainty_category(r) == "extraction_uncertainty" for r in e.uncertainty_reasons)
            else "needs_review" for e in model.elements if e.uncertain)),
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


def eu_report_to_markdown(r: EuValidationReport) -> str:
    L = [f"# EU validation report: {r.document}", "", f"Profile: `{r.profile}` · pages: {r.pages}", "", "## Metadata", ""]
    L += [f"- {k}: {v}" for k, v in r.metadata.items() if k != "metadata_provenance"]
    L += ["", "## Accounting", ""] + [f"- {k}: {v}" for k, v in r.accounting.items() if k != "segmented_items"]
    L += [f"- segmented items: {[s['ref'] for s in r.accounting['segmented_items']]}"]
    L += ["", "## Sequences", ""] + [f"- {k}: {v}" for k, v in r.sequences.items()]
    L += ["", "## Element counts", ""] + [f"- {k}: {v}" for k, v in r.element_counts.items()]
    L += ["", f"## Uncertain elements ({len(r.uncertain)})", ""] + [f"- {k}: {v}" for k, v in r.uncertainty_reason_counts.items()]
    L += ["", "<details><summary>All uncertain elements</summary>", ""]
    L += [f"- `{u['id']}` p.{u['pages']}: {', '.join(u['reasons'])}" for u in r.uncertain] + ["", "</details>"]
    L += [f"- category {k}: {v}" for k, v in r.uncertainty_category_counts.items()]
    L += ["", f"## Warnings ({len(r.warnings)})", ""] + [f"- [{w['severity']}] [{w.get('category') or 'needs_review'}] {w['code']}: {w['message']}" for w in r.warnings]  # fmt: skip
    L += ["", f"## Valid structural exceptions ({len(r.structure_notes)})", ""]
    L += [f"- {n['code']} `{n.get('element_id')}`: {n['message']}" for n in r.structure_notes]
    L += ["", "## Provenance", ""] + [f"- {k}: {v}" for k, v in r.provenance_coverage.items()]
    L += ["", "## Hierarchy examples", ""]
    for k, v in r.hierarchy_examples.items():
        L += [f"### {k}", "", "```", v, "```", ""]
    return "\n".join(L)


def write_eu_outputs(model: DocumentModel, docling_json: Path, out_dir: Path) -> tuple[Path, Path, Path]:
    return write_validation_outputs(model, docling_json, out_dir, build_eu_report, eu_report_to_markdown)
