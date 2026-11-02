"""Minimal SHACL validation demo for MBO § 37(5).

Run: python -m pip install pyshacl
     python evaluate.py
"""
from pathlib import Path
from rdflib import Graph, Namespace
from rdflib.namespace import RDF, SH
from pyshacl import validate

folder = Path(__file__).resolve().parent
EX = Namespace("https://example.org/odos/")

shapes = Graph().parse(folder / "rules.ttl", format="turtle")
twin = Graph().parse(folder / "digital_twin.ttl", format="turtle")

conforms, report, report_text = validate(
    data_graph=twin,
    shacl_graph=shapes,
    inference="none",
    abort_on_first=False,
    advanced=False,
)

violations = {}
for result in report.subjects(RDF.type, SH.ValidationResult):
    focus = report.value(result, SH.focusNode)
    message = report.value(result, SH.resultMessage)
    if focus is not None:
        violations.setdefault(focus, []).append(str(message or "Constraint violation"))

print("Overall graph conforms:", conforms)
expected = {
    EX.Window_OK: True,
    EX.Window_TooSmall: False,
    EX.Window_RoofTooFar: False,
    EX.Window_RoofWithPlatform: True,
}
for window, should_pass in expected.items():
    passed = window not in violations
    print(f"{str(window).rsplit('/', 1)[-1]}: {'PASS' if passed else 'FAIL'}")
    for message in violations.get(window, []):
        print(f"   - {message}")
    assert passed == should_pass, f"Unexpected result for {window}"

assert conforms is False
print("All 4 test expectations matched.")
