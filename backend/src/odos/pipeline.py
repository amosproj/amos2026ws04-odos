"""End-to-end pipeline used by the web API.

Reuses the existing extraction, normalization, AKN generation and validation
functions unchanged; the CLI keeps working on its own.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from odos.artifact_names import DOCLING_MARKDOWN, DOCLING_RAW, EXTRACTION_META
from odos.extraction import extract_pdf
from odos.parsing.engine import parse
from odos.parsing.profiles import LegalProfile, get
from odos.normalization.reading_order import write_evidence


class ProcessingMode(StrEnum):
    EXTRACT_ONLY = "extract_only"  # Docling only; makes no claim about the document type
    GERMAN_LAW = "german_law"  # Docling + German legal structure parser + Akoma Ntoso
    EU_LEGISLATION = "eu_legislation"  # Docling + EU legal structure parser (no Akoma Ntoso yet)


class Outcome(StrEnum):
    COMPLETED = "completed"
    UNSUPPORTED = "unsupported"  # processed, but no structure/XML is offered


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_or_reuse(pdf: Path, out_dir: Path) -> dict:
    """Run Docling once per PDF: reuse docling_raw.json/extracted.md when they belong to this exact file."""
    raw, md, meta = out_dir / DOCLING_RAW, out_dir / DOCLING_MARKDOWN, out_dir / EXTRACTION_META
    sha = _sha256(pdf)
    if raw.is_file() and md.is_file() and meta.is_file():
        try:
            m = json.loads(meta.read_text(encoding="utf-8"))
        except ValueError:
            m = {}
        if m.get("pdf_sha256") == sha:
            doc = json.loads(raw.read_text(encoding="utf-8"))
            return {"pages": len(doc.get("pages", {})), "docling_items": len(doc.get("texts", [])) + len(doc.get("tables", [])),
                    "docling_status": m.get("docling_status", "success"), "docling_warnings": m.get("docling_warnings", []),
                    "extraction_reused": True}  # fmt: skip
    ex = extract_pdf(pdf, out_dir)  # writes docling_raw.json / extracted.md
    meta.write_text(json.dumps({"pdf_sha256": sha, "docling_status": ex.status, "docling_warnings": ex.warnings}), encoding="utf-8")
    return {"pages": ex.pages, "docling_items": ex.text_items + ex.tables, "docling_status": ex.status,
            "docling_warnings": ex.warnings, "extraction_reused": False}  # fmt: skip


class PipelineResult(BaseModel):
    outcome: Outcome
    message: str | None = None
    summary: dict = Field(default_factory=dict)


def run_pipeline(
    pdf: Path, out_dir: Path, mode: ProcessingMode, retrieval_date: str,
    progress: Callable[[str], None] = lambda stage: None,
) -> PipelineResult:  # fmt: skip
    out_dir.mkdir(parents=True, exist_ok=True)
    progress("extracting")
    summary = extract_or_reuse(pdf, out_dir)
    if mode == ProcessingMode.EXTRACT_ONLY:
        return PipelineResult(outcome=Outcome.COMPLETED, summary=summary,
                              message="Extraction only. No legal structure or Akoma Ntoso XML was produced for this mode.")  # fmt: skip

    # PDF text-layer evidence for pages where Docling's layout boxes overlap (read by the parsers to verify
    # and, where provable, repair the reading order; see odos.normalization.reading_order)
    write_evidence(pdf, out_dir / DOCLING_RAW)

    return _run_structured(get(mode), out_dir, summary, progress, retrieval_date)


def _run_structured(profile: LegalProfile, out_dir: Path, summary: dict, progress: Callable[[str], None], retrieval_date: str) -> PipelineResult:  # fmt: skip
    """One run for every legal profile: the shared parsing lifecycle, the profile's reports, document.json and the
    profile's Akoma Ntoso. The profile supplies the structure check, the summary, the AKN generator and the messages."""
    progress("normalizing")
    raw = out_dir / DOCLING_RAW
    model = parse(raw, profile)
    if not profile.has_structure(model):
        return PipelineResult(outcome=Outcome.UNSUPPORTED, summary=summary | profile.unsupported_summary,
                              message=profile.unsupported_message)  # fmt: skip
    profile.write_reports(model, raw, out_dir)
    summary |= _legal_json(model, out_dir)
    summary |= profile.summary(model, raw)
    progress("generating_akn")
    try:
        art = profile.build_akn(model, retrieval_date, out_dir)
    except ValueError as exc:  # e.g. a date or number not printed: metadata is never invented
        return PipelineResult(outcome=Outcome.COMPLETED, summary=summary | {"akn_generated": False},
                              message=profile.akn_refused_message(exc))  # fmt: skip
    summary |= profile.akn_summary(art)
    return PipelineResult(outcome=Outcome.COMPLETED, summary=summary, message=profile.completed_message(art))


def _legal_json(model, out_dir: Path) -> dict:
    from odos.legal_json.artifacts import build_legal_json_artifacts

    rep = build_legal_json_artifacts(model, out_dir / DOCLING_RAW, out_dir)["report"]
    return {"json_valid": rep["valid"], "json_schema_valid": rep["schema_valid"],
            "json_text_identical": rep["text_preservation"]["identical_to_model"]}  # fmt: skip


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
