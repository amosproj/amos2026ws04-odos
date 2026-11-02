# ODOS frontend (static demonstration)

React + TypeScript + Vite. Upload a PDF, press **Process Document**, and see the original PDF next to the full
recognized legal structure (with highlights), plus one provision as Legal Document JSON and Akoma Ntoso XML with
downloads.

Nothing is processed in the browser. The chosen PDF is matched by its SHA-256 against the prepared documents
(Musterbauordnung, Regulation (EU) 2023/1230) and their previously generated pipeline results are shown. Any other
PDF is refused with an explanation.

```bash
npm ci
npm run demo:setup -- --mbo-pdf <MBO.pdf> --eu-pdf <eu_2023_1230.pdf>   # checks the PDFs, runs the pipeline, writes public/demo/
npm run demo:verify -- --mbo-pdf <MBO.pdf> --eu-pdf <eu_2023_1230.pdf>  # SHA-256 comparison with scripts/demo-reference.json
npm run dev          # http://localhost:5173
npm test             # unit tests (vitest)
npm run typecheck
npm run build:demo   # type check + static site in dist/ (relative paths, any sub-path)
npm run preview      # http://localhost:4173
```

`demo:setup` needs the backend installed (`../README.md`, which also explains what `demo:verify` guarantees and what it
does not). To build the fixtures from existing `odos process` output directories instead, run
`npm run demo:fixtures -- --mbo <dir> --eu <dir>`. The PDFs are never part of the build: the presenter opens their own copy.

**Data protection:** `public/demo/` and `dist/` contain the full text of the partner-supplied documents. Both are
git-ignored and must not be published or deployed until the licensing is clarified.

| Module | Role |
|---|---|
| `src/demo/DemoApp.tsx` | upload screen, result view, JSON/XML previews and downloads |
| `src/demo/fixtures.ts` | manifest, SHA-256 matching, upload checks, preview helpers |
| `src/components/` | `PdfViewer` (pdf.js with highlight overlays), `StructureTree`, `Icon` |
| `src/structure.ts` | display tree, labels, search, highlight geometry |
| `src/types.ts` | the DocumentModel fields the UI reads |
| `scripts/build-demo-fixtures.mjs` | builds `public/demo/` from the pipeline outputs |
| `scripts/demo-setup.mjs` | checks the PDFs, runs `odos process`, builds the fixtures, compares them with the reference |
| `scripts/demo-verify.mjs`, `scripts/demo-reference.json` | SHA-256 check of PDFs and fixtures against the committed reference (hashes only) |

Architecture: `../Documentation/architecture.md`.
