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

INPUT = Path(__file__).resolve().parents[1] / "data" / "input"
PRIVATE_INPUT = INPUT / "private"
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
def bdsg(tmp_path_factory):
    pdf = Path(os.environ.get("ODOS_BDSG_PDF") or INPUT / "BDSG.pdf")
    if not pdf.is_file():
        pytest.skip(f"{pdf} not found: set ODOS_BDSG_PDF or place the BDSG PDF there (data/input/SOURCE.md)")
    return process(pdf, tmp_path_factory.mktemp("bdsg"))


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


# ---- text that runs on over a page break: one element with every page that carries it (test_page_break_continuation.py) ----
MBO_PAR6_START = "1 Vor den Außenwänden von Gebäuden sind Abstandsflächen von oberirdischen Gebäuden freizuhalten. 2 Satz 1 gilt entsprechend"


def continuation_children(legal: dict) -> list[str]:
    """Ids of unnumbered text nodes that start in lowercase on a later page than the text before them: fragments of a
    text that a page break cut, left behind as separate children."""
    found = []

    def walk(node, previous_pages=None):
        pages = None
        for child in node.get("children", []):
            text = (child.get("text") or "").lstrip()
            earlier = pages or ([node["pages"][-1]] if node.get("pages") else None)
            if (child["type"] in ("text", "item") and text[:1].islower() and earlier and child["pages"][0] > earlier[-1]
                    and not (node.get("text") or "").rstrip().endswith((".", ":", ";", "!", "?"))):  # fmt: skip
                found.append(child["id"])
            pages = child["pages"]
            walk(child)

    for top in legal["structure"]:
        walk(top)
    return found


def test_mbo_par6_abs1_runs_over_pages_9_and_10(mbo):
    legal, model, _ = mbo
    absatz = find(legal, "section", "6")["children"][0]
    assert absatz["id"].endswith("par-6/abs-1")
    assert absatz["pages"] == [9, 10]
    assert absatz["text"].startswith(MBO_PAR6_START) and absatz["text"].endswith("nicht erforderlich vor Außenwänden,")
    assert [c["number"] for c in absatz["children"]] == ["1", "2"] and {c["type"] for c in absatz["children"]} == {"number"}
    assert all(c["text"] not in absatz["text"] for c in absatz["children"])
    element = next(e for e in model["elements"] if e["id"] == absatz["id"])
    assert [p["page_no"] for p in element["provenance"]] == [9, 10] and len(element["source_refs"]) == 2
    assert not [e for e in model["elements"] if e["id"].startswith(absatz["id"] + "/txt-")]
    assert not [e for e in model["elements"] if e["region"] == "body" and e.get("content_text", "").strip().isdigit()]  # page numbers


def test_mbo_has_no_page_break_fragments(mbo):
    legal, *_ = mbo
    assert continuation_children(legal) == []
    multi = [n for n in nodes(legal) if len(n.get("pages", [])) > 1 and n["type"] in ("subsection", "number", "letter", "text")]
    assert len(multi) >= 20  # the MBO has dozens of units that run over a page break


def test_bdsg_numbered_item_runs_over_a_page_break(bdsg):
    legal, *_ = bdsg
    assert continuation_children(legal) == []
    nummer = next(n for n in nodes(legal) if n["id"].endswith("par-46/nr-12"))
    assert nummer["pages"] == [28, 29] and not nummer.get("children")
    assert nummer["text"].count("die eindeutige Identifizierung") == 1


def test_eu_has_no_page_break_fragments_and_no_page_number_text(eu):
    legal, *_ = eu
    assert continuation_children(legal) == []
    assert [n["id"] for n in nodes(legal) if (n.get("text") or "").strip().isdigit()] == []


def test_mbo_par67_abs1_runs_over_pages_60_and_61_and_keeps_its_page_foot_notes_apart(mbo):
    """§ 67 (1): four notes "n nach Landesrecht" stand at the foot of page 60, between the text and its continuation.
    macOS labels them `footnote`; Docker labels them as body text (two of them also as page furniture): in both the
    notes stay separate source content and the Absatz is one text over both pages."""
    legal, model, _ = mbo
    absatz = next(n for n in nodes(legal) if n["id"].endswith("par-67/abs-1"))
    assert absatz["pages"] == [60, 61]
    assert "Belangen, insbesondere den Anforderungen des § 3 Satz 1 vereinbar ist." in absatz["text"]
    assert "nach Landesrecht" not in absatz["text"]
    notes = [e["original_text"] for e in [*model["elements"], *model["furniture"]]
             if 60 in e["pages"] and e["original_text"].endswith("nach Landesrecht") and len(e["original_text"]) < 25]  # fmt: skip
    assert sorted(notes) == [f"{n} nach Landesrecht" for n in range(1, 5)]  # every note exactly once, none lost or merged


def test_merged_elements_keep_their_pages_sources_and_highlight_pages(mbo, eu):
    for _, model, _ in (mbo, eu):
        for element in model["elements"]:
            if "page_break_continuation_merged_confirmed" not in element.get("hygiene_flags", []):
                continue
            pages = sorted({p["page_no"] for p in element["provenance"]})
            assert element["pages"] == pages and len(pages) >= 2, element["id"]
            assert len(set(element["source_refs"])) == len(element["source_refs"]) >= 2, element["id"]
            if element.get("highlight_boxes"):
                assert {h["page_no"] for h in element["highlight_boxes"]} == set(pages), element["id"]
            if element.get("source_spans"):
                assert {s["ref"] for s in element["source_spans"]} == set(element["source_refs"]), element["id"]
