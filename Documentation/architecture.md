# ODOS architecture

ODOS extracts legal PDFs and converts them into Custom Legal JSON 2.0. A Python backend processes uploaded PDFs; a React frontend displays the PDF, recognized legal structure and JSON outputs.

The current prototype does not interpret provisions as executable compliance rules. LLM rule extraction and digital-twin validation are future steps. Akoma Ntoso is not an output of this version.

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
| Frontend | `frontend/src/` | Upload, progress, PDF and result views |

## Live processing

1. The browser sends a PDF to `POST /api/jobs`.
2. The backend creates a job and runs Docling, producing `docling_raw.json` and `extracted.md`.
3. The pipeline records PDF text-layer evidence and attempts the German and EU profiles. Exactly one must recognize a supported structure; otherwise the document is reported as unsupported.
4. The parser creates the canonical `DocumentModel` and validation reports.
5. The exporter creates `document.json` and its validation report.
6. The browser loads `document_model.json` and `document.json`. It uses model provenance for PDF highlights.
7. Opening the Docling Raw JSON panel loads the complete `docling_raw.json` on demand, once the raw-preview extension is installed.

The files form different views of one processing run. Raw Docling JSON describes extraction and layout. The internal model adds legal structure and diagnostics. Public Legal JSON contains legal content without technical source coordinates.

## API

| Method and route | Purpose |
|---|---|
| `POST /api/jobs` | Submit a multipart PDF in field `file` |
| `GET /api/jobs/{id}` | Read status, stage, message and summary |
| `GET /api/jobs/{id}/files/{name}` | Read an allowed result file |
| `DELETE /api/jobs/{id}` | Remove a job and its files |

Statuses are `queued`, `processing`, `completed`, `unsupported` and `failed`. Result files are served only for completed jobs. The original implementation allows `document_model.json` and `document.json`; the raw-preview extension adds `docling_raw.json`.

The backend uses one processing worker and an in-memory job registry. Default storage is temporary and removed at shutdown. `ODOS_STORAGE_DIR` retains files at another location, but does not persist or restore the in-memory job registry. Old completed jobs can be removed as the job limit is reached. The uploaded PDF is deleted after processing; the browser displays its local copy.

## Frontend

`DemoApp.tsx` contains upload and result views despite its historical name. `live.ts` handles API requests and polling. `excerpts.mjs` formats JSON and currently displays `nativeType` as `germanType`; downloaded `document.json` retains `nativeType`.

The simplified `fixtures.ts` contains only the shared `DemoResult` type; it does not fetch examples. Keep its type imports until they have been moved to another file.

Artifacts show Custom Legal JSON for the selected element or full document, plus a collapsible full-document Docling preview. The normal live view requires a running backend. A frontend production build alone does not deploy that backend.
