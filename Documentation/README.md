# ODOS documentation

Technical documentation for ODOS. Start with the architecture overview.

| Document | Contents |
|---|---|
| [architecture.md](architecture.md) | Overview: where each concern lives, the PDF → JSON/XML pipeline, storage and API, review, classification, the future LLM integration point |
| [development.md](development.md) | Local setup, running backend and frontend, the `odos` CLI, tests, test inputs, golden equivalence |
| [parsing.md](parsing.md) | The universal parsing engine: lifecycle stages, legal profiles, how to add a profile, verification |
| [document-model.md](document-model.md) | The canonical `DocumentModel`: fields, IDs, provenance, derived annotations, compatibility rules |
| [legal-json.md](legal-json.md) | Custom Legal JSON 1.1 (`document.json`), its validation, and legacy schema 1.0 |
| [akn-mapping.md](akn-mapping.md) | Akoma Ntoso mapping for German law |
| [akn-eu-mapping.md](akn-eu-mapping.md) | Akoma Ntoso mapping for EU legislation |
| [akn4eu-mapping.md](akn4eu-mapping.md) | The AKN4EU export profile (EU), sample compatibility and its limits |

Sprint deliverables (planning documents, boards, logos) are in `../Deliverables/`.
