from pathlib import Path

import pytest

from odos.parsing import parse_document

BACKEND = Path(__file__).resolve().parents[1]
BDSG = BACKEND / "data" / "input" / "BDSG.pdf"
RAW = BACKEND / "output" / "bdsg" / "docling_raw.json"


@pytest.fixture(scope="session")
def raw_json() -> Path:
    if not RAW.exists():  # slow path: only when nobody ran `odos extract` yet
        from odos.extraction import extract_pdf

        extract_pdf(BDSG, RAW.parent)
    _evidence(BDSG, RAW)
    return RAW


def _evidence(pdf: Path, raw: Path) -> None:
    """The PDF text-layer evidence next to the Docling JSON, rebuilt from the PDF so it follows the current rules
    (as the pipeline does): it restores characters Docling normalised away and proves footnote anchors."""
    from odos.normalization.reading_order import write_evidence

    if pdf.exists():
        write_evidence(pdf, raw)


@pytest.fixture(scope="session")
def model(raw_json):
    return parse_document(raw_json, "german_law")


# The Musterbauordnung PDF was supplied by the industry partner and is not redistributed: tests take it from
# ODOS_MBO_PDF or data/input/private/ (gitignored). Its tests live in tests/private/ (gitignored too).
MBO_PDF = BACKEND / "data" / "input" / "private" / "MusterBauVerordnung.pdf"
MBO_RAW = BACKEND / "output" / "mbo" / "docling_raw.json"
MBO_SHA256 = "53fd13388013263c3f676a3a8024f6932e38b8d326af6d2d844ecb9be61d340c"
MBO_MISSING = ("Musterbauordnung PDF not available: set ODOS_MBO_PDF or copy it to "
               "backend/data/input/private/MusterBauVerordnung.pdf (gitignored)")  # fmt: skip


def _mbo_pdf_or_none() -> Path | None:
    import hashlib
    import os

    pdf = Path(os.environ["ODOS_MBO_PDF"]) if os.environ.get("ODOS_MBO_PDF") else MBO_PDF
    if not pdf.is_file():
        return None
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if sha != MBO_SHA256:
        pytest.skip(f"{pdf} is not the Musterbauordnung PDF the MBO tests are written for (sha256 {sha[:12]}…, expected {MBO_SHA256[:12]}…)")  # fmt: skip
    return pdf


@pytest.fixture(scope="session")
def mbo_pdf() -> Path:
    pdf = _mbo_pdf_or_none()
    if pdf is None:
        pytest.skip(MBO_MISSING)
    return pdf


@pytest.fixture(scope="session")
def mbo_raw_json() -> Path:
    pdf = _mbo_pdf_or_none()
    if not MBO_RAW.exists():
        if pdf is None:
            pytest.skip(MBO_MISSING)
        from odos.extraction import extract_pdf  # slow path (~1-2 min): run Docling once

        extract_pdf(pdf, MBO_RAW.parent)
    if pdf is not None:
        _evidence(pdf, MBO_RAW)
    elif not (MBO_RAW.parent / "pdf_text_lines.json").exists():
        pytest.skip(f"{MBO_MISSING}; its text-layer evidence cannot be built without it")
    return MBO_RAW


@pytest.fixture(scope="session")
def mbo_model(mbo_raw_json):
    return parse_document(mbo_raw_json, "german_law")


# The full Regulation (EU) 2023/1230 (the industry partner's PDF) is not redistributed with the repository. Tests
# take it from ODOS_EU_PDF or data/input/private/ (gitignored) -- never from the application's runtime storage -- and
# write derived files only under output/eu/. Without it, the full-document EU tests skip with this reason; the
# synthetic EU regulation (tests/synthetic_eu.py) always covers the EU profile.
EU_RAW = BACKEND / "output" / "eu" / "docling_raw.json"
EU_PDF = BACKEND / "data" / "input" / "private" / "eu_2023_1230.pdf"
EU_PDF_SHA256 = "fe36f0d148a84e790ec9a9825017baaea66fb931a5314ad0a614a1cde0ec182c"
EU_MISSING = ("Regulation (EU) 2023/1230 not available: set ODOS_EU_PDF or copy the PDF to "
              "backend/data/input/private/eu_2023_1230.pdf (gitignored)")  # fmt: skip


def _eu_pdf_or_none() -> Path | None:
    import hashlib
    import os

    pdf = Path(os.environ["ODOS_EU_PDF"]) if os.environ.get("ODOS_EU_PDF") else EU_PDF
    if not pdf.is_file():
        return None
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if sha != EU_PDF_SHA256:
        pytest.skip(f"{pdf} is not the Regulation (EU) 2023/1230 PDF the EU tests are written for (sha256 {sha[:12]}…, expected {EU_PDF_SHA256[:12]}…)")  # fmt: skip
    return pdf


@pytest.fixture(scope="session")
def eu_raw_json() -> Path:
    from odos.normalization.reading_order import load_evidence

    pdf = _eu_pdf_or_none()
    if not EU_RAW.exists():
        if pdf is None:
            pytest.skip(EU_MISSING)
        from odos.extraction import extract_pdf  # slow path (~2 min): run Docling once

        extract_pdf(pdf, EU_RAW.parent)
    # the PDF text layer that verifies reading order and split boundaries (pdf_text_lines.json, under output/eu/):
    # rebuilt from the PDF whenever it is available, so the evidence always follows the current evidence rules
    if pdf is not None:
        _evidence(pdf, EU_RAW)
    elif load_evidence(EU_RAW) is None:
        pytest.skip(f"{EU_MISSING}; its text-layer evidence cannot be built without it")
    return EU_RAW


@pytest.fixture(scope="session")
def eu_model(eu_raw_json):
    from odos.parsing import parse_document

    return parse_document(eu_raw_json, "eu_legislation")


@pytest.fixture(scope="session")
def eu_pdf() -> Path:
    pdf = _eu_pdf_or_none()
    if pdf is None:
        pytest.skip(EU_MISSING)
    return pdf


# ---- synthetic EU regulation: always available ------------------------------------------------------------------------
@pytest.fixture(scope="session")
def synthetic_eu_raw_json(tmp_path_factory) -> Path:
    import synthetic_eu

    return synthetic_eu.write(tmp_path_factory.mktemp("synthetic_eu"))


@pytest.fixture(scope="session")
def synthetic_eu_model(synthetic_eu_raw_json):
    from odos.parsing import parse_document

    return parse_document(synthetic_eu_raw_json, "eu_legislation")


# ---- synthetic German law: always available (with a real generated PDF, hence real PDF text-layer evidence) ------------
@pytest.fixture(scope="session")
def synthetic_german_raw_json(tmp_path_factory) -> Path:
    import synthetic_german

    return synthetic_german.write(tmp_path_factory.mktemp("synthetic_german"))


@pytest.fixture(scope="session")
def synthetic_german_model(synthetic_german_raw_json):
    from odos.parsing import parse_document

    return parse_document(synthetic_german_raw_json, "german_law")


# ---- golden coverage: which full-document equivalence checks ran in this session -------------------------------------
GOLDEN_COVERAGE = pytest.StashKey[dict]()


def pytest_configure(config):
    config.stash[GOLDEN_COVERAGE] = {}


def pytest_terminal_summary(terminalreporter, config):
    cov = config.stash.get(GOLDEN_COVERAGE, {})
    if not cov:
        terminalreporter.write_line("GOLDEN COVERAGE: not run in this session (tests/test_golden_equivalence.py not selected)")
        return
    names = {"mbo": "MBO", "bdsg": "BDSG", "eu": "EU", "synthetic_eu": "synthetic EU"}
    parts = [f"{names[k]} {cov[k]}" for k in names if k in cov]
    full = all(cov.get(k) == "✓" for k in ("mbo", "bdsg", "eu"))
    terminalreporter.write_line("GOLDEN COVERAGE: " + " · ".join(parts))
    terminalreporter.write_line("full three-document equivalence: " + ("yes" if full else "NO (see the reasons above)"))
