# ODOS frontend (React + TypeScript + Vite)

The web UI has three parts:

- **Document library:** upload, classification with a suggested mode, processing, filters and deletion.
- **Document workspace:** the original PDF next to the extracted structure, with exact highlights, the
  normalized table of contents, warnings and uncertain elements, and artifact previews and downloads.
- **Review and exports:** text corrections with revisions and validation, approval, and the AKN4EU
  export.

```bash
npm install
npm run dev          # http://localhost:5173 (proxies /api to http://127.0.0.1:8000)
npm test             # unit tests (vitest)
npm run build        # type check + production build
```

The browser only calls relative `/api/...` URLs:

- **Development:** Vite proxies them to `http://127.0.0.1:8000`. Point the proxy elsewhere with
  `ODOS_API_TARGET=http://host:port npm run dev`.
- **API on a different origin:** set `VITE_API_BASE`.

The backend must be running (`odos serve`).

| Module | Role |
|---|---|
| `src/App.tsx`, `src/documentLibrary.ts` | routes and the document library |
| `src/components/` | the UI components (Workspace, PdfViewer, StructureTree, ReviewPanel, …) |
| `src/structure.ts` | display tree, labels, filters, highlight geometry |
| `src/classification.ts`, `src/review.ts`, `src/exports.ts`, `src/format.ts` | feature logic (pure, unit-tested) |
| `src/api.ts`, `src/types.ts` | API client and the API's types |

Architecture and data model: `../Documentation/architecture.md`.
