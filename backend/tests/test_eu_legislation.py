"""The EU profile: first on the synthetic regulation (tests/synthetic_eu.py, always runs, needs no private file), then on
the real Regulation (EU) 2023/1230 (Machinery Regulation, German version), which skips when the PDF is not available."""

from collections import Counter

from odos.document_model import ElementType as T
from odos.parsing import engine, parse_document
from odos.parsing.profiles import EU_LEGISLATION
from odos.parsing.profiles.eu_legislation.report import build_eu_report


def kids(idx, element_id):
    return [idx[c].id.rsplit("/", 1)[1] for c in idx[element_id].children_ids]


# ---- synthetic regulation ------------------------------------------------------------------------------------------
def test_synthetic_metadata_and_every_eu_unit(synthetic_eu_raw_json, synthetic_eu_model):
    m = synthetic_eu_model
    trace: list[str] = []
    again = engine.parse(synthetic_eu_raw_json, EU_LEGISLATION, trace)
    assert trace == [name for name, _ in engine.STAGES] and again.model_dump_json() == m.model_dump_json()  # deterministic
    assert m.profile == "eu_legislation" and not m.warnings and not any(e.uncertain for e in m.elements)

    md = m.metadata
    assert (md.document_type, md.document_number, md.adoption_date, md.subject) == (
        "VERORDNUNG", "2099/1", "2099-01-01", "über synthetische Prüfmaschinen")  # fmt: skip
    assert (md.publication_reference, md.publication_date, md.eea_relevance) == ("L 1/1", "2099-01-01", True)

    idx = m.by_id()
    expected = {
        "doc/preamble/citation-2": T.CITATION, "doc/preamble/rec-2": T.RECITAL, "doc/preamble/enacting-formula": T.ENACTING_FORMULA,
        "doc/chp-1/art-1": T.ARTICLE, "doc/chp-1/art-2/pt-b": T.POINT, "doc/chp-2/sec-1": T.SECTION,
        "doc/chp-2/sec-1/art-3/para-2": T.ARTICLE_PARAGRAPH, "doc/conclusions/signature-1": T.SIGNATURE,
        "doc/annex-1/part-a": T.ANNEX_PART, "doc/annex-1/part-a/h-1/h-1.2": T.ANNEX_HEADING,
    }  # fmt: skip
    assert {i: idx[i].type for i in expected} == expected
    assert (idx["doc/chp-2"].number, idx["doc/chp-2"].title) == ("II", "PFLICHTEN")  # printed numbers are kept


def test_synthetic_footnote_furniture_and_sentences(synthetic_eu_model):
    idx = synthetic_eu_model.by_id()
    fn = idx["doc/preamble/citation-2/fn-1"]  # anchored to the citation that prints "( 1 )"
    assert fn.type == T.FOOTNOTE and fn.parent_id == "doc/preamble/citation-2"
    assert len(synthetic_eu_model.furniture) == 12 and all(f.region == "furniture" for f in synthetic_eu_model.furniture)
    assert [s.id for s in synthetic_eu_model.sentences] == [
        "doc/preamble/rec-1/s1", "doc/preamble/rec-2/s1", "doc/preamble/rec-2/s2", "doc/chp-1/art-1/s1",
        "doc/chp-1/art-2/s1", "doc/chp-2/sec-1/art-3/para-1/s1", "doc/chp-2/sec-1/art-3/para-2/s1",
        "doc/chp-2/sec-1/art-3/para-2/s2",
    ]  # fmt: skip


# ---- the real Regulation (EU) 2023/1230 ----------------------------------------------------------------------------
def test_real_regulation_structure_and_sequences(eu_model, eu_raw_json):
    idx = eu_model.by_id()
    c = Counter(e.type for e in eu_model.elements)
    assert (c[T.RECITAL], c[T.ARTICLE], c[T.CHAPTER], c[T.ANNEX]) == (86, 54, 9, 12)
    assert c[T.CITATION] == 5 and c[T.ENACTING_FORMULA] == 1 and c[T.ANNEX_PART] == 8 and c[T.FOOTNOTE] == 26
    assert c[T.ARTICLE_PARAGRAPH] == 191  # 189 in articles + the two numbered paragraphs of Annex III Part B 3.6.2
    assert not eu_model.of_type(T.UNRECOGNIZED)
    assert (idx["doc/chp-1"].title, idx["doc/chp-1/art-1"].title) == ("ALLGEMEINE BESTIMMUNGEN", "Gegenstand")
    assert idx["doc/chp-3"].docling_label == "text"  # Docling labelled it text; recognised by its pattern
    assert {idx[a.parent_id].type for a in eu_model.of_type(T.ARTICLE)} == {T.CHAPTER}
    assert kids(idx, "doc/preamble")[-1] == "enacting-formula" and len(kids(idx, "doc/preamble")) == 94
    assert [a.id for a in eu_model.of_type(T.ANNEX)] == [f"doc/annex-{i}" for i in range(1, 13)]
    report = build_eu_report(eu_model, eu_raw_json)
    assert all(report.sequences[k]["consecutive_from_1"] for k in ("recital", "chapter", "article", "annex"))  # nothing skipped


def test_real_regulation_metadata_paragraphs_and_points(eu_model):
    md = eu_model.metadata
    assert (md.document_type, md.document_number) == ("VERORDNUNG", "2023/1230")
    assert (md.adoption_date, md.publication_reference, md.publication_date) == ("2023-06-14", "L 165/1", "2023-06-29")
    assert md.ausfertigungsdatum is None  # the German-law field stays empty

    idx = eu_model.by_id()
    assert kids(idx, "doc/chp-2/art-11")[:4] == ["para-1", "para-2", "para-3", "para-4"]
    para = idx["doc/chp-2/art-11/para-3"]  # Docling merged paragraphs (1)-(7) into one item: this is a part of it
    assert para.source_spans and para.source_spans[0].ref == "#/texts/373" and para.original_text.startswith("(3) Die Hersteller bewahren")
    assert kids(idx, "doc/chp-2/art-16/para-2") == ["pt-a", "pt-b", "pt-c"]  # the list split inside one Docling item
    assert kids(idx, "doc/chp-1/art-2/para-2/pt-p") == ["sub-i", "sub-ii", "sub-iii", "sub-iv", "sub-v", "sub-vi"]  # roman sub-points
    assert idx["doc/chp-1/art-2/para-2/pt-i"].type == T.POINT  # "i)" after "h)" is a letter, not a roman numeral


def test_real_regulation_footnotes_and_source_accounting(eu_model, eu_raw_json):
    idx = eu_model.by_id()
    footnotes = eu_model.of_type(T.FOOTNOTE)
    for f in footnotes:  # every footnote sits under the element that prints its "( n )" reference, on the same page
        parent = idx[f.parent_id]
        assert f"( {f.number} )" in parent.original_text and set(f.pages) & set(parent.pages), f.id
    assert {w.code for w in eu_model.warnings} <= {"SENTENCE_SEGMENTATION_UNRESOLVED"}  # no structural warning

    report = build_eu_report(eu_model, eu_raw_json)
    assert report.accounting["exact"] and report.accounting["docling_items_total"] == 2217  # every character, exactly once
    p = report.provenance_coverage
    assert p["elements_with_source"] == p["with_page_provenance"] == p["with_bbox"]  # every element can be highlighted
    assert parse_document(eu_raw_json, "eu_legislation").model_dump_json() == eu_model.model_dump_json()  # deterministic
