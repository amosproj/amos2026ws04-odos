from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class ReviewState(StrEnum):  # independent of the processing-job status
    PENDING_REVIEW = "pending_review"
    IN_REVIEW = "in_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"


EditableField = Literal["content_text", "title", "marker"]


class Correction(BaseModel):
    id: str  # "c1", "c2", ...
    element_id: str
    field: EditableField
    original_value: str | None  # value in the original (unreviewed) model
    previous_value: str | None  # effective value just before this correction
    corrected_value: str
    timestamp: datetime
    review_revision: int  # review revision created by this correction
    model_revision: int  # model revision created by this correction
    note: str | None = None
    reviewer: str | None = None


class Confirmation(BaseModel):
    element_id: str
    reasons: list[str]  # the uncertainty reasons the reviewer looked at
    timestamp: datetime
    review_revision: int
    note: str | None = None
    reviewer: str | None = None


class RevisionValidation(BaseModel):
    model_revision: int
    generated: bool
    xsd_valid: bool | None = None
    xsd_errors: list[str] = Field(default_factory=list)
    text_identical_to_reviewed_model: bool | None = None
    document_order_preserved: bool | None = None
    unmapped: int | None = None
    uncorrected_text_differences: list[str] = Field(default_factory=list)  # must be empty: untouched text stays verbatim
    corrected_elements: list[str] = Field(default_factory=list)  # text is the reviewer's, NOT verbatim from the PDF
    blocking_errors: list[str] = Field(default_factory=list)
    xml_sha256: str | None = None
    # document.json, serialized from the same effective model as the XML (None in revisions made before it existed)
    json_valid: bool | None = None
    json_errors: list[str] = Field(default_factory=list)
    json_sha256: str | None = None
    model_sha256: str
    generated_at: datetime
    error: str | None = None


class Export(BaseModel):
    model_revision: int
    xml_sha256: str | None
    xsd_valid: bool | None
    status: Literal["current", "superseded", "approved"]
    created_at: datetime


class Approval(BaseModel):
    review_revision: int
    model_revision: int
    model_sha256: str
    xml_sha256: str
    json_sha256: str | None = None  # absent in approvals recorded before document.json existed
    approved_at: datetime
    note: str | None = None
    reviewer: str | None = None
    confirmed_uncertain: int
    corrections: int


class HistoryEvent(BaseModel):
    at: datetime
    event: str
    review_revision: int
    detail: str | None = None


class ReviewRecord(BaseModel):
    """Persisted review state of one document."""

    state: ReviewState = ReviewState.PENDING_REVIEW
    review_revision: int = 0
    model_revision: int = 0
    base_model_sha256: str
    profile: str | None = None
    retrieval_date: str
    approval: Approval | None = None
    previous_approvals: list[Approval] = Field(default_factory=list)
    exports: list[Export] = Field(default_factory=list)
    history: list[HistoryEvent] = Field(default_factory=list)


class ReviewView(BaseModel):
    """What the API returns."""

    document_id: str
    state: ReviewState
    review_revision: int
    model_revision: int
    profile: str | None
    corrections: list[Correction]
    confirmations: list[Confirmation]
    corrected_element_ids: list[str]
    uncertain_element_ids: list[str]
    unresolved_uncertain_ids: list[str]  # uncertain and neither confirmed nor corrected
    validation: RevisionValidation | None
    can_approve: bool
    approval_blockers: list[str]
    approval: Approval | None
    previous_approvals: list[Approval]
    exports: list[Export]
    original_export_superseded: bool
    structural_editing_supported: bool = False
    editable_fields: list[str] = ["content_text", "title", "marker"]
    history: list[HistoryEvent]


# requests -----------------------------------------------------------------------------------------------
class CorrectionRequest(BaseModel):
    base_revision: int
    element_id: str
    field: str  # validated in the service (structural fields get an explicit 'unsupported' error)
    value: str
    note: str | None = None
    reviewer: str | None = None


class ConfirmRequest(BaseModel):
    base_revision: int
    element_id: str
    note: str | None = None
    reviewer: str | None = None


class DecisionRequest(BaseModel):
    base_revision: int
    note: str | None = None
    reviewer: str | None = None
