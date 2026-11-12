# ODOS frontend

React, TypeScript and Vite web application for the ODOS live PDF-processing pipeline.

Select a PDF and press **Process Document**. The browser uploads the file to the Python backend, displays processing progress and loads the results. The backend recognizes supported German-law or German-language EU structures and produces Custom Legal JSON 2.0.

This simplified version has no prepared-example mode or bundled automated frontend tests. It does not require generated demo fixtures.

## Requirements

- Node.js 22.12 or newer, including npm
- The ODOS backend installed and running on port 8000

See the [project README](../README.md) for Python installation and backend setup. The first PDF extraction can take longer because Docling downloads its models.

## Start on Windows

In a terminal inside `backend`, start the installed backend:

```powershell
.\.venv\Scripts\python.exe -m uvicorn odos.api:app --port 8000
```

In a second terminal, starting from the project root:

```powershell
cd frontend
npm ci
npm run dev
```

Open the URL printed by Vite, normally `http://localhost:5173`. Keep both terminals running. On later starts, run `npm run dev` from `frontend`; dependency installation is not needed again unless the dependency setup changes.

## Result views

| View | Contents |
|---|---|
| Original PDF | The selected local PDF, with highlights for recognized elements |
| Legal structure | A hierarchy of legal units and source details for the selected element |
| Custom Legal JSON | Preview of the selected legal node or full document, plus full-document download |
| Docling Raw JSON | A collapsible full-document extraction preview below Custom Legal JSON |

The raw panel loads `docling_raw.json` on first opening and can be collapsed again. It is independent of the selected legal element. Loading errors offer a retry action.

The raw panel requires the corresponding frontend component and the `DOCLING_RAW` API allowlist entry. Rewriting this README does not add those code changes.

PDF highlights use provenance in `document_model.json`. Custom Legal JSON 2.0 omits technical source coordinates. Its node IDs link back to the model.

## Commands

Run these commands inside `frontend`:

| Command | Purpose |
|---|---|
| `npm ci` | Install dependencies using `package-lock.json` |
| `npm run dev` | Start the development server |
| `npm run typecheck` | Check TypeScript types |
| `npm run build` | Check types and write the frontend build to `dist/` |
| `npm run preview` | Serve the built frontend locally, normally on port 4173 |

Development and preview proxy `/api` to the backend. Both require the backend for PDF processing. A separate production host needs equivalent API routing; uploading `dist/` alone does not deploy the backend.

## API connection

The default proxy target is `http://127.0.0.1:8000`. To use another address, set `ODOS_API_URL` before starting Vite:

```powershell
$env:ODOS_API_URL = "http://127.0.0.1:8001"
npm run dev
```

The frontend submits `POST /api/jobs`, polls `GET /api/jobs/{id}`, and retrieves allowed result files from `/api/jobs/{id}/files/{name}`. With database persistence the start page lists the stored documents (`GET /api/documents`); a completed one is reopened from what the backend stored (job, result files and `GET /api/jobs/{id}/pdf`) without processing it again, and a finished one can be deleted after a confirmation (`DELETE /api/jobs/{id}`). Without persistence, going back to the start page removes the job through the API.

## Main files

| File | Responsibility |
|---|---|
| `src/main.tsx` | Application entry point |
| `src/demo/DemoApp.tsx` | Upload, progress, result tabs and raw JSON panel |
| `src/demo/live.ts` | Upload, polling, result loading and selected-node lookup |
| `src/demo/excerpts.mjs` | JSON formatting and presentation names |
| `src/demo/fixtures.ts` | Shared `DemoResult` type only after cleanup; update imports if renamed |
| `src/components/` | PDF viewer, structure tree and icons |
| `src/structure.ts` | Display labels and highlight geometry |
| `src/types.ts` | Internal model fields read by the UI |
| `vite.config.ts` | Vite setup and API proxy |

The historical folder name `demo` remains; these files also implement live processing.

## Troubleshooting

- **Vite not found:** run `npm ci` inside `frontend`.
- **Backend unreachable:** check that Uvicorn is running and the proxy target matches its address.
- **Port 8000 occupied:** stop the previous backend process with Ctrl+C before restarting it.
- **Raw JSON cannot load:** ensure `backend/src/odos/api.py` imports `DOCLING_RAW` and includes it in `RESULT_FILES`. Restart the backend and process the PDF again. Inspect the browser Network panel and backend log if it still fails.
- **Job no longer available:** jobs are tracked in memory and may be removed or lost on backend restart. Upload the PDF again.
- **Unsupported PDF:** the backend found no unique supported legal structure. Check the error message; changing the filename does not change recognition.

Before releasing, run `npm run build` and manually process representative German and EU PDFs. Check highlights, both JSON views, full-document download, collapse/reopen behavior and error messages. These checks do not establish comprehensive parser correctness.

Further details: [architecture](../Documentation/architecture.md) and [development guide](../Documentation/development.md).
