"""EU parser structure rules on small synthetic Official Journal layouts (no Docling, no PDF).

Each rule that resolves an ambiguity from source evidence (next marker, indentation, sequence, PDF text layer)
is tested together with a counter-case in which the evidence is missing or conflicting: there the warning
or uncertainty must stay, so nothing is resolved without proof."""

from odos.normalization.docling_reader import SourceItem
from odos.parsing.profiles.eu_legislation.recognizer import parse_eu_items
from odos.normalization.hygiene import apply_hygiene
from odos.document_model import BoundingBox, ElementType as T, Provenance, SourceInfo
from odos.normalization.reading_order import TextLayerEvidence, TextLine, starts_visual_line

MARGIN = 68.0
PREAMBLE = [
    ("DAS EUROPÄISCHE PARLAMENT UND DER RAT DER EUROPÄISCHEN UNION —", 0),
    ("in Erwägung nachstehender Gründe:", 0),
    ("(1) Ein Erwägungsgrund.", 0),
    ("HABEN FOLGENDE VERORDNUNG ERLASSEN:", 0),
]
ARTICLE = [("Artikel 1", "head"), ("Gegenstand", "head")]
ANNEX = [*ARTICLE, ("(1) Ein Absatz.", 0), ("ANHANG I", "head"), ("Anforderungen", "head")]


def _items(lines) -> list[SourceItem]:
    """lines: (text, indent in pt from the margin | "head" for a centred section header | ("text", l, r))."""
    out = []
    for n, (text, x) in enumerate([*PREAMBLE, *lines]):
        if isinstance(x, tuple):
            label, l, r = x
        else:
            label, l, r = ("section_header", 275.0, 320.0) if x == "head" else ("text", MARGIN + x, 528.0)
        top = 820.0 - 12 * n
        prov = [Provenance(page_no=1, bbox=BoundingBox(l=l, t=top, r=r, b=top - 10, coord_origin="BOTTOMLEFT"), charspan=(0, len(text)))]  # fmt: skip
        out.append(SourceItem(ref=f"#/texts/{n}", label=label, layer="body", orig=text, text=text, provenance=prov))
    return out


def parse(lines):
    m = parse_eu_items(SourceInfo(docling_json_sha256="0", num_pages=1), _items(lines), {1: (595.0, 842.0)})
    return m, m.by_id()


def kids(idx, eid):
    return [idx[c].id.rsplit("/", 1)[1] for c in idx[eid].children_ids]


def codes(m):
    return [w.code for w in m.warnings]


def letters(upto: str, x=0):
    return [(f"{c}) Begriff {c};", x) for c in "abcdefgh"[: "abcdefgh".index(upto) + 1]]


PARA = "doc/art-1/para-1"


# ---- "i)" after "h)": letter or roman numeral ----------------------------------------------------------------------------
def test_i_after_h_is_a_letter_by_column_and_next_marker():
    m, idx = parse([*ARTICLE, ("(1) Im Sinne dieser Verordnung bezeichnet der Ausdruck:", 0), *letters("h"),
                    ("i) Begriff i;", 0), ("j) Begriff j.", 0)])  # fmt: skip
    assert kids(idx, PARA) == [f"pt-{c}" for c in "abcdefghij"]
    i = idx[f"{PARA}/pt-i"]
    assert i.type == T.POINT and not i.uncertain and "point_kind_decided_by_layout:alpha" in i.hygiene_flags
    assert m.warnings == []


def test_i_after_h_is_a_roman_subpoint_when_indented_and_followed_by_ii():
    m, idx = parse([*ARTICLE, ("(1) Es gilt:", 0), *letters("h"), ("i) erste Unterposition;", 12), ("ii) zweite Unterposition.", 12)])  # fmt: skip
    assert kids(idx, f"{PARA}/pt-h") == ["sub-i", "sub-ii"]
    sub = idx[f"{PARA}/pt-h/sub-i"]
    assert sub.type == T.SUBPOINT and "point_kind_decided_by_layout:roman" in sub.hygiene_flags and m.warnings == []


def test_conflicting_evidence_keeps_the_ambiguity_warning():
    # same column as "h)" (-> letter) but followed by "ii)" (-> roman): not decidable, so not decided
    m, idx = parse([*ARTICLE, ("(1) Es gilt:", 0), *letters("h"), ("i) Unklar;", 0), ("ii) zweite Unterposition.", 12)])
    i = idx[f"{PARA}/pt-i"]
    assert i.uncertain and "roman_or_alphabetic_ambiguous" in i.uncertainty_reasons
    w = next(w for w in m.warnings if w.code == "ROMAN_ALPHA_AMBIGUOUS")
    assert w.element_id == i.id and w.category == "needs_review"  # linked to its element, classified


# ---- text between points: placed by indentation --------------------------------------------------------------------------
def test_indented_text_is_a_body_paragraph_of_the_point_and_list_continues():
    m, idx = parse([*ARTICLE, ("(1) Die Hersteller:", 0), ("a) stellen sicher, dass die Maschine sicher ist.", 0),
                    ("Dieser Unterabsatz gehört zu Buchstabe a.", 12), ("b) erstellen die Unterlagen.", 0),
                    ("Der Schlusssatz gilt für alle Buchstaben.", 0)])  # fmt: skip
    assert kids(idx, PARA) == ["pt-a", "pt-b", "txt-1"]  # one list a), b); the closing text after it
    assert kids(idx, f"{PARA}/pt-a") == ["txt-1"]
    assert "attached_by_indentation" in idx[f"{PARA}/pt-a/txt-1"].hygiene_flags
    assert "container_text_by_indentation" in idx[f"{PARA}/txt-1"].hygiene_flags
    assert m.warnings == [] and not any(e.uncertain for e in m.elements)


def test_text_between_the_columns_keeps_the_interrupted_list_warning():
    m, idx = parse([*ARTICLE, ("(1) Die Hersteller:", 0), ("a) stellen sicher, dass die Maschine sicher ist.", 0),
                    ("Diese Zeile steht zwischen den Spalten.", 4), ("b) erstellen die Unterlagen.", 0)])  # fmt: skip
    assert kids(idx, PARA) == ["pt-a", "txt-1", "pt-b"]
    assert "text_between_points_of_one_list" in idx[f"{PARA}/txt-1"].uncertainty_reasons
    assert codes(m) == ["LIST_INTERRUPTED"]


# ---- roman list introduced by a text line ----------------------------------------------------------------------------------
def test_roman_list_introduced_by_text_is_a_valid_structure():
    m, idx = parse([*ARTICLE, ("(1) Erster Satz.", 0), ("Die Betreiber prüfen zumindest", 0),
                    ("i) die Schutzeinrichtungen;", 0), ("ii) die Steuerung.", 0)])  # fmt: skip
    assert kids(idx, PARA) == ["txt-1", "sub-i", "sub-ii"]
    assert all(idx[f"{PARA}/{s}"].type == T.SUBPOINT and not idx[f"{PARA}/{s}"].uncertain for s in ("sub-i", "sub-ii"))
    assert m.warnings == []
    assert [(n.code, n.element_id, n.category) for n in m.structure_notes] == [("ROMAN_LIST_INTRODUCED_BY_TEXT", f"{PARA}/sub-i", "valid_structure")]  # fmt: skip


def test_roman_list_after_a_complete_sentence_stays_a_warning():
    m, idx = parse([*ARTICLE, ("(1) Erster Satz.", 0), ("Die Betreiber prüfen Folgendes.", 0), ("i) die Schutzeinrichtungen.", 0)])
    assert "point_sequence_unclear" in idx[f"{PARA}/sub-i"].uncertainty_reasons
    assert "POINT_SEQUENCE" in codes(m) and m.structure_notes == []


def test_parenthesised_marker_confirmed_by_the_letter_sequence():
    m, idx = parse([*ARTICLE, ("(1) Es gilt:", 0), ("k) erstens;", 0), ("(l) zweitens;", 0), ("m) drittens.", 0)])
    lp = next(e for e in m.elements if e.marker == "(l)")
    assert lp.type == T.POINT and not lp.uncertain and "point_marker_in_parentheses" in lp.hygiene_flags
    assert [n.code for n in m.structure_notes] == ["PARENTHESISED_POINT_MARKER"]


def test_parenthesised_marker_without_the_sequence_stays_uncertain():
    m, idx = parse([*ARTICLE, ("(1) Es gilt:", 0), ("k) erstens;", 0), ("(l) zweitens.", 0)])  # no "m)" after it
    lp = next(e for e in m.elements if e.marker == "(l)")
    assert lp.uncertain and "point_marker_in_parentheses" in lp.uncertainty_reasons and m.structure_notes == []


# ---- annexes ------------------------------------------------------------------------------------------------------------------
def test_numbered_paragraphs_in_an_annex():
    m, idx = parse([*ANNEX, ("(1) Auf jeder Maschine sind anzugeben:", 0), ("a) der Name;", 0), ("b) die Anschrift.", 0),
                    ("(2) Zusätzlich sind anzugeben:", 0), ("a) die Baureihe;", 0), ("b) das Baujahr.", 0)])  # fmt: skip
    assert kids(idx, "doc/annex-1") == ["para-1", "para-2"]
    assert kids(idx, "doc/annex-1/para-1") == kids(idx, "doc/annex-1/para-2") == ["pt-a", "pt-b"]
    assert idx["doc/annex-1/para-2"].type == T.ARTICLE_PARAGRAPH and m.warnings == []


def test_a_lone_parenthesised_number_in_an_annex_is_not_a_paragraph():
    m, idx = parse([*ANNEX, ("(1) Dieser Anhang gilt für alle Maschinen.", 0)])  # no "(2)": no paragraph sequence
    assert not any(e.type == T.ARTICLE_PARAGRAPH and e.id.startswith("doc/annex-1") for e in m.elements)


def test_untitled_part_followed_by_body_text_is_a_note_not_a_warning():
    m, idx = parse([*ANNEX, ("TEIL A", "head"), ("Die folgenden Anforderungen gelten für alle Maschinen:", 0),
                    ("TEIL B", "head"), ("Allgemeines", ("text", 270.0, 325.0))])  # fmt: skip
    assert idx["doc/annex-1/part-a"].title is None  # nothing invented
    assert [(n.code, n.element_id) for n in m.structure_notes] == [("UNTITLED_HEADING", "doc/annex-1/part-a")]
    # TEIL B: the next line is centred like a title and is not a sentence, so a lost title cannot be excluded
    assert [(w.code, w.element_id) for w in m.warnings] == [("HEADING_WITHOUT_TITLE", "doc/annex-1/part-b")]


def test_numbered_annex_headings_confirmed_by_sub_numbering_and_siblings():
    m, idx = parse([*ANNEX, ("1. Allgemeine Bestimmungen", 0), ("1.1. Anwendungsbereich", 0), ("Ein Satz.", 0),
                    ("2. Technische Unterlagen", 0), ("Die Unterlagen enthalten Angaben.", 0)])  # fmt: skip
    h1, h2 = idx["doc/annex-1/h-1"], idx["doc/annex-1/h-2"]
    assert not h1.uncertain and "numbered_heading_confirmed_by:sub_numbering" in h1.hygiene_flags
    assert not h2.uncertain and "numbered_heading_confirmed_by:sibling_headings" in h2.hygiene_flags


def test_numbered_annex_heading_without_evidence_stays_uncertain():
    m, idx = parse([*ANNEX, ("1. Prüfverfahren", 0), ("Die Prüfung wird dokumentiert.", 0)])
    assert "numbered_line_read_as_heading" in idx["doc/annex-1/h-1"].uncertainty_reasons


def test_new_numbered_sequence_of_another_kind_is_a_note():
    m, idx = parse([*ANNEX, ("1. Der Hersteller erstellt die Unterlagen.", 0), ("2. Der Hersteller bewahrt sie auf.", 0),
                    ("1. KONFORMITÄTSBEWERTUNG", 0), ("Ein Satz.", 0)])  # fmt: skip
    assert "SEQUENCE_BREAK" not in codes(m)
    assert [n.code for n in m.structure_notes] == ["NEW_NUMBERED_SEQUENCE"]


def test_restarted_list_of_the_same_kind_gets_its_own_run():
    m, idx = parse([*ANNEX, ("1. Der Hersteller erstellt die Unterlagen.", 0), ("2. Der Hersteller bewahrt sie auf.", 0),
                    ("1. Der Hersteller meldet Vorfälle.", 0)])  # fmt: skip
    assert kids(idx, "doc/annex-1") == ["pt-1", "pt-2", "run2-pt-1"] and m.warnings == []


def test_gap_in_a_numbering_is_still_a_sequence_break():
    m, idx = parse([*ANNEX, ("1. Der Hersteller erstellt die Unterlagen.", 0), ("2. Der Hersteller bewahrt sie auf.", 0),
                    ("4. Der Hersteller meldet Vorfälle.", 0)])  # fmt: skip
    assert codes(m) == ["SEQUENCE_BREAK"] and idx["doc/annex-1/pt-4"].uncertain and m.structure_notes == []


def test_numbered_paragraph_continuing_the_heading_numbering():
    m, idx = parse([*ANNEX, ("1. ALLGEMEINES", 0), ("Ein Satz.", 0), ("2. Der Hersteller trägt die Verantwortung.", 0)])
    p2 = idx["doc/annex-1/pt-2"]
    assert p2.type == T.NUMBERED_POINT and p2.parent_id == "doc/annex-1" and not p2.uncertain
    assert [(n.code, n.element_id) for n in m.structure_notes] == [("NUMBERED_PARAGRAPH_CONTINUES_HEADINGS", p2.id)]
    assert m.warnings == []


# ---- split boundaries verified by the PDF text layer -------------------------------------------------------------------------
SPLIT = "(1) Der Hersteller prüft, ob a) die Maschine den Anforderungen entspricht; b) die Unterlagen vollständig sind. (2) Er bewahrt sie auf."  # fmt: skip


def _split_item():
    prov = [Provenance(page_no=1, bbox=BoundingBox(l=68, t=500, r=528, b=460, coord_origin="BOTTOMLEFT"), charspan=(0, len(SPLIT)))]  # fmt: skip
    return SourceItem(ref="#/texts/1", label="text", layer="body", orig=SPLIT, text=SPLIT, provenance=prov)


def _evidence(*lines):
    return TextLayerEvidence(pdf_sha256="0", docling_json_sha256="0", extractor="pypdfium2 (test)",
                             pages={1: [TextLine(top=500 - 10 * i, bottom=491 - 10 * i, left=68, right=528, text=t) for i, t in enumerate(lines)]})  # fmt: skip


def test_split_boundary_verified_when_the_segment_starts_a_pdf_line():
    lines = ("(1) Der Hersteller prüft, ob", "a) die Maschine den Anforderungen entspricht;",
             "b) die Unterlagen vollständig sind.", "(2) Er bewahrt sie auf.")  # fmt: skip
    res = apply_hygiene([_split_item()], {1: (595.0, 842.0)}, _evidence(*lines))
    a = next(d for d in res.items if d.orig.startswith("a)"))
    assert a.boundary_flags == [] and "segment_boundary_verified_by_pdf_text_layer" in a.hygiene_flags
    assert "".join(d.orig for d in res.items).replace(" ", "") == SPLIT.replace(" ", "")  # text unchanged


def test_split_boundary_stays_uncertain_without_line_evidence():
    # the PDF line runs on through "ob a) …": the marker does not start a line, so nothing is proven
    lines = ("(1) Der Hersteller prüft, ob a) die Maschine den", "Anforderungen entspricht; b) die Unterlagen")
    for ev in (None, _evidence(*lines)):
        a = next(d for d in apply_hygiene([_split_item()], {1: (595.0, 842.0)}, ev).items if d.orig.startswith("a)"))
        assert a.boundary_flags == ["point_marker_without_preceding_punctuation"]
        assert "segment_boundary_verified_by_pdf_text_layer" not in a.hygiene_flags


def test_starts_visual_line_needs_a_long_enough_prefix():
    ev = _evidence("a) die Maschine den Anforderungen entspricht;")
    assert starts_visual_line(ev, 1, "a) die Maschine den Anforderungen entspricht; b) …")
    assert not starts_visual_line(ev, 1, "a) die")  # too short to prove anything
    assert not starts_visual_line(ev, 2, "a) die Maschine den Anforderungen entspricht;")  # no lines for that page
    assert not starts_visual_line(None, 1, "a) die Maschine den Anforderungen entspricht;")
