# Digital twin validation UI preview

After an extraction has finished (or when stored results are reopened), the rule extraction/review page offers **Continue to Validation**. This opens a new page with matching ODOS styling, the legal document's name, a digital twin file picker, and a Validate button. Back to rule extraction returns to the existing results without another model call, and the PDF object URL is retained across this navigation.

The file picker accepts JSON and JSON-LD filenames, displays the selected name/size, and offers Remove file. Validate is disabled until a file is selected. Clicking it displays a clearly labeled placeholder explaining that no rules or file contents have been checked. File contents are not read, parsed, uploaded, persisted, or sent to an LLM. No simulated compliance verdict is shown. Selecting a new file or removing it clears the placeholder. The chosen file is local page state and is cleared when leaving this page. The global Validation navigation remains a future placeholder; this contextual page is reached from extraction results.

## Apply

This cumulative update ZIP includes the earlier article-checklist, whole-document, stop and preservation changes. It contains updated/new files, not the entire standalone project. Merge its backend, frontend and Documentation folders into your existing newer develop project root beside compose.yaml. Replace matching files; keep .env and the rest of the project.

```powershell
docker compose up --build -d
```

Open a saved document, continue to Rule Extraction, and open its existing extraction results. Click Continue to Validation, select a JSON/JSON-LD file, and click Validate. This mock step does not incur LLM costs.

## Verification

Changed TS/TSX files parsed/transpiled. Lightweight component checks covered disabled Validate with no file, supported local selection, the demo-only result text, file removal, unsupported extensions, the back callback, and zero network requests. Navigation wiring and retention of the PDF URL were checked. Full TypeScript/Vitest/Docker/browser integration was not available here. Backend behavior is unchanged by this mock-page addition.
