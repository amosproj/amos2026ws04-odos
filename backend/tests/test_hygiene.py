"""Shared extraction-hygiene layer: segment splitting, partial-item provenance, search text, running headers."""

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import pytest

from odos.normalization.docling_reader import SourceItem, read_docling_json, read_page_sizes
from odos.normalization.hygiene import apply_hygiene, check_accounting, search_normalize, segment_item
from odos.document_model import BoundingBox, ElementType as T, Provenance, SourceInfo
from odos.parsing import parse_document
from odos.parsing.profiles.german_law.recognizer import parse_items
from odos.parsing.profiles.german_law.rules import GERMAN_LAW_RULES

# Docling items of the partner's EU PDF (partner-derived, not in Git): tests/fixtures/private/ is gitignored
FIXTURE = Path(__file__).parent / "fixtures" / "private" / "eu_2023_1230_hygiene_items.json"
BACKEND = Path(__file__).resolve().parents[1]

# the five Docling items of Regulation (EU) 2023/1230 that hold several paragraphs (Art. 10, 11, 14, 15, 16)
MERGED = {
    "#/texts/369": ["(9)", "(10)"],
    "#/texts/373": ["(1)", "(2)", "(3)", "(4)", "(5)", "(6)", "(7)"],
    "#/texts/416": ["(1)", "(2)"],
    "#/texts/443": ["(5)", "(6)"],
    "#/texts/447": ["(1)", "(2)", "a)", "b)", "c)", "(3)", "(4)", "(5)", "(6)"],
}
LEAD = re.compile(r"^(\(\d+[a-z]?\)|[a-z]\))")


@pytest.fixture(scope="module")
def eu():
    if not FIXTURE.is_file():
        pytest.skip("partner-derived fixture tests/fixtures/private/eu_2023_1230_hygiene_items.json not available (gitignored)")
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    items = [SourceItem.model_validate(x) for x in data["items"]]
    return items, {int(k): tuple(v) for k, v in data["page_sizes"].items()}


@pytest.fixture(scope="module")
def eu_result(eu):
    items, sizes = eu
    return apply_hygiene(items, sizes)


def by_ref(result):
    out = {}
    for d in result.items:
        out.setdefault(d.ref, []).append(d)
    return out


# ---- the five merged EU items --------------------------------------------------------------------------------
@pytest.mark.parametrize("ref,markers", MERGED.items())
def test_merged_items_are_split_into_exact_spans(eu, eu_result, ref, markers):
    item = next(i for i in eu[0] if i.ref == ref)
    segs = by_ref(eu_result)[ref]
    assert [LEAD.match(s.orig).group(1) for s in segs] == markers
    assert [s.segment_index for s in segs] == list(range(len(markers))) and {s.segment_count for s in segs} == {len(markers)}  # fmt: skip
    pos = 0
    for s in segs:
        a, b = s.span
        assert s.orig == item.orig[a:b]  # exact slice of the untouched Docling text
        assert item.orig[pos:a].strip() == "" and a >= pos  # only whitespace between segments
        assert s.orig == s.orig.strip()
        assert s.provenance[0].charspan == (a, b)
        assert s.provenance[0].page_no == item.provenance[0].page_no and s.provenance[0].bbox == item.provenance[0].bbox
        assert s.ref == ref and s.label == item.label and "split_from_merged_docling_item" in s.hygiene_flags
        pos = b
    assert item.orig[pos:].strip() == ""


def test_counts_and_accounting(eu, eu_result):
    r = eu_result.report
    assert [s["ref"] for s in r["split_items"]] == list(MERGED)
    assert r["segments_from_split_items"] == 22 and r["derived_items"] == r["docling_items"] + 22 - 5
    assert r["accounting"] == {"ok": True, "problems": []}
    assert check_accounting(eu[0], eu_result.items)["ok"]


def test_docling_items_are_not_modified(eu):
    items, sizes = eu
    before = [i.model_dump() for i in items]
    apply_hygiene(items, sizes)
    assert [i.model_dump() for i in items] == before


def test_uncertain_boundary_is_marked_only_where_ambiguous(eu_result):
    segs = by_ref(eu_result)["#/texts/447"]
    flags = {LEAD.match(s.orig).group(1): s.boundary_flags for s in segs}
    assert flags["a)"] == ["point_marker_without_preceding_punctuation"]  # Art. 16 (2): "... überprüfen die Händler, ob a) ..."
    assert all(flags[m] == [] for m in flags if m != "a)")
    assert segs[1].orig.endswith(", ob") and segs[2].orig.startswith("a) der unvollständigen Maschine")
    assert eu_result.report["uncertain_boundaries"] == 1


def test_markers_of_later_segments_are_derived_and_flagged(eu_result):
    segs = by_ref(eu_result)["#/texts/447"]
    assert segs[0].marker == "(1)"  # Docling's own marker field (list_item)
    assert segs[1].marker == "(2)" and "marker_derived_from_text" in segs[1].hygiene_flags
    assert "marker_derived_from_text" not in segs[0].hygiene_flags


def test_items_without_embedded_paragraphs_stay_whole(eu, eu_result):
    whole = [d for d in eu_result.items if d.ref not in MERGED]
    assert all(d.span is None and d.segment_count == 1 for d in whole)
    src = {i.ref: i for i in eu[0]}
    assert all(d.orig == src[d.ref].orig for d in whole)
    recitals = [d for d in whole if d.ref in {f"#/texts/{n}" for n in range(18, 23)}]
    assert len(recitals) == 5  # "(1)".."(5)" lead their own item and are not split


# ---- running headers ---------------------------------------------------------------------------------------------
def test_running_headers_are_flagged_not_removed(eu, eu_result):
    items = eu_result.items
    assert len(items) == len(eu[0]) + 17  # nothing dropped
    leaked = [d for d in items if "furniture_labelled_as_body_by_docling" in d.hygiene_flags]
    assert len(leaked) == 21 and {d.label for d in leaked} == {"text"}
    assert {d.orig.strip() for d in leaked} <= {"DE", "L 165/20", "L 165/24", "29.6.2023"}
    assert eu_result.report["running_furniture"]["labelled_as_body_by_docling"] == sorted((d.ref for d in leaked), key=lambda r: int(r.rsplit("/", 1)[1]))  # fmt: skip
    headers = [d for d in items if d.label == "page_header"]
    assert sum("running_header" in d.hygiene_flags for d in headers) == 315  # 3 merged header lines repeat too rarely
    body = [d for d in items if d.label in ("text", "list_item") and "furniture_labelled_as_body_by_docling" not in d.hygiene_flags]  # fmt: skip
    assert not any(f in d.hygiene_flags for d in body for f in ("running_header", "running_footer"))
    assert not any("running_footer" in d.hygiene_flags for d in items if d.label == "footnote")


# ---- search text --------------------------------------------------------------------------------------------------
def test_search_text_is_derived_and_original_kept(eu_result):
    soft = [d for d in eu_result.items if "\xad" in d.orig]
    assert soft and all(d.search_text and "\xad" not in d.search_text and "soft_hyphen_removed" in d.hygiene_flags for d in soft)  # fmt: skip
    spaced = [d for d in eu_result.items if "letter_spacing_collapsed" in d.hygiene_flags]
    assert any(d.search_text.startswith("1.2.4.1. NormalesStillsetzen") for d in spaced)
    assert all(" " in d.orig for d in spaced)  # originals keep their spacing


@pytest.mark.parametrize("raw,expected,flag", [
    ("Mitglied\xad staaten", "Mitgliedstaaten", "soft_hyphen_removed"),
    ("des Rates ( 3 ) wurde", "des Rates (3) wurde", "spaced_reference_compacted"),
    ("1.2.4.1. B e i s p i e l t e x t", "1.2.4.1. Beispieltext", "letter_spacing_collapsed"),
    ("a  b\n c ", "a b c", "whitespace_normalised"),
])  # fmt: skip
def test_search_normalize(raw, expected, flag):
    out, flags = search_normalize(raw)
    assert out == expected and flag in flags


def test_search_normalize_leaves_legal_tokens_alone():
    for s in ("§ 16a Bauarten", "(1) 1 Dieses Gesetz gilt.", "Artikel 11 Absatz 8", "a) b) c)"):
        assert search_normalize(s)[0] == s


# ---- negative controls and edge cases (synthetic) --------------------------------------------------------------------
def _it(orig, label="text", marker=None, prov=None):
    return SourceItem(ref="#/texts/1", label=label, layer="body", orig=orig, text=orig, marker=marker,
                      provenance=prov or [Provenance(page_no=1, charspan=(0, len(orig)))])  # fmt: skip


@pytest.mark.parametrize("orig", [
    "(1) 1 Dieses Gesetz gilt für bauliche Anlagen. 2 Es gilt auch für Grundstücke.",  # German Satz numbers
    "(1) Es gilt Absatz 3. (3) bleibt unberührt.",  # does not continue the numbering
    "Siehe Artikel 5. (2) Satz 1 gilt.",  # a single embedded marker without a leading one
    "(2) Die Buchstaben a) und b) gelten entsprechend.",  # references, not a list
])  # fmt: skip
def test_no_split_for_non_merged_text(orig):
    assert [(s.start, s.end) for s in segment_item(_it(orig))] == [(0, len(orig))]


def test_split_without_leading_marker_is_uncertain():
    segs = segment_item(_it("Satz. (2) Erster. (3) Zweiter."))
    assert [s.marker for s in segs] == [None, "(2)", "(3)"]
    assert segs[1].boundary_flags == ["item_has_no_leading_paragraph_marker"]


def test_lowercase_after_marker_is_uncertain():
    segs = segment_item(_it("(1) Erster Satz. (2) und weiter."))
    assert segs[1].boundary_flags == ["text_after_marker_not_capitalised"]


def test_headers_footnotes_and_furniture_are_never_split():
    for label in ("section_header", "footnote", "page_header", "caption"):
        assert len(segment_item(_it("(1) Eins. (2) Zwei.", label=label))) == 1


def test_multi_page_item_spans_map_to_the_right_page():
    orig = "(1) Erster Absatz steht hier. (2) Zweiter Absatz auf Seite zwei."
    bb = BoundingBox(l=0, t=10, r=10, b=0, coord_origin="BOTTOMLEFT")
    item = _it(orig, prov=[Provenance(page_no=1, bbox=bb, charspan=(0, 30)), Provenance(page_no=2, bbox=bb, charspan=(30, len(orig)))])  # fmt: skip
    res = apply_hygiene([item], {1: (100, 100), 2: (100, 100)})
    first, second = res.items
    assert first.pages == [1] and second.pages == [2]
    assert second.provenance[0].charspan == (second.span[0], len(orig))
    assert res.report["accounting"]["ok"]


def test_parser_keeps_partial_provenance_on_elements():
    orig = "(1) Erster Absatz. (2) Zweiter Absatz."
    items = [
        SourceItem(ref="#/texts/0", label="section_header", layer="body", orig="§ 1 Titel", text="§ 1 Titel", provenance=[Provenance(page_no=1, charspan=(0, 9))]),  # fmt: skip
        _it(orig),
    ]
    derived = apply_hygiene(items, {1: (100, 100)}).items
    m = parse_items(SourceInfo(docling_json_sha256="0", num_pages=1), derived, GERMAN_LAW_RULES)
    a1, a2 = m.by_id()["doc/par-1/abs-1"], m.by_id()["doc/par-1/abs-2"]
    assert a1.source_refs == a2.source_refs == ["#/texts/1"]
    assert (a1.source_spans[0].start, a1.source_spans[0].end) == (0, 18) and a1.original_text == "(1) Erster Absatz."
    assert a2.original_text == orig[a2.source_spans[0].start : a2.source_spans[0].end] == "(2) Zweiter Absatz."
    assert a2.source_spans[0].bbox_scope == "docling_item" and a2.provenance[0].charspan == (19, len(orig))
    whole = m.by_id()["doc/par-1"]
    assert whole.source_spans == [] and "source_spans" not in json.loads(whole.model_dump_json())  # omitted when empty


# ---- full EU document (skips with the reason when Regulation (EU) 2023/1230 is not available) -----------------------
def test_full_eu_document_accounting(eu_raw_json):
    path = eu_raw_json
    _, items = read_docling_json(path)
    res = apply_hygiene(items, read_page_sizes(path))
    assert [s["ref"] for s in res.report["split_items"]] == list(MERGED)  # exactly the five, nothing else
    assert res.report["accounting"]["ok"] and len(res.report["running_furniture"]["labelled_as_body_by_docling"]) == 21
    from odos.parsing.profiles.german_law.report import build_report

    from odos.normalization.reading_order import load_evidence

    model = parse_document(path, "german_law")
    rep = build_report(model, path)
    assert not rep.docling_items_missing and not rep.docling_items_duplicated and not rep.text_mismatches
    # with the upload's PDF text-layer evidence, the Art. 47 items repaired from it are slices of Docling items too
    repaired = ["#/texts/745", "#/texts/746", "#/texts/747", "#/texts/748"] if load_evidence(path) else []
    assert [s["ref"] for s in rep.segmented_items] == [*MERGED, *repaired] and all(s["tiles_item_exactly"] for s in rep.segmented_items)  # fmt: skip


# ---- BDSG and MBO stay stable ----------------------------------------------------------------------------------------------
# Pinned before the hygiene layer existed (same Docling JSON). New derived fields are excluded from the model hash.
# Model and full-XML hashes changed with the PDF text-layer restoration (Docling's dropped line-end hyphens and
# ASCII quotes/dashes restored, page numbers out of the structure, evidenced footnote anchors). The BDSG § 1-2
# excerpt contains no repaired character and is unchanged.
# Then: sentences, TOC entries and table-cell boxes added to the model (annotations only: BDSG XML unchanged); MBO XML
# changed only where 14 footnotes became proven from their reference marks and lost their odos:uncertain attribute.
PINNED = {
    "bdsg": {"raw": "dd49591bfd8dab883a86c173dfbf93ca188fc0ed3685b569d718972614ef8ba0",
             "model": "391d99def0d7b1a89c4f9dac267815e44b153ea297f6fadface9841926a5476b",
             "xml_excerpt": "0e7a7141ecbb643637a4488636acc33bc15e26b04c5474b9158f14c44f222019",
             "xml_full": "232e7818cc097a224c507564928fd83898b07da532027a3383bc43a158bb2670"},
    "mbo": {"raw": "1c5ec2ab2c7b0330d274890b4f2fe654676f8b1ddd99691d369678ee7d585632",
            "model": "bd6f345e394d9d16f2029c8d6edf03faa56dfc6f22d53fde0509a79bd1d2a504",
            "xml_full": "d99b7dc2cb1d510d16dceec327ffde433d709d9adf96023446159c6408b146a0"},
}  # fmt: skip
NEW_FIELDS = {"source_spans", "search_text", "hygiene_flags"}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.mark.parametrize("name", ["bdsg", "mbo"])
def test_existing_documents_are_unchanged(name, raw_json, mbo_raw_json):
    from odos.akn.generator import generate_excerpt

    path = raw_json if name == "bdsg" else mbo_raw_json
    if _sha(path.read_bytes()) != PINNED[name]["raw"]:
        pytest.skip("Docling output differs from the pinned extraction on this machine; hashes not comparable")
    m = parse_document(path, "german_law")
    excl = {"elements": {"__all__": NEW_FIELDS}, "furniture": {"__all__": NEW_FIELDS}}
    assert _sha(m.model_dump_json(exclude=excl).encode()) == PINNED[name]["model"]
    allp = [e.number for e in m.of_type(T.PARAGRAPH)]
    if name == "bdsg":
        assert _sha(generate_excerpt(m, ["1", "2"], "2026-10-27").xml) == PINNED[name]["xml_excerpt"]
        assert _sha(generate_excerpt(m, allp, "2026-10-27").xml) == PINNED[name]["xml_full"]
    else:
        assert _sha(generate_excerpt(m, allp, "2026-10-27", undated_policy="processing_date").xml) == PINNED[name]["xml_full"]
    assert not any(e.source_spans for e in m.elements)  # nothing split


def test_additive_hygiene_annotations_on_existing_documents(model, mbo_model):
    flags = lambda m: Counter(f for e in [*m.elements, *m.furniture] for f in e.hygiene_flags)  # noqa: E731
    assert flags(model) == {"running_header": 45, "running_footer": 45, "letter_spacing_collapsed": 17,
                            "enumeration_closing_clause_confirmed": 9, "text_restored_from_pdf_text_layer": 21,
                            "sentence_interlaced_list_restart": 1, "sentence_interlaced_list_continuation": 1}
    assert flags(mbo_model) == {"running_footer": 83, "furniture_labelled_as_body_by_docling": 6,
                                "moved_out_of_structure_as_page_furniture": 6, "text_restored_from_pdf_text_layer": 25,
                                "footnote_anchor_from_pdf_reference_mark": 35, "footnote_recognised_from_pdf_reference_mark": 1,
                                "title_taken_from_next_header_line": 5, "text_after_list_satz_n_confirmed": 36,
                                "numbered_item_labelled_section_header_by_docling_confirmed": 5,
                                "text_after_colon_ending_nummer_confirmed": 4,
                                "absatz_labelled_section_header_by_docling_confirmed": 2,
                                "enumeration_closing_clause_confirmed": 21,
                                "unmarked_list_item_satz_n_confirmed": 4,
                                "sentence_interlaced_list_restart": 15, "sentence_interlaced_list_continuation": 27}
    leaked = [e for e in mbo_model.furniture if "furniture_labelled_as_body_by_docling" in e.hygiene_flags]
    assert all(e.original_text.strip() == str(e.pages[0]) for e in leaked) and len(leaked) == 6  # page numbers labelled as text
    assert not [e for e in mbo_model.elements if "furniture_labelled_as_body_by_docling" in e.hygiene_flags]  # none left in the tree


# ---- overlapping layout boxes: unreliable reading order ----------------------------------------------------------------------
def _item(ref, text, l, t, r, b, label="text", page=1):
    prov = [Provenance(page_no=page, bbox=BoundingBox(l=l, t=t, r=r, b=b, coord_origin="BOTTOMLEFT"), charspan=(0, len(text)))]
    return SourceItem(ref=ref, label=label, layer="body", orig=text, text=text, provenance=prov)


def test_overlapping_body_boxes_are_flagged_and_kept():
    items = [
        _item("#/texts/1", "(1) Erster Absatz, dessen letzte Zeile fehlt", 68, 260, 528, 250),
        _item("#/texts/2", "(2) Zweiter Absatz, dessen letzte Zeile fehlt", 68, 229, 529, 179),
        _item("#/texts/3", "Bedingungen übertragen. Zeitraums.", 68, 248, 163, 95),  # line ends cut out of (1)-(2)
        _item("#/texts/4", "(3) Danach, ohne Überlappung", 68, 84, 528, 55),
        _item("#/texts/5", "( 1 ) Fußnote", 68, 240, 300, 230, label="footnote"),  # footnotes do not count
    ]
    res = apply_hygiene(items, {1: (595.0, 842.0)})
    assert [o["refs"] for o in res.report["layout_overlaps"]] == [["#/texts/2", "#/texts/3"]]
    flagged = {i.ref for i in res.items if i.order_flags}
    assert flagged == {"#/texts/2", "#/texts/3"} and all("layout_box_overlap" in i.hygiene_flags for i in res.items if i.ref in flagged)
    assert [i.orig for i in res.items] == [i.orig for i in items]  # nothing changed, moved or dropped
    model = parse_items(SourceInfo(docling_json_sha256="0" * 64, num_pages=1), res.items, GERMAN_LAW_RULES)
    reasons = [r for e in model.elements for r in e.uncertainty_reasons if r.startswith("reading_order_uncertain")]
    assert reasons == ["reading_order_uncertain:layout_box_overlaps_other_item"] * 2


def test_layout_overlaps_in_the_reference_extractions(raw_json, mbo_raw_json, eu_raw_json):
    def overlaps(p):
        _, items = read_docling_json(p)
        return apply_hygiene(items, read_page_sizes(p)).report["layout_overlaps"]

    assert overlaps(raw_json) == [] and overlaps(mbo_raw_json) == []  # BDSG and MBO: nothing flagged, outputs unchanged
    # Regulation (EU) 2023/1230, Art. 47: the last lines of paragraphs (1)-(3) form one stray item (#/texts/748)
    assert [(o["page"], o["refs"]) for o in overlaps(eu_raw_json)] == [(36, ["#/texts/746", "#/texts/748"]), (36, ["#/texts/747", "#/texts/748"])]  # fmt: skip


# ---- German law parser: sentence-interlaced list restarts -------------------------------------------------------
def _gl_item(ref, text, label="text"):
    prov = [Provenance(page_no=1, bbox=BoundingBox(l=68, t=800, r=528, b=790, coord_origin="BOTTOMLEFT"), charspan=(0, len(text)))]
    return SourceItem(ref=ref, label=label, layer="body", orig=text, text=text, provenance=prov)


def _gl_parse(texts):
    items = [_gl_item(f"#/texts/{i}", t, "section_header" if t.startswith("§") or t.startswith("Teil") else "text")
             for i, t in enumerate(texts)]
    return parse_items(SourceInfo(docling_json_sha256="0" * 64, num_pages=1), items, GERMAN_LAW_RULES)


def test_sentence_interlaced_list_restart_gets_run_ids():
    """Pattern: § N (n) has lists '1. ... 2. ...' then Satz-N text then '1. ... 2. ...' again."""
    m = _gl_parse(["§ 1 Anwendungsbereich", "(1) Die Verordnung regelt:",
                    "1. feuerbeständig,", "2. rauchdicht.",
                    "3 Die Anforderungen gelten auch für:",
                    "1. Sonderbauten,", "2. Garagen."])
    idx = m.by_id()
    abs1 = "doc/par-1/abs-1"
    kids = [idx[c].id.rsplit("/", 1)[1] for c in idx[abs1].children_ids]
    assert kids == ["nr-1", "nr-2", "txt-1", "run2-nr-1", "run2-nr-2"]
    assert "sentence_interlaced_list_restart" in idx[f"{abs1}/run2-nr-1"].hygiene_flags
    assert "sentence_interlaced_list_continuation" in idx[f"{abs1}/run2-nr-2"].hygiene_flags
    assert not any(w.code == "DUPLICATE_ID_RESOLVED" for w in m.warnings)
    assert not any(w.code == "NUMMER_SEQUENCE" for w in m.warnings)


def test_direct_list_restart_without_text_between():
    """§66 Abs. 3 pattern: two lists back to back with no text between."""
    m = _gl_parse(["§ 1 Brandschutz", "(1) Es bedarf der Prüfung bei:",
                    "1. Gebäuden,", "2. wenn dies erforderlich ist,",
                    "1. Sonderbauten,", "2. Garagen,", "3. Gebäuden."])
    idx = m.by_id()
    abs1 = "doc/par-1/abs-1"
    kids = [idx[c].id.rsplit("/", 1)[1] for c in idx[abs1].children_ids]
    assert kids == ["nr-1", "nr-2", "run2-nr-1", "run2-nr-2", "run2-nr-3"]
    assert not any(w.code == "DUPLICATE_ID_RESOLVED" for w in m.warnings)


def test_satz_n_text_after_list_is_confirmed():
    """Text starting with Satz N (≥2) after a numbered list is not uncertain."""
    m = _gl_parse(["§ 1 Begriffe", "(1) Es gilt:",
                    "1. feuerbeständig,", "2. rauchdicht.",
                    "3 Satz 1 gilt auch für Sonderbauten."])
    txt = next(e for e in m.elements if e.type == T.TEXT)
    assert not txt.uncertain
    assert "text_after_list_satz_n_confirmed" in txt.hygiene_flags


def test_text_after_list_without_satz_n_stays_uncertain():
    """Plain text after a list that doesn't start with Satz N stays uncertain."""
    m = _gl_parse(["§ 1 Begriffe", "(1) Es gilt:",
                    "1. feuerbeständig,", "2. rauchdicht.",
                    "Dies gilt auch für andere Bauten."])
    txt = next(e for e in m.elements if e.type == T.TEXT)
    assert txt.uncertain
    assert "text_after_list_attached_to_enclosing_container" in txt.uncertainty_reasons


def test_colon_ending_nummer_text_is_confirmed():
    """Text under a Nummer ending with ':' is correctly placed (confirmed, not uncertain)."""
    m = _gl_parse(["§ 1 Kategorien", "(1) Es werden unterschieden:",
                    "1. Kategorie 1:", "Einzelobjekte."])
    colon_text = next(e for e in m.elements if e.original_text == "Einzelobjekte.")
    assert not colon_text.uncertain
    assert "text_after_colon_ending_nummer_confirmed" in colon_text.hygiene_flags


def test_title_from_next_line_is_confirmed():
    """Heading whose title is in the next Docling item is correct behavior, not a warning."""
    items = [_gl_item("#/texts/0", "Teil 1", "section_header"),
             _gl_item("#/texts/1", "Allgemeine Vorschriften", "section_header"),
             _gl_item("#/texts/2", "§ 1 Anwendungsbereich", "section_header"),
             _gl_item("#/texts/3", "(1) Text.", "text")]
    m = parse_items(SourceInfo(docling_json_sha256="0" * 64, num_pages=1), items, GERMAN_LAW_RULES)
    teil = next(e for e in m.elements if e.type == T.TEIL)
    assert teil.title == "Allgemeine Vorschriften"
    assert "title_taken_from_next_header_line" in teil.hygiene_flags
    assert not teil.uncertain
    assert not any(w.code == "TITLE_FROM_NEXT_LINE" for w in m.warnings)


def test_triple_restart_gets_run3_ids():
    """Three successive lists under the same Absatz."""
    m = _gl_parse(["§ 1 Test", "(1) Regeln:",
                    "1. A,", "2. B.",
                    "3 Satz 2:", "1. C,", "2. D.",
                    "4 Satz 3:", "1. E."])
    idx = m.by_id()
    abs1 = "doc/par-1/abs-1"
    kids = [idx[c].id.rsplit("/", 1)[1] for c in idx[abs1].children_ids]
    assert kids == ["nr-1", "nr-2", "txt-1", "run2-nr-1", "run2-nr-2", "txt-2", "run3-nr-1"]
    assert not any(w.code == "DUPLICATE_ID_RESOLVED" for w in m.warnings)
