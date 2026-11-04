"""PDF extraction with Docling.

Converts a PDF into a DoclingDocument and writes two artifacts:
``docling_raw.json`` (full structure and provenance) and ``extracted.md``
(for human inspection).
"""

from __future__ import annotations

import json
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import DoclingDocument
from pydantic import BaseModel

from odos.artifact_names import DOCLING_MARKDOWN, DOCLING_RAW


class ExtractionResult(BaseModel):
    source: Path
    json_path: Path
    markdown_path: Path
    status: str
    pages: int
    text_items: int
    tables: int
    warnings: list[str]


def build_converter(do_ocr: bool = False) -> DocumentConverter:
    """OCR is off by default: gesetze-im-internet.de PDFs have a text layer."""
    options = PdfPipelineOptions(do_ocr=do_ocr)
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )


def extract_pdf(
    pdf_path: Path, output_dir: Path, do_ocr: bool = False
) -> ExtractionResult:
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    result = build_converter(do_ocr).convert(pdf_path)
    doc: DoclingDocument = result.document

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / DOCLING_RAW
    markdown_path = output_dir / DOCLING_MARKDOWN

    doc.save_as_json(json_path)
    doc.save_as_markdown(markdown_path)

    return ExtractionResult(
        source=pdf_path,
        json_path=json_path,
        markdown_path=markdown_path,
        status=str(result.status.value),
        pages=len(doc.pages),
        text_items=len(doc.texts),
        tables=len(doc.tables),
        warnings=[str(e.error_message) for e in result.errors],
    )


def load_raw_json(json_path: Path) -> dict:
    return json.loads(Path(json_path).read_text(encoding="utf-8"))
