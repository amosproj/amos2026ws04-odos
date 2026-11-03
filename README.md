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

## Prepared examples (static, you need your own copy of both PDFs)

Opening the page as `http://localhost:5173/?example` shows previously generated results for the two partner documents without
processing anything, as the earlier static prototype did. It needs the demo data built below.

The two PDFs were supplied by the industry partner and are **not** in this repository. The generated demo data contains
their full text and is **not** in Git either (`frontend/public/demo/` is git-ignored). You create it locally from your
PDFs with the offline pipeline. Required: Node.js 22.12 or newer, Python 3.12, network access for the first run (Docling
downloads its models, several minutes), and a few GB of disk space.

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

`demo:setup` refuses a PDF whose SHA-256 differs from the one the demo is prepared for. Without a `backend/.venv` it
looks for `odos` on the PATH, or use `--odos <path to the odos executable>`.

Other commands (in `frontend/`): `npm test`, `npm run typecheck`, `npm run build` (type check and static site in
`dist/`), `npm run preview`. `public/demo/` and `dist/` hold the full text of the partner documents: do not publish or
deploy them until the licensing is clarified.

## Verify that two machines show the same thing

| Expected SHA-256 | File |
|---|---|
| `53fd13388013263c3f676a3a8024f6932e38b8d326af6d2d844ecb9be61d340c` | Musterbauordnung PDF |
| `fe36f0d148a84e790ec9a9825017baaea66fb931a5314ad0a614a1cde0ec182c` | Regulation (EU) 2023/1230 PDF |

```bash
cd frontend
npm run demo:verify -- --mbo-pdf /path/to/MusterBauVerordnung.pdf --eu-pdf /path/to/eu_2023_1230.pdf
```

The command compares your two PDFs and the six fixture files plus `manifest.json` in `public/demo/` with
`frontend/scripts/demo-reference.json` (hashes only, no text). For each it prints `identical` (same bytes),
`equivalent` (see below), `DIFFERENT` or `MISSING`. Exit code 0 means identical or equivalent, 1 a difference, 2 a
missing file.

**Two different guarantees.**
- *Static fixtures:* the demo only reads the files in `public/demo/` (and matches the uploaded PDF by its SHA-256). If
  `demo:verify` reports every file `identical`, both machines display exactly the same structure, highlights, previews
  and downloads. The same holds for `equivalent` files, which differ only in Docling's float noise (below).
- *Regenerating with Docling:* `demo:setup` runs the real pipeline again. This is **not guaranteed to be byte-for-byte
  deterministic**. We verified it on one machine: of four regenerations of the two documents, three were byte-identical to
  the reference and one differed in a single table box of the EU regulation, by about 2e-5 pt (the other 1749 elements,
  all text, structure and the Legal JSON excerpts were identical). Such a file is reported as `equivalent` when it
  is exactly equal after rounding all numbers to 0.01 pt. Other Docling/torch versions segment documents differently
  (`Documentation/development.md`); that shows up as `DIFFERENT`, and the demo may then not show the reference data.
  Regeneration on a second machine has not been verified.
- `manifest.json` also holds the SHA-256 of the whole pipeline outputs (`sources`); these follow the float noise and are
  left out of the `equivalent` comparison.

## Repository layout

| Path | Contents |
|---|---|
| `backend/` | the pipeline (`odos`): Docling extraction, parsing engine, Custom Legal JSON, the web API, tests (`backend/README.md`) |
| `frontend/` | the web app (React, TypeScript, Vite), its live and prepared-example modes, the fixture scripts (`frontend/README.md`) |
| `Documentation/` | architecture, parsing, document model, Legal JSON, development guide |

The public backend tests (`pytest`) use synthetic documents and need no partner PDF; the real-PDF regression suite
is kept locally in `backend/tests/private/` (`Documentation/development.md`).
