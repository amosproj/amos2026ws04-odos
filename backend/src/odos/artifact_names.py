"""Names of the files ODOS writes for a document: one source for the pipeline and the CLI.

The demo fixture script (frontend/scripts/build-demo-fixtures.mjs) and the web API (`odos.api`) read them by these names:
never rename one.
"""

from __future__ import annotations

DOCLING_RAW = "docling_raw.json"  # Docling's lossless JSON
DOCLING_MARKDOWN = "extracted.md"  # Docling's Markdown, for people
EXTRACTION_META = "extraction.json"  # kept next to the Docling output; not a downloadable artifact
READING_ORDER_EVIDENCE = "pdf_text_lines.json"  # PDF text layer (normalization.reading_order)
DOCUMENT_MODEL = "document_model.json"  # canonical model incl. internal diagnostics
VALIDATION_REPORT = "validation_report.json"
VALIDATION_REPORT_MD = "validation_report.md"
LEGAL_JSON = "document.json"  # public JSON serialization of the canonical model
LEGAL_JSON_REPORT = "legal_json_validation_report.json"
