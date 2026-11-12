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
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

import psycopg
from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, computed_field

from odos.artifact_names import DOCUMENT_MODEL, LEGAL_JSON, DOCLING_RAW
from odos.pipeline import Outcome, run_pipeline
from odos.document_repository import (
    create_document,
    delete_document,
    finish_document,
    get_pdf_storage_key,
    list_documents,
    list_recent_documents,
    mark_interrupted_jobs,
    update_document_status,
)

log = logging.getLogger("odos.api")

MAX_UPLOAD_BYTES = int(os.environ.get("ODOS_MAX_UPLOAD_MB", "50")) * 1024 * 1024
MAX_JOBS = 10  # when a new job comes in, the oldest finished ones beyond this are deleted with their files
# the job files the frontend reads; nothing else in a job directory is served
RESULT_FILES = (DOCUMENT_MODEL, LEGAL_JSON, DOCLING_RAW)
SOURCE_PDF = "source.pdf"  # the uploaded PDF inside a job directory; kept only with database persistence
FAILED_MESSAGE = "The PDF could not be processed. It may be damaged, encrypted or a scanned image without a text layer."
NOT_STORED_MESSAGE = "The PDF was processed, but its result could not be stored in the database."
DATABASE_UNAVAILABLE = "The ODOS database is not available. Check that PostgreSQL is running and try again."


def _persistent() -> bool:
    return os.environ.get("ODOS_DATABASE_ENABLED") == "1"


class Job(BaseModel):
    id: str
    filename: str  # the uploaded file's name, for display and the download name only
    status: Literal["queued", "processing", "completed", "unsupported", "failed"] = "queued"
    stage: str | None = None  # while processing: run_pipeline's progress ("extracting", "normalizing")
    message: str | None = None
    summary: dict = Field(default_factory=dict)  # run_pipeline's summary (pages, counts, json_schema_valid, ...)

    @computed_field
    @property
    def persistent(self) -> bool:
        """Kept in the database: the frontend then leaves the job in place instead of deleting it when done."""
        return _persistent()


class StoredDocument(BaseModel):
    """A document of the database as listed on the upload page: metadata only."""

    id: str
    filename: str
    status: Literal["queued", "processing", "completed", "unsupported", "failed"]
    created_at: datetime


_jobs: dict[str, Job] = {}
_lock = threading.Lock()
_storage = Path()
_executor = ThreadPoolExecutor(max_workers=1)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _storage, _executor
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

    with _lock:
        _jobs.clear()
        if _persistent():
            mark_interrupted_jobs()
            for row in list_documents():
                job = Job(**row)
                _jobs[job.id] = job

    try:
        yield
    finally:
        # queued jobs are cancelled (with the database they are marked as interrupted at the next start); with the
        # database the running job is awaited so that its result is stored
        _executor.shutdown(wait=_persistent(), cancel_futures=True)

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
        finished = [j for j in _jobs.values() if j.status in ("completed", "unsupported", "failed")]
        if not _persistent():
            for old in finished[: max(0, len(_jobs) + 1 - MAX_JOBS)]:
                _remove(old.id)
        _jobs[job.id] = job
    queued = job.model_copy()  # as created: the worker may already be changing `job`
    _executor.submit(_process, job, pdf)
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
    if not path.is_file():  # e.g. a restored job whose files were removed or live under another ODOS_STORAGE_DIR
        raise HTTPException(404, "The result file is no longer available.")
    filename = f"{Path(job.filename).stem}.legal.json" if download else None
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


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: str) -> Response:
    with _lock:
        job = _job(job_id)
        if _persistent() and job.status in ("queued", "processing"):
            raise HTTPException(409, "Cannot delete a running job.")
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
    if job.id not in _jobs:  # deleted while it waited
        return

    job.status = "processing"
    status, message, summary, legal_json = "failed", FAILED_MESSAGE, job.summary, None

    try:
        if _persistent():
            update_document_status(job.id, "processing")

        def on_progress(stage: str) -> None:
            job.stage = stage
            if _persistent():
                update_document_status(job.id, "processing", stage)

        res = run_pipeline(pdf, pdf.parent, progress=on_progress)

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

    except Exception:
        log.exception("job %s failed", job.id)  # the details stay in the server log
        status, message = "failed", FAILED_MESSAGE

    finally:
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
        job.status = status

        if job.id not in _jobs:  # deleted while it ran
            shutil.rmtree(pdf.parent, ignore_errors=True)
