# ODOS documentation

Documentation for the simplified live PDF-processing prototype. Start with the architecture overview.

| Document | Contents |
|---|---|
| [design-documentation.md](design-documentation.md) | **Consolidated technical design**, architecture, stack, data flow, models, API, storage, conventions, extension and maintenance |
| [architecture.md](architecture.md) | Components, live data flow, API and frontend |
| [development.md](development.md) | Windows setup, startup, CLI and manual verification |
| [document-model.md](document-model.md) | Internal structure, text, source references and diagnostics |
| [legal-json.md](legal-json.md) | Custom Legal JSON 2.0, schema and traceability |
| [rule-json.md](rule-json.md) | The Rule JSON schema, examples, validation and migration from 1.0 |
| [parsing.md](parsing.md) | Parsing stages and German/EU profiles |
| [database-poc.md](database-poc.md) | Optional PostgreSQL 17 + JSONB persistence (proof of concept, macOS setup, tests) |
| [docker-postgresql-guide.md](docker-postgresql-guide.md) | Docker Compose workflow, `psql` inspection of persisted Legal JSON, JSONPath queries, volumes and troubleshooting |

## Scope of this documentation

These files describe the simplified target version: live processing only and no prepared-example mode. Runtime schema and structural validation remain part of PDF processing. Automated tests live in `backend/tests/` and next to the frontend sources; [development.md](development.md) and [database-poc.md](database-poc.md) describe how to run them.

This README is the documentation index, not a replacement for the repository's root README. Sprint submissions belong in `Deliverables/`.
