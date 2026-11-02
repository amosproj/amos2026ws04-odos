"""Golden equivalence: every output is byte-identical to a baseline recorded before a refactoring started. A
difference is a regression to investigate, never a value to refresh.

* MBO and Regulation (EU) 2023/1230: tests/golden/phase3_baseline.json (recorded 2026-10-31, before Phase 3; the
  entry of a third, public German law was removed from it together with that law's test input).
  Each runs only on the exact Docling extraction the baseline was computed from (checked by sha256); a missing or
  different extraction is reported as missing coverage, with its reason, in the skip list and in the
  "GOLDEN COVERAGE" line at the end of the run -- never as a pass.
* the synthetic EU regulation (tests/synthetic_eu.py): tests/golden/synthetic_eu_baseline.json (recorded before
  Phase 4). It needs no external file, so it always runs.

Covered per document: document_model.json, the parser validation report (key order ignored), every element / sentence
/ TOC entry, the element id list and the summary counts, and document.json 2.0 with its JSON validation report
(tests/golden/legal_json_2_0_baseline.json, recorded when 2.0 replaced 1.1, after checking that every 1.1 node, footnote,
sentence and TOC entry kept its legal fields). Outputs are computed in memory (golden_outputs.py). The older baselines
also hold the hashes of outputs ODOS no longer produces (Akoma Ntoso XML, Legal JSON 1.1 / 1.0 and their report);
those are not compared (golden_outputs.RETIRED)."""

import hashlib
import json
from pathlib import Path

import pytest
from conftest import GOLDEN_COVERAGE
from golden_outputs import fingerprint, first_differences

GOLDEN = Path(__file__).parent / "golden"
BASELINE = json.loads((GOLDEN / "phase3_baseline.json").read_text())
LEGAL_JSON_2_0 = json.loads((GOLDEN / "legal_json_2_0_baseline.json").read_text())
FIXTURES = {"mbo": ("mbo_model", "mbo_raw_json"), "eu": ("eu_model", "eu_raw_json")}
# the Docling extractions the baseline was computed from (the model hash pins them too; checked first for a clear reason)
INPUTS = {
    "mbo": "1c5ec2ab2c7b0330d274890b4f2fe654676f8b1ddd99691d369678ee7d585632",
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
    expected = {**expected, "outputs": {**expected["outputs"], **LEGAL_JSON_2_0[name]}}
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
