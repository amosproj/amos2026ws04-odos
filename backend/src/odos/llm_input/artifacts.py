"""Create V1/V2 and a separate audit without modifying the original Legal JSON."""
import hashlib
import json
import os
import tempfile
from pathlib import Path

from odos.artifact_names import LLM_INPUT_V1, LLM_INPUT_V2, LLM_INPUT_REPORT
from odos.llm_input.reduction import reduce_document
from odos.llm_input.applicability import apply_applicability


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def build_inputs(legal):
    v1, removed = reduce_document(legal)
    v2, applicability = apply_applicability(v1)
    sizes = {k: len(compact(v)) for k, v in (("original", legal), ("v1", v1), ("v2", v2))}
    report = {"version": 2, "sourceSha256": hashlib.sha256(compact(legal).encode()).hexdigest(),
              "characters": sizes, "estimatedTokens": {k: (v + 2) // 3 for k, v in sizes.items()},
              "estimateNote": "Characters / 3, not a model tokenizer; excludes prompt and output tokens.",
              "reduction": {"removed": removed, "omittedNodeFields": ["germanType", "nativeType", "marker (printed label with type and number)"],
                            "preservedMetadata": ["null values", "empty fields", "pageCount", "pages", "sentence markers and ranges", "footnote markers"]}, "applicability": applicability,
              "note": "Derived project-scope views; consult the original for excluded context and cross-references."}
    return v1, v2, report


def _write(path, value):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".llm-input-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def write_input_artifacts(legal, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    v1, v2, report = build_inputs(legal)
    for name, value in ((LLM_INPUT_V1, v1), (LLM_INPUT_V2, v2), (LLM_INPUT_REPORT, report)):
        _write(directory / name, value)
    return report
