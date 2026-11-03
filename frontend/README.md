# ODOS frontend

React + TypeScript + Vite. Upload a PDF, press **Process Document**, and see the original PDF next to the full
recognized legal structure (tab **Legal structure**, with source highlighting) and the Custom Legal JSON (tab
**Artifacts**: preview of the selected element or of the full document, and the download).

**Live mode**: the PDF is sent to the ODOS backend
(`uvicorn odos.api:app --port 8000`, reached under `/api` through the Vite proxy of `npm run dev` and `npm run
preview`; set `ODOS_API_URL` for another address), which recognizes German or EU legislation from the document and runs the whole pipeline on it; the page polls the job and
then loads its document model and `document.json`. The JSON preview shows the selected element's node or, with the
**Full document** switch, the whole document, with `nativeType` shown as `germanType`; the **Download** is the complete
`document.json`, unchanged and schema-validated. A PDF whose type is not recognized, or that fails, is shown as an
error message.

The JSON preview shows the actual Custom Legal JSON 2.0 output (`*.legal.json`, written by
`scripts/build-demo-fixtures.mjs`): the nodes of `document.json` from a top-level unit down to the shown provisions
(MBO: Zweiter Teil → § 6 → Absatz 1 with Nummer 1 and 2, Absatz 2; EU: Kapitel II → Artikel 10 → Absatz 1 and 2),
copied unchanged; only children off that path are left out. For the stakeholder presentation the file shows the key
`nativeType` as `germanType` (a temporary presentation name: values are unchanged, and the Legal JSON schema and
`document.json` keep `nativeType`). The download is the same file. The PDF highlighting does
not use it: it reads the provenance of the document model (`structure.json`), found by the node ids.


```bash
npm ci
npm run demo:setup -- --mbo-pdf <MBO.pdf> --eu-pdf <eu_2023_1230.pdf>   # checks the PDFs, runs the pipeline, writes public/demo/
npm run demo:verify -- --mbo-pdf <MBO.pdf> --eu-pdf <eu_2023_1230.pdf>  # SHA-256 comparison with scripts/demo-reference.json
npm run dev          # http://localhost:5173
npm test             # unit tests (vitest)
npm run typecheck
npm run build   # type check + static site in dist/ (relative paths, any sub-path)
npm run preview      # http://localhost:4173
```

`demo:setup` needs the backend installed (`../README.md`, which also explains what `demo:verify` guarantees and what it
does not). To build the fixtures from existing `odos process` output directories instead, run
`npm run demo:fixtures -- --mbo <dir> --eu <dir>`. The PDFs are never part of the build: the presenter opens their own copy.

**Data protection:** `public/demo/` and `dist/` contain the full text of the partner-supplied documents. Both are
git-ignored and must not be published or deployed until the licensing is clarified.

| Module | Role |
|---|---|
| `src/demo/DemoApp.tsx` | upload screen, result view, Custom Legal JSON preview and download |
| `src/demo/live.ts` | live mode: upload, job polling, loading the results, the selected element's JSON node |
| `src/demo/excerpts.mjs` | presentation names (`germanType`) and JSON formatting, shared with `scripts/build-demo-fixtures.mjs` |
| `src/demo/fixtures.ts` | prepared examples: manifest, SHA-256 matching, upload checks, loading the fixtures |
| `src/components/` | `PdfViewer` (pdf.js with highlight overlays), `StructureTree`, `Icon` |
| `src/structure.ts` | display tree, labels, search, highlight geometry |
| `src/types.ts` | the DocumentModel fields the UI reads |
| `scripts/build-demo-fixtures.mjs` | builds `public/demo/` from the pipeline outputs (the structure and a Legal JSON 2.0 excerpt); checks its ids, text and pages against the model |
| `scripts/demo-setup.mjs` | checks the PDFs, runs `odos process`, builds the fixtures, compares them with the reference |
| `scripts/demo-verify.mjs`, `scripts/demo-reference.json` | SHA-256 check of PDFs and fixtures against the committed reference (hashes only) |

Architecture: `../Documentation/architecture.md`.
