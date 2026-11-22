# ODOS architecture

ODOS extracts legal PDFs and converts them into Custom Legal JSON 2.0. A Python backend processes uploaded PDFs; a React frontend displays the PDF, recognized legal structure and JSON outputs.

The current prototype does not interpret provisions as executable compliance rules. LLM rule extraction is available as an optional step, started from the frontend's Rule Extraction page, the API or the command line ([bedrock-rule-extraction.md](bedrock-rule-extraction.md)); digital-twin validation is a future step. Akoma Ntoso is not an output of this version.

## Components

| Component | Location | Responsibility |
|---|---|---|
| Web API | `backend/src/odos/api.py` | Uploads, processing jobs, result files and deletion |
| Pipeline | `backend/src/odos/pipeline.py` | Extraction, profile selection, parsing and export |
| Extraction | `backend/src/odos/extraction.py` | Docling JSON and Markdown |
| Normalization | `backend/src/odos/normalization/` | Reading order, text evidence and highlighting |
| Parser | `backend/src/odos/parsing/` | Legal hierarchy, sentences and footnotes |
| Internal model | `backend/src/odos/document_model.py` | Content, hierarchy, provenance and diagnostics |
| Public export | `backend/src/odos/legal_json/` | Custom Legal JSON and validation |
| Persistence | `backend/src/odos/database.py`, `backend/src/odos/document_repository.py` | Optional PostgreSQL storage of jobs and Legal JSON (`psycopg` with plain SQL, no ORM; schema in `backend/db/001_documents.sql`, no migrations tool) |
| LLM rule extraction | `backend/src/odos/llm/` | Amazon Bedrock client and Legal JSON 2.0 → Rule JSON extraction (CLI `odos extract-rules`, or `POST /api/jobs/{id}/rule-extraction` as a background step of a completed job; not part of live processing) |
| Schemas | `backend/schemas/` | Legal JSON 2.0 and Rule JSON (JSON Schema Draft 2020-12) |
| Frontend | `frontend/src/` | Upload, progress, document library, PDF and result views |

## Live processing

1. The browser sends a PDF to `POST /api/jobs`.
2. The backend creates a job and runs Docling, producing `docling_raw.json` and `extracted.md`.
3. The pipeline records PDF text-layer evidence and attempts the German and EU profiles. Exactly one must recognize a supported structure; otherwise the document is reported as unsupported.
4. The parser creates the canonical `DocumentModel` and validation reports.
5. The exporter creates `document.json` and its validation report.
6. The browser loads `document_model.json` and `document.json`. It uses model provenance for PDF highlights.
7. Opening the Docling Raw JSON panel loads the complete `docling_raw.json` on demand.
8. The browser also requests the optional `rules.json` (Rule JSON); it exists only after a rule extraction was run for the job (`odos extract-rules` or `POST /api/jobs/{id}/rule-extraction`), so the Artifacts Rule JSON view is empty until then. The Rule Extraction page reads the extraction status and `rules.json` and shows the stored rules without starting a new extraction. The API keeps the extraction status in `rule_extraction.json` and unusable model answers in `llm-diagnostics/` in the job directory; neither is served.

The files form different views of one processing run. Raw Docling JSON describes extraction and layout. The internal model adds legal structure and diagnostics. Public Legal JSON contains legal content without technical source coordinates.

## API

| Method and route | Purpose |
|---|---|
| `POST /api/jobs` | Submit a multipart PDF in field `file` |
| `GET /api/jobs/{id}` | Read status, stage, message and summary |
| `GET /api/jobs/{id}/files/{name}` | Read an allowed result file |
| `GET /api/documents` | Metadata of the newest stored documents (`id`, `filename`, `status`, `created_at`); `[]` without database persistence |
| `GET /api/jobs/{id}/pdf` | The original PDF of a completed, stored document (database persistence only; looked up through the document's stored key inside `ODOS_STORAGE_DIR`) |
| `DELETE /api/jobs/{id}` | Remove a job and its files (with database persistence, a queued or processing job cannot be deleted: `409`) |

Statuses are `queued`, `processing`, `completed`, `unsupported` and `failed`. Result files are served only for completed jobs. The allowed result files are `document_model.json`, `document.json`, `docling_raw.json` and the optional `rules.json`.

The backend uses one processing worker and an in-memory job registry. Without database persistence, default storage is temporary and removed at shutdown, `ODOS_STORAGE_DIR` retains files at another location but does not restore the job registry, old completed jobs are removed as the job limit is reached, and the uploaded PDF is deleted after processing (the browser displays its local copy). With `ODOS_DATABASE_ENABLED=1` (as in Docker Compose), every job is also recorded in PostgreSQL, the jobs are restored at startup, and the uploaded PDF stays in `ODOS_STORAGE_DIR` for `GET /api/jobs/{id}/pdf`; see [database-poc.md](database-poc.md).

## Frontend

`DemoApp.tsx` contains upload and result views despite its historical name. `live.ts` handles API requests and polling.

The simplified `fixtures.ts` contains only the shared `DemoResult` type; it does not fetch examples. Keep its type imports until they have been moved to another file.

Artifacts show Custom Legal JSON for the selected element or full document, plus a collapsible full-document Docling preview. The normal live view requires a running backend. A frontend production build alone does not deploy that backend.
