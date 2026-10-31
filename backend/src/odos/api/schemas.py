from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from odos.classification.router import RoutingDecision
from odos.pipeline import Outcome, ProcessingMode


class JobStatus(StrEnum):
    UPLOADED = "uploaded"  # stored, not yet processed
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ArtifactInfo(BaseModel):
    type: str
    filename: str
    media_type: str
    size_bytes: int
    url: str


class DocumentStatus(BaseModel):
    id: str
    filename: str  # sanitised display name only; never used as a path
    size_bytes: int
    uploaded_at: datetime
    status: JobStatus
    stage: str | None = None
    mode: ProcessingMode | None = None
    outcome: Outcome | None = None
    message: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    summary: dict = Field(default_factory=dict)
    routing: RoutingDecision | None = None  # suggested vs chosen mode of the last processing request
    artifacts: list[ArtifactInfo] = Field(default_factory=list)
    # derived on read from the document's own files (never persisted in meta.json)
    document_type: str | None = None  # classification.json: recognised document type
    review_state: str | None = None  # review/review.json: human review state, if a review exists


class ProcessRequest(BaseModel):
    mode: ProcessingMode = Field(description="Explicit processing mode; there is no implicit default.")


class DeletionItem(BaseModel):
    category: str  # original_pdf | generated_artifacts | classification | review | review_archive | metadata | other
    label: str
    files: int
    size_bytes: int
    details: list[str] = Field(default_factory=list)


class DeletionPreview(BaseModel):
    """What deleting one document removes: everything inside its own directory, nothing else."""

    id: str
    filename: str
    can_delete: bool
    blocked_reason: str | None = None
    items: list[DeletionItem]
    total_files: int
    total_bytes: int


class DeleteResult(BaseModel):
    id: str
    filename: str
    deleted: bool
    removed: DeletionPreview


class Akn4EuRequest(BaseModel):
    eli: str | None = Field(default=None, description="The act's ELI if known; checked against the printed type and number, never derived.")  # fmt: skip


class ErrorBody(BaseModel):
    code: str
    message: str


class HealthResponse(BaseModel):
    status: str
    max_upload_mb: float
    queue_capacity: int
    modes: list[str]
