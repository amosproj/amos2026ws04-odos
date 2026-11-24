# Frontend artifact and navigation update

Apply this update to the newer develop version with the rule review components and the previous extraction-preview update already applied.

Extract the ZIP and copy its frontend and Documentation folders into the repository root beside compose.yaml. Merge folders and replace matching files; do not delete existing folders. Keep .env unchanged.

Rebuild from the project root:

```powershell
docker compose up --build -d
```

Changes:
- The collapsible raw output heading is now Docling Raw JSON, without anzeigen / ausblenden.
- Its Download button is on the right of the heading and works without opening the disclosure.
- Artifacts shows Custom Legal JSON, V1, V2, and raw Docling. The Rule JSON selector and its artifact display are removed from this view. Saved Rule JSON is still retained and available on the extraction/review page.
- The top-right Processing navigation item is now a disabled Validation button. No page or route is created.
- PDF processing controls, V1/V2 downloads, extraction preview, the 1/3 call selector, and backend extraction behavior are unchanged.

Verification: changed TypeScript/TSX files parsed and transpiled, and lightweight component rendering checks covered labels, raw download destination/name, retained JSON views, and disabled Validation in workspace and legal headers. Full TypeScript/Vitest/build checks were not available in the editing environment.
