"""The full pipeline (Docling, normalization, legal parser, Legal JSON) on the two partner reference documents.

Regression for the fragmented MBO structure in the Docker backend: without a substitute for the MBO's non-embedded
fonts, the layout model received empty glyph boxes, and § 2 came out as loose TEXT nodes with list markers ("2.",
"5.") split from their text (see test_page_rendering.py). The PDFs are not in Git (data/input/SOURCE.md): set
ODOS_MBO_PDF / ODOS_EU_PDF or place them under data/input/private/; the tests skip with the reason otherwise.
Run inside the backend image to test the Docker runtime (Documentation/development.md).
"""

import json
import os
import re
from pathlib import Path

import pytest

from odos.artifact_names import DOCUMENT_MODEL, LEGAL_JSON, LEGAL_JSON_REPORT
from odos.pipeline import Outcome, run_pipeline

PRIVATE_INPUT = Path(__file__).resolve().parents[1] / "data" / "input" / "private"
BARE_MARKER = re.compile(r"\s*(\d+\.|[a-z]\)|\(\d+\))\s*")  # a list or Absatz marker without its text
LEGAL_UNITS = {"part", "division", "chapter", "section", "article", "subsection", "paragraph", "number", "letter",
               "point", "subpoint", "recital", "annex"}  # numbered units; text blocks and formulas have no germanType

pytestmark = pytest.mark.slow


def reference_pdf(variable: str, filename: str) -> Path:
    pdf = Path(os.environ.get(variable) or PRIVATE_INPUT / filename)
    if not pdf.is_file():
        pytest.skip(f"{pdf} not found: set {variable} or place the partner PDF there (data/input/SOURCE.md)")
    return pdf


def process(pdf: Path, out_dir: Path) -> tuple[dict, dict, dict]:
    """run_pipeline as the web API calls it (profile recognized from the document); Legal JSON, model, validation report."""
    result = run_pipeline(pdf, out_dir)
    assert result.outcome == Outcome.COMPLETED, result.message
    return tuple(json.loads((out_dir / name).read_text(encoding="utf-8")) for name in (LEGAL_JSON, DOCUMENT_MODEL, LEGAL_JSON_REPORT))


def nodes(legal: dict) -> list[dict]:
    found = []

    def walk(node):
        found.append(node)
        for child in node.get("children", []):
            walk(child)

    for node in legal["structure"]:
        walk(node)
    return found


def find(legal: dict, node_type: str, number: str) -> dict:
    return next(n for n in nodes(legal) if n["type"] == node_type and n.get("number") == number)


def children(node: dict, node_type: str) -> list[dict]:
    return [c for c in node.get("children", []) if c["type"] == node_type]


def numbers(node: dict, node_type: str) -> list[str]:
    return [c["number"] for c in children(node, node_type)]


@pytest.fixture(scope="module")
def mbo(tmp_path_factory):
    return process(reference_pdf("ODOS_MBO_PDF", "MusterBauVerordnung.pdf"), tmp_path_factory.mktemp("mbo"))


@pytest.fixture(scope="module")
def eu(tmp_path_factory):
    return process(reference_pdf("ODOS_EU_PDF", "eu_2023_1230.pdf"), tmp_path_factory.mktemp("eu"))


def test_mbo_document_outline(mbo):
    legal, *_ = mbo
    assert (legal["documentType"], legal["title"]) == ("de_legislation", "MUSTERBAUORDNUNG")
    assert [(n["type"], n["number"]) for n in legal["structure"]] == [("part", str(i)) for i in range(1, 7)] + [("annex", "1")]
    sections = [n["number"] for n in nodes(legal) if n["type"] == "section"]
    assert {str(i) for i in range(1, 88)} <= set(sections)
    assert len(sections) == len(set(sections)) == 96


def test_mbo_section_1_and_2_hierarchy(mbo):
    legal, *_ = mbo
    assert numbers(find(legal, "section", "1"), "subsection") == ["1", "2"]

    section_2 = find(legal, "section", "2")
    assert section_2["title"] == "Begriffe"
    absaetze = children(section_2, "subsection")
    assert [a["number"] for a in absaetze] == [str(i) for i in range(1, 12)]
    assert absaetze[0]["text"].startswith("1 Bauliche Anlagen sind mit dem Erdboden verbundene")
    assert numbers(absaetze[0], "number") == [str(i) for i in range(1, 9)]
    assert children(absaetze[0], "number")[1]["text"] == "Lagerplätze, Abstellplätze und Ausstellungsplätze,"

    gebaeudeklassen = children(absaetze[2], "number")
    assert [(n["number"], n["text"]) for n in gebaeudeklassen] == [(str(i), f"Gebäudeklasse {i}:") for i in range(1, 6)]
    assert numbers(gebaeudeklassen[0], "letter") == ["a", "b"]


def test_mbo_has_no_fragmented_markers(mbo):
    legal, *_ = mbo
    assert [n["id"] for n in nodes(legal) if n["type"] == "text" and BARE_MARKER.fullmatch(n.get("text") or "")] == []


def test_mbo_source_references(mbo):
    legal, model, _ = mbo
    assert all(n.get("pages") for n in nodes(legal))
    absatz = next(e for e in model["elements"] if e["id"] == find(legal, "section", "2")["children"][0]["id"])
    assert absatz["source_refs"] and absatz["provenance"][0]["page_no"] == 5


def test_eu_articles_and_annexes(eu):
    legal, *_ = eu
    assert legal["documentType"] == "eu_regulation"
    assert "2023/1230" in legal["title"]
    found = nodes(legal)
    assert [n["number"] for n in found if n["type"] == "chapter"] == ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX"]
    assert [n["number"] for n in found if n["type"] == "article"] == [str(i) for i in range(1, 55)]
    assert [n["number"] for n in found if n["type"] == "annex"] == [
        "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]
    assert sum(n["type"] == "recital" for n in found) == 86
    assert [n["id"] for n in found if n["type"] == "text" and BARE_MARKER.fullmatch(n.get("text") or "")] == []


@pytest.mark.parametrize("document", ["mbo", "eu"])
def test_legal_json_is_schema_valid(document, request):
    legal, _, report = request.getfixturevalue(document)
    assert (report["schema_valid"], report["schema_errors"]) == (True, [])
    units = [n for n in nodes(legal) if n["type"] in LEGAL_UNITS]
    assert units and all(n.get("germanType") for n in units)  # the source-language term is kept, not dropped
