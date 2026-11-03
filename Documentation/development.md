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

The first extraction downloads Docling's layout and table models from Hugging Face (several minutes, network
needed). Later runs take about 10 s for a 45-page law. Setting `HF_TOKEN` silences the unauthenticated-request
warning.

## Command line (`odos`)

```bash
odos process <pdf> -o <dir> --mode german_law|eu_legislation   # the whole pipeline
odos extract <pdf> -o output/doc                               # Docling: docling_raw.json + extracted.md (--ocr for scans)
odos normalize output/doc/docling_raw.json --pdf <pdf>         # document_model.json + validation report (--mode eu_legislation)
odos legal-json output/doc/document_model.json                 # document.json (Custom Legal JSON 2.0) + validation report
```

- **`--mode` for `process`:** required. The profile is never guessed from the document.
- **`--pdf` for `normalize`:** it writes the PDF text-layer evidence (`pdf_text_lines.json`) first.
  Without it, reading-order repair, character restoration, footnote anchoring and exact highlights are
  skipped.
- **Custom Legal JSON is the only export.** Akoma Ntoso XML (`odos akn`, `--retrieval-date`) was removed from the
  prototype.

## Running the web application

```bash
cd backend && source .venv/bin/activate && uvicorn odos.api:app --port 8000   # terminal 1
cd frontend && npm run dev                                                     # terminal 2: http://localhost:5173
```

`ODOS_STORAGE_DIR` keeps the job directories somewhere other than a temporary directory (they are not removed at
shutdown then; inside the repository use a `storage/documents/` path, which is gitignored). `ODOS_MAX_UPLOAD_MB`
sets the upload limit (default 50). `ODOS_API_URL` points the frontend's proxy at another backend address.

## Producing the demonstration data (prepared examples)

```bash
# 1. pipeline output for the two demo documents
odos process <MBO.pdf>          -o output/mbo --mode german_law
odos process <eu_2023_1230.pdf> -o output/eu  --mode eu_legislation

# 2. demo fixtures (frontend/public/demo/, git-ignored) and the static site
cd ../frontend
npm ci
npm run demo:fixtures -- --mbo ../backend/output/mbo --eu ../backend/output/eu
# (or, in one step with PDF and fixture hash checks: npm run demo:setup -- --mbo-pdf <MBO.pdf> --eu-pdf <eu.pdf>)
npm run dev                # http://localhost:5173
npm run build         # type check + static site in dist/
npm run preview            # http://localhost:4173
```

The fixtures contain the full text of the partner documents. `public/demo/` and `dist/` are git-ignored and must
not be published (see the root README).

## Tests

```bash
cd backend && source .venv/bin/activate && pytest     # about 50 tests, about 1 minute (network needed for Docling models)
cd frontend && npm test && npm run typecheck && npm run build
```

**Test inputs:**

- **No public law is stored in the repository.** Docling extractions of the partner PDFs are written to
  `backend/output/` (gitignored) on the first run, which takes a few minutes.
- **The Musterbauordnung (MBO)** was supplied by the industry partner and is not in Git. Provide it as
  `backend/data/input/private/MusterBauVerordnung.pdf` or with `ODOS_MBO_PDF`. The tests that need it are in
  `backend/tests/private/` (gitignored: they assert on the partner document) and skip with a reason when it is
  missing.
- **The full Regulation (EU) 2023/1230** is not redistributed with the repository. Provide it in one of
  two ways:
  - set `ODOS_EU_PDF=/path/to/the.pdf`
  - copy it to `backend/data/input/private/eu_2023_1230.pdf` (gitignored, so it cannot be committed)

  The tests check its SHA-256 (`fe36f0d1…`). Without it, the full-document EU tests skip and say why.
- **The synthetic German law** (`backend/tests/synthetic_german.py`) always runs. It is original text with a
  generated PDF, so the PDF text-layer evidence is real: footnote anchors and printed Satz numbers are proven
  from superscript marks. Glyph coordinates come from pdfium and can differ in the last decimals between
  platforms, so the tests assert structure and validity, not hashes.
- **The synthetic EU regulation** (`backend/tests/synthetic_eu.py`) always runs. It is original text in
  Docling's JSON shape and covers every EU structural unit end to end, including Legal JSON 2.0.
- **Frontend:** `frontend/src/demo/mbo_par6.test.ts` and `legal_json_excerpt.test.ts` read the local fixtures
  (`public/demo/`, and `.demo-work/` for the comparison with `document.json`) and skip without them. All other frontend tests use synthetic data.
- **Never runtime output:** tests write only to temporary directories and `backend/output/`.

**Where each kind of test lives:**

| Test | What it covers |
|---|---|
| `test_api.py` | the web API: upload checks, job lifecycle, result files and download, document type detection, errors, cleanup; the real pipeline on the synthetic PDF and (when available) the MBO and Regulation (EU) 2023/1230 |
| `test_extraction.py` | Docling extraction (missing PDF, a real conversion) and the locked dependency set |
| `test_german_law.py`, `test_eu_legislation.py` | the German and EU profiles on the synthetic documents, and the EU profile on the real regulation |
| `tests/private/test_mbo.py` (local only) | the real Musterbauordnung: paragraph set against the PDF text layer, hierarchy, footnotes, page-break text, no content loss |
| `test_legal_json.py` | Custom Legal JSON 2.0: schema, text equal to the model and the PDF text layer, no internal data, nesting rules, schema drift, real MBO and EU examples |
| `test_highlights.py` | exact highlight rectangles from PDF glyphs, and missing or unreadable PDF evidence |
| `frontend/src/structure.test.ts` | hierarchy, search, highlight geometry, TOC view |
| `frontend/src/demo/*.test.ts(x)` | upload and matching, unsupported PDFs, result view, Custom Legal JSON preview and downloads, MBO § 6 Absatz 1, the Legal JSON 2.0 excerpts and their traceability to the model |
| `frontend/src/demo/live.test.tsx` | live mode against a fake backend (stages, errors, unreachable backend), the result view, preview (selected element and full document) and download; on the real pipeline outputs in `.demo-work/` when present |

## Conventions

- **The DocumentModel is the single source of truth.** Exports are one-way serializations; nothing reads
  them back as input.
- **Nothing is invented.** Uncertain readings are kept and flagged (`uncertain`, `uncertainty_reasons`). Text is
  never silently changed: every restored character is recorded with its evidence.
- **Output changes are deliberate.** Any change to legal text, IDs, hierarchy, sentences, TOC links,
  footnote anchors, coordinates or JSON must be deliberate: the real-document tests and `npm run demo:verify` show it.
