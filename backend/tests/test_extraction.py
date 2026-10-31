import hashlib
from pathlib import Path

import pytest

from odos.cli import build_parser, main
from odos.extraction import extract_pdf, load_raw_json

BACKEND = Path(__file__).resolve().parents[1]
BDSG = BACKEND / "data" / "input" / "BDSG.pdf"
BDSG_SHA256 = "859631d6203e0c3d12b280a1982c83d0521ccfe6c4eaa04ae5bc264112711004"


def test_input_pdf_hash_matches_recorded_value():
    assert hashlib.sha256(BDSG.read_bytes()).hexdigest() == BDSG_SHA256


def test_missing_pdf_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        extract_pdf(tmp_path / "nope.pdf", tmp_path)


def test_cli_missing_pdf_returns_error(tmp_path):
    assert main(["extract", str(tmp_path / "nope.pdf"), "-o", str(tmp_path)]) == 1


def test_cli_parser_defaults():
    args = build_parser().parse_args(["extract", "x.pdf"])
    assert args.output_dir == Path("output") and args.ocr is False


@pytest.fixture(scope="module")
def bdsg_result(tmp_path_factory):
    return extract_pdf(BDSG, tmp_path_factory.mktemp("bdsg"))


@pytest.mark.slow
def test_bdsg_extraction_outputs(bdsg_result):
    assert bdsg_result.json_path.stat().st_size > 0
    md = bdsg_result.markdown_path.read_text(encoding="utf-8")
    assert "Bundesdatenschutzgesetz" in md
    assert bdsg_result.pages == 45


@pytest.mark.slow
def test_bdsg_json_has_structure_and_provenance(bdsg_result):
    raw = load_raw_json(bdsg_result.json_path)
    assert raw["texts"] and raw["pages"]
    assert raw["texts"][0]["prov"][0]["page_no"] >= 1
