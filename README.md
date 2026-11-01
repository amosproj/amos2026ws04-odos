# ODOS – Ontology-Driven Operating System (AMOS WS 2026)

ODOS turns legal PDFs into a reviewable, machine-readable legal structure:

1. **Extraction:** Docling reads the PDF.
2. **Parsing:** a universal parsing engine with declarative legal profiles builds one canonical
   **DocumentModel**. The profiles cover German law and EU legislation.
3. **Outputs and review:** from that model ODOS derives **Custom Legal JSON 1.1** and **Akoma Ntoso
   3.1 XML** (validated against the official OASIS XSD). People review and correct the result in a web
   UI, with PDF highlights.

## Quick start

```bash
cd backend && python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.lock && pip install --no-deps -e ".[dev]"
odos serve                                    # API: http://127.0.0.1:8000

cd frontend && npm install && npm run dev     # UI:  http://localhost:5173
```

Details, the CLI and the tests: [Documentation/development.md](Documentation/development.md).

## Where is what

| Concern | Location |
|---|---|
| PDF extraction | `backend/src/odos/extraction.py` |
| Reading order and text normalization | `backend/src/odos/normalization/` |
| Universal parsing engine | `backend/src/odos/parsing/` (entry point `parse_document`) |
| German and EU legal profiles | `backend/src/odos/parsing/profiles/` |
| Canonical DocumentModel | `backend/src/odos/document_model.py` |
| Custom Legal JSON 1.1 | `backend/src/odos/legal_json/`, `backend/schemas/odos-legal-json/` |
| Akoma Ntoso XML | `backend/src/odos/akn/`, `backend/schemas/akn-3.1-os/` |
| Review corrections and revisions | `backend/src/odos/review/` |
| Classification and routing | `backend/src/odos/classification/` |
| Pipeline, API, CLI | `backend/src/odos/pipeline.py`, `backend/src/odos/api/`, `backend/src/odos/cli.py` |
| Web UI | `frontend/src/` |

The architecture overview is [Documentation/architecture.md](Documentation/architecture.md); all
technical documentation is indexed in [Documentation/](Documentation/README.md).

## Repository layout

```
backend/        Python package `odos` (src/), tests, schemas (Legal JSON, OASIS AKN 3.1 XSD), test input PDFs
frontend/       React + TypeScript + Vite web UI
Documentation/  technical documentation
Deliverables/   sprint deliverables
```
