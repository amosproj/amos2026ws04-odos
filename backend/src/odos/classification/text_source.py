"""Text lines for the classifier from the PDF text layer (lightweight) or from an existing Docling output."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

MAX_PAGES = 250  # pages scanned from the PDF text layer


class Line(BaseModel):
    page: int
    text: str
    ref: str | None = None


class Lines(BaseModel):
    lines: list[Line]
    pages_total: int
    pages_scanned: int
    source: str


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\xad", "").replace(" ", " ")).strip()


def lines_from_pdf(pdf_path: Path, max_pages: int = MAX_PAGES) -> Lines:
    """Text layer via pypdfium2: no layout analysis, no Docling. Roughly a second for 100 pages."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        total = len(pdf)
        out: list[Line] = []
        for p in range(min(total, max_pages)):
            page = pdf[p]
            text = page.get_textpage().get_text_bounded()
            for n, raw in enumerate(re.split(r"\r?\n", text), start=1):
                t = _clean(raw)
                if t:
                    out.append(Line(page=p + 1, text=t, ref=f"pdf_text_layer:p{p + 1}:l{n}"))
        return Lines(lines=out, pages_total=total, pages_scanned=min(total, max_pages), source="pdf_text_layer")
    finally:
        pdf.close()


def lines_from_docling(docling_json: Path) -> Lines:
    """Items of an existing Docling extraction (no new conversion)."""
    from odos.normalization.docling_reader import read_docling_json

    info, items = read_docling_json(Path(docling_json))
    out: list[Line] = []
    for it in items:
        t = _clean(it.orig)
        if t and it.pages:
            out.append(Line(page=it.pages[0], text=t, ref=it.ref))
    return Lines(lines=out, pages_total=info.num_pages, pages_scanned=info.num_pages, source="docling")
