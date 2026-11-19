# Partner-provided test inputs (not in Git)

The Musterbauordnung (MBO) and Regulation (EU) 2023/1230 were supplied by the industry partner as files and are
not redistributed. Keep them under `backend/data/input/private/` (gitignored) or point `ODOS_MBO_PDF` /
`ODOS_EU_PDF` at them; the tests that need them skip with a printed reason when they are absent.

| File | SHA-256 |
|---|---|
| `private/MusterBauVerordnung.pdf` | `53fd13388013263c3f676a3a8024f6932e38b8d326af6d2d844ecb9be61d340c` |
| `private/eu_2023_1230.pdf` | `fe36f0d148a84e790ec9a9825017baaea66fb931a5314ad0a614a1cde0ec182c` |

For the `technical_standard` parser, point `ODOS_DIN_EN_ISO_12100_PDF` at the full DIN EN ISO 12100:2011-03 PDF
(copyrighted, not in Git). `tests/test_technical_standard_parser.py::test_din_en_iso_12100_end_to_end` skips with a
printed reason when the environment variable is absent or the file is not readable.

No public law or copyrighted standard is stored in this repository. The always-running tests use synthetic Docling
output with invented text (`tests/docling_synthetic.py`) and generated PDFs (`tests/test_page_rendering.py`), freely
redistributable. The synthetic technical-standard fixtures in `test_technical_standard_parser.py` model DIN, DIN EN,
DIN ISO, DIN EN ISO, DIN VDE, DIN SPEC and ISO structural patterns without reproducing copyrighted standard text.

Further standards for the routing tests go in `private/standards/*.pdf` (Git-ignored; `test_real_standard_pdfs_route_automatically`
runs each through the whole upload path). Files used so far, all from their publishers: ETSI EN 303 645 V2.1.1 (etsi.org, free),
IEC 61508-1 ed. 2.0 and ISO/IEC 27000 ed. 5 previews (vde-verlag.de preview PDFs), DIN SPEC 91345 contents pages (din.de).
The TOC excerpts of DIN EN ISO 9001, DIN ISO 31000, DIN EN 619, DIN EN ISO/IEC 27001, DIN ISO/IEC 27001 and ISO/IEC 27001 are the contents
PDFs that DIN Media offers on each standard's public page (din.de `.../toc-<id>/download`).
FAU Nautos (read-only university session) was used only to read catalogue records (identifier forms, document types, language and amendment relations); documents were opened in its in-browser viewer for structure only (DIN EN ISO 9001:2015-11 and DIN 14675-1:2020-01, by screenshot); nothing was downloaded or saved, and the viewer's download and print functions were not used.
