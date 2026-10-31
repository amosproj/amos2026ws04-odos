"""German-law Akoma Ntoso artifacts: the XML (a § excerpt, or the whole body), its official-XSD validation report
and the traceability file. The EU counterpart is `akn.eu_artifacts`."""

from __future__ import annotations

import json
from pathlib import Path

from odos.akn.generator import generate_excerpt
from odos.akn.validate import validate_xml
from odos.akn.verify import verify_text
from odos.artifact_names import AKN_REPORT, AKN_TRACEABILITY
from odos.document_model import DocumentModel


def build_artifacts(model: DocumentModel, paragraphs: list[str], retrieval_date: str, out: Path, xml_name: str = "bdsg_excerpt.xml", undated_policy: str = "refuse") -> dict:
    result = generate_excerpt(model, paragraphs, retrieval_date, undated_policy=undated_policy)
    out.mkdir(parents=True, exist_ok=True)
    xml_path = out / xml_name
    xml_path.write_bytes(result.xml)
    validation = validate_xml(result.xml)  # real XSD validation of the bytes just written
    text = verify_text(model, result)

    report = validation.model_dump()
    report["xml_file"] = xml_path.name
    report["excerpt"] = result.excerpt
    report["generator_warnings"] = result.warnings
    report["unmapped"] = result.unmapped
    report["text_preservation"] = text
    (out / AKN_REPORT).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    trace = {
        "excerpt": result.excerpt,
        "xml_sha256": validation.xml_sha256,
        "source": model.source.model_dump(),
        "nodes": [e.model_dump() for e in result.entries],
        "included_model_elements": result.included_ids,
        "excluded_model_elements": {k: v for k, v in result.excluded.items()},
        "excluded_counts": {k: len(v) for k, v in result.excluded.items()},
        "uncertain": [e.model_dump(include={"model_id", "eId", "uncertainty_reasons", "original_text"}) for e in result.entries if e.uncertain],
        "unmapped": result.unmapped,
    }  # fmt: skip
    (out / AKN_TRACEABILITY).write_text(json.dumps(trace, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"result": result, "validation": validation, "text": text, "dir": out}
