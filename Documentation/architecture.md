# ODOS architecture

ODOS is an offline pipeline plus a static demonstration:

- a Python package (`backend/src/odos/`) with a command line (`odos`) that turns a PDF into structured legal data
- a React application (`frontend/`) that shows pre-computed results of that pipeline for two prepared documents

There is one canonical data model, the `DocumentModel`. Every output is derived from it. There is no server, no
database and no user interface for corrections.

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
| Demonstration | `frontend/src/demo/`, `frontend/scripts/build-demo-fixtures.mjs` | below |

**Dependency direction:** `document_model` ← `normalization` ← `parsing` ← `legal_json` ← `pipeline` ← `cli`.
No module imports "upwards".

## The pipeline (`pipeline.run_pipeline`, `odos process`)

1. **Extraction:** Docling converts the PDF once (`docling_raw.json`, `extracted.md`). `extraction.json` records
   the PDF's SHA-256.
2. **PDF text-layer evidence:** `pdf_text_lines.json`, used to verify and repair the reading order, restore
   characters, prove footnote anchors and compute exact highlights.
3. **Parsing:** with the explicitly chosen profile (`german_law` or `eu_legislation`) through the shared lifecycle.
   A document without the profile's structure ends as `unsupported` with a plain explanation.
4. **Outputs:** `document_model.json`, `document.json` (schema-validated, text checked against the model) and the
   validation reports. Custom Legal JSON is the only export; Akoma Ntoso XML is no longer part of the prototype.

Every artifact name is defined once, in `artifact_names.py`.

## The static demonstration (`frontend/`)

React + TypeScript + Vite. Nothing is processed in the browser.

1. `npm run demo:fixtures` reads the pipeline output directories and writes `public/demo/`: per document a
   `structure.json` (the part of the DocumentModel the UI shows, with the provenance the highlighting uses), a
   Legal JSON 2.0 excerpt cut out of `document.json` (`*.legal.json`: a top-level unit down to the shown provisions,
   nodes unchanged) and `pipeline.json` (processing details), plus a `manifest.json` with the PDF's SHA-256.
2. The user picks a PDF. The browser hashes it and looks the hash up in the manifest (`demo/fixtures.ts`). Unknown
   files are refused with an explanation.
3. `DemoApp` shows the PDF (`pdfjs-dist`) with highlights, the full structure tree, the Custom Legal JSON preview
   with download, and the processing details (Docling output → legal parser → Custom Legal JSON).

| Module | Role |
|---|---|
| `src/demo/DemoApp.tsx` | upload screen, result view, Custom Legal JSON preview and download |
| `src/demo/PipelineView.tsx` | the "Processing details" tab |
| `src/demo/fixtures.ts` | manifest, SHA-256 matching, upload checks, preview helpers |
| `src/components/PdfViewer.tsx`, `StructureTree.tsx` | PDF pages with highlight overlays, the structure tree |
| `src/structure.ts` | display tree, labels, search, highlight geometry |
| `src/types.ts` | the fields of the DocumentModel the UI reads |

The demo fixtures hold the full document text, so `public/demo/` and `dist/` must stay local (see the root
README).
