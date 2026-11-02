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
odos process <pdf> -o <dir> --mode german_law|eu_legislation --retrieval-date YYYY-MM-DD   # the whole pipeline
odos extract <pdf> -o output/doc                               # Docling: docling_raw.json + extracted.md (--ocr for scans)
odos normalize output/doc/docling_raw.json --pdf <pdf>         # document_model.json + validation report (--mode eu_legislation)
odos legal-json output/doc/document_model.json                 # document.json (Custom Legal JSON 1.1) + validation report
odos akn output/doc/document_model.json --retrieval-date YYYY-MM-DD   # Akoma Ntoso: German § excerpt (--paragraphs 1 2) -> german_law_excerpt.xml, EU whole document -> document_akn.xml
```

- **`--mode` for `process`:** required. The profile is never guessed from the document.
- **`--pdf` for `normalize`:** it writes the PDF text-layer evidence (`pdf_text_lines.json`) first.
  Without it, reading-order repair, character restoration, footnote anchoring and exact highlights are
  skipped.
- **Retrieval date:** `odos akn` and `odos process` require `--retrieval-date YYYY-MM-DD`, the date the PDF was
  retrieved. It is recorded in the XML (`Abruf`, `Konvertierung`) and never assumed.

## Producing the demonstration data

```bash
# 1. pipeline output for the two demo documents
odos process <MBO.pdf>          -o output/mbo --mode german_law    --retrieval-date YYYY-MM-DD
odos process <eu_2023_1230.pdf> -o output/eu  --mode eu_legislation --retrieval-date YYYY-MM-DD

# 2. demo fixtures (frontend/public/demo/, git-ignored) and the static site
cd ../frontend
npm ci
npm run demo:fixtures -- --mbo ../backend/output/mbo --eu ../backend/output/eu
# (or, in one step with PDF and fixture hash checks: npm run demo:setup -- --mbo-pdf <MBO.pdf> --eu-pdf <eu.pdf>)
npm run dev                # http://localhost:5173
npm run build:demo         # type check + static site in dist/
npm run preview            # http://localhost:4173
```

The fixtures contain the full text of the partner documents. `public/demo/` and `dist/` are git-ignored and must
not be published (see the root README).

## Tests

```bash
cd backend && source .venv/bin/activate && pytest     # ~370 tests, about 2 minutes (network needed for Docling models)
cd frontend && npm test && npm run typecheck && npm run build:demo
```

**Test inputs:**

- **No public law is stored in the repository.** Docling extractions of the partner PDFs are written to
  `backend/output/` (gitignored) on the first run, which takes a few minutes.
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
  from superscript marks. It has no golden baseline: glyph coordinates come from pdfium and can differ in the last
  decimals between platforms, so the tests assert structure and validity.
- **The synthetic EU regulation** (`backend/tests/synthetic_eu.py`) always runs. It is original text in
  Docling's JSON shape and covers every EU structural unit end to end, including JSON 1.1, the 1.0
  downgrade and Akoma Ntoso XSD validation.
- **Frontend:** `frontend/src/demo/mbo_par6.test.ts` reads the local fixtures (`public/demo/`) and skips without
  them. All other frontend tests use synthetic data.
- **Never runtime output:** tests write only to temporary directories and `backend/output/`.

**Golden equivalence** (`tests/test_golden_equivalence.py`):

- **What it checks:** every output against the recorded baselines in `tests/golden/`, on the exact
  Docling extractions the baselines were built from.
- **What every run prints:**

  ```
  GOLDEN COVERAGE: MBO ✓ · EU ✓ · synthetic EU ✓
  full partner-document equivalence (MBO and EU): yes
  ```

- **Missing or different input:** shown as `✗ not covered: <reason>`, never as a pass. Skip reasons are
  always printed (`-rs`).
- **A difference** is a regression to investigate, never a value to refresh: `record_baseline` refuses
  to overwrite a baseline.
- **The MBO § 6 Absatz 1 baseline** records the one deliberate change since the original baselines (the page-break
  merge, see [parsing.md](parsing.md)).

**Where each kind of test lives:**

| Test | What it covers |
|---|---|
| `test_golden_equivalence.py`, `golden_outputs.py` | byte-identical outputs and coverage reporting |
| `test_engine_profiles.py` | registry, lifecycle order, profile tables, import isolation, CLI dispatch |
| `test_synthetic_eu.py`, `test_synthetic_german.py` | the EU and German profiles end to end without private files |
| `test_normalization.py`, `test_eu_parser.py`, `test_eu_parser_rules.py` (plus the local-only `tests/private/test_mbo.py`) | German and EU recognition (real and synthetic) |
| `test_hygiene.py`, `test_reading_order.py`, `test_source_text.py`, `test_highlights.py`, `test_sentences_toc_refs.py` | the source layer and the lifecycle stages |
| `test_legal_json.py`, `test_akn.py`, `test_eu_akn.py` | exports and their validation |
| `test_extraction.py`, `test_environment.py` | extraction, dependency drift |
| `frontend/src/structure.test.ts` | hierarchy, search, highlight geometry, TOC view |
| `frontend/src/demo/*.test.ts(x)` | upload and matching, unsupported PDFs, result view, JSON/XML previews and downloads, MBO § 6 Absatz 1 |

## Conventions

- **The DocumentModel is the single source of truth.** Exports are one-way serializations; nothing reads
  them back as input.
- **Nothing is invented.** Uncertain readings are kept and flagged (`uncertain`, `uncertainty_reasons`). Text is
  never silently changed: every restored character is recorded with its evidence.
- **Output changes are deliberate.** Any change to legal text, IDs, hierarchy, sentences, TOC links,
  footnote anchors, coordinates, JSON or XML must show up as a golden difference and be explained.
