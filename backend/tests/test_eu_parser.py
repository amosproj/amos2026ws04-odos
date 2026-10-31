"""EU legal structure parser on the real Regulation (EU) 2023/1230 (Machinery Regulation, German version)."""

import hashlib
import json
import re
from collections import Counter

import pytest

from odos.normalization.docling_reader import read_docling_json
from odos.parsing import parse_document
from odos.parsing.profiles.eu_legislation.report import build_eu_report
from odos.document_model import ElementType as T


@pytest.fixture(scope="module")
def idx(eu_model):
    return eu_model.by_id()


@pytest.fixture(scope="module")
def report(eu_model, eu_raw_json):
    return build_eu_report(eu_model, eu_raw_json)


def kids(idx, eid):
    return [idx[c].id.rsplit("/", 1)[1] for c in idx[eid].children_ids]


def first_with(m, prefix):
    return next(e for e in m.elements if e.original_text.startswith(prefix))


# ---- required counts ------------------------------------------------------------------------------------------
def test_counts(eu_model):
    c = Counter(e.type for e in eu_model.elements)
    assert (c[T.RECITAL], c[T.ARTICLE], c[T.CHAPTER], c[T.ANNEX]) == (86, 54, 9, 12)
    assert c[T.CITATION] == 5 and c[T.PREAMBLE_FORMULA] == 1 and c[T.ENACTING_FORMULA] == 1
    # 189 in articles + Annex III Part B 3.6.2 "(1)", "(2)" (numbered paragraphs inside an annex, verified on p.70)
    assert c[T.ANNEX_PART] == 8 and c[T.FOOTNOTE] == 26 and c[T.ARTICLE_PARAGRAPH] == 191


def test_sequences_are_complete_and_in_order(report):
    for k in ("recital", "chapter", "article", "annex"):
        assert report.sequences[k]["consecutive_from_1"], k
    assert report.sequences["chapter"]["markers"][-1] == "KAPITEL IX"
    assert report.sequences["annex"]["markers"][-1] == "ANHANG XII"


# ---- preamble and metadata ----------------------------------------------------------------------------------------
def test_preamble_order(idx):
    pre = kids(idx, "doc/preamble")
    assert pre[0] == "formula" and pre[1:6] == [f"citation-{i}" for i in range(1, 6)]
    assert pre[6] == "recitals-intro" and pre[7:93] == [f"rec-{i}" for i in range(1, 87)]
    assert pre[-1] == "enacting-formula" and len(pre) == 94
    assert idx["doc/preamble/formula"].original_text.startswith("DAS EUROPÄISCHE PARLAMENT UND DER RAT")
    assert idx["doc/preamble/enacting-formula"].original_text == "HABEN FOLGENDE VERORDNUNG ERLASSEN:"
    assert idx["doc/preamble/rec-86"].region == "preamble" and idx["doc/preamble/rec-86"].marker == "(86)"


def test_metadata_is_authentic_and_traceable(eu_model, idx):
    md = eu_model.metadata
    assert (md.document_type, md.document_number) == ("VERORDNUNG", "2023/1230")
    assert md.issuing_bodies == "DES EUROPÄISCHEN PARLAMENTS UND DES RATES"
    assert (md.adoption_date_text, md.adoption_date) == ("vom 14. Juni 2023", "2023-06-14")
    assert md.subject.startswith("über Maschinen und zur Aufhebung der Richtlinie 2006/42/EG")
    assert md.eea_relevance is True
    assert (md.publication_reference, md.publication_date) == ("L 165/1", "2023-06-29")
    assert md.ausfertigungsdatum is None  # German field stays empty: no German-law assumption
    furn = {f.id: f for f in eu_model.furniture}
    for field, ids in md.metadata_provenance.items():
        for i in ids:
            el = idx.get(i) or furn[i]
            assert el.source_refs and el.provenance, (field, i)
    assert eu_model.profile == "eu_legislation"


# ---- body hierarchy --------------------------------------------------------------------------------------------------
def test_chapters_and_articles(eu_model, idx):
    assert [c.id for c in eu_model.of_type(T.CHAPTER)] == [f"doc/chp-{i}" for i in range(1, 10)]
    assert idx["doc/chp-1"].title == "ALLGEMEINE BESTIMMUNGEN" and idx["doc/chp-3"].marker == "KAPITEL III"
    assert idx["doc/chp-3"].docling_label == "text"  # Docling labelled it text; recognised by pattern
    arts = eu_model.of_type(T.ARTICLE)
    assert [a.number for a in arts] == [str(i) for i in range(1, 55)]
    assert all(a.title for a in arts) and idx["doc/chp-1/art-1"].title == "Gegenstand"
    assert idx["doc/chp-9/art-54"].title == "Inkrafttreten und Anwendung"
    assert {idx[a.parent_id].type for a in arts} == {T.CHAPTER}
    assert len(idx["doc/chp-2/art-10"].source_refs) == 2  # "Artikel 10" + its title line, both kept


def test_article_paragraphs_including_split_items(report, idx):
    p = report.paragraphs_per_article
    for art, n in (("Artikel 10", 10), ("Artikel 11", 10), ("Artikel 14", 8), ("Artikel 15", 6), ("Artikel 16", 6)):
        assert p[art] == [f"({i})" for i in range(1, n + 1)], art
    assert p["Artikel 1"] == [] and idx["doc/chp-1/art-1"].children_ids  # unnumbered text kept under the article
    para = idx["doc/chp-2/art-11/para-3"]
    assert para.source_spans and para.source_spans[0].ref == "#/texts/373"
    assert para.original_text.startswith("(3) Die Hersteller bewahren")
    assert kids(idx, "doc/chp-2/art-16/para-2") == ["pt-a", "pt-b", "pt-c"]
    # the split boundary "… ob a) …" is no longer only inferred: "a) …" starts its own line on p.24 of the PDF
    pt_a = idx["doc/chp-2/art-16/para-2/pt-a"]
    assert not pt_a.uncertain and "segment_boundary_verified_by_pdf_text_layer" in pt_a.hygiene_flags


def test_points_and_roman_subpoints(idx):
    assert kids(idx, "doc/chp-1/art-2/para-2") == [f"pt-{c}" for c in "abcdefghijklmnopq"]
    assert kids(idx, "doc/chp-1/art-2/para-2/pt-p") == ["sub-i", "sub-ii", "sub-iii", "sub-iv", "sub-v", "sub-vi"]
    assert kids(idx, "doc/chp-1/art-2/para-2/pt-q") == ["sub-i", "sub-ii"]
    assert idx["doc/chp-1/art-2/para-2/pt-p/sub-v"].type == T.SUBPOINT  # "v)" continues the roman list
    i_alpha = idx["doc/chp-1/art-2/para-2/pt-i"]  # "i)" after "h)": same column as "h)", followed by "j)"
    assert i_alpha.type == T.POINT and not i_alpha.uncertain and "point_kind_decided_by_layout:alpha" in i_alpha.hygiene_flags
    assert kids(idx, "doc/chp-3/art-20/para-3/pt-a") == ["sub-i", "sub-ii", "sub-iii"]
    assert idx["doc/chp-3/art-20/para-3/pt-b"].type == T.POINT


def test_numbered_definitions(idx):
    k = kids(idx, "doc/chp-1/art-3")
    assert k[0] == "txt-1" and k[1:] == [f"pt-{i}" for i in range(1, 37)]
    assert kids(idx, "doc/chp-1/art-3/pt-1") == [f"pt-{c}" for c in "abcdef"]
    assert idx["doc/chp-1/art-3/pt-2"].type == T.NUMBERED_POINT


# ---- conclusions, annexes, footnotes, furniture -------------------------------------------------------------------------
def test_conclusions_and_signature(idx):
    assert kids(idx, "doc/conclusions") == ["formula-1", "formula-2", "signature-1"]
    assert idx["doc/conclusions/formula-1"].original_text.startswith("Diese Verordnung ist in allen ihren Teilen verbindlich")
    assert re.fullmatch(r"Geschehen zu \S+ am \d{1,2}\. \w+ \d{4}\.", idx["doc/conclusions/formula-2"].original_text)
    sig = idx["doc/conclusions/signature-1"]
    assert sig.type == T.SIGNATURE and sig.table.rows[0] == ["Im Namen des Europäischen Parlaments", "Im Namen des Rates"]


def test_annexes(eu_model, idx):
    annexes = eu_model.of_type(T.ANNEX)
    assert [a.id for a in annexes] == [f"doc/annex-{i}" for i in range(1, 13)]
    assert all(a.title for a in annexes) and annexes[3].title == "Technische Dokumentation"
    assert annexes[8].title.endswith("(Modul H)") and len(annexes[8].source_refs) == 3  # title spans two lines
    assert [p.id for p in eu_model.of_type(T.ANNEX_PART)] == [f"doc/annex-{a}/part-{p}" for a in (1, 3, 4, 5) for p in "ab"]
    h = idx["doc/annex-3/part-b/h-1/h-1.2/h-1.2.4/h-1.2.4.1"]
    assert h.type == T.ANNEX_HEADING and h.original_text.startswith("1.2.4.1. N o r m a l e s")
    assert h.search_text.startswith("1.2.4.1. NormalesStillsetzen")  # derived only
    assert max(e.number.count(".") + 1 for e in eu_model.of_type(T.ANNEX_HEADING)) == 5
    assert kids(idx, "doc/annex-1/part-b/pt-1")[:2] == ["pt-1.1", "pt-1.2"]  # dotted sub-items, not headings
    assert [idx[c].type for c in idx["doc/annex-12"].children_ids] == [T.TABLE, T.TABLE]  # table continues on p. 102


def test_footnotes_anchored_to_their_reference(eu_model, idx):
    fns = eu_model.of_type(T.FOOTNOTE)
    assert len(fns) == 26 and not any("footnote_reference_not_found_on_page" in f.uncertainty_reasons for f in fns)
    for f in fns:
        parent = idx[f.parent_id]
        assert f"( {f.number} )" in parent.original_text and set(f.pages) & set(parent.pages), f.id
    assert idx["doc/preamble/rec-1/fn-3"].original_text.startswith("( 3 ) Richtlinie 2006/42/EG")


def test_furniture_kept_not_deleted(eu_model):
    c = Counter(f.type for f in eu_model.furniture)
    assert c == {T.PAGE_HEADER: 339, T.PICTURE: 65}
    assert sum("furniture_labelled_as_body_by_docling" in f.hygiene_flags for f in eu_model.furniture) == 21
    assert all("repeated_page_decoration" in f.hygiene_flags for f in eu_model.furniture if f.type == T.PICTURE)


# ---- integrity ------------------------------------------------------------------------------------------------------------
def test_exact_source_accounting_and_provenance(report):
    a = report.accounting
    assert a["exact"] and a["docling_items_total"] == 2217
    assert a["source_non_whitespace_chars"] == a["accounted_non_whitespace_chars"]
    # the five merged items, and the four of Art. 47 whose reading order was repaired from the PDF text layer
    assert [s["ref"] for s in a["segmented_items"]] == ["#/texts/369", "#/texts/373", "#/texts/416", "#/texts/443", "#/texts/447",
                                                        "#/texts/745", "#/texts/746", "#/texts/747", "#/texts/748"]  # fmt: skip
    assert all(s["tiles_item_exactly"] for s in a["segmented_items"])
    p = report.provenance_coverage
    assert p["elements_with_source"] == p["with_page_provenance"] == p["with_bbox"] == 2150  # the stray item is no element any more
    assert p["with_partial_item_spans"] == 25  # 22 + Art. 47(1)-(3)


def test_text_is_docling_text_plus_recorded_pdf_repairs(eu_model, eu_raw_json):
    from odos.parsing.accounting import canonical_sources, text_repair_check

    _, items = read_docling_json(eu_raw_json)
    src = canonical_sources(eu_model, items)  # Docling's text with the evidenced repairs ("—", "„…“") applied
    chk = text_repair_check(eu_model, items)
    assert chk["reverts_to_docling_exactly"] and chk["without_evidence"] == 0 and chk["unresolved"] == 0
    for e in [*eu_model.elements, *eu_model.furniture]:
        if e.source_spans:
            assert e.original_text == "\n".join(src[s.ref].orig[s.start : s.end] for s in e.source_spans)
        elif e.source_refs:
            assert e.original_text == "\n".join(src[r].orig for r in e.source_refs)


def test_ids_unique_and_stable(eu_model, report):
    ids = [e.id for e in [*eu_model.elements, *eu_model.furniture]]
    assert len(ids) == len(set(ids)) and not report.duplicate_ids
    assert not any("~" in i for i in ids)  # no collision had to be resolved
    assert "DUPLICATE_ID_RESOLVED" not in report.warning_counts
    body = sorted(e.id for e in eu_model.elements)
    # previous values: f440b403... (incl. the stray Art. 47 item repaired away), 7a0b412f... (before 16 Annex III
    # elements were re-parented: 1.7.4.2 u)/x) body texts, 3.2.2 a) body texts, 3.6.2 paragraphs (1)/(2))
    assert hashlib.sha256("\n".join(body).encode()).hexdigest() == "e18ebbfb1872ad6aaa01ced26ed3528d4c9cafe328e90b28b783acb00bb3370f"
    assert "doc/chp-7/art-47/para-3/txt-1" not in body


def test_deterministic(eu_model, eu_raw_json):
    assert parse_document(eu_raw_json, "eu_legislation").model_dump_json() == eu_model.model_dump_json()


def test_warning_and_uncertainty_profile(eu_model, report):
    """Pinned so changes are noticed. The former 14 warnings were all resolved from source evidence (next marker,
    indentation, sequence, PDF text layer) or are valid structures, now listed as structure notes."""
    # no structural warning; two sentence ends the rules cannot decide ("Teil B. Sie", a sentence end inside point d)
    assert report.warning_counts == {"SENTENCE_SEGMENTATION_UNRESOLVED": 2}
    assert {w.element_id for w in eu_model.warnings} == {"doc/chp-1/art-6/para-5", "doc/chp-3/art-22/para-2"}
    assert len(report.uncertain) == 3  # Art. 47(1)-(3): reading order repaired from the PDF text layer, for review
    assert report.uncertainty_category_counts == {"extraction_uncertainty": 3}
    assert not eu_model.of_type(T.UNRECOGNIZED)
    order = [e.id for e in eu_model.elements if "reading_order_uncertain:layout_box_overlaps_other_item" in e.uncertainty_reasons]
    assert order == ["doc/chp-7/art-47/para-1", "doc/chp-7/art-47/para-2", "doc/chp-7/art-47/para-3"]
    assert all("reading_order_uncertain:repaired_from_pdf_text_layer" in eu_model.by_id()[i].uncertainty_reasons for i in order)
    lp = first_with(eu_model, "(l) Angaben zu Restrisiken")  # printed "(l)" instead of "l)"
    assert lp.type == T.POINT and lp.marker == "(l)" and not lp.uncertain  # "k)", "(l)", "m)" confirm the sequence
    assert "point_marker_in_parentheses" in lp.hygiene_flags  # the printed deviation is still recorded


STRUCTURE_NOTES = [  # verified against the PDF: valid structures of the source, not parser problems
    ("UNTITLED_HEADING", "doc/annex-1/part-a"),  # p.40: "TEIL A", then the left-aligned intro line ending ":"
    ("UNTITLED_HEADING", "doc/annex-1/part-b"),
    ("PARENTHESISED_POINT_MARKER", "doc/annex-3/part-b/h-1/h-1.7/h-1.7.4/h-1.7.4.2/pt-1/pt-l"),
    ("ROMAN_LIST_INTRODUCED_BY_TEXT", "doc/annex-3/part-b/h-3/h-3.3/h-3.3.3/sub-i"),  # "... erfüllen:"
    ("NUMBERED_PARAGRAPH_CONTINUES_HEADINGS", "doc/annex-7/pt-8"),
    ("NUMBERED_PARAGRAPH_CONTINUES_HEADINGS", "doc/annex-9/pt-6"),
    ("ROMAN_LIST_INTRODUCED_BY_TEXT", "doc/annex-10/h-2/sub-i"),  # "... zumindest"
    ("NEW_NUMBERED_SEQUENCE", "doc/annex-3/part-b/h-1"),  # paragraphs 1-5, then headings 1-6
]


def test_structure_notes(eu_model, report, idx):
    assert [(n.code, n.element_id) for n in eu_model.structure_notes] == STRUCTURE_NOTES
    assert all(n.category == "valid_structure" and n.severity == "info" and n.element_id in idx for n in eu_model.structure_notes)
    assert report.structure_note_counts == dict(Counter(c for c, _ in STRUCTURE_NOTES))
    assert idx["doc/annex-1/part-a"].title is None  # no title invented


def test_resolved_annex_iii_hierarchy(idx):
    base = "doc/annex-3/part-b/h-1/h-1.7/h-1.7.4/h-1.7.4.2/pt-1"
    assert kids(idx, f"{base}/pt-u")[-7:] == [f"txt-{i}" for i in range(1, 8)]  # body paragraphs of u) (x=135.9 vs 121)
    assert kids(idx, f"{base}/pt-x")[-1] == "txt-1"  # "... Unterabsatz 1 ..." under x)
    assert all("attached_by_indentation" in idx[f"{base}/pt-u/txt-{i}"].hygiene_flags for i in range(1, 8))
    lvl = "doc/annex-3/part-b/h-3/h-3.6/h-3.6.2"
    assert kids(idx, lvl) == ["para-1", "para-2"]
    assert kids(idx, f"{lvl}/para-1") == kids(idx, f"{lvl}/para-2") == ["pt-a", "pt-b"]
    assert kids(idx, "doc/annex-3/part-b/h-3/h-3.2/h-3.2.2/pt-a")[-2:] == ["txt-1", "txt-2"]


# ---- interface ------------------------------------------------------------------------------------------------------------
def test_explicit_parser_modes(eu_raw_json, eu_model):
    assert parse_document(eu_raw_json, "eu_legislation").model_dump_json() == eu_model.model_dump_json()
    with pytest.raises(ValueError):
        parse_document(eu_raw_json, "auto")


def test_german_models_carry_no_eu_fields(model, mbo_model):
    for m in (model, mbo_model):
        d = json.loads(m.model_dump_json())
        assert "profile" not in d and "document_number" not in d["metadata"] and "metadata_provenance" not in d["metadata"]


@pytest.mark.slow
def test_pipeline_eu_mode(tmp_path, eu_pdf):
    from odos.pipeline import Outcome, ProcessingMode, run_pipeline

    res = run_pipeline(eu_pdf, tmp_path, ProcessingMode.EU_LEGISLATION, "2026-10-27")
    assert res.outcome == Outcome.COMPLETED and "Akoma Ntoso XML generated" in res.message
    s = res.summary
    assert (s["recitals"], s["chapters"], s["articles"], s["annexes"]) == (86, 9, 54, 12)
    assert s["source_accounting_exact"] is True and s["akn_generated"] is True and s["akn_xsd_valid"] is True
    assert (tmp_path / "document_akn.xml").exists()
    assert json.loads((tmp_path / "document_model.json").read_text())["profile"] == "eu_legislation"
