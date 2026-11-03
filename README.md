# ODOS – Ontology-Driven Operating System (AMOS WS 2026)

Research prototype: upload a legal PDF and the ODOS backend recognizes whether it is German or EU legislation and
runs the real pipeline on it (Docling extraction, normalization, legal parser, DocumentModel, Custom Legal
JSON 2.0 with schema validation). The browser shows the original PDF next to the recognized legal structure (with
source highlighting), a JSON preview of the selected element or of the full document, and the download of the complete
Custom Legal JSON 2.0 document. Custom Legal JSON is the only export; Akoma Ntoso XML is no longer part of the
prototype.

## Run ODOS (live processing)

Required: Python 3.12, Node.js 22.12 or newer, network access for the first run (Docling downloads its models,
several minutes), and a few GB of disk space.

```bash
# 1. the backend (once)
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
pip install --no-deps -e ".[dev]"

# 2. start the API (http://127.0.0.1:8000, single instance; jobs and their files are kept in a temporary directory
#    that is removed at shutdown, or under ODOS_STORAGE_DIR; uploads are limited to ODOS_MAX_UPLOAD_MB, default 50)
uvicorn odos.api:app --port 8000

# 3. in a second terminal: the frontend (proxies /api to the backend; another address: ODOS_API_URL=...)
cd frontend
npm ci
npm run dev                # http://localhost:5173
```

Pick a PDF and press **Process Document**. Every upload is processed by the pipeline, also a PDF that is one of the
prepared examples; nothing is looked up by file hash. The document type is recognized from the document's own structure
(German sections `§ <n>` or EU articles `Artikel <n>`), never from the file name. Processing
the MBO (83 pages) or Regulation (EU) 2023/1230 (102 pages) takes about 20 seconds on a recent Mac once the Docling
models are downloaded. A document in which neither or both structures are found is refused with a clear message; a PDF Docling
cannot read is reported as failed (details only in the server log).

API (`backend/src/odos/api.py`): `POST /api/jobs` (multipart `file`), `GET /api/jobs/{id}` (status, stage,
message, summary), `GET /api/jobs/{id}/files/{name}` (`document_model.json`, `document.json`;
`?download=true` for an attachment), `DELETE /api/jobs/{id}`.


```bash
# 1. the offline pipeline (once)
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock          # exactly the versions the reference data was produced with
pip install --no-deps -e ".[dev]"
cd ..

# 2. the frontend
cd frontend
npm ci

# 3. check your PDFs, run the pipeline on both, build the demo data and compare it with the reference (10+ minutes)
npm run demo:setup -- --mbo-pdf /path/to/MusterBauVerordnung.pdf --eu-pdf /path/to/eu_2023_1230.pdf

# 4. start the demo and upload one of the two PDFs at http://localhost:5173/?example
npm run dev
```


Other commands (in `frontend/`): `npm test`, `npm run typecheck`, `npm run build` (type check and static site in
`dist/`), `npm run preview`. `public/demo/` and `dist/` hold the full text of the partner documents: do not publish or
deploy them until the licensing is clarified.


## Repository layout

| Path | Contents |
|---|---|
| `backend/` | the pipeline (`odos`): Docling extraction, parsing engine, Custom Legal JSON, the web API, tests (`backend/README.md`) |
| `frontend/` | the web app (React, TypeScript, Vite), its live and prepared-example modes, the fixture scripts (`frontend/README.md`) |
| `Documentation/` | architecture, parsing, document model, Legal JSON, development guide |

The always-running backend tests use synthetic documents and need no partner PDF
(`Documentation/development.md`).
