# ODOS – Ontology-Driven Operating System

AMOS WS 2026 research prototype for converting legal PDFs into structured legal JSON.

Project mission: In this project we turn laws and standards into rules that a computer can check. We start with two documents, the EU Machinery Regulation and the German Musterbauordnung. We read their PDFs into a structured JSON, extract the rules from it, and check digital twins against those rules, so that only designs that follow the law pass. For Wisdom Bridge AI, we deliver a clear recommendation and a working prototype.

Upload a PDF in the web app. The Python backend extracts its content with Docling, recognizes a German-law or German-language EU structure, and exports Custom Legal JSON 2.0. The frontend displays the original PDF, the recognized hierarchy with source highlighting, and JSON results.

## Current scope

- Live PDF processing through a FastAPI backend.
- German-law and EU-legislation parsing profiles, developed around the Musterbauordnung and Regulation (EU) 2023/1230.
- Custom Legal JSON for the selected element or the full document, with a full-document download.
- A collapsible Docling Raw JSON view below Custom Legal JSON, provided the raw-output API and UI extension has been applied.
- Runtime schema validation and diagnostic reports.

The simplified version has no prepared-example mode. Automated backend and frontend tests are described in [development](Documentation/development.md#manual-verification). Recognition of a document's structure does not guarantee that every passage is parsed correctly. Review warnings and compare the output with the PDF.

LLM-based rule extraction and digital-twin validation are future steps. Akoma Ntoso XML is not generated in this version.

## Requirements

- Python 3.12
- Node.js 22.12 or newer, including npm
- Network access for installation and the first Docling model download
- A few GB of free disk space

Processing time depends on the computer and PDF. The first extraction may take considerably longer while Docling downloads its models.

## First-time setup on Windows

Extract the ZIP completely, or clone the repository. Open the project folder containing `backend` and `frontend` in VS Code. Execute commands one at a time and stop if a command fails.

### Backend

From the project root, open a PowerShell terminal:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m uvicorn odos.api:app --port 8000
```

Leave this terminal running. The backend API documentation is available at `http://127.0.0.1:8000/docs`. A 404 at `/` is expected: the backend does not serve the frontend page there.

### Frontend

Open a second PowerShell terminal at the project root:

```powershell
cd frontend
npm ci
npm run dev
```

Open the URL printed by Vite, normally `http://localhost:5173`. Select a PDF and press **Process Document**. No demo-data generation is needed. Leave both terminals running.

The document type is recognized from legal structures such as German section headings or EU articles, not from the filename. Unrecognized or ambiguous documents are reported as unsupported.

## Later starts

Installation is only needed again when dependencies change or a new environment is created.

In a terminal inside `backend`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn odos.api:app --port 8000
```

In another terminal inside `frontend`:

```powershell
npm run dev
```

Stop a server with **Ctrl+C**. If port 8000 is occupied, stop the previous backend instance before starting another. After a backend restart, process the PDF again: in this local setup job information is held in memory. Docker Compose stores jobs in PostgreSQL instead, see [DOCKER.md](DOCKER.md).

## Results

| File | Purpose |
|---|---|
| `docling_raw.json` | Original Docling extraction, including layout and source references |
| `document_model.json` | Internal legal model with provenance, highlights and diagnostics |
| `document.json` | Public Custom Legal JSON 2.0 |
| `legal_json_validation_report.json` | Schema, structure and source-related validation results |

The internal model links the public legal nodes to Docling items and PDF locations. Technical provenance remains in the model, rather than the public 2.0 schema.

Legal JSON nodes give the source-language legal term in `germanType`, for example `Absatz`. The schema also accepts the earlier name `nativeType`, so documents written before the rename stay valid; the frontend preview shows either as `germanType`.

If the Docling panel cannot load, check that `DOCLING_RAW` is imported and included in `RESULT_FILES` in `backend/src/odos/api.py`. Restart the backend after changing it and process the PDF again.

## Build and manual verification

From `frontend`:

```powershell
npm run typecheck
npm run build
npm run preview
```

The build also checks TypeScript and writes the frontend to `dist/`. Preview normally runs at `http://localhost:4173` and still requires the backend. A separate production host needs API routing; the frontend build does not deploy Python.

Before a release, process both a German-law and EU example. Check the hierarchy, selected-element and full-document JSON, downloaded JSON, PDF highlights and collapsible raw output. Also check the error shown for an unsupported document. Runtime validation remains enabled in every run; the automated tests do not replace this check.

## Configuration and storage

| Variable | Purpose |
|---|---|
| `ODOS_STORAGE_DIR` | Backend job-file location; temporary storage is used by default |
| `ODOS_MAX_UPLOAD_MB` | Upload size limit; default 50 MB |
| `ODOS_API_URL` | Vite proxy's backend address; default `http://127.0.0.1:8000` |

Set variables before starting the corresponding process. Jobs are processed one at a time. Uploaded PDFs are deleted after processing; the browser displays its own local copy. Temporary storage is removed on shutdown, and old completed jobs may be deleted as the job limit is reached.

Setting `ODOS_STORAGE_DIR` retains files but does not restore the in-memory job registry after restart. Do not commit uploaded PDFs, generated document data, virtual environments or `node_modules`.

Optional persistence: with a local PostgreSQL 17 database (Docker Compose) and `ODOS_DATABASE_ENABLED=1`, jobs and their Legal JSON are stored as JSONB and restored after a backend restart; the uploaded PDF and result files are kept, and old jobs are not removed automatically. See the [PostgreSQL proof of concept](Documentation/database-poc.md). [DOCKER.md](DOCKER.md) runs PostgreSQL, backend and frontend with Docker Compose, with this persistence enabled. To start the stack and inspect the stored Legal JSON with `psql`, see the [Docker and PostgreSQL developer guide](Documentation/docker-postgresql-guide.md).

## Repository layout

| Folder | Contents |
|---|---|
| `backend/` | Python pipeline, API, CLI and Legal JSON schema |
| `frontend/` | React/TypeScript application and Vite configuration |
| `Documentation/` | [Architecture and development documentation](Documentation/README.md) |
| `Deliverables/` | Sprint submission materials |

For command-line processing, parsing details and schema changes, see [Documentation/README.md](Documentation/README.md).
