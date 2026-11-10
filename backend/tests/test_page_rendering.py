"""Docling's page images must show real glyphs for PDFs whose fonts are not embedded.

Docling's layout model classifies regions from the rendered page image. The docling-parse renderer draws text in
non-embedded fonts (the MBO uses ArialMT and TimesNewRomanPSMT without embedding them) with a system font found under
/usr/share/fonts; without one, every glyph becomes an empty box. The layout model then sees no list items, headings
or footnotes, and the German parser receives fragmented text (§ 2 of the MBO split into loose TEXT nodes). The
backend image therefore installs fonts-liberation (metric-compatible Arial / Times New Roman / Courier New).

The reference rendering is PDFium's (pypdfium2), which carries its own fallback fonts and does not depend on the
system. Empty boxes carry about a third of the ink of real glyphs.
"""

import io

import numpy as np
import pypdfium2 as pdfium
import pytest
from docling.datamodel.base_models import InputFormat
from docling.datamodel.document import InputDocument
from docling.document_converter import PdfFormatOption

TEXT = "Bauliche Anlagen 1. 2. (3) Gebäudeklasse"


def pdf_with_font(base_font: str) -> bytes:
    """A one-page PDF that writes TEXT in a non-embedded TrueType font (no FontFile2, as in the MBO)."""
    content = f"BT /F1 24 Tf 30 100 Td ({TEXT}) Tj ET".encode("cp1252")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 200] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        f"<< /Type /Font /Subtype /TrueType /BaseFont /{base_font} /Encoding /WinAnsiEncoding >>".encode(),
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % number + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    out.write(b"".join(b"%010d 00000 n \n" % offset for offset in offsets))
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref))
    return out.getvalue()


def ink(image) -> float:
    return float((1 - np.asarray(image.convert("L"), dtype=float) / 255).sum())


def docling_page_image(pdf):
    """The page image of Docling's default PDF backend at scale 1, as the layout model receives it."""
    option = PdfFormatOption()
    doc = InputDocument(path_or_stream=pdf, format=InputFormat.PDF, backend=option.backend,
                        backend_options=option.backend_options)
    backend = doc._backend
    try:
        pages = list(backend.iter_pages())  # consumed completely: the threaded parser cannot unload mid-iteration
        return pages[0].get_page_image(scale=1.0)
    finally:
        backend.unload()


@pytest.mark.parametrize("base_font", ["ArialMT", "TimesNewRomanPSMT"])
def test_non_embedded_fonts_render_as_glyphs(tmp_path, base_font):
    pdf = tmp_path / f"{base_font}.pdf"
    pdf.write_bytes(pdf_with_font(base_font))

    reference = ink(pdfium.PdfDocument(pdf)[0].render(scale=1).to_pil())
    rendered = ink(docling_page_image(pdf))

    assert 0.7 < rendered / reference < 1.3, (
        f"Docling renders {base_font} with {rendered / reference:.0%} of the reference ink: the glyphs are empty boxes. "
        "No substitute font is installed (the backend image needs fonts-liberation)."
    )
