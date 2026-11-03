"""Docling extraction: error handling, a real conversion, and the locked dependency set.

Docling's output is not determined by the docling version alone: a newer docling-parse, torch, transformers or
docling-core segments, labels and orders the same PDF differently. A drift is reported here, with its cause, instead
of as unexplained parser assertion failures elsewhere."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pytest

from odos.cli import main
from odos.extraction import extract_pdf, load_raw_json

LOCK = Path(__file__).resolve().parents[1] / "requirements.lock"
EXTRACTION_PACKAGES = ("docling", "docling-core", "docling-parse", "docling-ibm-models", "torch", "torchvision", "transformers")


def test_missing_pdf_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        extract_pdf(tmp_path / "nope.pdf", tmp_path)
    assert main(["extract", str(tmp_path / "nope.pdf"), "-o", str(tmp_path)]) == 1  # the command line reports it


@pytest.mark.slow
def test_real_docling_conversion_of_the_generated_pdf(synthetic_german_raw_json, tmp_path):
    """The real Docling conversion of the generated synthetic German law (original text, freely redistributable)."""
    result = extract_pdf(synthetic_german_raw_json.parent / "original.pdf", tmp_path)
    assert result.pages == 3 and "Beispielgesetz" in result.markdown_path.read_text(encoding="utf-8")
    raw = load_raw_json(result.json_path)
    assert raw["texts"] and raw["pages"] and raw["texts"][0]["prov"][0]["page_no"] >= 1  # text items with provenance


def test_installed_extraction_dependencies_match_the_lock():
    pins = {}
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            name, _, ver = line.partition("==")
            pins[name.lower().replace("_", "-").replace(".", "-")] = ver.strip()
    assert all(p in pins for p in EXTRACTION_PACKAGES)

    def installed(name):
        try:
            return version(name)
        except PackageNotFoundError:
            return None

    drift = {p: {"locked": pins[p], "installed": installed(p)} for p in EXTRACTION_PACKAGES if installed(p) != pins[p]}
    assert not drift, (
        f"Extraction dependencies differ from requirements.lock: {drift}. Docling output (and the pinned test values) "
        "would change. Reinstall with: pip install -r requirements.lock && pip install --no-deps -e '.[dev]'"
    )
