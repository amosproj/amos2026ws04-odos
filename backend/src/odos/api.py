"""Thin web API over the pipeline (`uvicorn odos.api:app`): upload a PDF, poll its job, read the results.

A single-instance development MVP: jobs live in memory and run one at a time in a background thread (Docling is
slow and memory-hungry). Each job writes the usual `odos process` files into its own directory under
ODOS_STORAGE_DIR (default: a temporary directory, removed at shutdown). Every upload runs the real pipeline
(`run_pipeline`, which recognizes German or EU legislation from the document's own structure); no precomputed result
is ever substituted.

With ODOS_DATABASE_ENABLED=1 (PostgreSQL proof of concept, see Documentation/database-poc.md) every job is also
recorded in the `documents` table (status, summary and Legal JSON as JSONB), the uploaded PDF and the result files
stay in ODOS_STORAGE_DIR, and the jobs are restored at startup. Run a single API process only: the job registry
and the worker are per process.

Rule extraction (optional, Amazon Bedrock, paid): `POST /api/jobs/{id}/rule-extraction` starts it for a completed job
from the job's Legal JSON artifact (`document.json`) and returns at once; the model call runs in its own single-worker
executor (one paid extraction at a time, at most `MAX_QUEUED_RULE_EXTRACTIONS` waiting), outside the request. Its state
is part of the job (`ruleExtraction`, also `GET /api/jobs/{id}/rule-extraction`) and is kept as a status file in the
job directory (`RULE_EXTRACTION_STATUS`, restored with the job; the database schema is unchanged). The result is the
job's `rules.json` artifact, served like the other result files. Unusable model answers are kept for diagnosis in the
job directory (`llm-diagnostics/`, never served).

Human review of the extracted rules (needs the database and `backend/db/002_rule_reviews.sql`): `GET/POST /api/jobs/{id}/rule-reviews`,
`GET .../rule-reviews/history` and `GET .../rule-reviews/approved-export`. Decisions are append-only events in PostgreSQL bound to one
extraction and one record hash; `rules.json` is never modified (Documentation/review-state-design.md).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
import urllib.parse
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

import psycopg
from fastapi import Body, FastAPI, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, computed_field

from odos.artifact_names import DOCUMENT_MODEL, LEGAL_JSON, DOCLING_RAW, RULE_JSON, LLM_INPUT_V1, LLM_INPUT_V2, LLM_INPUT_REPORT
from odos.llm_input.artifacts import write_input_artifacts
from odos.pipeline import Outcome, run_pipeline
from odos import rule_extraction_jobs as rx
from odos import rule_reviews as rv
from odos.document_repository import (
    create_document,
    delete_document,
    ensure_cancelled_status,
    finish_document,
    get_pdf_storage_key,
    list_documents,
    list_recent_documents,
    mark_interrupted_jobs,
    update_document_status,
)

log = logging.getLogger("odos.api")


def _log_odos_messages() -> None:
    """Uvicorn configures only its own loggers, so the INFO lines of `odos.*` (Bedrock request outcome and token counts,
    no document text) were not shown in the server log. Give them a handler when the process has none."""
    odos = logging.getLogger("odos")
    if not odos.handlers and not logging.getLogger().handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
        odos.addHandler(handler)
        odos.setLevel(logging.INFO)
        odos.propagate = False


_log_odos_messages()

MAX_UPLOAD_BYTES = int(os.environ.get("ODOS_MAX_UPLOAD_MB", "50")) * 1024 * 1024
MAX_JOBS = 10  # when a new job comes in, the oldest finished ones beyond this are deleted with their files
# the job files the frontend reads; nothing else in a job directory is served
RESULT_FILES = (DOCUMENT_MODEL, LEGAL_JSON, DOCLING_RAW, RULE_JSON, LLM_INPUT_V1, LLM_INPUT_V2, LLM_INPUT_REPORT, "rule_extraction_report.json")
SOURCE_PDF = "source.pdf"  # the uploaded PDF inside a job directory; kept only with database persistence
FAILED_MESSAGE = "The PDF could not be processed. It may be damaged, encrypted or a scanned image without a text layer."
NOT_STORED_MESSAGE = "The PDF was processed, but its result could not be stored in the database."
DATABASE_UNAVAILABLE = "The ODOS database is not available. Check that PostgreSQL is running and try again."
CANCELLED_DOCUMENT = "Processing was cancelled."


class JobCancelled(Exception):
    pass


def _persistent() -> bool:
    return os.environ.get("ODOS_DATABASE_ENABLED") == "1"


class Job(BaseModel):
    id: str
    filename: str  # the uploaded file's name, for display and the download name only
    status: Literal["queued", "processing", "completed", "unsupported", "failed", "cancelled"] = "queued"
    stage: str | None = None  # while processing: run_pipeline's progress ("extracting", "normalizing")
    message: str | None = None
    summary: dict = Field(default_factory=dict)  # run_pipeline's summary (pages, counts, json_schema_valid, ...)
    cancelRequested: bool = False  # set when the user asks to stop document processing
    ruleExtraction: rx.RuleExtraction | None = None  # the latest LLM rule extraction of this job, if one was started

    @computed_field
    @property
    def persistent(self) -> bool:
        """Kept in the database: the frontend then leaves the job in place instead of deleting it when done."""
        return _persistent()


class StoredDocument(BaseModel):
    """A document of the database as listed on the upload page: metadata only."""

    id: str
    filename: str
    status: Literal["queued", "processing", "completed", "unsupported", "failed", "cancelled"]
    created_at: datetime


_jobs: dict[str, Job] = {}
_lock = threading.Lock()
_storage = Path()
_executor = ThreadPoolExecutor(max_workers=1)
_rule_executor = ThreadPoolExecutor(max_workers=1)  # paid Bedrock calls: one at a time, never alongside each other
_rule_run_ids: dict[str, str] = {}  # job_id -> active runId; used by should_stop to detect superseded runs
_doc_futures: dict[str, Future] = {}  # job_id -> document processing future; used to cancel queued jobs immediately


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _storage, _executor, _rule_executor
    configured = os.environ.get("ODOS_STORAGE_DIR")

    if _persistent() and not configured:
        raise RuntimeError(
            "ODOS_STORAGE_DIR is required when database persistence is enabled."
        )

    _storage = Path(configured) if configured else Path(
        tempfile.mkdtemp(prefix="odos-jobs-")
    )
    _storage.mkdir(parents=True, exist_ok=True)
    _executor = ThreadPoolExecutor(max_workers=1)
    _rule_executor = ThreadPoolExecutor(max_workers=1)

    with _lock:
        _jobs.clear()
        _doc_futures.clear()
        if _persistent():
            try:
                ensure_cancelled_status()
            except Exception:  # best effort: a database that is down is reported by the requests that need it
                log.exception("could not allow the 'cancelled' document status; apply backend/db/003_cancelled_status.sql")
            mark_interrupted_jobs()
            for row in list_documents():
                job = Job(**row)
                job.ruleExtraction = rx.restore(_storage / job.id)  # an extraction cut off by the restart is failed
                _jobs[job.id] = job

    try:
        yield
    finally:
        # queued jobs are cancelled (with the database they are marked as interrupted at the next start); with the
        # database the running job is awaited so that its result is stored
        _executor.shutdown(wait=_persistent(), cancel_futures=True)
        _rule_executor.shutdown(wait=_persistent(), cancel_futures=True)

        if not _persistent():
            for job_id in list(_jobs):
                _remove(job_id)
            if not configured:
                shutil.rmtree(_storage, ignore_errors=True)


app = FastAPI(title="ODOS", lifespan=lifespan)


@app.post("/api/jobs", status_code=202)
def create_job(file: UploadFile = File(...)) -> Job:
    job = Job(id=uuid.uuid4().hex, filename=Path(file.filename or "document.pdf").name[:200])
    pdf = _storage / job.id / SOURCE_PDF
    pdf.parent.mkdir(parents=True)
    try:
        _save_pdf(file, pdf)
    except HTTPException:
        shutil.rmtree(pdf.parent, ignore_errors=True)
        raise
    if _persistent():
        try:
            create_document(job.id, job.filename, f"{job.id}/{SOURCE_PDF}")  # relative to ODOS_STORAGE_DIR
        except psycopg.Error as e:
            shutil.rmtree(pdf.parent, ignore_errors=True)
            log.exception("could not register job %s", job.id)
            raise HTTPException(503, DATABASE_UNAVAILABLE) from e
        except Exception:
            shutil.rmtree(pdf.parent, ignore_errors=True)
            raise

    with _lock:
        finished = [j for j in _jobs.values() if j.status in ("completed", "unsupported", "failed") and not rx.active(j.ruleExtraction)]
        if not _persistent():
            for old in finished[: max(0, len(_jobs) + 1 - MAX_JOBS)]:
                _remove(old.id)
        _jobs[job.id] = job
    queued = job.model_copy()  # as created: the worker may already be changing `job`
    future = _executor.submit(_process, job, pdf)
    _doc_futures[job.id] = future
    return queued


@app.get("/api/documents")
def list_stored_documents() -> list[StoredDocument]:
    """The most recently stored documents (newest first); empty without database persistence."""
    if not _persistent():
        return []
    try:
        return [StoredDocument(**row) for row in list_recent_documents()]
    except psycopg.Error as e:
        log.exception("could not list documents")
        raise HTTPException(503, DATABASE_UNAVAILABLE) from e


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> Job:
    return _job(job_id)


@app.get("/api/jobs/{job_id}/files/{name}")
def get_file(job_id: str, name: str, download: bool = False) -> FileResponse:
    """A result file of a completed job; `download` offers it as an attachment named after the uploaded PDF."""
    job = _job(job_id)
    if name not in RESULT_FILES:
        raise HTTPException(404, "No such result file.")
    if job.status != "completed":
        raise HTTPException(409, "The job has no results.")
    path = _storage / job.id / name
    if name in (LLM_INPUT_V1, LLM_INPUT_V2, LLM_INPUT_REPORT):
        original = _storage / job.id / LEGAL_JSON
        if original.is_file():
            write_input_artifacts(json.loads(original.read_text(encoding="utf-8")), original.parent)
    if not path.is_file():  # e.g. a restored job whose files were removed or live under another ODOS_STORAGE_DIR
        raise HTTPException(404, "The result file is no longer available.")
    filename = None
    if download:
        suffix = {RULE_JSON: ".rules.json", LLM_INPUT_V1: ".llm-input-v1.json",
                  LLM_INPUT_V2: ".llm-applicability-input-v2.json",
                  LLM_INPUT_REPORT: ".llm-input-report.json",
                  "rule_extraction_report.json": ".report.json"}.get(name, ".legal.json")
        filename = f"{Path(job.filename).stem}{suffix}"
    return FileResponse(path, media_type="application/json", filename=filename)


@app.get("/api/jobs/{job_id}/pdf")
def get_pdf(job_id: str) -> FileResponse:
    """The original PDF of a completed, stored document (what the viewer shows beside the recognized structure)."""
    job = _job(job_id)
    if job.status != "completed":
        raise HTTPException(409, "The job has no results.")
    path = _stored_pdf(job.id)
    if path is None:  # without persistence the upload is deleted after processing
        raise HTTPException(404, "The original PDF is no longer available.")
    return FileResponse(path, media_type="application/pdf", filename=job.filename, content_disposition_type="inline")


@app.post("/api/jobs/{job_id}/rule-extraction/preview")
def preview_rule_extraction(job_id: str, request: rx.RuleExtractionRequest | None = Body(default=None)) -> dict:
    """Prepare the V2 extraction estimate without starting or charging for inference."""
    with _lock:
        job = _job(job_id)
        if job.status != "completed":
            raise HTTPException(409, "Rules can only be previewed for a completed job.")
        directory = _storage / job.id
    # Do not regenerate/write artifacts or change extraction status for a preview.
    path = directory / LEGAL_JSON
    if not path.is_file():
        raise HTTPException(404, "The Legal JSON of this job is no longer available.")
    try:
        legal = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(422, "The Legal JSON of this job cannot be read.") from None
    if not isinstance(legal, dict) or not legal.get("structure"):
        raise HTTPException(422, "The Legal JSON of this job has no structure to extract rules from.")
    return _review_db(lambda: rx.preview_request(legal, request or rx.RuleExtractionRequest(), directory))


@app.post("/api/jobs/{job_id}/rule-extraction", status_code=202)
def start_rule_extraction(job_id: str, request: rx.RuleExtractionRequest | None = Body(default=None)) -> rx.RuleExtraction:
    """Start an LLM rule extraction (Amazon Bedrock, paid) from the job's Legal JSON; poll the job or
    `GET /api/jobs/{id}/rule-extraction` for its status. The rules become the job's `rules.json` (drafts for review)."""
    request = request or rx.RuleExtractionRequest()
    with _lock:
        job = _job(job_id)
        if job.status != "completed":
            raise HTTPException(409, "Rules can only be extracted from a completed job.")
        if rx.active(job.ruleExtraction):
            raise HTTPException(409, "A rule extraction of this job is already queued or running.")
        if sum(rx.active(j.ruleExtraction) for j in _jobs.values()) >= rx.MAX_QUEUED_RULE_EXTRACTIONS:
            raise HTTPException(429, "Too many rule extractions are waiting. Try again when one has finished.")
        directory = _storage / job.id
        legal = rx.load_legal_json(directory)  # HTTPException 404/422
        request._context = _review_db(lambda: rx.plan_request(legal, request, directory))
        rx.check_request(legal, request)  # scope, size and configuration before anything is queued (HTTPException)
        (directory / rx.STOP_FILE).unlink(missing_ok=True)
        extraction = rx.RuleExtraction.queued(request)
        rx.save(directory, extraction)
        job.ruleExtraction = extraction
    queued = extraction.model_copy(deep=True)
    _rule_executor.submit(_extract_rules, job, request)
    return queued


@app.post("/api/jobs/{job_id}/rule-extraction/stop", status_code=202)
def stop_rule_extraction(job_id: str) -> rx.RuleExtraction:
    """Cooperative stop: finish in-flight responses, schedule no more chunks/corrections."""
    with _lock:
        job = _job(job_id)
        if not rx.active(job.ruleExtraction):
            raise HTTPException(409, "There is no queued or running extraction to stop.")
        (_storage / job.id / rx.STOP_FILE).touch()
        job.ruleExtraction.stopRequested = True
        job.ruleExtraction.message = "Stopping: waiting for requests already sent to Bedrock."
        rx.save(_storage / job.id, job.ruleExtraction)
        return job.ruleExtraction.model_copy(deep=True)


@app.get("/api/jobs/{job_id}/rule-extraction")
def get_rule_extraction(job_id: str) -> rx.RuleExtraction:
    job = _job(job_id)
    if job.ruleExtraction is None:
        raise HTTPException(404, "No rule extraction was started for this job.")
    return job.ruleExtraction


def _settle_document_cancel(job: Job, pdf: Path) -> None:
    """Mark the job as cancelled and clean up. Caller must hold _lock."""
    job.stage = None
    job.cancelRequested = False
    job.status = "cancelled"
    job.message = CANCELLED_DOCUMENT
    if _persistent():
        try:
            update_document_status(job.id, "cancelled")
        except psycopg.Error:
            log.exception("could not persist cancelled status for job %s", job.id)
    else:
        pdf.unlink(missing_ok=True)


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> Job:
    """Stop a document that is queued or processing. A stage already inside Docling cannot be interrupted,
    but its result will be discarded once the current stage finishes."""
    with _lock:
        job = _job(job_id)
        if job.status not in ("queued", "processing"):
            raise HTTPException(409, "This document is no longer being processed.")
        job.cancelRequested = True
        future = _doc_futures.get(job.id)
        if job.status == "queued" and future is not None and future.cancel():
            _settle_document_cancel(job, _storage / job.id / SOURCE_PDF)
        else:
            job.stage = "cancelling"
            if _persistent():
                try:
                    update_document_status(job.id, "processing", "cancelling")
                except psycopg.Error:
                    log.exception("could not record cancellation of job %s", job.id)
        return job.model_copy()


@app.post("/api/jobs/{job_id}/rule-extraction/cancel")
def cancel_rule_extraction(job_id: str) -> rx.RuleExtraction:
    """Ask the running extraction to stop. Returns the current status at once; keep polling until it is terminal."""
    with _lock:
        job = _job(job_id)
        if job.ruleExtraction is None:
            raise HTTPException(404, "No rule extraction was started for this job.")
        if not rx.active(job.ruleExtraction):
            if job.ruleExtraction.status == "cancelled":
                return job.ruleExtraction
            raise HTTPException(409, "The rule extraction has already finished.")
        job.ruleExtraction.cancelRequested = True
        rx.save(_storage / job.id, job.ruleExtraction)
    return job.ruleExtraction


def _extract_rules(job: Job, request: rx.RuleExtractionRequest) -> None:
    """The worker: runs outside the HTTP request; the status file is written before each published change."""
    directory = _storage / job.id
    with _lock:
        extraction = job.ruleExtraction.model_copy(deep=True)
        run_id = extraction.runId
        _rule_run_ids[job.id] = run_id
        extraction.mark_running()
        extraction.stopRequested = (directory / rx.STOP_FILE).exists()
        rx.save(directory, extraction)
        job.ruleExtraction = extraction

    def should_stop() -> bool:
        with _lock:
            current = job.ruleExtraction
            return (current is None or current.runId != run_id or current.cancelRequested
                    or _rule_run_ids.get(job.id) != run_id)

    def on_stage(stage: str) -> None:
        with _lock:
            current = job.ruleExtraction
            if current is not None and current.runId == run_id:
                current.stage = stage
                try:
                    rx.save(directory, current)
                except OSError:
                    pass

    def on_request() -> None:
        with _lock:
            current = job.ruleExtraction
            if current is not None and current.runId == run_id:
                current.externalRequestStarted = True
                try:
                    rx.save(directory, current)
                except OSError:
                    pass

    # run() sets the final status on the object it gets: a private copy, so that clients never see "completed" before
    # rules.json and its report are written (they would load a missing or the previous run's file)
    work = extraction.model_copy(deep=True)
    result = rx.run(directory, request, work,  # never raises
                    should_stop=should_stop, on_stage=on_stage, on_request=on_request)

    with _lock:
        current = job.ruleExtraction
        cancelled = (current is None or current.runId != run_id or current.cancelRequested
                     or _rule_run_ids.get(job.id) != run_id)
        if current is not None and current.runId == run_id:  # set on the published object by on_request / cancel
            work.externalRequestStarted = work.externalRequestStarted or current.externalRequestStarted
            work.cancelRequested = work.cancelRequested or current.cancelRequested
        if result is not None and not cancelled:
            try:
                rx.save_rules(result, directory)
            except OSError:
                log.exception("could not write rules.json for job %s", job.id)
                work.status, work.rulesFile = "failed", None
                work.errorCode, work.message = rx.FAILED
        elif (result is not None and cancelled) or work.status == "cancelled":
            work.mark_cancelled()  # (again) with the merged flags, so a possible charge is reported
        _rule_run_ids.pop(job.id, None)

        finished = work
        try:
            rx.save(directory, finished)
        except OSError:
            log.exception("could not store the rule extraction status of job %s", job.id)
        job.ruleExtraction = finished  # publish under the same lock as the cancellation check and artifact save


# ── human review of the extracted rules (decisions are events in PostgreSQL; rules.json is never modified) ──────────────


def _review_job(job_id: str) -> tuple[Job, Path]:
    job = _job(job_id)
    if job.status != "completed":
        raise HTTPException(409, "The job has no results.")
    rv.require_storage(_persistent())
    return job, _storage / job.id


def _review_db(call):
    """Runs a review database operation; database errors become 503 (an unknown document, deleted meanwhile, 404)."""
    try:
        return call()
    except psycopg.errors.ForeignKeyViolation:
        raise HTTPException(404, "Unknown job.") from None
    except psycopg.Error as e:
        log.exception("review database error")
        raise HTTPException(503, DATABASE_UNAVAILABLE) from e


@app.get("/api/jobs/{job_id}/rule-reviews")
def get_rule_reviews(job_id: str) -> dict:
    """The review state of every rule of the job's current rules.json (see Documentation/review-state-design.md)."""
    job, directory = _review_job(job_id)
    return _review_db(lambda: rv.review_state(job.id, directory))


@app.post("/api/jobs/{job_id}/rule-reviews", status_code=201)
def post_rule_review(job_id: str, request: rv.ReviewRequest) -> dict:
    """Append one review event (accept, reject, edit, reset) to one rule; returns the rule's new review entry."""
    # Serialize the last human decision with taking an incremental-run snapshot.
    with _lock:
        job, directory = _review_job(job_id)
        if rx.active(job.ruleExtraction):
            raise HTTPException(409, "A rule extraction of this job is running; rules can be reviewed when it has finished.")
        return _review_db(lambda: rv.record_review(job.id, directory, request))


@app.get("/api/jobs/{job_id}/rule-reviews/history")
def get_rule_review_history(job_id: str, ruleId: str) -> list[dict]:
    """The audit trail of one rule, oldest first."""
    job, directory = _review_job(job_id)
    return _review_db(lambda: rv.rule_history(job.id, directory, ruleId))


@app.get("/api/jobs/{job_id}/rule-reviews/approved-export")
def get_approved_rules(job_id: str, download: bool = False) -> JSONResponse:
    """The accepted rules as Rule JSON 2.0 (`review.status: approved`); rejected and pending rules are not included."""
    job, directory = _review_job(job_id)
    body = _review_db(lambda: rv.approved_export(job.id, directory))
    headers = {}
    if download:
        name = urllib.parse.quote(f"{Path(job.filename).stem}.approved.rules.json")
        headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{name}"
    return JSONResponse(body, headers=headers)


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: str) -> Response:
    with _lock:
        job = _job(job_id)
        if _persistent() and job.status in ("queued", "processing"):
            raise HTTPException(409, "Cannot delete a running job.")
        if rx.active(job.ruleExtraction):
            raise HTTPException(409, "Cannot delete a job while its rule extraction is running.")
        try:
            _remove(job.id)
        except psycopg.Error as e:  # nothing was removed: the row, the job and its files are kept
            log.exception("could not delete job %s", job.id)
            raise HTTPException(503, DATABASE_UNAVAILABLE) from e
    return Response(status_code=204)


def _job(job_id: str) -> Job:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job.")
    return job


def _stored_pdf(job_id: str) -> Path | None:
    """The PDF file of a stored document, found through its database record; None when there is no such file inside
    ODOS_STORAGE_DIR. Only the stored key is followed, never a path from the request."""
    if not _persistent():
        return None
    try:
        key = get_pdf_storage_key(job_id)
    except psycopg.Error as e:
        log.exception("could not look up the PDF of job %s", job_id)
        raise HTTPException(503, DATABASE_UNAVAILABLE) from e
    if not key:
        return None
    root = _storage.resolve()
    path = (root / key).resolve()  # resolved: a symlink or ".." in the key must not lead out of the storage folder
    return path if path.is_relative_to(root) and path.is_file() else None


def _remove(job_id: str) -> None:
    if _persistent():
        delete_document(job_id)  # first: if it fails, the job and its files stay
    _jobs.pop(job_id, None)
    _doc_futures.pop(job_id, None)
    shutil.rmtree(_storage / job_id, ignore_errors=True)


def _save_pdf(file: UploadFile, dest: Path) -> None:
    size = 0
    with dest.open("wb") as out:
        while chunk := file.file.read(1 << 20):
            if size == 0 and not chunk.startswith(b"%PDF-"):
                raise HTTPException(415, "The file is not a PDF.")
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(413, f"The PDF is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
            out.write(chunk)
    if size == 0:
        raise HTTPException(415, "The file is not a PDF.")


def _process(job: Job, pdf: Path) -> None:
    with _lock:
        if job.id not in _jobs:  # deleted while it waited
            return
        if job.cancelRequested or job.status == "cancelled":
            _settle_document_cancel(job, pdf)
            return
        job.status = "processing"

    status, message, summary, legal_json = "failed", FAILED_MESSAGE, job.summary, None
    cancelled = False

    try:
        if _persistent():
            update_document_status(job.id, "processing")

        def on_progress(stage: str) -> None:
            if job.cancelRequested:  # stop before the next stage; a stage already inside Docling cannot be killed
                raise JobCancelled()
            job.stage = stage
            if _persistent():
                update_document_status(job.id, "processing", stage)

        res = run_pipeline(pdf, pdf.parent, progress=on_progress)
        if job.cancelRequested:
            raise JobCancelled()

        # Docling's warnings may quote file paths: only their number leaves the server
        summary = res.summary | {
            "docling_warnings": len(res.summary.get("docling_warnings", []))
        }

        if res.outcome == Outcome.COMPLETED and _persistent():
            legal_json = json.loads(
                (pdf.parent / LEGAL_JSON).read_text(encoding="utf-8")
            )

        status = "completed" if res.outcome == Outcome.COMPLETED else "unsupported"
        message = res.message

    except JobCancelled:
        cancelled = True
    except Exception:
        log.exception("job %s failed", job.id)  # the details stay in the server log
        status, message = "failed", FAILED_MESSAGE

    # Decision, database write and publication are one step under the lock: a cancel arriving now either came first
    # (and is honoured) or finds the job finished (409); it can never overwrite the stored result.
    with _lock:
        if job.id not in _jobs:  # deleted while it ran
            shutil.rmtree(pdf.parent, ignore_errors=True)
            return
        if cancelled or job.cancelRequested or job.status == "cancelled":
            _settle_document_cancel(job, pdf)
            return

        if _persistent():
            try:
                finish_document(job.id, status, summary, legal_json, message)
            except Exception:
                log.exception("could not persist job %s", job.id)
                # the API must not report a result the database does not have (it would be gone after a restart)
                status, message = "failed", NOT_STORED_MESSAGE
                try:
                    finish_document(job.id, status, summary, None, message)
                except Exception:  # the row stays queued/processing and is marked as interrupted at the next start
                    log.exception("could not mark job %s as failed", job.id)
        else:
            pdf.unlink(missing_ok=True)  # the browser shows its own copy; the upload is not kept

        # published only now, after the database has the result; the status last, as clients poll for it
        job.stage, job.message, job.summary = None, message, summary
        job.cancelRequested = False
        job.status = status
