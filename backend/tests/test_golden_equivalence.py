"""Golden equivalence: every output is byte-identical to a baseline recorded before a refactoring started. A
difference is a regression to investigate, never a value to refresh.

* MBO, BDSG and Regulation (EU) 2023/1230: tests/golden/phase3_baseline.json (recorded 2026-10-31, before Phase 3).
  Each runs only on the exact Docling extraction the baseline was computed from (checked by sha256); a missing or
  different extraction is reported as missing coverage, with its reason, in the skip list and in the
  "GOLDEN COVERAGE" line at the end of the run -- never as a pass.
* the synthetic EU regulation (tests/synthetic_eu.py): tests/golden/synthetic_eu_baseline.json (recorded before
  Phase 4). It needs no external file, so it always runs.

Covered per document: document_model.json, document.json 1.1, its 1.0 downgrade, the JSON validation report, the AKN
XML (German: full and § 1-2 excerpt; EU: full), XSD validity, the parser validation report (key order ignored), every
element / sentence / TOC entry, the element id list and the summary counts. Outputs are computed in memory with
fixed dates (golden_outputs.py)."""

import hashlib
import json
from pathlib import Path

import pytest
from conftest import GOLDEN_COVERAGE
from golden_outputs import fingerprint, first_differences

GOLDEN = Path(__file__).parent / "golden"
BASELINE = json.loads((GOLDEN / "phase3_baseline.json").read_text())
FIXTURES = {"mbo": ("mbo_model", "mbo_raw_json"), "bdsg": ("model", "raw_json"), "eu": ("eu_model", "eu_raw_json")}
# the Docling extractions the baseline was computed from (the model hash pins them too; checked first for a clear reason)
INPUTS = {
    "mbo": "1c5ec2ab2c7b0330d274890b4f2fe654676f8b1ddd99691d369678ee7d585632",
    "bdsg": "dd49591bfd8dab883a86c173dfbf93ca188fc0ed3685b569d718972614ef8ba0",
    "eu": "f8b091a72fd595b56f3ab050448bb4a3d83a100f6719c6ec13b7c3dda48a4879",
}


def _check(request, name: str, expected: dict, model_fixture: str, raw_fixture: str) -> None:
    coverage = request.config.stash[GOLDEN_COVERAGE]
    try:
        raw = request.getfixturevalue(raw_fixture)
    except pytest.skip.Exception as skip:
        coverage[name] = f"✗ not covered: {skip.msg}"
        raise
    if name in INPUTS:
        sha = hashlib.sha256(Path(raw).read_bytes()).hexdigest()
        if sha != INPUTS[name]:
            reason = f"different Docling extraction (sha256 {sha[:12]}…, baseline built from {INPUTS[name][:12]}…)"
            coverage[name] = f"✗ not covered: {reason}"
            pytest.skip(f"{name}: {reason}")
    actual = fingerprint(request.getfixturevalue(model_fixture), raw)
    diff = first_differences(expected, actual)
    coverage[name] = "✓" if not diff else "✗ DIFFERS"
    assert not diff, f"{name} differs from the baseline:\n" + "\n".join(diff)


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_outputs_identical_to_the_pre_refactoring_baseline(request, name):
    _check(request, name, BASELINE[name], *FIXTURES[name])


def test_synthetic_eu_outputs_identical_to_its_baseline(request):
    expected = json.loads((GOLDEN / "synthetic_eu_baseline.json").read_text())
    _check(request, "synthetic_eu", expected, "synthetic_eu_model", "synthetic_eu_raw_json")
