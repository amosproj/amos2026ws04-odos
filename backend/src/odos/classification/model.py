from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

CLASSIFIER_VERSION = "1.0"

CONFIDENCE_NOTE = (
    "Confidence is a heuristic band, not a probability. high: >= 14 evidence points and >= 8 ahead of the "
    "runner-up; medium: >= 8 points and >= 4 ahead; low: anything else. Points are weights of rule matches, "
    "not statistics."
)


class DocumentType(StrEnum):
    GERMAN_LAW = "german_law"
    GERMAN_MODEL_REGULATION = "german_model_regulation"
    EU_REGULATION = "eu_regulation"
    EU_DIRECTIVE = "eu_directive"
    TECHNICAL_STANDARD = "technical_standard"
    UNKNOWN = "unknown"


class Band(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SupportStatus(StrEnum):
    SUPPORTED = "supported"  # a structured pipeline exists and the evidence is sufficient
    RECOGNISED_NOT_SUPPORTED = "recognised_not_supported"  # type recognised, no pipeline for it yet
    UNCERTAIN = "uncertain"  # a pipeline might fit, but the evidence is too weak to suggest it
    UNSUPPORTED = "unsupported"  # unknown type


class Evidence(BaseModel):
    rule_id: str
    description: str
    supports: list[DocumentType]
    weight: int
    page: int | None = None
    snippet: str | None = None  # the matching text (<= 160 chars), verbatim
    source_ref: str | None = None  # Docling ref ("#/texts/12") or "pdf_text_layer:p<page>:l<line>"
    count: int | None = None  # for count-based rules


class InputInfo(BaseModel):
    source: str  # "pdf_text_layer" | "docling"
    pages_total: int
    pages_scanned: int
    lines: int
    characters: int


class ClassificationResult(BaseModel):
    classifier_version: str = CLASSIFIER_VERSION
    document_type: DocumentType
    suggested_processing_mode: str  # a ProcessingMode value
    candidate_mode: str | None = None  # the mode this type would use if the evidence were sufficient
    confidence_band: Band
    confidence_note: str = CONFIDENCE_NOTE
    support_status: SupportStatus
    supported: bool
    summary: str
    evidence: list[Evidence]
    points: dict[str, int] = Field(description="Heuristic evidence points per candidate type (not probabilities)")
    warnings: list[str] = Field(default_factory=list)
    input: InputInfo
    pdf_sha256: str | None = None
