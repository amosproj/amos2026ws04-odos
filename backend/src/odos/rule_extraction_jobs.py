"""Rule extraction as part of an API job (`odos.api`): request validation, the worker step and the status file.

The API's job is the processed document; a rule extraction is a step on it, not a second job system. Its state
(`RuleExtraction`) lives on the job and in a status file in the job directory (`RULE_EXTRACTION_STATUS`), so it is
restored with the job after a restart (an extraction that was running then is reported as interrupted). The database
schema is not changed. The Rule JSON is the job's `rules.json` artifact (`odos.artifact_names.RULE_JSON`).

Nothing here puts document text, model output or credentials into a status, an error message or the log: errors are
reported as a fixed message per error class plus a code. Unusable model answers are kept in the job directory under
`DIAGNOSTICS_DIR` (0700/0600, never served).
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field

from odos.artifact_names import LEGAL_JSON, RULE_JSON
from odos.llm.bedrock import (
    API_KEY_ENV,
    BedrockAuthError,
    BedrockClient,
    BedrockConfig,
    BedrockConfigError,
    BedrockContextLimitError,
    BedrockError,
    BedrockRequestError,
    BedrockResponseError,
    BedrockThrottledError,
    BedrockTimeoutError,
    BedrockUnavailableError,
    load_bedrock_env,
)
from odos.llm.rule_extraction import (
    DocumentTooLargeError,
    ExtractionCancelled,
    ExtractionResult,
    InvalidScopeError,
    MalformedOutputError,
    OutputTruncatedError,
    extract_rules,
    prepare_request,
    write_rules_json,
)

log = logging.getLogger("odos.rule_extraction_jobs")

RULE_EXTRACTION_STATUS = "rule_extraction.json"  # internal; not one of the served result files
DIAGNOSTICS_DIR = "llm-diagnostics"
MAX_QUEUED_RULE_EXTRACTIONS = int(os.environ.get("ODOS_RULE_EXTRACTION_MAX_QUEUED", "3"))  # each one is a paid call
MAX_ELEMENT_IDS = 100
INTERRUPTED = "The rule extraction was interrupted by a server restart."
CANCELLED = "Finding rules was cancelled."
CANCELLED_CHARGED = "Finding rules was cancelled. A request that had already started may still be charged."
REVIEW = {"status": "draft", "humanReviewRequired": True,
          "reason": "LLM-generated drafts; no rule is a legal compliance decision until a person has reviewed it."}

# error class -> (code, message for the client); checked in order, the first match wins
ERRORS: tuple[tuple[type[Exception], str, str], ...] = (
    (BedrockConfigError, "not_configured", "Amazon Bedrock is not configured on the server."),
    (BedrockAuthError, "bedrock_auth", "Amazon Bedrock rejected the credentials or the model access."),
    (BedrockThrottledError, "bedrock_throttled", "Amazon Bedrock is busy. Try again later."),
    (BedrockTimeoutError, "bedrock_timeout", "Amazon Bedrock did not answer in time."),
    (BedrockUnavailableError, "bedrock_unavailable", "Amazon Bedrock is not available."),
    (BedrockContextLimitError, "too_large", "The selected text is too large for the model. Select fewer provisions."),
    (BedrockRequestError, "bedrock_request", "Amazon Bedrock rejected the request (model or region)."),
    (BedrockResponseError, "model_response", "Amazon Bedrock returned no usable answer."),
    (DocumentTooLargeError, "too_large", "The selected text is too large for the model. Select fewer provisions."),
    (OutputTruncatedError, "output_truncated", "The answer exceeded the output limit. Select fewer provisions."),
    (MalformedOutputError, "malformed_output",
     "The model's answer was not valid JSON (also after the allowed retry); nothing was used. It was kept for diagnosis on the server."),
    (InvalidScopeError, "invalid_scope", "The selected element IDs are not part of this document."),
    (BedrockError, "bedrock_error", "The Amazon Bedrock request failed."),
)
FAILED = ("internal", "The rule extraction failed.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RuleExtractionRequest(BaseModel):
    """Body of `POST /api/jobs/{id}/rule-extraction`; without `elementIds` the whole document is sent."""

    model_config = {"extra": "forbid"}
    elementIds: list[str] | None = Field(default=None, min_length=1, max_length=MAX_ELEMENT_IDS)


class RuleExtraction(BaseModel):
    """What the client sees of a rule extraction. Counts, coverage and review hints come from `_generation` of the
    job's `rules.json`, which holds the full detail (rejected candidates, repairs, flags on each rule)."""

    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    scope: list[str] | Literal["document"] = "document"
    requestedAt: str
    startedAt: str | None = None
    finishedAt: str | None = None
    runId: str = ""  # identifies this run so a late result cannot overwrite a newer one
    stage: Literal["preparing", "finding", "checking"] | None = None  # real phases of the one request; no section counts
    cancelRequested: bool = False
    externalRequestStarted: bool = False  # true only after a model request has actually been sent
    message: str | None = None
    errorCode: str | None = None
    errorDetail: dict = Field(default_factory=dict)  # failed only: awsCode, httpStatus, cause, retryAttempts, elapsedSeconds
    modelId: str | None = None
    promptVersion: str | None = None
    counts: dict = Field(default_factory=dict)  # proposed, accepted, rejected, repaired, flagged
    coverage: dict = Field(default_factory=dict)  # counts and the IDs of uncited sentences/elements
    modelOutput: dict = Field(default_factory=dict)  # requests, parse mode, partial, number of kept diagnostics
    review: dict = Field(default_factory=lambda: dict(REVIEW))
    rulesFile: str | None = None  # RULE_JSON once completed

    @classmethod
    def queued(cls, request: RuleExtractionRequest) -> RuleExtraction:
        return cls(status="queued", scope=request.elementIds or "document", requestedAt=_now(),
                   runId=uuid.uuid4().hex, stage="preparing")

    def mark_running(self) -> None:
        self.status, self.startedAt = "running", self.startedAt or _now()

    def mark_cancelled(self) -> None:
        """Terminal cancelled state. Does not touch `rules.json` or any other job's files."""
        self.status, self.stage, self.finishedAt = "cancelled", None, _now()
        self.rulesFile = None
        self.errorCode = "cancelled"
        self.message = CANCELLED_CHARGED if self.externalRequestStarted else CANCELLED


def active(extraction: RuleExtraction | None) -> bool:
    return extraction is not None and extraction.status in ("queued", "running")


# ── status file ───────────────────────────────────────────────────────────────────────────────────────────────────────


def save(directory: Path, extraction: RuleExtraction) -> None:
    """Write the status file atomically."""
    path = directory / RULE_EXTRACTION_STATUS
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(extraction.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def restore(directory: Path) -> RuleExtraction | None:
    """The stored status of a job's rule extraction; one that was queued or running is marked as interrupted."""
    path = directory / RULE_EXTRACTION_STATUS
    if not path.is_file():
        return None
    try:
        extraction = RuleExtraction.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("unreadable rule extraction status in %s", path.parent.name)
        return None
    if active(extraction):
        if extraction.cancelRequested:
            extraction.mark_cancelled()  # a restart finished the cancellation; nothing new is written
        else:
            extraction.status, extraction.finishedAt = "failed", _now()
            extraction.errorCode, extraction.message = "interrupted", INTERRUPTED
        try:
            save(directory, extraction)
        except OSError:
            log.exception("could not store the interrupted rule extraction of %s", path.parent.name)
    return extraction


# ── request validation (in the HTTP request, before anything is queued or paid for) ─────────────────────────────────


def load_legal_json(directory: Path) -> dict:
    path = directory / LEGAL_JSON
    if not path.is_file():
        raise HTTPException(404, "The Legal JSON of this job is no longer available.")
    try:
        legal = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(422, "The Legal JSON of this job cannot be read.") from None
    if not isinstance(legal, dict) or not legal.get("structure"):
        raise HTTPException(422, "The Legal JSON of this job has no structure to extract rules from.")
    from odos.llm_input.artifacts import write_input_artifacts
    write_input_artifacts(legal, directory)
    return legal


def bedrock_settings() -> BedrockConfig:
    """The Bedrock configuration (from the environment and the Bedrock lines of .env); 503 if it is incomplete."""
    load_bedrock_env()
    try:
        config = BedrockConfig.from_env()
    except BedrockConfigError as e:
        log.warning("Bedrock configuration rejected: %s", e)
        raise HTTPException(503, "Amazon Bedrock is not configured correctly on the server.") from None
    if not (os.environ.get(API_KEY_ENV) or "").strip():
        raise HTTPException(503, "Rule extraction is not available: Amazon Bedrock is not configured on the server.")
    return config


def check_request(legal: dict, request: RuleExtractionRequest) -> None:
    """Scope, size and configuration, so that a request that cannot succeed is refused before it is queued."""
    if request.elementIds and any(not isinstance(i, str) or not i or len(i) > 300 for i in request.elementIds):
        raise HTTPException(422, "Element IDs must be non-empty strings.")
    config = bedrock_settings()
    try:
        prepare_request(legal, config, request.elementIds)
    except InvalidScopeError:
        raise HTTPException(422, "The selected element IDs are not part of this document.") from None
    except DocumentTooLargeError:
        raise HTTPException(413, "The selected text is too large for the model. Select fewer provisions.") from None


# ── the worker step ───────────────────────────────────────────────────────────────────────────────────────────────────


def save_rules(result: ExtractionResult, directory: Path) -> None:
    """Write `rules.json` atomically. Callers do this only for a run they have just accepted."""
    write_rules_json(result, directory / RULE_JSON)


def bedrock_client() -> BedrockClient:
    """The client of one extraction (replaced in tests)."""
    load_bedrock_env()
    return BedrockClient()


def run(directory: Path, request: RuleExtractionRequest, extraction: RuleExtraction, *,
        client: BedrockClient | None = None, should_stop: Callable[[], bool] | None = None,
        on_stage: Callable[[str], None] | None = None, on_request: Callable[[], None] | None = None) -> ExtractionResult | None:
    """Extract and return the records to write, or None when the run failed or was cancelled.

    Does not write `rules.json`: the caller writes it only after it has checked, under its own lock, that the run was
    not cancelled. Never raises. An existing `rules.json` is therefore replaced only by a successful extraction the
    caller still accepts."""
    began = time.monotonic()
    try:
        if should_stop is not None and should_stop():
            raise ExtractionCancelled()
        legal = json.loads((directory / LEGAL_JSON).read_text(encoding="utf-8"))
        result = extract_rules(legal, client=client or bedrock_client(), element_ids=request.elementIds,
                               diagnostics_dir=directory / DIAGNOSTICS_DIR,
                               accept_partial=os.environ.get("ODOS_RULE_EXTRACTION_ACCEPT_PARTIAL") == "1",
                               should_stop=should_stop, on_stage=on_stage, on_request=on_request)
        if should_stop is not None and should_stop():
            raise ExtractionCancelled()
    except ExtractionCancelled:
        extraction.mark_cancelled()
        return None
    except Exception as e:  # noqa: BLE001 - every failure becomes a reported status
        if should_stop is not None and should_stop():
            extraction.mark_cancelled()  # the connection was closed; the answer is not a failure and is not saved
            return None
        code, message = next(((c, m) for cls, c, m in ERRORS if isinstance(e, cls)), FAILED)
        detail = {**(e.diagnostics() if isinstance(e, BedrockError) else {}), "elapsedSeconds": round(time.monotonic() - began)}
        if code == "internal":
            log.exception("rule extraction in %s failed", directory.name)
        else:  # class, code and the AWS facts only: messages of model or document errors stay out of the log
            log.warning("rule extraction in %s failed: %s (%s) %s", directory.name, type(e).__name__, code,
                        " ".join(f"{k}={v}" for k, v in detail.items()))
        extraction.status, extraction.errorCode, extraction.message = "failed", code, message
        extraction.errorDetail = detail
        if isinstance(e, MalformedOutputError):
            extraction.modelOutput = {"diagnostics": len(e.diagnostic_ids)}
        extraction.stage, extraction.finishedAt = None, _now()
        return None

    g = result.generation
    cov = g["coverage"]
    extraction.status, extraction.stage, extraction.finishedAt = "completed", None, _now()
    extraction.rulesFile = RULE_JSON
    extraction.modelId, extraction.promptVersion = g["modelId"], g["promptVersion"]
    extraction.counts = dict(g["counts"])
    extraction.coverage = {
        "sentences": cov["sentences"], "sentencesCited": cov["sentencesCited"],
        "elements": cov["elements"], "elementsCited": cov["elementsCited"],
        "uncitedSentenceIds": [u["id"] for u in cov["uncitedSentences"]],
        "uncitedElementIds": [u["id"] for u in cov["uncitedElements"]],
        "citedOnlyByRejected": cov["citedOnlyByRejected"],
        "coveredByExceptionTextIds": [c["id"] for c in cov.get("coveredByExceptionText", [])],  # text match, not verified provenance
    }
    out = g["modelOutput"]
    extraction.modelOutput = {"requests": out["requests"], "parse": out["parse"], "partial": out["partial"],
                              "diagnostics": len(out["diagnostics"])}
    extraction.review = {**REVIEW, "rulesFlagged": g["counts"]["flagged"], "rulesRejected": g["counts"]["rejected"],
                         "partialModelOutput": out["partial"]}
    extraction.message = (f"{extraction.counts['accepted']} rules accepted as drafts, {extraction.counts['rejected']} rejected, "
                          f"{extraction.counts['flagged']} flagged for review.")
    return result
