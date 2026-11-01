# ODOS backend (offline pipeline)

The Python package `odos` turns a legal PDF into structured data. It is used offline to create the data shown by
the static demo in `../frontend/`.

- **Docling extraction** of the PDF
- **The universal parsing engine** with the German-law and EU-legislation profiles
- **The canonical DocumentModel**
- **Exports:** Custom Legal JSON 1.1 and Akoma Ntoso 3.1 (XSD-validated)
- **The `odos` command line**

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.lock && pip install --no-deps -e ".[dev]"
odos --help
odos process <pdf> -o output/<name> --mode german_law|eu_legislation --retrieval-date YYYY-MM-DD
pytest
```

| Path | Contents |
|---|---|
| `src/odos/` | the package (map: `../Documentation/architecture.md`) |
| `tests/` | pytest suite, golden baselines (`tests/golden/`), the synthetic EU regulation and German law |
| `schemas/` | Custom Legal JSON schemas (1.1 active, 1.0 frozen) and the official OASIS AKN 3.1 XSD (SHA-256 pinned) |
| `data/input/` | `SOURCE.md` (the partner test inputs and their SHA-256); `private/` (gitignored) for documents that may not be redistributed. No public law is stored |
| `requirements.lock` | the exact dependency set the outputs were verified with |

Setup details, the CLI and the tests: `../Documentation/development.md`.
