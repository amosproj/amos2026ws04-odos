# ODOS with Docker (local development)

Install and start Docker Desktop. On Windows use Linux containers with the WSL 2 backend. Extract the ZIP, open a terminal in the folder containing compose.yaml, then run:

    docker compose up --build

Open http://localhost:5173 after the frontend starts. API docs: http://localhost:8000/docs.
No local Python, venv or Node installation is needed. Internet access is required for image/dependency downloads and the first Docling model download. Allow several GB of disk space and sufficient Docker memory; 8 GB is a reasonable starting allocation, not a guaranteed minimum for every document.

Later starts: docker compose up
Stop: Ctrl+C, then docker compose down
Background: docker compose up -d
Logs: docker compose logs -f
After code changes: docker compose up --build

Sources are copied into the images, so local code edits require rebuilding. The Vite frontend forwards /api to backend:8000. Both ports are bound to localhost. This configuration is for local development, not public hosting.

Downloaded models remain in the model-cache volume. Jobs do not survive restarts: the registry is in memory and application shutdown removes job directories. Download results before stopping. A storage volume alone would not fix this. docker compose down --volumes intentionally removes the model cache too.

The backend uses one worker and includes schemas alongside src for the existing schema lookup. Existing dependency pins are preserved. The Python lockfile originated on macOS ARM64 and still needs installation verification on Linux. If installation fails, retain the exact error rather than blindly upgrading Docling, since versions may change extraction results.

Fonts: the backend image installs fonts-liberation. Docling's layout model works on rendered page images, and PDFs with non-embedded fonts (the MBO uses Arial and Times New Roman without embedding them) are rendered with system fonts. Without any, the glyphs become empty boxes and the legal structure falls apart (e.g. MBO § 2 split into loose TEXT nodes); EU documents embed their fonts and are not affected. Liberation is metric-compatible but not identical to Arial, so Docker results can differ in details from a macOS run (most visibly: MBO footnotes are classified as body text).

Regression tests in the backend image (tests are not copied into it):

    docker compose run --rm --no-deps -v ./backend/tests:/app/backend/tests:ro backend python -m pytest -v tests/test_page_rendering.py tests/test_reference_documents.py

The MBO/EU reference tests skip without the partner PDFs; when backend/data/input/private/ holds them (see backend/data/input/SOURCE.md), add -v ./backend/data/input/private:/app/backend/data/input/private:ro (a few minutes; run nothing else Docling-heavy at the same time, 8 GB is not enough for two conversions).

Troubleshooting:
- Port occupied: stop local Vite/Uvicorn, or change the host port (left-hand port) in compose.yaml.
- MBO structure fragmented, EU fine: the backend image was built without fonts-liberation; rebuild with docker compose up --build.
- Backend unhealthy: docker compose logs backend
- Slow first extraction: models may still be downloading; check backend logs.
- Exit code 137/process killed: increase Docker memory and retry.

Verification: YAML and ZIP checked statically. Docker is unavailable in the editing environment, so container builds and real PDF conversion have not been run. Frontend image build runs TypeScript/build checks; backend build runs pip check. After starting, process representative German and EU PDFs and check JSON downloads and highlights.
