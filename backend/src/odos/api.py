"""Thin web API over the pipeline (`uvicorn odos.api:app`): upload a PDF, poll its job, read the results.

A single-instance development MVP: jobs live in memory and run one at a time in a background thread (Docling is
slow and memory-hungry). Each job writes the usual `odos process` files into its own directory under
ODOS_STORAGE_DIR (default: a temporary directory, removed at shutdown). Every upload runs the real pipeline
(`run_pipeline`, which recognizes German or EU legislation from the document's own structure); no precomputed result
is ever substituted.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from odos.artifact_names import DOCUMENT_MODEL, LEGAL_JSON
from odos.pipeline import Outcome, run_pipeline

log = logging.getLogger("odos.api")

MAX_UPLOAD_BYTES = int(os.environ.get("ODOS_MAX_UPLOAD_MB", "50")) * 1024 * 1024
MAX_JOBS = 10  # when a new job comes in, the oldest finished ones beyond this are deleted with their files
# the job files the frontend reads; nothing else in a job directory is served
RESULT_FILES = (DOCUMENT_MODEL, LEGAL_JSON)
FAILED_MESSAGE = "The PDF could not be processed. It may be damaged, encrypted or a scanned image without a text layer."


class Job(BaseModel):
    id: str
    filename: str  # the uploaded file's name, for display and the download name only
    status: Literal["queued", "processing", "completed", "unsupported", "failed"] = "queued"
    stage: str | None = None  # while processing: run_pipeline's progress ("extracting", "normalizing")
    message: str | None = None
    summary: dict = Field(default_factory=dict)  # run_pipeline's summary (pages, counts, json_schema_valid, ...)


_jobs: dict[str, Job] = {}
_lock = threading.Lock()
_storage = Path()
_executor = ThreadPoolExecutor(max_workers=1)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _storage, _executor
    configured = os.environ.get("ODOS_STORAGE_DIR")
    _storage = Path(configured) if configured else Path(tempfile.mkdtemp(prefix="odos-jobs-"))
    _storage.mkdir(parents=True, exist_ok=True)
    _executor = ThreadPoolExecutor(max_workers=1)
    _jobs.clear()
    try:
        yield
    finally:
        _executor.shutdown(wait=False, cancel_futures=True)
        for job_id in list(_jobs):
            _remove(job_id)
        if not configured:
            shutil.rmtree(_storage, ignore_errors=True)


app = FastAPI(title="ODOS", lifespan=lifespan)


@app.post("/api/jobs", status_code=202)
def create_job(file: UploadFile = File(...)) -> Job:
    job = Job(id=uuid.uuid4().hex, filename=Path(file.filename or "document.pdf").name[:200])
    pdf = _storage / job.id / "source.pdf"
    pdf.parent.mkdir(parents=True)
    try:
        _save_pdf(file, pdf)
    except HTTPException:
        shutil.rmtree(pdf.parent, ignore_errors=True)
        raise
    with _lock:
        finished = [j for j in _jobs.values() if j.status in ("completed", "unsupported", "failed")]
        for old in finished[: max(0, len(_jobs) + 1 - MAX_JOBS)]:
            _remove(old.id)
        _jobs[job.id] = job
    queued = job.model_copy()  # as created: the worker may already be changing `job`
    _executor.submit(_process, job, pdf)
    return queued


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
    filename = f"{Path(job.filename).stem}.legal.json" if download else None
    return FileResponse(_storage / job.id / name, media_type="application/json", filename=filename)


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: str) -> Response:
    with _lock:
        _remove(_job(job_id).id)
    return Response(status_code=204)


def _job(job_id: str) -> Job:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job.")
    return job


def _remove(job_id: str) -> None:
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
    try:
        res = run_pipeline(pdf, pdf.parent, progress=lambda stage: setattr(job, "stage", stage))
    except Exception:
        log.exception("job %s failed", job.id)  # the details stay in the server log
        job.status, job.message = "failed", FAILED_MESSAGE
    else:
        # Docling's warnings may quote file paths: only their number leaves the server
        summary = res.summary | {"docling_warnings": len(res.summary.get("docling_warnings", []))}
        job.status = "completed" if res.outcome == Outcome.COMPLETED else "unsupported"
        job.message, job.summary = res.message, summary
    finally:
        job.stage = None
        pdf.unlink(missing_ok=True)  # the browser shows its own copy; the upload is not kept
        if job.id not in _jobs:  # deleted while it ran
            shutil.rmtree(pdf.parent, ignore_errors=True)
