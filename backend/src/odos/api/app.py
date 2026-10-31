"""FastAPI application. Run: ``uvicorn odos.api.app:app --reload``."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from fastapi.concurrency import run_in_threadpool

from odos.api.config import Settings
from odos.api.jobs import JobManager, PipelineFn, QueueFull
from odos.api.schemas import Akn4EuRequest, DeleteResult, DeletionPreview, DocumentStatus, ErrorBody, HealthResponse, JobStatus, ProcessRequest
from odos.api.storage import DeleteBlocked, NotFound, Store
from odos.artifact_names import ARTIFACTS, DOCLING_RAW
from odos.classification import ClassificationResult, classify_lines, lines_from_docling, lines_from_pdf, route
from odos.classification.model import Band, DocumentType, InputInfo, SupportStatus
from odos.document_model import DocumentModel
from odos.parsing.profiles import for_model
from odos.review.model import ConfirmRequest, CorrectionRequest, DecisionRequest, ReviewView
from odos.review.service import ReviewError, ReviewService
from odos.pipeline import Outcome, ProcessingMode, load_json, run_pipeline

PDF_MAGIC = b"%PDF-"
CHUNK = 1024 * 1024


def err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail=ErrorBody(code=code, message=message).model_dump())


def create_app(settings: Settings | None = None, pipeline: PipelineFn = run_pipeline) -> FastAPI:
    settings = settings or Settings()
    store = Store(settings.documents_dir)
    jobs = JobManager(store, pipeline, workers=settings.workers, max_queue=settings.max_queue)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        jobs.shutdown()

    app = FastAPI(title="ODOS API", version="0.1.0", lifespan=lifespan,
                  description="Local MVP: upload PDFs, process them with Docling and the German-law prototype parser.")  # fmt: skip
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["GET", "POST", "DELETE"], allow_headers=["*"])  # fmt: skip
    reviews = ReviewService(store)
    app.state.store, app.state.jobs, app.state.settings, app.state.reviews = store, jobs, settings, reviews

    def get_doc(doc_id: str) -> DocumentStatus:
        try:
            return store.read(doc_id)
        except NotFound:
            raise err(404, "document_not_found", "No document with this id.") from None

    @app.exception_handler(HTTPException)
    async def http_exc(_, exc: HTTPException):  # flatten to {code, message}
        d = exc.detail if isinstance(exc.detail, dict) and "code" in exc.detail else {"code": "error", "message": str(exc.detail)}  # fmt: skip
        return JSONResponse(status_code=exc.status_code, content=d)

    @app.exception_handler(ReviewError)
    async def review_exc(_, exc: ReviewError):
        return JSONResponse(status_code=exc.status, content={"code": exc.code, "message": exc.message, **exc.extra})

    @app.get("/api/health", response_model=HealthResponse)
    def health():
        return HealthResponse(status="ok", max_upload_mb=settings.max_upload_mb, queue_capacity=settings.max_queue,
                              modes=[m.value for m in ProcessingMode])  # fmt: skip

    @app.get("/api/documents", response_model=list[DocumentStatus])
    def list_documents():
        return store.list()

    @app.post("/api/documents", response_model=DocumentStatus, status_code=201,
              responses={400: {"model": ErrorBody}, 413: {"model": ErrorBody}, 415: {"model": ErrorBody}})  # fmt: skip
    async def upload(file: UploadFile = File(...)):
        name = file.filename or ""
        if not name.lower().endswith(".pdf"):
            raise err(415, "unsupported_file_type", "Only PDF files (.pdf) are accepted.")
        head = await file.read(len(PDF_MAGIC))
        if head != PDF_MAGIC:
            raise err(415, "not_a_pdf", "The file content is not a PDF (missing %PDF- header).")
        doc_id, target = store.create(name, 0)
        size = len(head)
        try:
            with target.open("wb") as out:
                out.write(head)
                while chunk := await file.read(CHUNK):
                    size += len(chunk)
                    if size > settings.max_upload_bytes:
                        raise err(413, "file_too_large", f"The file exceeds the upload limit of {settings.max_upload_mb:g} MB.")  # fmt: skip
                    out.write(chunk)
        except HTTPException:
            _discard(store, doc_id)
            raise
        st = store.update(doc_id, size_bytes=size)
        # Lightweight classification from the PDF text layer; Docling is not run here (and is reused later).
        await run_in_threadpool(_classify_and_store, store, doc_id)
        return st

    @app.post("/api/documents/{doc_id}/process", response_model=DocumentStatus, status_code=202,
              responses={404: {"model": ErrorBody}, 409: {"model": ErrorBody}, 429: {"model": ErrorBody}})  # fmt: skip
    def process(doc_id: str, req: ProcessRequest):
        st = get_doc(doc_id)
        if st.status in (JobStatus.QUEUED, JobStatus.PROCESSING):
            raise err(409, "already_running", "This document is already queued or being processed.")
        decision = route(get_or_make_classification(doc_id), req.mode.value)  # records suggested vs chosen
        reviews.archive(doc_id, f"document reprocessed in mode {req.mode.value}")  # a review belongs to one extraction
        try:
            jobs.submit(doc_id, req.mode)
        except QueueFull:
            raise err(429, "queue_full", "The processing queue is full. Try again shortly.") from None
        return store.update(doc_id, routing=decision)

    def get_or_make_classification(doc_id: str, refresh: bool = False) -> ClassificationResult:
        stored = None if refresh else store.read_classification(doc_id)
        if stored is not None:
            return stored
        return _classify_and_store(store, doc_id)

    @app.get("/api/documents/{doc_id}/classification", response_model=ClassificationResult,
             responses={404: {"model": ErrorBody}})  # fmt: skip
    async def classification(doc_id: str, refresh: bool = False):
        """Stored classification; `refresh=true` recomputes it (from the Docling output if one exists)."""
        get_doc(doc_id)
        return await run_in_threadpool(get_or_make_classification, doc_id, refresh)

    @app.get("/api/documents/{doc_id}/deletion-preview", response_model=DeletionPreview, responses={404: {"model": ErrorBody}})
    def deletion_preview(doc_id: str):
        """What `DELETE /api/documents/{id}` would remove (read-only)."""
        get_doc(doc_id)
        try:
            return store.deletion_preview(doc_id)
        except NotFound:
            raise err(404, "document_not_found", "No document with this id.") from None

    @app.delete("/api/documents/{doc_id}", response_model=DeleteResult,
                responses={404: {"model": ErrorBody}, 409: {"model": ErrorBody}, 500: {"model": ErrorBody}})  # fmt: skip
    def delete_document(doc_id: str):
        """Permanently delete one document: its PDF, artifacts, classification, reviews and record. Nothing else."""
        st = get_doc(doc_id)
        try:
            with reviews.store.lock(doc_id):  # no review write may run while the folder disappears
                removed = store.delete(doc_id)
        except NotFound:
            raise err(404, "document_not_found", "No document with this id.") from None
        except DeleteBlocked as exc:
            raise err(409, exc.code, exc.message) from None
        except OSError as exc:
            raise err(500, "delete_failed", f"The document could not be fully deleted ({exc.strerror or type(exc).__name__}). It is still listed; try again.") from None  # fmt: skip
        return DeleteResult(id=doc_id, filename=st.filename, deleted=True, removed=removed)

    @app.get("/api/documents/{doc_id}/status", response_model=DocumentStatus, responses={404: {"model": ErrorBody}})
    def status(doc_id: str):
        return get_doc(doc_id)

    @app.get("/api/documents/{doc_id}/structure", response_model=DocumentModel,
             responses={404: {"model": ErrorBody}, 409: {"model": ErrorBody}})  # fmt: skip
    def structure(doc_id: str):
        st = get_doc(doc_id)
        if st.status != JobStatus.COMPLETED:
            raise err(409, "not_ready", f"Document is {st.status.value}; structure is available after processing completes.")  # fmt: skip
        if st.outcome == Outcome.UNSUPPORTED:
            raise err(409, "unsupported_document_type", st.message or "Unsupported document type.")
        try:
            return load_json(store.artifact_path(doc_id, "document_model"))
        except NotFound:
            raise err(409, "no_structure", "No legal structure was produced (extract_only mode, or the parser did not run).") from None  # fmt: skip

    # ---- human review -------------------------------------------------------------------------------------------
    def reviewable(doc_id: str) -> None:
        st = get_doc(doc_id)
        if st.status != JobStatus.COMPLETED:
            raise err(409, "not_ready", f"Document is {st.status.value}; it can be reviewed after processing completes.")

    @app.get("/api/documents/{doc_id}/review", response_model=ReviewView, responses={404: {"model": ErrorBody}, 409: {"model": ErrorBody}})  # fmt: skip
    async def review(doc_id: str):
        reviewable(doc_id)
        return await run_in_threadpool(reviews.view, doc_id)

    @app.get("/api/documents/{doc_id}/review/model", response_model=DocumentModel)
    async def review_model(doc_id: str, revision: int | None = None):
        reviewable(doc_id)
        return await run_in_threadpool(reviews.effective_model, doc_id, revision)

    @app.get("/api/documents/{doc_id}/review/revisions/{revision}/{kind}")
    def review_revision_file(doc_id: str, revision: int, kind: str):
        reviewable(doc_id)
        p = reviews.revision_file(doc_id, revision, kind)
        media = "application/xml" if p.suffix == ".xml" else "application/json"
        return FileResponse(p, media_type=media, filename=f"{doc_id[:8]}_r{revision}_{p.name}")

    @app.post("/api/documents/{doc_id}/review/corrections", response_model=ReviewView)
    async def review_correct(doc_id: str, req: CorrectionRequest):
        reviewable(doc_id)
        return await run_in_threadpool(reviews.correct, doc_id, req)

    @app.post("/api/documents/{doc_id}/review/confirmations", response_model=ReviewView)
    async def review_confirm(doc_id: str, req: ConfirmRequest):
        reviewable(doc_id)
        return await run_in_threadpool(reviews.confirm, doc_id, req)

    @app.post("/api/documents/{doc_id}/review/approve", response_model=ReviewView)
    async def review_approve(doc_id: str, req: DecisionRequest):
        reviewable(doc_id)
        return await run_in_threadpool(reviews.approve, doc_id, req)

    @app.post("/api/documents/{doc_id}/review/request-changes", response_model=ReviewView)
    async def review_request_changes(doc_id: str, req: DecisionRequest):
        reviewable(doc_id)
        return await run_in_threadpool(reviews.request_changes, doc_id, req)

    @app.post("/api/documents/{doc_id}/review/reopen", response_model=ReviewView)
    async def review_reopen(doc_id: str, req: DecisionRequest):
        reviewable(doc_id)
        return await run_in_threadpool(reviews.reopen, doc_id, req)

    # ---- AKN4EU export (separate profile; the pipeline's own AKN artifacts are not touched) -- ---------------------------
    def akn4eu_dir(doc_id: str):
        return store.output_dir(doc_id) / "akn4eu"

    @app.post("/api/documents/{doc_id}/exports/akn4eu", responses={404: {"model": ErrorBody}, 409: {"model": ErrorBody}, 422: {"model": ErrorBody}})  # fmt: skip
    async def export_akn4eu(doc_id: str, req: Akn4EuRequest | None = None):
        """Generate the AKN4EU files from the EU document model and return the validation report."""
        model = DocumentModel.model_validate(structure(doc_id))
        if "akn4eu" not in for_model(model).capabilities:
            raise err(409, "profile_not_supported", "The AKN4EU export is only available for documents processed as EU legislation.")  # fmt: skip
        from odos.akn.akn4eu_artifacts import build_akn4eu_artifacts

        try:
            art = await run_in_threadpool(build_akn4eu_artifacts, model, date.today().isoformat(), akn4eu_dir(doc_id), (req or Akn4EuRequest()).eli)  # fmt: skip
        except ValueError as exc:
            raise err(422, "akn4eu_refused", str(exc)) from None
        return art["report"]

    def akn4eu_report(doc_id: str) -> dict:
        from odos.akn.akn4eu_artifacts import REPORT_NAME

        p = akn4eu_dir(doc_id) / REPORT_NAME
        if not p.is_file():
            raise err(404, "no_akn4eu_export", "No AKN4EU export yet; POST /exports/akn4eu first.")
        return load_json(p)

    @app.get("/api/documents/{doc_id}/exports/akn4eu", responses={404: {"model": ErrorBody}})
    def get_akn4eu(doc_id: str):
        """The validation report of the current AKN4EU export."""
        get_doc(doc_id)
        return akn4eu_report(doc_id)

    @app.get("/api/documents/{doc_id}/exports/akn4eu/files/{name}", responses={404: {"model": ErrorBody}})
    def export_akn4eu_xml(doc_id: str, name: str):
        """One XML file of the export (act or annex); only names listed in the export's report are served."""
        get_doc(doc_id)
        if name not in akn4eu_report(doc_id)["files"]:
            raise err(404, "artifact_not_found", f"'{name}' is not a file of this AKN4EU export.")
        return FileResponse(akn4eu_dir(doc_id) / name, media_type="application/xml", filename=name)

    @app.get("/api/documents/{doc_id}/exports/akn4eu/{kind}", responses={404: {"model": ErrorBody}})
    def export_akn4eu_file(doc_id: str, kind: str):
        get_doc(doc_id)
        from odos.akn.akn4eu_artifacts import PACKAGE_NAME, REPORT_NAME

        names = {"package": (PACKAGE_NAME, "application/zip"), "report": (REPORT_NAME, "application/json"),
                 "traceability": ("akn4eu_traceability.json", "application/json"),
                 "text_report": ("akn4eu_text_preservation.json", "application/json")}  # fmt: skip
        if kind not in names:
            raise err(404, "artifact_not_found", f"Unknown AKN4EU file '{kind}'. Known: {', '.join(names)}.")
        p = akn4eu_dir(doc_id) / names[kind][0]
        if not p.is_file():
            raise err(404, "artifact_not_found", "No AKN4EU export yet; POST /exports/akn4eu first.")
        return FileResponse(p, media_type=names[kind][1], filename=f"{doc_id[:8]}_{p.name}")

    @app.get("/api/documents/{doc_id}/original", responses={404: {"model": ErrorBody}})
    def original(doc_id: str):
        get_doc(doc_id)
        return FileResponse(store.original(doc_id), media_type="application/pdf", headers={"Content-Disposition": "inline"})

    @app.get("/api/documents/{doc_id}/artifacts/{artifact_type}", responses={404: {"model": ErrorBody}})
    def artifact(doc_id: str, artifact_type: str):
        get_doc(doc_id)
        try:
            path = store.artifact_path(doc_id, artifact_type)
        except NotFound:
            known = ", ".join(ARTIFACTS)
            raise err(404, "artifact_not_found", f"No artifact '{artifact_type}' for this document. Known types: {known}.") from None  # fmt: skip
        return FileResponse(path, media_type=ARTIFACTS[artifact_type][1], filename=f"{doc_id[:8]}_{path.name}")

    return app


def _classify_and_store(store: Store, doc_id: str) -> ClassificationResult:
    """Classify from an existing Docling extraction if there is one, otherwise from the PDF text layer."""
    pdf = store.original(doc_id)
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    try:
        raw = store.output_dir(doc_id) / DOCLING_RAW
        data = lines_from_docling(raw) if raw.is_file() else lines_from_pdf(pdf)
        result = classify_lines(data, pdf_sha256=sha)
    except Exception as exc:  # noqa: BLE001 - classification must never block upload or processing
        result = ClassificationResult(
            document_type=DocumentType.UNKNOWN, suggested_processing_mode="extract_only", confidence_band=Band.LOW,
            support_status=SupportStatus.UNSUPPORTED, supported=False, evidence=[], points={},
            summary="The document could not be classified; extraction only is suggested.",
            warnings=[f"Classification failed: {type(exc).__name__}: {exc}"[:300]],
            input=InputInfo(source="none", pages_total=0, pages_scanned=0, lines=0, characters=0), pdf_sha256=sha,
        )  # fmt: skip
    store.write_classification(doc_id, result)
    return result


def _discard(store: Store, doc_id: str) -> None:
    import shutil

    shutil.rmtree(store.doc_dir(doc_id), ignore_errors=True)


app = create_app()
