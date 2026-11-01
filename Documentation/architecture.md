# ODOS architecture

ODOS turns legal PDFs into a reviewable, machine-readable legal structure. It is a modular monolith:

- a Python backend (`backend/src/odos/`) with a CLI (`odos`) and an HTTP API (FastAPI)
- a React frontend (`frontend/`)

There is one canonical data model, the `DocumentModel`. Every output is derived from it.

```
PDF ──Docling──▶ docling_raw.json ──parse_document──▶ document_model.json ──┬─▶ document.json (Custom Legal JSON 1.1)
        (extraction)        + pdf_text_lines.json   (normalization +        ├─▶ document_akn.xml (Akoma Ntoso 3.1, XSD-validated)
                              (PDF text-layer evidence) parsing)            ├─▶ validation reports
                                                                            └─▶ review: corrections → revisions (all of the above, again)
```

## Where is what

| Concern | Location | Docs |
|---|---|---|
| PDF extraction (Docling) | `backend/src/odos/extraction.py` | [development.md](development.md) |
| Reading order, text restoration, extraction hygiene, highlight geometry | `backend/src/odos/normalization/` | [parsing.md](parsing.md) |
| The universal parsing engine (lifecycle) | `backend/src/odos/parsing/engine.py` (entry point `odos.parsing.parse_document`) | [parsing.md](parsing.md) |
| German and EU legal profiles | `backend/src/odos/parsing/profiles/german_law/`, `…/eu_legislation/` | [parsing.md](parsing.md) |
| The canonical DocumentModel | `backend/src/odos/document_model.py` | [document-model.md](document-model.md) |
| Custom Legal JSON 1.1 (export and validation) | `backend/src/odos/legal_json/`, `backend/schemas/odos-legal-json/` | [legal-json.md](legal-json.md) |
| Akoma Ntoso XML (generation and XSD validation) | `backend/src/odos/akn/`, `backend/schemas/akn-3.1-os/` | [akn-mapping.md](akn-mapping.md), [akn-eu-mapping.md](akn-eu-mapping.md), [akn4eu-mapping.md](akn4eu-mapping.md) |
| Review corrections and revisions | `backend/src/odos/review/` | below |
| Document classification and routing | `backend/src/odos/classification/` | below |
| Pipeline (one processing run) | `backend/src/odos/pipeline.py` | below |
| HTTP API, job queue, document storage | `backend/src/odos/api/` | below |
| CLI | `backend/src/odos/cli.py` | [development.md](development.md) |
| Names of the files written per document | `backend/src/odos/artifact_names.py` | below |
| Frontend (document library, workspace, review) | `frontend/src/` | below |
| Future LLM rule extraction | not implemented; integration point below | below |

**Dependency direction:**

- `document_model` ← `normalization` ← `parsing` ← `legal_json`, `akn` ← `pipeline`, `review` ← `api`, `cli`
- `classification` only reads the source layer.
- No module imports "upwards".

## The pipeline (`pipeline.run_pipeline`)

1. **Extraction:** Docling converts the PDF once (`docling_raw.json`, `extracted.md`). `extraction.json`
   records the PDF's SHA-256, so a later run in another mode reuses the extraction.
2. **Mode `extract_only`:** stops here. It makes no claim about the document type.
3. **PDF text-layer evidence:** `pdf_text_lines.json`, used to verify and repair the reading order,
   restore characters, prove footnote anchors and compute exact highlights.
4. **Parsing:** with the mode's profile (`german_law`, `eu_legislation`), through the shared lifecycle.
   - A document without the profile's structure ends as `unsupported` with a plain explanation.
   - In that case only the Docling artifacts are offered.
5. **Outputs:**
   - `document_model.json` with the profile's validation report
   - `document.json` with its validation report
   - the profile's Akoma Ntoso XML with its XSD validation, traceability and text checks
   - The profile supplies the summary and the messages.

Every artifact name is defined once, in `artifact_names.py`. The names are part of the storage layout
and the API, so they never change.

## Storage and API

**Documents.** Each document lives in `backend/storage/documents/<uuid>/` (`ODOS_STORAGE_DIR`):

- `meta.json`: status, mode, routing, summary
- `original.pdf`
- `classification.json`
- `artifacts/`: the files above, plus `akn4eu/` for the optional AKN4EU export
- `review/`: `review.json`, `confirmations.json`, and `revisions/<n>/`

Stored documents and revisions are never rewritten by an upgrade. New code must keep reading them.

**HTTP API.** All routes are under `/api` (OpenAPI at `/docs`):

| Area | Routes |
|---|---|
| Health and library | `GET /health`, `GET /documents`, `POST /documents` (upload) |
| Processing | `POST /documents/{id}/process` (explicit `mode`), `GET …/status`, `GET …/classification` |
| Results | `GET …/structure` (the DocumentModel), `GET …/original`, `GET …/artifacts/{type}` |
| Review | `GET …/review`, `GET …/review/model`, `GET …/review/revisions/{n}/{kind}`, `POST …/review/{corrections,confirmations,approve,request-changes,reopen}` |
| Export | `POST/GET …/exports/akn4eu`, `GET …/exports/akn4eu/files/{name}`, `GET …/exports/akn4eu/{kind}` |
| Deletion | `GET …/deletion-preview`, `DELETE /documents/{id}` |

**Jobs.** They run on an in-process thread pool (`api/jobs.py`): one worker and a bounded queue. There
is no database and no authentication; this is a local MVP.

## Review (`review/`)

Corrections are versioned patches over the untouched original model. Each correction:

- creates a new immutable **model revision**: the effective model plus everything regenerated from it
  (`document.json`, Akoma Ntoso, their validations, the text report)
- regenerates only the sentences and TOC entries that depend on corrected elements
- goes through optimistic locking (`base_revision`)

Only text fields can be corrected (content, title, marker); the structure cannot be edited.
Approval references one revision. It is refused while blocking validation errors, or unchecked
uncertain elements, remain.

## Classification and routing (`classification/`)

The classifier works from the PDF text layer at upload: no Docling, no network, no file name. It
returns:

- a document type
- a confidence *band* (a documented heuristic, not a probability)
- the evidence, with page and snippet

The router (`router.py`) maps the type to a suggested mode:

- German law and model regulations → `german_law`
- EU regulations → `eu_legislation`
- directives, technical standards and unknown documents → `extract_only`

Processing always uses an explicit mode. A manual override is allowed and recorded, with warnings.

## Frontend (`frontend/src/`)

React + TypeScript + Vite. The browser only calls `/api/...`; Vite proxies it to the backend in
development.

| Module | Role |
|---|---|
| `App.tsx`, `documentLibrary.ts` | routes, document library (filter, sort, delete flow) |
| `components/Workspace.tsx` | one document: PDF viewer, structure tree, details, review, exports |
| `structure.ts` | display tree, labels, filters, highlight geometry |
| `classification.ts`, `review.ts`, `exports.ts`, `format.ts` | feature logic (pure functions, unit-tested) |
| `api.ts`, `types.ts` | the API client and the API's types (mirrors the backend models) |

## Future LLM rule extraction (integration point, not implemented)

No code exists for it yet; a `rule_extraction/` package will be created together with the feature.
It should:

- **Read** `document.json` 1.1. It carries the stable element IDs, sentences with exact text ranges,
  TOC entries, footnotes and PDF provenance, so every extracted rule can cite its source.
- **Write** separate artifacts that reference those IDs and sentence IDs.
- **Never** modify the `DocumentModel` or the review revisions.

Extracted rules would get their own review step, in the same way as structure corrections.
