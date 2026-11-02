# ODOS – Ontology-Driven Operating System (AMOS WS 2026)

Static research prototype: upload one of two prepared legal PDFs (Musterbauordnung, Regulation (EU) 2023/1230) and see
the original PDF next to its recognized legal structure (with source highlighting), plus one provision as Custom Legal
JSON and Akoma Ntoso XML with previews and downloads. Nothing is processed in the browser: the demo shows results that
the offline pipeline in `backend/` generated beforehand.

## Run the demo (you need your own copy of both PDFs)

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

# 4. start the demo and upload one of the two PDFs
npm run dev                # http://localhost:5173
```

`demo:setup` refuses a PDF whose SHA-256 differs from the one the demo is prepared for. Without a `backend/.venv` it
looks for `odos` on the PATH, or use `--odos <path to the odos executable>`.

Other commands (in `frontend/`): `npm test`, `npm run typecheck`, `npm run build:demo` (type check and static site in
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
  all text, structure and the Legal JSON/XML excerpts were identical). Such a file is reported as `equivalent` when it
  is exactly equal after rounding all numbers to 0.01 pt. Other Docling/torch versions segment documents differently
  (`Documentation/development.md`); that shows up as `DIFFERENT`, and the demo may then not show the reference data.
  Regeneration on a second machine has not been verified.
- `manifest.json` also holds the SHA-256 of the whole pipeline outputs (`sources`); these follow the float noise and are
  left out of the `equivalent` comparison.

The retrieval date recorded in the XML (`2026-10-27`) is pinned in the reference; `--retrieval-date` overrides it, which
changes the full generated XML (and the `sources` hashes in `manifest.json`), not the displayed excerpts.

## Repository layout

| Path | Contents |
|---|---|
| `backend/` | the offline pipeline (`odos`): Docling extraction, parsing engine, Legal JSON, Akoma Ntoso, tests (`backend/README.md`) |
| `frontend/` | the static demo (React, TypeScript, Vite) and the fixture scripts (`frontend/README.md`) |
| `Documentation/` | architecture, parsing, document model, Legal JSON and Akoma Ntoso mapping, development guide |

The always-running backend tests use synthetic documents and need no partner PDF
(`Documentation/development.md`).
