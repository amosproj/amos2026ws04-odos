# Restored LLM-call dropdown

The frontend again offers 1 call - no corrections (default) and 3 calls - up to 2 corrections. Selecting an option invalidates the preview and refreshes its estimates, and Start sends that exact setting to the backend.

The Maximum workflow calls, per-call output ceiling and text-group count remain hidden below the dropdown. The output ceiling for the run remains visible. The input field still estimates initial requests; it does not pretend to predict correction prompts that do not exist yet. The shortened note remains unchanged. This supersedes the fixed-one-call frontend note in minimal-extraction-preview.md.

Merge this cumulative update into the existing project, replace matching files and run docker compose up --build -d. Keep .env and the rest of the project. Syntax/transpilation and lightweight component interactions passed, including switching to three calls, waiting for the new preview, and starting with the selected limit. Full TypeScript/Vitest/Docker build was not run here.
