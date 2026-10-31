# ODOS backend

The Python package `odos`:

- **Docling extraction** of legal PDFs
- **The universal parsing engine** with the German-law and EU-legislation profiles
- **The canonical DocumentModel**
- **Exports:** Custom Legal JSON 1.1 and Akoma Ntoso 3.1 (XSD-validated)
- **Review** with versioned revisions
- **Classification** and routing
- **The `odos` CLI and the FastAPI web API**

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.lock && pip install --no-deps -e ".[dev]"
odos --help
odos serve                 # http://127.0.0.1:8000 (OpenAPI: /docs)
pytest                     # see the coverage line at the end of the run
```

| Path | Contents |
|---|---|
| `src/odos/` | the package (map: `../Documentation/architecture.md`) |
| `tests/` | pytest suite, golden baselines (`tests/golden/`), the synthetic EU regulation, fixtures |
| `schemas/` | Custom Legal JSON schemas (1.1 active, 1.0 frozen) and the official OASIS AKN 3.1 XSD (SHA-256 pinned) |
| `data/input/` | test input PDFs with their SHA-256 (`SOURCE.md`); `private/` (gitignored) for documents that may not be redistributed |
| `requirements.lock` | the exact dependency set the outputs were verified with |

Setup details, configuration, the CLI and the tests: `../Documentation/development.md`.
