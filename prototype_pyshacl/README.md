# MBO § 37(5): SHACL + pySHACL demo

This demo models *windows serving as rescue routes under MBO § 33(2), sentence 2*.

- `rules.ttl` – SHACL shape with base dimensions and conditional eaves-distance rule
- `digital_twin.ttl` – four example windows: two expected passes, two expected failures
- `evaluate.py` – runs pySHACL, lists per-window outcomes, and asserts the expected results

## Run

```sh
python -m pip install pyshacl
python evaluate.py
```

## Expected test results

```
Overall graph conforms: False
Window_OK: PASS
Window_TooSmall: FAIL
Window_RoofTooFar: FAIL
Window_RoofWithPlatform: PASS
All 4 test expectations matched.
```

The results above are expected outcomes, not a record of actual execution of pySHACL in this sandbox. The TTL was parsed using RDFLib and the test case dimensions were checked independently, but pySHACL could not be installed in the execution environment due to unavailable internet access.

## Model caveats

This is a **demonstration**, not an authoritative compliance opinion. It assumes clear width and height correspond to the 0.90 × 1.20 m dimensions, uses a simplified location classification, and assumes the Digital Twin has measured the needed distances (rather than calculating geometry). The real legal applicability of § 33(2), sentence 2, local state building codes, measurement conventions, and exceptions need separate treatment. SHACL violations signal that the model does not satisfy the encoded constraints, not necessarily that a building is legally noncompliant.
