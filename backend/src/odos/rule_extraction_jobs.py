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
import copy
import logging
import os
import time
from uuid import uuid4
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator, PrivateAttr

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
    InvalidScopeError,
    MalformedOutputError,
    OutputTruncatedError,
    write_rules_json,
)
from odos.llm.document_extraction import extract_document as extract_rules, check_document_request, plan_chunks, prepare_chunk

log = logging.getLogger("odos.rule_extraction_jobs")

RULE_EXTRACTION_STATUS = "rule_extraction.json"  # internal; not one of the served result files
DIAGNOSTICS_DIR = "llm-diagnostics"
MAX_QUEUED_RULE_EXTRACTIONS = int(os.environ.get("ODOS_RULE_EXTRACTION_MAX_QUEUED", "3"))  # each one is a paid call
MAX_ELEMENT_IDS = 100
INTERRUPTED = "The rule extraction was interrupted by a server restart."
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
    maxModelCalls: Literal[1, 3] = 1
    articleIds: list[str] | None = Field(default=None, max_length=MAX_ELEMENT_IDS)
    sampleChunks: Literal[1, 3] | None = None
    sampleSeed: int | None = Field(default=None, ge=0, le=2147483647, strict=True)
    sampleArticleIds: list[str] | None = Field(default=None, min_length=1, max_length=12)
    preserveReviewed: Literal[True] = True
    _context: object = PrivateAttr(default=None)

    @field_validator("maxModelCalls", "sampleChunks", mode="before")
    @classmethod
    def valid_call_limit(cls, value):
        if value is None:
            return value
        if type(value) is not int or value not in (1, 3):
            raise ValueError("maxModelCalls must be the integer 1 or 3")
        return value


class RuleExtraction(BaseModel):
    """What the client sees of a rule extraction. Counts, coverage and review hints come from `_generation` of the
    job's `rules.json`, which holds the full detail (rejected candidates, repairs, flags on each rule)."""

    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    scope: list[str] | Literal["document"] = "document"
    maxModelCalls: Literal[1, 3] | None = None  # unknown for status files from earlier versions
    stopRequested: bool = False
    sampleChunks: Literal[1, 3] | None = None
    requestedAt: str
    startedAt: str | None = None
    finishedAt: str | None = None
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
    reportFile: str | None = None
    workflow: dict = Field(default_factory=dict)

    @classmethod
    def queued(cls, request: RuleExtractionRequest) -> RuleExtraction:
        scope = request.elementIds or "document"
        if request._context is not None and (request.articleIds is not None or request.sampleChunks is not None or request._context["skipped"]):
            scope = [chunk.id for chunk in request._context["chunks"]]
        return cls(status="queued", scope=scope,
                   maxModelCalls=request.maxModelCalls, sampleChunks=request.sampleChunks, requestedAt=_now())

    def mark_running(self) -> None:
        self.status, self.startedAt = "running", _now()


def active(extraction: RuleExtraction | None) -> bool:
    return extraction is not None and extraction.status in ("queued", "running")


# ── status file ───────────────────────────────────────────────────────────────────────────────────────────────────────


def save(directory: Path, extraction: RuleExtraction) -> None:
    """Write the status file atomically."""
    path = directory / RULE_EXTRACTION_STATUS
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
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


STOP_FILE = "rule-extraction.stop"


def plan_request(legal, request, directory=None):
    from odos.llm.incremental import eligible_chunks
    if request._context is not None:
        return request._context
    try:
        scoped, chunks = plan_chunks(legal, request.elementIds)
    except InvalidScopeError:
        raise HTTPException(422, "The selected element IDs are not part of the reduced V2 input.") from None
    previous, reviews, skipped = {}, {}, []
    if directory is not None and (directory / RULE_JSON).is_file():
        from odos import rule_reviews
        try:
            previous = json.loads((directory / RULE_JSON).read_text(encoding="utf-8"))
            if not isinstance(previous, dict) or not isinstance(previous.get("rules"), list):
                raise ValueError("Invalid rules")
        except (ValueError, OSError):
            raise HTTPException(422, "Saved rules cannot be read. They were left unchanged.") from None
        reviews = rule_reviews.review_state(directory.name, directory)
    sample_articles, available_articles = [], []
    if request.articleIds is not None:
        if request.sampleChunks is not None or request.sampleArticleIds is not None:
            raise HTTPException(422, "Choose either explicit articles or the legacy sample scope.")
        from odos.llm.sampling import selected_groups
        chunks, skipped, eligible, sample_articles, available_articles = selected_groups(
            scoped, previous, reviews, request.articleIds)
    elif request.sampleChunks is not None:
        from odos.llm.sampling import sample_groups
        chunks, skipped, eligible, sample_articles = sample_groups(
            scoped, previous, reviews, request.sampleChunks, request.sampleSeed, request.sampleArticleIds)
    else:
        if request.sampleArticleIds is not None:
            raise HTTPException(422, "Article sample IDs require a sample scope.")
        chunks, skipped = eligible_chunks(chunks, previous, reviews)
        eligible = len(chunks)
    return {"chunks": chunks, "previous": previous, "reviews": reviews, "skipped": skipped,
            "eligible": eligible, "sampleArticles": sample_articles, "availableArticles": available_articles}


def preview_request(legal: dict, request: RuleExtractionRequest, directory=None) -> dict:
    """Local prompt preparation only: no client, credentials, inference or result writes."""
    load_bedrock_env()
    try:
        config = BedrockConfig.from_env()
        context = plan_request(legal, request, directory)
        chunks = context["chunks"]
        details = []
        for chunk in chunks:
            try:
                prepared, _ = prepare_chunk(legal, chunk, config)
                details.append({"elementId": chunk.id, "estimatedInputTokens": prepared.estimated_input_tokens,
                                "ready": True})
            except DocumentTooLargeError:
                details.append({"elementId": chunk.id, "estimatedInputTokens": None, "ready": False})
    except InvalidScopeError:
        raise HTTPException(422, "The selected element IDs are not part of the reduced V2 input.") from None
    except BedrockConfigError:
        raise HTTPException(503, "Amazon Bedrock model settings are not configured correctly.") from None
    ready = sum(d["ready"] for d in details)
    return {"inputView": "llm_applicability_input_v2.json", "modelId": config.model_id,
            "scope": request.articleIds if request.articleIds is not None else request.elementIds or "document", "chunks": len(chunks),
            "sampleChunks": request.sampleChunks, "sampleSeed": request.sampleSeed,
            "sampleArticles": context.get("sampleArticles", []),
            "availableArticles": context.get("availableArticles", []),
            "articleIds": request.articleIds,
            "selectedArticleIds": [a["id"] for a in context.get("sampleArticles", [])],
            "protectedChunksSkipped": len(context["skipped"]),
            "eligibleChunks": context["eligible"], "preservedRules": len(context["previous"].get("rules", [])), "readyChunks": ready,
            "blockedChunks": len(chunks) - ready, "canStart": ready > 0,
            "maxModelCalls": request.maxModelCalls, "maximumModelCalls": ready * request.maxModelCalls,
            "estimatedInitialInputTokens": sum(d["estimatedInputTokens"] or 0 for d in details),
            "maximumOutputTokens": ready * request.maxModelCalls * config.max_tokens,
            "outputTokensPerCall": config.max_tokens, "details": details,
            "estimateNote": "Input is an estimate for initial requests, including repeated prompts and reference context. "
                            "Correction input and generated output are unknown."}


def check_request(legal: dict, request: RuleExtractionRequest) -> None:
    """Scope, size and configuration, so that a request that cannot succeed is refused before it is queued."""
    if request.elementIds and any(not isinstance(i, str) or not i or len(i) > 300 for i in request.elementIds):
        raise HTTPException(422, "Element IDs must be non-empty strings.")
    config = bedrock_settings()
    try:
        if request._context is None:
            check_document_request(legal, config, request.elementIds)
        else:
            chunks = request._context["chunks"]
            ready = 0
            for chunk in chunks:
                try:
                    prepare_chunk(legal, chunk, config)
                    ready += 1
                except DocumentTooLargeError:
                    pass
            if not ready:
                raise HTTPException(422, "No eligible targets remain in this selection. Accepted/edited provisions are protected; choose another sample or keep the saved results.")
    except InvalidScopeError:
        raise HTTPException(422, "The selected element IDs are not part of this document.") from None
    except DocumentTooLargeError:
        raise HTTPException(413, "The selected text is too large for the model. Select fewer provisions.") from None


# ── the worker step ───────────────────────────────────────────────────────────────────────────────────────────────────


def bedrock_client() -> BedrockClient:
    """The client of one extraction (replaced in tests)."""
    load_bedrock_env()
    return BedrockClient()


def run(directory: Path, request: RuleExtractionRequest, extraction: RuleExtraction) -> RuleExtraction:
    """Extract, write `rules.json`, and return the finished status. Never raises; an existing `rules.json` is replaced
    only by a successful extraction."""
    began = time.monotonic()
    try:
        legal = json.loads((directory / LEGAL_JSON).read_text(encoding="utf-8"))
        from odos.llm.incremental import merge_previous
        from odos.llm.extraction_workflow import inspect_candidates
        from odos.llm.rule_extraction import PreparedRequest, _write_report
        context = plan_request(legal, request, directory)
        stopped = lambda: (directory / STOP_FILE).exists()
        if stopped():
            extraction.status, extraction.finishedAt = "cancelled", _now()
            extraction.message = "Stopped before extraction started. Existing results are unchanged."
            extraction.stopRequested = True
            return extraction
        client = bedrock_client()
        result = extract_rules(legal, client=client, element_ids=request.elementIds,
                               planned_chunks=context["chunks"], should_stop=stopped,
                               diagnostics_dir=directory / DIAGNOSTICS_DIR, max_model_calls=request.maxModelCalls,
                               accept_partial=os.environ.get("ODOS_RULE_EXTRACTION_ACCEPT_PARTIAL") == "1")
        if context["previous"]:
            snapshot = directory / "extraction-runs" / result.generation["runId"]
            _write_report(context["previous"], snapshot / "previous-rules.json")
            _write_report(context["reviews"], snapshot / "previous-reviews.json")
            result = merge_previous(result, context["previous"], context["reviews"])
        # Recompute combined checks on effective human-edited content. Originals
        # stay unchanged so carried decisions remain bound to the right hashes.
        effective = [result.generation.get("carriedReviews", {}).get(rule.get("id"), {}).get("effectiveRule") or rule
                     for rule in result.rules]
        from odos.llm_input.artifacts import build_inputs
        combined_target = build_inputs(legal)[1]
        prepared = PreparedRequest("", "", "document", legal, 0, client.config.max_tokens, client.config.context_tokens,
                                   target_document=combined_target)
        _, checks = inspect_candidates(effective, legal, prepared, client)
        invalid = [c for c in checks["records"] if c["errors"] or not c["schemaValid"]]
        result.generation["coverage"] = checks["coverage"]
        result.generation["rulesWithIssues"] = invalid
        result.generation["counts"].update({"retained": len(result.rules), "accepted": len(result.rules)-len(invalid),
            "invalid": len(invalid), "flagged": sum(bool(c["flags"]) for c in checks["records"])})
        result.report["combinedChecks"] = checks
        result.generation["workflow"]["schemaValid"] = checks["schemaValid"]
        selection = {"articleIds": request.articleIds, "sampleChunks": request.sampleChunks, "sampleSeed": request.sampleSeed,
                     "sampleArticles": context.get("sampleArticles", []), "selectedChunkIds": [c.id for c in context["chunks"]],
                     "protectedChunkIds": context["skipped"]}
        result.generation["selection"] = result.report["selection"] = selection
        result.generation["workflow"]["sampleChunks"] = request.sampleChunks
        result.generation["workflow"]["protectedChunksSkipped"] = context["skipped"]
        result.generation["modelOutput"]["partial"] |= bool(stopped() or request.sampleChunks is not None or request.articleIds is not None)
        result.report["partial"] = result.generation["modelOutput"]["partial"]
        if result.report["partial"]:
            result.report["outcome"] = result.generation["workflow"]["outcome"] = "completed_with_issues"
        write_rules_json(result, directory / RULE_JSON)
        extraction.stopRequested = stopped()
    except Exception as e:  # noqa: BLE001 - every failure becomes a reported status
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
        extraction.finishedAt = _now()
        return extraction

    g = result.generation
    cov = g["coverage"]
    extraction.status, extraction.finishedAt, extraction.rulesFile = "completed", _now(), RULE_JSON
    extraction.workflow = dict(g.get("workflow", {}))
    extraction.reportFile = extraction.workflow.get("reportFile")
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
                         "rulesWithIssues": g["counts"].get("invalid", 0),
                         "partialModelOutput": out["partial"]}
    extraction.message = (f"{extraction.counts.get('retained', extraction.counts['accepted'])} candidate rules retained as drafts, "
                          f"{extraction.counts.get('invalid', 0)} with validation issues, "
                          f"{extraction.counts['flagged']} flagged for review.")
    if extraction.stopRequested:
        extraction.message = "Stopped. Completed responses and previous rules were saved; this extraction is partial."
    return extraction
