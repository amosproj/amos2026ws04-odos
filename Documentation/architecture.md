# ODOS architecture

ODOS is a pipeline with a thin web API plus a web application:

- a Python package (`backend/src/odos/`) with a command line (`odos`) that turns a PDF into structured legal data,
  and a web API (`odos.api`, FastAPI) that runs that pipeline on uploaded PDFs
- a React application (`frontend/`) that uploads a PDF to the API and shows the results; a prepared example mode
  shows pre-computed results for two prepared documents without processing

There is one canonical data model, the `DocumentModel`. Every output is derived from it. There is no database and no
user interface for corrections; the API is a single-instance development MVP (jobs in memory, one at a time).

```
PDF ──Docling──▶ docling_raw.json ──parse_document──▶ document_model.json ──┬─▶ document.json (Custom Legal JSON 2.0)
        (extraction)        + pdf_text_lines.json   (normalization +        └─▶ validation reports
                              (PDF text-layer evidence) parsing)                          │
                                                       frontend/scripts/build-demo-fixtures.mjs
                                                                                          ▼
                                                    frontend/public/demo/  ──▶  static site (dist/)
```

## Where is what

| Concern | Location | Docs |
|---|---|---|
| PDF extraction (Docling) | `backend/src/odos/extraction.py` | [development.md](development.md) |
| Reading order, text restoration, extraction hygiene, highlight geometry | `backend/src/odos/normalization/` | [parsing.md](parsing.md) |
| The universal parsing engine (lifecycle) | `backend/src/odos/parsing/engine.py` (entry point `odos.parsing.parse_document`) | [parsing.md](parsing.md) |
| German and EU legal profiles | `backend/src/odos/parsing/profiles/german_law/`, `…/eu_legislation/` | [parsing.md](parsing.md) |
| The canonical DocumentModel | `backend/src/odos/document_model.py` | [document-model.md](document-model.md) |
| Custom Legal JSON 2.0 (export and validation) | `backend/src/odos/legal_json/`, `backend/schemas/odos-legal-json/` | [legal-json.md](legal-json.md) |
| Pipeline (one processing run) | `backend/src/odos/pipeline.py` | below |
| CLI | `backend/src/odos/cli.py` | [development.md](development.md) |
| Names of the files written per document | `backend/src/odos/artifact_names.py` | below |
| Web API (upload, jobs, result files) | `backend/src/odos/api.py` | below |
| Web application | `frontend/src/demo/`, `frontend/scripts/build-demo-fixtures.mjs` | below |

**Dependency direction:** `document_model` ← `normalization` ← `parsing` ← `legal_json` ← `pipeline` ← `cli`, `api`.
No module imports "upwards".

## The pipeline (`pipeline.run_pipeline`, `odos process`)

1. **Extraction:** Docling converts the PDF once (`docling_raw.json`, `extracted.md`). `extraction.json` records
   the PDF's SHA-256.
2. **PDF text-layer evidence:** `pdf_text_lines.json`, used to verify and repair the reading order, restore
   characters, prove footnote anchors and compute exact highlights.
3. **Parsing:** with the explicitly chosen profile (`german_law` or `eu_legislation`, as `odos process --mode` does) or,
   without one (the web API), with every profile: exactly one must find its structure (`has_structure`), which is the
   document's type. A document without the structure, or where both are found, ends as `unsupported` with a plain
   explanation.
4. **Outputs:** `document_model.json`, `document.json` (schema-validated, text checked against the model) and the
   validation reports. Custom Legal JSON is the only export; Akoma Ntoso XML is no longer part of the prototype.

Every artifact name is defined once, in `artifact_names.py`.

## The web API (`odos.api`)

A thin layer over `run_pipeline`: `POST /api/jobs` stores the upload (PDF header and size checked) in a fresh job
directory and queues it; one background thread runs the pipeline per job (stages `extracting`, `normalizing`); `GET
/api/jobs/{id}` reports `queued`, `processing`, `completed`, `unsupported` or `failed`; `GET
/api/jobs/{id}/files/{name}` serves the two result files the app reads (`document_model.json`, `document.json`) (`?download=true`: as an attachment);
`DELETE` removes a job with its files. The uploaded PDF is deleted after processing; the oldest finished jobs beyond
ten are removed; the storage directory is temporary unless `ODOS_STORAGE_DIR` is set. Failures are logged on the
server; the client gets a plain message without paths or stack traces.

## The web application (`frontend/`)

React + TypeScript + Vite. Nothing is computed in the browser beyond cutting the selected element's node out of `document.json`.

**Live mode** (`demo/live.ts`): the PDF is uploaded, the job is polled, and the
document model and `document.json` are loaded. The result view is the one described below; the JSON preview shows the
selected element's node or the full document (`demo/excerpts.mjs` gives `nativeType` the presentation name
`germanType`), and the download is the complete `document.json`.

**Prepared example mode:**

1. `npm run demo:fixtures` reads the pipeline output directories and writes `public/demo/`: per document a
   `structure.json` (the part of the DocumentModel the UI shows, with the provenance the highlighting uses), a
   Legal JSON 2.0 excerpt cut out of `document.json` (`*.legal.json`: a top-level unit down to the shown provisions,
   nodes unchanged except that the key `nativeType` is shown as `germanType`), plus a `manifest.json` with the PDF's SHA-256.
2. The user picks a PDF. The browser hashes it and looks the hash up in the manifest (`demo/fixtures.ts`). Unknown
   files are refused with an explanation.
3. `DemoApp` shows the PDF (`pdfjs-dist`) with highlights, the full structure tree, the Custom Legal JSON preview
   with download (two tabs: Legal structure and Artifacts).

| Module | Role |
|---|---|
| `src/demo/DemoApp.tsx` | upload screen, result view, Custom Legal JSON preview and download |
| `src/demo/live.ts` | live mode: API calls, job polling, the selected element's JSON node |
| `src/demo/excerpts.mjs` | presentation names and JSON formatting, shared with the fixture script |
| `src/demo/fixtures.ts` | prepared examples: manifest, SHA-256 matching, upload checks |
| `src/components/PdfViewer.tsx`, `StructureTree.tsx` | PDF pages with highlight overlays, the structure tree |
| `src/structure.ts` | display tree, labels, search, highlight geometry |
| `src/types.ts` | the fields of the DocumentModel the UI reads |

The demo fixtures hold the full document text, so `public/demo/` and `dist/` must stay local (see the root
README).
