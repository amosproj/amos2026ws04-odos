"""EU Akoma Ntoso artifacts: XML, XSD validation report, traceability, text-preservation report."""

from __future__ import annotations

import json
from pathlib import Path

from odos.akn.eu_generator import NOTES, generate_eu_akn
from odos.akn.validate import validate_xml
from odos.akn.verify import verify_text
from odos.artifact_names import AKN_REPORT, AKN_TEXT_REPORT, AKN_TRACEABILITY, AKN_XML
from odos.document_model import DocumentModel, ElementType as T



def text_preservation(model: DocumentModel, result) -> dict:
    """Text and order of the XML compared with the Internal Document Model (and through it, with Docling)."""
    t = verify_text(model, result)
    included = set(result.included_ids)
    model_order = [e.id for e in model.elements if e.id in included and e.type not in NOTES]
    xml_order = [i for i in result.included_ids if model.by_id()[i].type not in NOTES]
    by_type: dict[str, int] = {}
    for i in result.included_ids:
        k = model.by_id()[i].type.value
        by_type[k] = by_type.get(k, 0) + 1
    return {
        **t,
        "document_order_preserved": model_order == xml_order,
        "elements_in_xml": len(result.included_ids),
        "elements_in_xml_by_type": dict(sorted(by_type.items())),
        "elements_not_in_xml": {k: len(v) for k, v in result.excluded.items()},
        "unmapped": result.unmapped,
        "counts": {
            "recitals": len([i for i in result.included_ids if model.by_id()[i].type == T.RECITAL]),
            "chapters": len([i for i in result.included_ids if model.by_id()[i].type == T.CHAPTER]),
            "articles": len([i for i in result.included_ids if model.by_id()[i].type == T.ARTICLE]),
            "annexes": len([i for i in result.included_ids if model.by_id()[i].type == T.ANNEX]),
        },
    }


def build_eu_akn_artifacts(model: DocumentModel, retrieval_date: str, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    result = generate_eu_akn(model, retrieval_date)
    xml_path = out / AKN_XML
    xml_path.write_bytes(result.xml)  # written even if invalid: it is the diagnostic output
    validation = validate_xml(result.xml)
    text = text_preservation(model, result)

    report = validation.model_dump()
    report |= {"xml_file": xml_path.name, "profile": "eu_legislation", "scope": result.excerpt,
               "generator_warnings": result.warnings, "unmapped": result.unmapped,
               "text_preservation_summary": {k: text[k] for k in ("same_order_and_text", "document_order_preserved",
                                                                   "atoms_expected", "atoms_in_xml", "characters_compared")}}  # fmt: skip
    (out / AKN_REPORT).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / AKN_TEXT_REPORT).write_text(json.dumps(text, indent=2, ensure_ascii=False), encoding="utf-8")
    trace = {
        "profile": "eu_legislation",
        "xml_sha256": validation.xml_sha256,
        "source": model.source.model_dump(),
        "nodes": [e.model_dump() for e in result.entries],
        "included_model_elements": result.included_ids,
        "excluded_model_elements": result.excluded,
        "excluded_counts": {k: len(v) for k, v in result.excluded.items()},
        "uncertain": [e.model_dump(include={"model_id", "eId", "uncertainty_reasons", "original_text", "source_spans"})
                      for e in result.entries if e.uncertain],  # fmt: skip
        "unmapped": result.unmapped,
    }
    (out / AKN_TRACEABILITY).write_text(json.dumps(trace, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"result": result, "validation": validation, "text": text}
