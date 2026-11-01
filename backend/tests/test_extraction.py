from pathlib import Path

import pytest

from odos.cli import build_parser, main
from odos.extraction import extract_pdf, load_raw_json


def test_missing_pdf_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        extract_pdf(tmp_path / "nope.pdf", tmp_path)


def test_cli_missing_pdf_returns_error(tmp_path):
    assert main(["extract", str(tmp_path / "nope.pdf"), "-o", str(tmp_path)]) == 1


def test_cli_parser_defaults():
    args = build_parser().parse_args(["extract", "x.pdf"])
    assert args.output_dir == Path("output") and args.ocr is False


@pytest.fixture(scope="module")
def synthetic_result(synthetic_german_raw_json, tmp_path_factory):
    """The real Docling conversion of the generated synthetic German law (original text, freely redistributable)."""
    pdf = synthetic_german_raw_json.parent / "original.pdf"
    return extract_pdf(pdf, tmp_path_factory.mktemp("synthetic_extraction"))


@pytest.mark.slow
def test_extraction_outputs(synthetic_result):
    assert synthetic_result.json_path.stat().st_size > 0
    md = synthetic_result.markdown_path.read_text(encoding="utf-8")
    assert "Beispielgesetz" in md
    assert synthetic_result.pages == 3


@pytest.mark.slow
def test_extracted_json_has_structure_and_provenance(synthetic_result):
    raw = load_raw_json(synthetic_result.json_path)
    assert raw["texts"] and raw["pages"]
    assert raw["texts"][0]["prov"][0]["page_no"] >= 1
