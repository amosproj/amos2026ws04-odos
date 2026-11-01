# Local development and testing

## Backend setup (Python 3.12)

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock          # the exact dependency set the outputs were verified with
pip install --no-deps -e ".[dev]"
```

**Install from the lock, not with a plain `pip install -e .`.** Docling's output depends on
`docling-parse`, `torch`, `transformers` and `docling-core`, and newer versions segment, label and order
the same PDF differently. `tests/test_environment.py` reports such drift. Even with the lock, a few
table and picture box coordinates vary by about 1e-5 between extractions; text, items, labels and order
do not.

The first extraction downloads Docling's layout and table models from Hugging Face (several minutes).
Later runs take about 10 s for the 45-page BDSG. Setting `HF_TOKEN` silences the unauthenticated-request
warning.

## Run the application

```bash
cd backend && source .venv/bin/activate && odos serve          # API on http://127.0.0.1:8000 (OpenAPI: /docs)
cd frontend && npm install && npm run dev                      # UI on http://localhost:5173 (proxies /api to :8000)
```

- **Restart:** stop either process with Ctrl+C and start it again.
- **Live reload:** `odos serve --reload` reloads the backend on code changes. Vite always reloads the
  frontend.
- **Port in use:** if 5173 is taken, Vite picks the next free port (it prints it).
- **Other backend:** `ODOS_API_TARGET=http://host:port npm run dev` points the frontend's proxy at it.

**Backend configuration (environment variables):**

| Variable | Default | Meaning |
|---|---|---|
| `ODOS_STORAGE_DIR` | `backend/storage` (gitignored) | uploaded documents, artifacts and reviews |
| `ODOS_MAX_UPLOAD_MB` | 50 | upload limit |
| `ODOS_MAX_QUEUE` | 8 | waiting jobs |
| `ODOS_WORKERS` | 1 | processing threads |
| `ODOS_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | only needed when the UI is served from another origin |

## Command line (`odos`)

```bash
odos extract data/input/BDSG.pdf -o output/bdsg                        # Docling: docling_raw.json + extracted.md (--ocr for scans)
odos normalize output/bdsg/docling_raw.json --pdf data/input/BDSG.pdf  # document_model.json + validation report (--mode eu_legislation)
odos legal-json output/bdsg/document_model.json                        # document.json (Custom Legal JSON 1.1) + validation report
odos akn output/bdsg/document_model.json                               # Akoma Ntoso: German § excerpt (--paragraphs 1 2), EU whole document
odos akn4eu output/eu/document_model.json                              # AKN4EU export of an EU document (--eli <verified ELI>)
odos classify data/input/BDSG.pdf                                      # suggested document type and mode, with evidence
odos serve                                                             # the web API
```

- **`--pdf` for `normalize`:** it writes the PDF text-layer evidence (`pdf_text_lines.json`) first.
  Without it, reading-order repair, character restoration, footnote anchoring and exact highlights are
  skipped.
- **Retrieval date for `odos akn`:** pass `--retrieval-date`. If omitted, the command takes the
  download date recorded in `data/input/SOURCE.md`.

## Tests

```bash
cd backend && source .venv/bin/activate && pytest     # ~610 tests, about 4–5 minutes
cd frontend && npm test && npm run build              # 64 unit tests; type check and production build
```

**Test inputs:**

- **BDSG:** `backend/data/input/BDSG.pdf` is public, in Git and hash-pinned in `SOURCE.md`. Docling
  extractions of all test PDFs are written to `backend/output/` (gitignored) on the first run, which takes
  a few minutes.
- **The Musterbauordnung (MBO)** was supplied by the industry partner and is not in Git. Provide it as
  `backend/data/input/private/MusterBauVerordnung.pdf` or with `ODOS_MBO_PDF`. The tests that need it are in
  `backend/tests/private/` (gitignored: they assert on the partner document) and skip with a reason when it is
  missing. `backend/tests/fixtures/private/` (gitignored) holds partner-derived Docling items for the
  hygiene tests.
- **The full Regulation (EU) 2023/1230** is not redistributed with the repository. Provide it in one of
  two ways:
  - set `ODOS_EU_PDF=/path/to/the.pdf`
  - copy it to `backend/data/input/private/eu_2023_1230.pdf` (gitignored, so it cannot be committed)

  The tests check its SHA-256 (`fe36f0d1…`). Without it, the full-document EU tests skip and say why.
- **The synthetic German law** (`backend/tests/synthetic_german.py`) always runs. It is original text with a
  generated PDF, so the PDF text-layer evidence is real: footnote anchors and printed Satz numbers are proven
  from superscript marks. It covers Teil, Kapitel, §, Absatz, Nummer, Buchstabe, Anlage with a table, the
  table of contents and its links, JSON 1.1, the 1.0 downgrade, Akoma Ntoso XSD validation and the whole
  pipeline run. It has no golden baseline: glyph coordinates come from pdfium and can differ in the last
  decimals between platforms, so the tests assert structure and validity.
- **The synthetic EU regulation** (`backend/tests/synthetic_eu.py`) always runs. It is original text in
  Docling's JSON shape and covers every EU structural unit end to end, including JSON 1.1, the 1.0
  downgrade and Akoma Ntoso XSD validation.
- **Never runtime storage:** tests do not read `backend/storage/`, and they write only to temporary
  directories and `backend/output/`.

**Golden equivalence** (`tests/test_golden_equivalence.py`):

- **What it checks:** every output against the recorded baselines in `tests/golden/`, on the exact
  Docling extractions the baselines were built from.
- **What every run prints:**

  ```
  GOLDEN COVERAGE: MBO ✓ · BDSG ✓ · EU ✓ · synthetic EU ✓
  full three-document equivalence: yes
  ```

- **Missing or different input:** shown as `✗ not covered: <reason>`, never as a pass. Skip reasons are
  always printed (`-rs`).
- **A difference** is a regression to investigate, never a value to refresh: `record_baseline` refuses
  to overwrite a baseline.
- **Long runs on a laptop:** several API tests run the real Docling extraction and poll with a timeout.
  If the machine sleeps during the run, they time out, so keep it awake (macOS: `caffeinate -i pytest`).

**Where each kind of test lives:**

| Test | What it covers |
|---|---|
| `test_golden_equivalence.py`, `golden_outputs.py` | byte-identical outputs and coverage reporting |
| `test_engine_profiles.py` | registry, lifecycle order, profile tables, import isolation, CLI dispatch |
| `test_synthetic_eu.py`, `test_synthetic_german.py` | the EU and German profiles end to end without private files |
| `test_normalization.py`, `test_eu_parser.py`, `test_eu_parser_rules.py` (plus the local-only `tests/private/test_mbo.py`) | German and EU recognition (real and synthetic) |
| `test_hygiene.py`, `test_reading_order.py`, `test_source_text.py`, `test_highlights.py`, `test_sentences_toc_refs.py` | the source layer and the lifecycle stages |
| `test_legal_json.py`, `test_akn.py`, `test_eu_akn.py`, `test_akn4eu.py` | exports and their validation |
| `test_api.py`, `test_review.py`, `test_delete.py`, `test_classification.py`, `test_extraction.py`, `test_environment.py` | API, review, deletion, classification, extraction, dependency drift |

## Conventions

- **The DocumentModel is the single source of truth.** Exports are one-way serializations; nothing reads
  them back as input.
- **Nothing is invented.** Uncertain readings are kept, flagged (`uncertain`, `warnings`) and left for
  review. Text is never silently changed: every restored character is recorded with its evidence.
- **Output changes are deliberate.** Any change to legal text, IDs, hierarchy, sentences, TOC links,
  footnote anchors, coordinates, warnings, JSON or XML must show up as a golden difference and be
  explained.
