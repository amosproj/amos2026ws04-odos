"""The reference extractions need the locked dependency set (requirements.lock).

Docling's output is not determined by the docling version alone: a newer docling-parse, torch,
transformers or docling-core segments, labels and orders the same PDF differently (2026-10-29: 11 EU
tests failed after an unpinned reinstall, and one paragraph of Art. 15 was read out of order). A drift is
reported here, with its cause, instead of as unexplained parser assertion failures elsewhere.
"""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

LOCK = Path(__file__).resolve().parents[1] / "requirements.lock"
EXTRACTION_PACKAGES = ("docling", "docling-core", "docling-parse", "docling-ibm-models", "torch", "torchvision", "transformers")


def _norm(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def _locked() -> dict[str, str]:
    pins = {}
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            name, _, ver = line.partition("==")
            pins[_norm(name)] = ver.strip()
    return pins


def _installed(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def test_lock_file_pins_every_extraction_dependency():
    pins = _locked()
    assert all(p in pins for p in EXTRACTION_PACKAGES)
    assert all(v and v[0].isdigit() for v in pins.values())


def test_extraction_dependencies_match_the_lock():
    pins = _locked()
    drift = {p: {"locked": pins[p], "installed": _installed(p)} for p in EXTRACTION_PACKAGES if _installed(p) != pins[p]}
    assert not drift, (
        f"Extraction dependencies differ from requirements.lock: {drift}. Docling output (and the pinned test values) "
        "would change. Reinstall with: pip install -r requirements.lock && pip install --no-deps -e '.[dev]'"
    )
