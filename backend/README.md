# ODOS backend

The Python package `odos` converts legal PDFs into structured legal data. The frontend submits PDFs through a FastAPI web API; the command line can run the pipeline independently.

## Current scope

- PDF extraction with Docling.
- Normalization and legal parsing with German-law and German-language EU profiles.
- An internal `DocumentModel` with source references, coordinates and diagnostics.
- Custom Legal JSON 2.0 export with runtime validation.
- A web API for uploads, processing status, result files and job deletion.

Automated tests are in `tests/` (`python -m pytest tests` from `backend`): the API with and without PostgreSQL persistence, Legal JSON schema compatibility, page rendering and, when the partner PDFs are available, the MBO and EU 2023/1230 reference structures. Tests whose database or PDFs are missing are skipped with the reason; see [database-poc.md](../Documentation/database-poc.md#run-the-tests-safely). Runtime validation remains part of processing. LLM rule extraction and digital-twin validation are not implemented, and Akoma Ntoso XML is not generated.

## Requirements and installation

Use Python 3.12. From the repository root, run these commands in PowerShell:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

Run commands one at a time and stop if one fails. The lockfile pins dependencies; changing Docling-related versions can change extraction results. The first extraction downloads models and requires network access. Processing time depends on the machine and document.

## Start the API

From `backend`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn odos.api:app --port 8000
```

Leave this terminal running. Start the frontend in a separate terminal using the [frontend instructions](../frontend/README.md).

API documentation is available at `http://127.0.0.1:8000/docs`. A 404 at `/` is expected: the backend does not serve the frontend there. If port 8000 is occupied, stop the previous backend process with Ctrl+C before restarting.

## Web processing

The API calls the pipeline without an explicit legal profile. The pipeline attempts its configured profiles and accepts exactly one recognized structure. Unsupported or ambiguous structures are reported to the frontend; recognition does not establish complete parsing accuracy.

| Method and route | Purpose |
|---|---|
| `POST /api/jobs` | Upload a PDF as multipart field `file`; returns a queued job |
| `GET /api/jobs/{id}` | Read job status and progress |
| `GET /api/jobs/{id}/files/{name}` | Read an allowed result file for a completed job |
| `DELETE /api/jobs/{id}` | Remove a job and its files |

Statuses are `queued`, `processing`, `completed`, `unsupported` and `failed`. Processing uses one worker. Detailed exceptions are logged in the backend terminal.

## Files and raw-output preview

| File | Purpose |
|---|---|
| `docling_raw.json` | Original Docling extraction |
| `extracted.md` | Extraction as Markdown |
| `document_model.json` | Internal model with legal structure, provenance and diagnostics |
| `document.json` | Public Custom Legal JSON 2.0 |
| `validation_report.json` / `validation_report.md` | Parser diagnostics and content-accounting reports |
| `legal_json_validation_report.json` | Public JSON validation results |
| `pdf_text_lines.json` | PDF text-layer evidence used during normalization |

The API serves only filenames in `RESULT_FILES` in `src/odos/api.py`. The original implementation includes `DOCUMENT_MODEL` and `LEGAL_JSON`. The collapsible frontend raw-output panel additionally requires:

```python
from odos.artifact_names import DOCUMENT_MODEL, LEGAL_JSON, DOCLING_RAW

RESULT_FILES = (DOCUMENT_MODEL, LEGAL_JSON, DOCLING_RAW)
```

After applying that code change, restart the backend and process the PDF again. The raw file is available at `/api/jobs/{id}/files/docling_raw.json`; other generated reports are not automatically exposed. This README does not implement the API or UI changes.

The frontend's Legal JSON download uses `?download=true`. Technical source coordinates remain in the internal model, linked through node IDs; they are not part of public schema 2.0.

## Command line

From `backend`:

```powershell
.\.venv\Scripts\odos.exe --help
.\.venv\Scripts\odos.exe process "C:\path\law.pdf" -o output/law --mode german_law
.\.venv\Scripts\odos.exe process "C:\path\eu.pdf" -o output/eu --mode eu_legislation
```

Replace the example paths with actual PDF paths. The CLI requires an explicit profile for `process`, unlike automatic profile selection through the web API.

To run individual steps:

```powershell
.\.venv\Scripts\odos.exe extract "C:\path\law.pdf" -o output/raw
.\.venv\Scripts\odos.exe normalize output/raw/docling_raw.json --pdf "C:\path\law.pdf" --mode german_law
.\.venv\Scripts\odos.exe legal-json output/raw/document_model.json
```

`extract --ocr` enables OCR for extraction. The current upload interface does not expose an OCR option. Supplying `--pdf` during normalization provides the text-layer evidence needed for applicable source repairs and precise highlights.

## Storage and configuration

| Variable | Meaning |
|---|---|
| `ODOS_STORAGE_DIR` | Job-file directory; defaults to temporary storage removed at shutdown |
| `ODOS_MAX_UPLOAD_MB` | Upload size limit; default 50 MB |

Set environment variables before starting Uvicorn. Jobs are registered in memory. Retaining files using `ODOS_STORAGE_DIR` does not restore old jobs after restart, unless the optional PostgreSQL persistence (`ODOS_DATABASE_ENABLED=1`) is used; see [database-poc.md](../Documentation/database-poc.md). Without it, older completed jobs may be removed as the job limit is reached.

Without database persistence the uploaded PDF is deleted after processing (the frontend displays its local copy); with it, the PDF and the result files stay in `ODOS_STORAGE_DIR` until the job is deleted. Docker Compose enables the persistence, see [DOCKER.md](../DOCKER.md). Keep uploaded PDFs, generated data and virtual environments out of Git.

## Source layout

| Path | Contents |
|---|---|
| `src/odos/api.py` | Web API and job handling |
| `src/odos/pipeline.py` | End-to-end pipeline |
| `src/odos/extraction.py` | Docling extraction |
| `src/odos/normalization/` | Source preparation and highlight geometry |
| `src/odos/parsing/` | Shared parsing engine and legal profiles |
| `src/odos/document_model.py` | Internal data model |
| `src/odos/legal_json/` | Public definitions, export and validation |
| `schemas/odos-legal-json/2.0/` | Published Legal JSON schema |
| `pyproject.toml` | Package metadata, direct dependencies and CLI entry point |
| `requirements.lock` | Pinned dependency set |

## Manual verification

After backend changes, process representative German and EU PDFs. Inspect the output, warnings and validation reports; compare selected passages, numbering, lists and source locations against the PDFs. Verify the frontend can load the model, Legal JSON and raw JSON.

Runtime validation checks output structure and consistency; it does not prove legal correctness or replace an automated regression suite.

Further information: [architecture](../Documentation/architecture.md), [development](../Documentation/development.md) and [Legal JSON](../Documentation/legal-json.md).
