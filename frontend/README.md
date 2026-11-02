# ODOS frontend (static demonstration)

React + TypeScript + Vite. Upload a PDF, press **Process Document**, and see the original PDF next to the full
recognized legal structure (with highlights), plus one provision as Custom Legal JSON with preview and download. The
optional **Processing details** tab shows, for that provision, the Docling items it was extracted from, the elements the
legal parser recognized from them, and the resulting Custom Legal JSON nodes.

The JSON preview shows the actual Custom Legal JSON 2.0 output (`*.legal.json`, written by
`scripts/build-demo-fixtures.mjs`): the nodes of `document.json` from a top-level unit down to the shown provisions
(MBO: Zweiter Teil → § 6 → Absatz 1 with Nummer 1 and 2, Absatz 2; EU: Kapitel II → Artikel 10 → Absatz 1 and 2),
copied unchanged; only children off that path are left out. For the stakeholder presentation the file shows the key
`nativeType` as `germanType` (a temporary presentation name: values are unchanged, and the Legal JSON schema and
`document.json` keep `nativeType`). The download is the same file. The PDF highlighting does
not use it: it reads the provenance of the document model (`structure.json`), found by the node ids.

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
| `src/demo/DemoApp.tsx` | upload screen, result view, Custom Legal JSON preview and download |
| `src/demo/fixtures.ts` | manifest, SHA-256 matching, upload checks, loading the fixtures |
| `src/demo/PipelineView.tsx` | the "Processing details" tab (reads `pipeline.json`, the Legal JSON excerpt and the structure; computes nothing) |
| `src/components/` | `PdfViewer` (pdf.js with highlight overlays), `StructureTree`, `Icon` |
| `src/structure.ts` | display tree, labels, search, highlight geometry |
| `src/types.ts` | the DocumentModel fields the UI reads |
| `scripts/build-demo-fixtures.mjs` | builds `public/demo/` from the pipeline outputs, including `pipeline.json` (Docling items and model elements of the previewed provision) and the Legal JSON 2.0 excerpt; checks its ids, text and pages against the model |
| `scripts/demo-setup.mjs` | checks the PDFs, runs `odos process`, builds the fixtures, compares them with the reference |
| `scripts/demo-verify.mjs`, `scripts/demo-reference.json` | SHA-256 check of PDFs and fixtures against the committed reference (hashes only) |

Architecture: `../Documentation/architecture.md`.
