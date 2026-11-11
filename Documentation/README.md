# ODOS documentation

Documentation for the simplified live PDF-processing prototype. Start with the architecture overview.

| Document | Contents |
|---|---|
| [architecture.md](architecture.md) | Components, live data flow, API and frontend |
| [development.md](development.md) | Windows setup, startup, CLI and manual verification |
| [document-model.md](document-model.md) | Internal structure, text, source references and diagnostics |
| [legal-json.md](legal-json.md) | Custom Legal JSON 2.0, schema and traceability |
| [parsing.md](parsing.md) | Parsing stages and German/EU profiles |
| [database-poc.md](database-poc.md) | Optional PostgreSQL 17 + JSONB persistence (proof of concept, macOS setup, tests) |
| [docker-postgresql-guide.md](docker-postgresql-guide.md) | Docker Compose workflow, `psql` inspection of persisted Legal JSON, JSONPath queries, volumes and troubleshooting |

## Scope of this documentation

These files describe the simplified target version: live processing only, no prepared-example mode, and no bundled automated test suite. Runtime schema and structural validation remain part of PDF processing.

The collapsible Docling Raw JSON preview requires the API allowlist and frontend changes described in [development.md](development.md). Documentation alone does not implement these changes.

Place these six files in the repository's `Documentation/` folder. This README is the documentation index, not a replacement for the repository's root README. Sprint submissions belong in `Deliverables/`.
