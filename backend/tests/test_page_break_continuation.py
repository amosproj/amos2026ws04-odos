"""A page break is not a legal boundary: text cut by the page end is one element with every page that carries it.

Regression for the MBO § 6 (1) (pages 9 and 10): in the Docker run Docling labelled the printed page number "9" as body
text instead of `page_footer`, the parser opened a text element for it between the two fragments, and the continuation
stayed a separate `txt` child while the Absatz kept only `pages: [9]`. The tests below run the real parsing lifecycle,
the Legal JSON export and its validation on synthetic Docling output (`docling_synthetic`), once with the page numbers
labelled the way macOS gave them (`page_footer`) and once the way Docker gave them (`text`): the result must not depend
on it. The partner documents are checked in test_reference_documents.py.
"""

import json
from pathlib import Path

import pytest
from collections import Counter

from docling_synthetic import build, item, page_numbers
from jsonschema import Draft202012Validator

from odos.document_model import DocumentModel, SourceSpan
from odos.legal_json.artifacts import published_schema, serialize
from odos.legal_json.exporter import to_legal_json
from odos.normalization.docling_reader import SourceItem
from odos.parsing import continuation, parse_document
from odos.parsing.builder import StructureBuilder
from odos.document_model import ElementType as T, Provenance, BoundingBox

FOOTERS = pytest.mark.parametrize("footers", ["page_footer", "text"])
MERGED = continuation.FLAG


def parse(tmp_path: Path, mode: str, pages: int, items: list[dict], footers: str = "text") -> DocumentModel:
    return parse_document(build(tmp_path / f"{mode}-{footers}.json", pages, items, footers=footers), mode)


def by_id(model: DocumentModel) -> dict:
    return {e.id: e for e in model.elements}


def legal(model: DocumentModel) -> dict:
    return json.loads(serialize(to_legal_json(model)))


def node(legal_doc: dict, node_id: str) -> dict:
    stack = list(legal_doc["structure"])
    while stack:
        n = stack.pop()
        if n["id"] == node_id:
            return n
        stack += n.get("children", [])
    raise KeyError(node_id)


def body_texts(model: DocumentModel) -> list[str]:
    return [e.original_text for e in model.elements if e.region == "body"]


# ---- German law -----------------------------------------------------------------------------------------------------
PAR6_INTRO = ("1 Vor den Außenwänden von Gebäuden sind Abstandsflächen von oberirdischen Gebäuden freizuhalten. "
              "2 Satz 1 gilt entsprechend für andere Anlagen. 3 Eine Abstandsfläche ist nicht erforderlich vor Außenwänden,")


def par6(extra: list[dict] | None = None) -> list[dict]:
    """The shape of MBO § 6 (1): the introduction runs from page 9 over to page 10, two Nummern follow, then (2)."""
    return [
        item("section_header", "MUSTERGESETZ", 1),
        item("section_header", "Inhaltsübersicht", 1),
        item("text", "§ 6 Abstandsflächen, Abstände", 1),
        item("section_header", "§ 6 Abstandsflächen, Abstände", 9),
        item("text", "(1) 1 Vor den Außenwänden von Gebäuden sind Abstandsflächen von", 9, "bottom"),
        item("text", "oberirdischen Gebäuden freizuhalten. 2 Satz 1 gilt entsprechend für andere Anlagen. "
                     "3 Eine Abstandsfläche ist nicht erforderlich vor Außenwänden,", 10, "top"),
        item("list_item", "die an Grundstücksgrenzen errichtet werden, wenn gebaut werden muss, oder", 10, marker="1.", enumerated=True),
        item("list_item", "die nicht länger als 1 m sind.", 10, marker="2.", enumerated=True),
        item("text", "(2) 1 Abstandsflächen müssen auf dem Grundstück selbst liegen.", 10),
        *(extra or []),
    ]


@FOOTERS
def test_mbo_par6_abs1_is_one_element_over_pages_9_and_10(tmp_path, footers):
    model = parse(tmp_path, "german_law", 10, par6(), footers)
    elements = by_id(model)
    absatz = elements["doc/par-6/abs-1"]
    assert absatz.content_text == PAR6_INTRO
    assert absatz.pages == [9, 10]
    assert [p.page_no for p in absatz.provenance] == [9, 10]
    assert len(absatz.source_refs) == 2 and len(set(absatz.source_refs)) == 2  # one Docling item per page
    assert absatz.original_text.split("\n")[0].startswith("(1) 1 Vor den Außenwänden")
    assert absatz.children_ids == ["doc/par-6/abs-1/nr-1", "doc/par-6/abs-1/nr-2"]  # genuine children kept, no txt
    assert MERGED in absatz.hygiene_flags
    assert not any("/txt-" in i for i in elements)
    assert elements["doc/par-6/abs-2"].pages == [10]


def test_the_result_does_not_depend_on_how_docling_labelled_the_page_numbers(tmp_path):
    """Stable ids and complete texts whether the page number is `page_footer` (macOS) or `text` (Docker)."""
    mac = parse(tmp_path, "german_law", 10, par6(), "page_footer")
    docker = parse(tmp_path, "german_law", 10, par6(), "text")
    assert [e.id for e in mac.elements] == [e.id for e in docker.elements]
    assert [(e.content_text, e.pages) for e in mac.elements] == [(e.content_text, e.pages) for e in docker.elements]
    assert sorted(f.content_text for f in docker.furniture) == sorted(f.content_text for f in mac.furniture) == sorted(str(p) for p in range(1, 11))  # fmt: skip


@FOOTERS
def test_legal_json_carries_the_complete_text_and_both_pages(tmp_path, footers):
    model = parse(tmp_path, "german_law", 10, par6(), footers)
    doc = legal(model)
    absatz = node(doc, "doc/par-6/abs-1")
    assert (absatz["text"], absatz["pages"]) == (PAR6_INTRO, [9, 10])
    assert [(c["type"], c["number"], c["pages"]) for c in absatz["children"]] == [("number", "1", [10]), ("number", "2", [10])]
    assert node(doc, "doc/par-6")["pages"] == [9]  # the § heading is on page 9 only: a parent does not collect its children's pages
    errors = [e.message for e in Draft202012Validator(published_schema()).iter_errors(doc)]
    assert errors == []
    for c in absatz["children"]:  # no text of a child is repeated in its parent
        assert c["text"] not in absatz["text"]


@FOOTERS
def test_no_text_is_lost_or_duplicated(tmp_path, footers):
    items = par6()
    model = parse(tmp_path, "german_law", 10, items, footers)
    pieces = Counter(piece for e in [*model.elements, *model.furniture] for piece in (e.original_text.split("\n") if e.original_text else []))  # fmt: skip
    assert pieces == Counter(i["text"] for i in [*items, *page_numbers(10)])  # every source text exactly once, none invented
    assert len(model.furniture) == 10  # page numbers 1..10 are furniture, not content


def test_nummer_buchstabe_and_text_blocks_across_pages(tmp_path):
    items = [
        item("section_header", "§ 35 Rettungswege", 1),
        item("text", "(5) 1 Treppen müssen so angeordnet sein, dass sie sicher begehbar sind. 2 Es gilt:", 1),
        item("list_item", "Wände aus brennbaren Baustoffen müssen eine Bekleidung aus", 1, "bottom", marker="2.", enumerated=True),
        item("list_item", "nichtbrennbaren Baustoffen in ausreichender Dicke haben,", 2, "top"),
        item("list_item", "Fluchtwege, die", 2, marker="a)", enumerated=True),
        item("text", "Kommentar zu den Fluchtwegen, der sich über mehrere Absätze und Seiten dieses Teils der Verordnung erstreckt und weiter", 2, "bottom"),
        item("text", "auf die Folgeseite reicht und dort noch nicht endet, sondern über die dritte Seite hinaus bis zu seinem Ende führt und", 3, "full"),
        item("text", "und endet erst auf der vierten Seite.", 4, "top"),
    ]
    model = parse(tmp_path, "german_law", 4, items)
    elements = by_id(model)
    nr2 = elements["doc/par-35/abs-5/nr-2"]
    assert nr2.content_text == ("Wände aus brennbaren Baustoffen müssen eine Bekleidung aus nichtbrennbaren Baustoffen "
                                "in ausreichender Dicke haben,")
    assert nr2.pages == [1, 2]
    chain = next(e for e in model.elements if e.type == T.TEXT)
    assert chain.pages == [2, 3, 4]  # a text cut twice is one element over three pages
    assert chain.content_text.endswith("und endet erst auf der vierten Seite.")
    assert chain.content_text.count("Folgeseite") == 1
    assert not any(e.type == T.UNMARKED_LIST_ITEM for e in model.elements)


# not a continuation: each case keeps its own element
@pytest.mark.parametrize("name, prev, nxt", [
    ("sentence ends", "(1) 1 Die Behörde entscheidet über den Antrag.", item("text", "Die Entscheidung ergeht schriftlich.", 2, "top")),
    ("colon introduces a list", "(1) 1 Dies gilt insbesondere für folgende Fälle:", item("text", "ausgenommen sind Notfälle.", 2, "top")),
    ("next page opens with an Absatz", "(1) 1 Die Behörde entscheidet über den Antrag und teilt", item("text", "(2) 1 Die Frist beträgt einen Monat.", 2, "top")),
    ("next page opens with a Satz number", "(1) 1 Die Behörde entscheidet über den Antrag und", item("text", "2 Die Entscheidung ergeht schriftlich.", 2, "top")),
    ("next page opens with a Nummer", "(1) 1 Die Behörde entscheidet über den Antrag und", item("text", "3. Die Entscheidung ergeht schriftlich.", 2, "top")),
    ("capitalised start without any open end", "(1) 1 Die Behörde", item("text", "Die Entscheidung ergeht schriftlich.", 2, "top")),
    ("no geometric page boundary", "(1) 1 Die Behörde entscheidet über den Antrag und teilt", item("text", "dem Antragsteller das Ergebnis mit.", 2, "middle")),
])  # fmt: skip
def test_no_merge_when_the_evidence_is_missing(tmp_path, name, prev, nxt):
    items = [item("section_header", "§ 1 Anwendungsbereich", 1), item("text", prev, 1, "bottom"), nxt]
    model = parse(tmp_path, "german_law", 4, items)
    absatz = by_id(model)["doc/par-1/abs-1"]
    assert MERGED not in absatz.hygiene_flags, name
    assert absatz.pages == [1], name
    assert any(nxt["text"] in e.original_text for e in model.elements if e.pages == [2]), name  # the item is still there, on its own


def test_a_footnote_labelled_as_text_is_not_a_host_for_the_continuation(tmp_path):
    items = [
        item("section_header", "§ 1 Anwendungsbereich", 1),
        item("text", "(1) 1 Die Behörde entscheidet über den Antrag nach Landesrecht und", 1, "middle"),
        item("text", "2 nach Landesrecht", 1, "bottom"),
        item("text", "teilt dem Antragsteller das Ergebnis mit.", 2, "top"),
    ]
    absatz = by_id(parse(tmp_path, "german_law", 4, items))["doc/par-1/abs-1"]
    assert absatz.pages == [1] and MERGED not in absatz.hygiene_flags


def test_an_uncertain_continuation_stays_flagged(tmp_path):
    items = [item("section_header", "§ 1 Anwendungsbereich", 1),
             item("text", "(1) 1 Die Behörde entscheidet über den Antrag und teilt", 1, "bottom"),
             item("text", "dem Antragsteller das Ergebnis mit.", 2, "middle")]
    model = parse(tmp_path, "german_law", 4, items)
    flagged = [e for e in model.elements if "continuation_across_page_break_attached_to_previous_element" in e.uncertainty_reasons]
    assert len(flagged) == 1 and flagged[0].parent_id == "doc/par-1/abs-1"


def test_downstream_stages_see_the_complete_unit(tmp_path):
    """Sentences are ranges over the merged text; the Legal JSON validation (schema, nesting, sentence ranges, text
    identity with the model, content accounting of every Docling item) accepts the multi-page unit."""
    from odos.parsing.profiles import get
    from odos.pipeline import _run_structured

    items = [
        item("section_header", "MUSTERGESETZ", 1), item("section_header", "Inhaltsübersicht", 1), item("text", "§ 1 Verfahren", 1),
        item("section_header", "§ 1 Verfahren", 2),
        item("text", "(1) Die Behörde entscheidet über den Antrag. Sie teilt dem Antragsteller das Ergebnis mit, und", 2, "bottom"),
        item("text", "die Entscheidung ergeht schriftlich. Der Bescheid ist zuzustellen.", 3, "top"),
    ]
    out = tmp_path / "out"
    out.mkdir()
    build(out / "docling_raw.json", 4, items)
    result = _run_structured([get("german_law")], out, {}, lambda stage: None)
    assert result.summary["json_valid"] and result.summary["json_schema_valid"] and result.summary["json_text_identical"]
    report = json.loads((out / "validation_report.json").read_text(encoding="utf-8"))
    assert not report["docling_items_missing"] and not report["docling_items_duplicated"] and not report["text_mismatches"]
    doc = json.loads((out / "document.json").read_text(encoding="utf-8"))
    absatz = node(doc, "doc/par-1/abs-1")
    assert absatz["pages"] == [2, 3] and absatz["text"].endswith("Der Bescheid ist zuzustellen.")
    ranges = [r for s in doc["sentences"] if s["unitId"] == absatz["id"] for r in s["ranges"]]
    assert [absatz["text"][r["start"]:r["end"]] for r in ranges] == [
        "Die Behörde entscheidet über den Antrag.",
        "Sie teilt dem Antragsteller das Ergebnis mit, und die Entscheidung ergeht schriftlich.",  # one sentence over the break
        "Der Bescheid ist zuzustellen.",
    ]


# ---- page-foot notes that Docling labelled as body text -------------------------------------------------------------------
NOTE = continuation.NOTE_FLAG


def with_notes(first: dict, second: dict, notes: list[dict]) -> list[dict]:
    return [item("section_header", "§ 67 Abweichungen", 1), first, *notes, second]


@FOOTERS
def test_page_foot_notes_between_a_text_and_its_continuation_stay_separate(tmp_path, footers):
    """MBO § 67 (1) in Docker: the notes "1 nach Landesrecht", "2 ..." sit between the text and its continuation."""
    items = with_notes(
        item("text", "(1) 1 Die Bauaufsichtsbehörde soll Abweichungen zulassen, wenn sie mit den öffentlichen Belangen,", 1, "above_notes"),
        item("text", "insbesondere den Anforderungen des § 3 Satz 1 vereinbar sind.", 2, "top"),
        [item("text", "1 nach Landesrecht", 1, "note1"), item("text", "2 nach Landesrecht", 1, "note2")])
    model = parse(tmp_path, "german_law", 4, items, footers)
    elements = by_id(model)
    absatz = elements["doc/par-67/abs-1"]
    assert absatz.pages == [1, 2] and absatz.content_text.endswith("Belangen, insbesondere den Anforderungen des § 3 Satz 1 vereinbar sind.")  # fmt: skip
    assert "nach Landesrecht" not in absatz.content_text  # a note is never part of the paragraph's text
    notes = [elements[c] for c in absatz.children_ids]
    assert [n.content_text for n in notes] == ["1 nach Landesrecht", "2 nach Landesrecht"]
    assert all(n.pages == [1] and NOTE in n.hygiene_flags for n in notes)
    assert [n.source_refs for n in notes] == [["#/texts/2"], ["#/texts/3"]] and len(absatz.source_refs) == 2


@FOOTERS
def test_page_foot_notes_between_an_eu_paragraph_and_its_continuation_stay_separate(tmp_path, footers):
    items = [
        item("text", "DAS EUROPÄISCHE PARLAMENT UND DER RAT DER EUROPÄISCHEN UNION -", 1),
        item("text", "in Erwägung nachstehender Gründe:", 1), item("text", "(1) Erste Erwägung.", 1),
        item("text", "HABEN FOLGENDE VERORDNUNG ERLASSEN:", 1),
        item("section_header", "KAPITEL I", 2), item("section_header", "ALLGEMEINE BESTIMMUNGEN", 2),
        item("section_header", "Artikel 1", 2), item("section_header", "Gegenstand", 2),
        item("text", "(1) Die Mitgliedstaaten wenden diese Verordnung auf die Erzeugnisse an, die sie nach Landesrecht und", 2, "above_notes"),
        item("text", "1 nach Landesrecht", 2, "note1"), item("text", "2 nach Landesrecht", 2, "note2"),
        item("text", "den Vorschriften der Union in Verkehr bringen.", 3, "top"),
    ]
    model = parse(tmp_path, "eu_legislation", 4, items, footers)
    elements = by_id(model)
    para = elements["doc/chp-1/art-1/para-1"]
    assert para.pages == [2, 3] and para.content_text.endswith("Landesrecht und den Vorschriften der Union in Verkehr bringen.")
    assert [(e.content_text, e.pages) for e in model.elements if e.id.startswith(para.id + "/")] == [("1 nach Landesrecht", [2]), ("2 nach Landesrecht", [2])]  # fmt: skip
    assert all(NOTE in e.hygiene_flags for e in model.elements if e.id.startswith(para.id + "/"))


def test_a_numbered_text_block_at_the_page_foot_is_a_host_not_a_note(tmp_path):
    """"2 Satz 1 gilt ..." is a Satz-numbered text block: it must receive its own continuation, never be skipped as a note."""
    items = [
        item("section_header", "§ 1 Anwendungsbereich", 1),
        item("text", "(1) 1 Dieses Gesetz gilt für bauliche Anlagen.", 1),
        item("list_item", "Gebäude,", 1, marker="1.", enumerated=True),
        item("text", "2 Satz 1 gilt entsprechend für andere Anlagen, von denen Wirkungen wie von Gebäuden ausgehen, und", 1, "bottom"),
        item("text", "für Grundstücksgrenzen.", 2, "top"),
    ]
    model = parse(tmp_path, "german_law", 4, items)
    block = next(e for e in model.elements if e.content_text.startswith("2 Satz 1 gilt"))
    assert block.pages == [1, 2] and block.content_text.endswith("und für Grundstücksgrenzen.")
    assert NOTE not in block.hygiene_flags


def test_a_note_is_never_a_continuation_and_a_lone_late_note_is_not_skipped(tmp_path):
    items = [item("section_header", "§ 1 Anwendungsbereich", 1),
             item("text", "(1) 1 Die Behörde entscheidet über den Antrag und teilt das Ergebnis", 1, "above_notes"),
             item("text", "3 nach Landesrecht", 1, "note1"),  # a lone note that is not the page's first: not recognised as a note
             item("text", "dem Antragsteller mit.", 2, "top")]
    model = parse(tmp_path, "german_law", 4, items)
    absatz = by_id(model)["doc/par-1/abs-1"]
    assert absatz.pages == [1] and MERGED not in absatz.hygiene_flags  # uncertain: stays separate and flagged
    items = [item("section_header", "§ 1 Anwendungsbereich", 1),
             item("text", "(1) 1 Die Behörde entscheidet über den Antrag und teilt das Ergebnis", 1, "above_notes"),
             item("text", "dem Antragsteller mit.", 2, "top"),
             item("text", "2 nach Landesrecht", 2, "top")]
    model = parse(tmp_path, "german_law", 4, items)
    assert not any("nach Landesrecht" in e.content_text for e in model.elements if MERGED in e.hygiene_flags)


# ---- EU legislation: recitals, articles, paragraphs, points, annexes ------------------------------------------------------
def eu_items() -> list[dict]:
    return [
        item("text", "DAS EUROPÄISCHE PARLAMENT UND DER RAT DER EUROPÄISCHEN UNION -", 1),
        item("text", "in Erwägung nachstehender Gründe:", 1),
        item("text", "(1) Die Sicherheit von Maschinen im Binnenmarkt muss gewährleistet und die Anforderungen müssen", 1, "bottom"),
        item("text", "einheitlich festgelegt werden, damit der freie Verkehr sichergestellt ist.", 2, "top"),
        item("text", "(2) Zweite Erwägung.", 2),
        item("text", "HABEN FOLGENDE VERORDNUNG ERLASSEN:", 2),
        item("section_header", "KAPITEL I", 3), item("section_header", "ALLGEMEINE BESTIMMUNGEN", 3),
        item("section_header", "Artikel 1", 3), item("section_header", "Gegenstand", 3),
        item("text", "(1) Diese Verordnung gilt für die in Absatz 2 genannten Maschinen und für Zubehör, das von", 3, "bottom"),
        item("text", "Herstellern in Verkehr gebracht wird. Sie regelt außerdem die Marktüberwachung.", 4, "top"),
        item("text", "(2) Diese Verordnung gilt nicht für", 4),
        item("list_item", "a) Erzeugnisse, die ausschließlich für", 4, "bottom"),
        item("list_item", "Forschungszwecke bestimmt sind;", 5, "top"),
        item("list_item", "b) Waffen.", 5),
        item("section_header", "Artikel 2", 5), item("section_header", "Begriffsbestimmungen", 5),
        item("text", "(1) Im Sinne dieser Verordnung bezeichnet der Ausdruck", 5, "bottom"),
        item("text", "„Maschine“ eine Gesamtheit verbundener Teile.", 6, "top"),
        item("text", "(2) Im Sinne dieser Verordnung gilt als Hersteller, wer", 6),
        item("list_item", "a) eine Maschine entwirft und", 6),
        item("text", "ANHANG I", 6), item("section_header", "ANFORDERUNGEN", 6),
        item("text", "1. Der Hersteller stellt sicher, dass die Maschine so konstruiert und gebaut ist, dass ihr Betrieb unter den vorgesehenen Bedingungen und bei", 6, "bottom"),
        item("text", "vernünftigerweise vorhersehbarer Fehlanwendung kein Risiko darstellt.", 7, "top"),
        item("list_item", "a) Die Maschine muss so beschaffen sein, dass sie bei", 7),
        item("list_item", "i) normalem Betrieb sicher ist und bei", 7, "bottom"),
        item("list_item", "ii) Störungen nicht gefährlich wird;", 8, "top"),
        item("text", "2. Zweiter Punkt des Anhangs.", 8),
    ]


@FOOTERS
def test_eu_recitals_paragraphs_points_and_annex_over_page_breaks(tmp_path, footers):
    model = parse(tmp_path, "eu_legislation", 8, eu_items(), footers)
    elements = by_id(model)
    expected = {
        "doc/preamble/rec-1": ([1, 2], "Die Sicherheit von Maschinen im Binnenmarkt muss gewährleistet und die Anforderungen müssen einheitlich festgelegt werden, damit der freie Verkehr sichergestellt ist."),  # fmt: skip
        "doc/chp-1/art-1/para-1": ([3, 4], "Diese Verordnung gilt für die in Absatz 2 genannten Maschinen und für Zubehör, das von Herstellern in Verkehr gebracht wird. Sie regelt außerdem die Marktüberwachung."),  # fmt: skip
        "doc/chp-1/art-1/para-2/pt-a": ([4, 5], "Erzeugnisse, die ausschließlich für Forschungszwecke bestimmt sind;"),
        "doc/chp-1/art-2/para-1": ([5, 6], "Im Sinne dieser Verordnung bezeichnet der Ausdruck „Maschine“ eine Gesamtheit verbundener Teile."),
    }
    for eid, (pages, text) in expected.items():
        assert (elements[eid].pages, elements[eid].content_text) == (pages, text), eid
        assert MERGED in elements[eid].hygiene_flags
    assert elements["doc/chp-1/art-1/para-2"].children_ids == ["doc/chp-1/art-1/para-2/pt-a", "doc/chp-1/art-1/para-2/pt-b"]
    assert not any("/txt-" in i for i in elements if i.startswith("doc/chp-1") or i.startswith("doc/preamble"))
    assert len(model.furniture) == 8


@FOOTERS
def test_eu_annex_numbered_points_and_nested_lists_over_page_breaks(tmp_path, footers):
    model = parse(tmp_path, "eu_legislation", 8, eu_items(), footers)
    annex = [e for e in model.elements if e.region == "annex"]
    point = next(e for e in annex if e.type == T.NUMBERED_POINT and e.number == "1")
    assert point.pages == [6, 7]
    assert point.content_text.endswith("bei vernünftigerweise vorhersehbarer Fehlanwendung kein Risiko darstellt.")
    sub = next(e for e in annex if e.type == T.SUBPOINT and e.number == "i")
    assert sub.content_text == "normalem Betrieb sicher ist und bei"
    assert next(e for e in annex if e.type == T.SUBPOINT and e.number == "ii").pages == [8]  # a genuine sibling stays apart
    assert next(e for e in annex if e.type == T.NUMBERED_POINT and e.number == "2").pages == [8]


def test_eu_legal_json_validates_and_keeps_stable_ids(tmp_path):
    mac = parse(tmp_path, "eu_legislation", 8, eu_items(), "page_footer")
    docker = parse(tmp_path, "eu_legislation", 8, eu_items(), "text")
    assert [(e.id, e.pages, e.content_text) for e in mac.elements] == [(e.id, e.pages, e.content_text) for e in docker.elements]
    doc = legal(docker)
    assert [e.message for e in Draft202012Validator(published_schema()).iter_errors(doc)] == []
    para = node(doc, "doc/chp-1/art-1/para-1")
    assert para["pages"] == [3, 4] and para["text"].startswith("Diese Verordnung gilt für") and para["text"].endswith("Marktüberwachung.")  # fmt: skip


# ---- the builder keeps provenance, source spans and PDF highlight boxes -----------------------------------------------------
def box(page: int, top: float, bottom: float) -> Provenance:
    return Provenance(page_no=page, bbox=BoundingBox(l=57, t=top, r=538, b=bottom, coord_origin="BOTTOMLEFT"))


def source(ref: str, text: str, page: int, *, span=None, boxes=None) -> SourceItem:
    return SourceItem(ref=ref, label="text", layer="body", orig=text, text=text, provenance=[box(page, 700, 80)], span=span,
                      highlight_boxes=boxes or [])  # fmt: skip


def builder_with(first: SourceItem) -> tuple[StructureBuilder, object]:
    b = StructureBuilder({T.ABSATZ: 1})
    return b, b.add(first, T.ABSATZ, b.root, "body", local="abs-1", number="1", marker="(1)", content=first.orig.removeprefix("(1) "))


def test_extend_with_whole_items_keeps_one_box_per_page():
    b, el = builder_with(source("#/texts/1", "(1) Der Text läuft über", 9))
    b.extend(el, source("#/texts/2", "die Seite hinaus.", 10))
    assert (el.pages, el.source_refs, el.content_text) == ([9, 10], ["#/texts/1", "#/texts/2"], "Der Text läuft über die Seite hinaus.")  # fmt: skip
    assert el.original_text == "(1) Der Text läuft über\ndie Seite hinaus."
    assert [p.page_no for p in el.provenance] == [9, 10] and not el.highlight_boxes and not el.source_spans


def test_extend_with_exact_partial_pieces_draws_exact_rectangles_on_both_pages():
    first = source("#/texts/1", "(1) Der Text läuft über", 9, span=(0, 23), boxes=[box(9, 100, 80)])
    b, el = builder_with(first)
    assert el.highlight_boxes and el.source_spans  # `add` recorded the partial piece with its exact rectangles
    b.extend(el, source("#/texts/2", "die Seite hinaus.", 10, span=(0, 17), boxes=[box(10, 780, 760)]))
    assert [(h.page_no, h.bbox.t) for h in el.highlight_boxes] == [(9, 100), (10, 780)]
    assert [(s.ref, s.start, s.end) for s in el.source_spans] == [("#/texts/1", 0, 23), ("#/texts/2", 0, 17)]


def test_extend_whole_first_item_with_partial_continuation_keeps_exact_boxes():
    b, el = builder_with(source("#/texts/1", "(1) Der Text läuft über", 9))
    b.extend(el, source("#/texts/2", "die Seite hinaus. (2) Neu", 10, span=(0, 17), boxes=[box(10, 780, 760)]))
    assert [h.page_no for h in el.highlight_boxes] == [9, 10]
    assert [s.ref for s in el.source_spans] == ["#/texts/1", "#/texts/2"] and el.source_spans[0].end == len("(1) Der Text läuft über")  # fmt: skip


def test_extend_without_exact_boxes_falls_back_to_the_provenance_boxes():
    first = source("#/texts/1", "(1) Der Text läuft über", 9, span=(0, 23), boxes=[box(9, 100, 80)])
    b, el = builder_with(first)
    assert el.highlight_boxes and el.source_spans  # `add` recorded the partial piece with its exact rectangles
    b.extend(el, source("#/texts/2", "die Seite hinaus.", 10, span=(0, 17)))  # partial item, no exact rectangles
    assert el.highlight_boxes == [] and [p.page_no for p in el.provenance] == [9, 10]  # viewer draws the item boxes, approximate


# ---- the decision rule itself -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text, closed", [
    ("Das gilt nicht.", True), ("Wie folgt:", True), ("Fall a;", True), ("gemäß Abs.", False), ("im Sinne von z. B.", False),
    ("nach Absatz 1", False), ("und dann,", False), ("Er sagte „Ja.“", True), ("", True),
])  # fmt: skip
def test_sentence_end_detection(text, closed):
    assert continuation._is_closed(text) is closed


@pytest.mark.parametrize("text, expected", [("und", "dangling_word"), ("Gebäuden,", "comma"), ("Brand-", "hyphen"), ("Gebäude", None), ("Ausdruck", None)])  # fmt: skip
def test_open_phrase_detection(text, expected):
    assert continuation._open_phrase(text) == expected


def test_page_furniture_is_found_by_both_recognizers_when_docling_labelled_it_as_text(tmp_path):
    for mode, items, pages in (("german_law", par6(), 10), ("eu_legislation", eu_items(), 8)):
        model = parse(tmp_path, mode, pages, items, "text")
        assert all(not (e.content_text.strip().isdigit() and e.region == "body") for e in model.elements), mode
        assert all(f.type in (T.PAGE_FOOTER, T.PAGE_HEADER) for f in model.furniture), mode
