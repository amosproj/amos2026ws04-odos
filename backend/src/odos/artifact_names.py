"""Names of the files ODOS writes for a document: one source for the pipeline, the API, review revisions and the CLI.

The names are part of the storage layout (existing documents are read by them) and of the API
(`/api/documents/{id}/artifacts/{artifact_type}`): never rename one.
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
AKN_XML = "document_akn.xml"
AKN_REPORT = "akn_validation_report.json"
AKN_TRACEABILITY = "akn_traceability.json"
AKN_TEXT_REPORT = "akn_text_preservation.json"

# artifact type -> (file name in the document directory, media type)
ARTIFACTS: dict[str, tuple[str, str]] = {
    "docling_raw": (DOCLING_RAW, "application/json"),
    "extracted_md": (DOCLING_MARKDOWN, "text/markdown; charset=utf-8"),
    "document_model": (DOCUMENT_MODEL, "application/json"),
    "legal_json": (LEGAL_JSON, "application/json"),
    "legal_json_validation_report": (LEGAL_JSON_REPORT, "application/json"),
    "validation_report": (VALIDATION_REPORT, "application/json"),
    "akn_xml": (AKN_XML, "application/xml"),
    "akn_validation_report": (AKN_REPORT, "application/json"),
    "akn_traceability": (AKN_TRACEABILITY, "application/json"),
    "akn_text_report": (AKN_TEXT_REPORT, "application/json"),
    "reading_order_evidence": (READING_ORDER_EVIDENCE, "application/json"),  # PDF text layer of pages with overlapping boxes
}
