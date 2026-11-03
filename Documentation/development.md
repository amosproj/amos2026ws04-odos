# Local development

## Requirements

- Python 3.12
- Node.js 22.12 or newer and npm
- Network access for dependency installation and the first Docling model download
- Disk space for Python packages and model files

Run commands from the indicated folder. Stop if a command fails. The examples below use Windows PowerShell.

## Install the backend

From the repository root:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

The lockfile supplies the pinned dependency set. Different Docling-related versions can change extraction results. Processing time depends on the machine, PDF and whether models are cached.

Start the backend from `backend`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn odos.api:app --port 8000
```

Leave this terminal running. `http://127.0.0.1:8000/docs` shows the API documentation. A 404 at the backend root `/` is expected; the frontend is served separately.

## Install and start the frontend

In a second terminal, from the repository root:

```powershell
cd frontend
npm ci
npm run dev
```

Open the URL printed by Vite, normally `http://localhost:5173`. Select a supported legal PDF and press **Process Document**. No demo-data generation is required.

## Build and preview

From `frontend`:

```powershell
npm run typecheck
npm run build
npm run preview
```

`build` also runs TypeScript checking and writes the website to `dist/`. Preview normally uses port 4173. Both Vite development and preview proxy `/api` to the backend. A separately hosted production site needs its own API routing configuration.

## Configuration

| Variable | Purpose |
|---|---|
| `ODOS_STORAGE_DIR` | Location for backend job files instead of temporary storage |
| `ODOS_MAX_UPLOAD_MB` | PDF upload limit; default 50 MB |
| `ODOS_API_URL` | Backend address used by the Vite proxy; default `http://127.0.0.1:8000` |

Set variables before starting the corresponding process. Retaining files does not make old jobs available after a backend restart: the registry is in memory.

## Docling Raw JSON panel

The panel assumes these code changes have been applied:

- In `backend/src/odos/api.py`, import `DOCLING_RAW` and include it in `RESULT_FILES`.
- In `frontend/src/demo/DemoApp.tsx`, render a collapsible panel below Custom Legal JSON. Fetch `/api/jobs/{id}/files/docling_raw.json` when opened, show loading/errors, and reset its state when the job changes.

It displays the entire extracted document, not just the selected legal node. It does not alter the pipeline or the Legal JSON schema. Restart the backend after changing its allowlist and process the PDF again if the old job is gone.

## Command line

From `backend`, use `.\.venv\Scripts\odos.exe`:

```powershell
.\.venv\Scripts\odos.exe process "C:\path\law.pdf" -o output/law --mode german_law
.\.venv\Scripts\odos.exe process "C:\path\eu.pdf" -o output/eu --mode eu_legislation
.\.venv\Scripts\odos.exe extract "C:\path\law.pdf" -o output/raw
.\.venv\Scripts\odos.exe normalize output/raw/docling_raw.json --pdf "C:\path\law.pdf" --mode german_law
.\.venv\Scripts\odos.exe legal-json output/raw/document_model.json
```

The CLI `process` command requires an explicit profile. The web API calls the pipeline without a profile and selects one by recognized structure. `extract --ocr` enables OCR for the extraction command; the current upload UI does not expose an OCR option.

## Manual verification

This simplified version does not include an automated test suite. Verify changes by building the frontend and processing both an MBO and German-language EU example:

1. Confirm progress ends successfully and both JSON files can be displayed.
2. Select legal elements and check their text, pages and PDF highlights.
3. Switch between selected-element and full-document Legal JSON.
4. Open and close the Docling panel; compare its source items with the legal output.
5. Download Legal JSON and check that it contains the full document.
6. Try an unsupported PDF and confirm that an understandable error appears.

Runtime validation reports remain useful, but are not a substitute for a test suite or review of the extracted content. Do not commit virtual environments, installed packages, uploaded PDFs or generated document data.
