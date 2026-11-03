# ODOS backend

The Python package `odos` turns a legal PDF into structured data. The web app in `../frontend/` uses it through a
thin web API; the command line produces the same files offline.

- **Docling extraction** of the PDF
- **The universal parsing engine** with the German-law and EU-legislation profiles
- **The canonical DocumentModel**
- **Export:** Custom Legal JSON 2.0 (schema-validated; provenance stays in the document model)
- **The `odos` command line**
- **The web API** (`src/odos/api.py`): upload, job status, result files, download; one job at a time

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.lock && pip install --no-deps -e ".[dev]"
odos --help
odos process <pdf> -o output/<name> --mode german_law|eu_legislation
uvicorn odos.api:app --port 8000      # the web API for ../frontend
pytest
```

| Path | Contents |
|---|---|
| `src/odos/` | the package (map: `../Documentation/architecture.md`) |
| `tests/` | pytest suite, golden baselines (`tests/golden/`), the synthetic EU regulation and German law |
| `schemas/` | the Custom Legal JSON 2.0 schema |
| `data/input/` | `SOURCE.md` (the partner test inputs and their SHA-256); `private/` (gitignored) for documents that may not be redistributed. No public law is stored |
| `requirements.lock` | the exact dependency set the outputs were verified with |

Setup details, the CLI and the tests: `../Documentation/development.md`.
