"""Write `document.json` and its validation report (JSON Schema + structural rules + text check)."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

from odos.artifact_names import LEGAL_JSON, LEGAL_JSON_REPORT
from odos.legal_json.exporter import load_source_context, to_legal_json
from odos.legal_json.nesting import validate_structure
from odos.legal_json.legacy import downgrade_information_loss, downgrade_to_1_0
from odos.legal_json.verify import verify_export
from odos.document_model import DocumentModel
from odos.normalization.reading_order import load_evidence
from odos.normalization.source_text import source_fidelity

SCHEMAS = Path(__file__).resolve().parents[3] / "schemas" / "odos-legal-json"
SCHEMA_PATH = SCHEMAS / "1.1" / "legal-document.schema.json"  # generated from the view classes (drift-tested)
SCHEMA_1_0_PATH = SCHEMAS / "1.0" / "legal-document.schema.json"  # frozen: never regenerated


@lru_cache(maxsize=2)
def published_schema(version: str = "1.1") -> dict:
    return json.loads((SCHEMA_PATH if version == "1.1" else SCHEMA_1_0_PATH).read_text(encoding="utf-8"))


def _schema_errors(data: dict, version: str) -> list[str]:
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}"
            for e in Draft202012Validator(published_schema(version)).iter_errors(data)]  # fmt: skip


def serialize(doc) -> bytes:
    return json.dumps(doc.model_dump(mode="json"), indent=2, ensure_ascii=False).encode("utf-8")


def build_legal_json_artifacts(model: DocumentModel, docling_json: Path | None, out_dir: Path) -> dict:
    ctx = load_source_context(docling_json) if docling_json is not None and Path(docling_json).is_file() else None
    doc = to_legal_json(model, ctx)
    data = serialize(doc)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / LEGAL_JSON).write_bytes(data)

    parsed = json.loads(data)
    schema_errors = _schema_errors(parsed, "1.1")
    errors_1_0 = _schema_errors(downgrade_to_1_0(parsed), "1.0")  # a 1.0 consumer still gets a valid document
    structure_errors = validate_structure(doc)
    text = verify_export(model, doc)
    evidence = load_evidence(Path(docling_json)) if docling_json is not None and Path(docling_json).is_file() else None
    fidelity = source_fidelity(model, evidence)
    report = {
        "json_file": LEGAL_JSON,
        "schema": published_schema()["$id"],
        "json_sha256": hashlib.sha256(data).hexdigest(),
        # the canonical model this JSON was serialized from (same bytes as document_model.json / effective_model.json)
        "model_sha256": hashlib.sha256(model.model_dump_json(indent=2).encode("utf-8")).hexdigest(),
        "schema_valid": not schema_errors,
        "schema_errors": schema_errors[:50],
        "downgrade_to_1_0_valid": not errors_1_0,
        "downgrade_to_1_0_errors": errors_1_0[:20],
        # informational: what a 1.0 consumer does not get (1.1 stays the default; this never affects `valid`)
        "downgrade_to_1_0_information_loss": downgrade_information_loss(parsed),
        "structure_valid": not structure_errors,
        "structure_errors": structure_errors[:50],
        # equality with the canonical model only: says nothing about fidelity to the PDF (see source_fidelity)
        "text_preservation": text,
        "source_fidelity": fidelity,
        "page_dimensions_available": bool(doc.pages),
        "footnotes": {"total": len(doc.footnotes), "anchored": sum(bool(f.anchorElementIds) for f in doc.footnotes),
                      "single_anchor": sum(f.anchorElementId is not None for f in doc.footnotes),
                      "references": sum(len(f.references) for f in doc.footnotes),
                      "anchor_unknown": [f.id for f in doc.footnotes if not f.anchorElementIds]},  # fmt: skip
        "sentences": {"total": len(doc.sentences), "with_printed_number": sum(s.number is not None for s in doc.sentences),
                      "spanning_several_nodes": sum(len({r.elementId for r in s.ranges}) > 1 for s in doc.sentences)},  # fmt: skip
        "table_of_contents_entries": {"total": len(doc.tableOfContentsEntries),
                                      "linked": sum(t.targetElementId is not None for t in doc.tableOfContentsEntries)},  # fmt: skip
    }
    report["valid"] = report["schema_valid"] and report["structure_valid"] and text["identical_to_model"] and report["downgrade_to_1_0_valid"]
    (out_dir / LEGAL_JSON_REPORT).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"document": doc, "report": report, "valid": report["valid"], "json_sha256": report["json_sha256"]}
