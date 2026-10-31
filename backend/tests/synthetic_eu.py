"""A small EU regulation in Docling's JSON shape, written for the ODOS tests (original text, freely redistributable).

It lets every test run exercise the EU profile end to end without private documents: front matter and metadata,
running page headers (one of them labelled as body text, as Docling sometimes does), preamble (citations, recitals),
chapters, a section, articles with and without numbered paragraphs, lettered points, a footnote with its "( 1 )"
reference, conclusions with a signature table, and an annex with a part, numbered and dotted headings. No PDF text
layer is given, so nothing is repaired from evidence; the layout is regular (one column, margin 68 pt).
"""

from __future__ import annotations

import json
from pathlib import Path

WIDTH, HEIGHT = 595.276, 841.89
MARGIN, RIGHT = 68.0, 528.0
TOP = 760.0  # first body line; running headers sit above it in the top band
STEP = 14.0  # one body line per item

HEADER = [("page_header", "L 1/{p}", 68.0, 110.0), ("text", "DE", 290.0, 305.0),  # "DE" labelled as body text
          ("page_header", "Amtsblatt der Europäischen Union", 330.0, 470.0), ("page_header", "1.1.2099", 480.0, 528.0)]  # fmt: skip

# (label, text, left, right[, top]); section headers are centred (C)
C = (250.0, 345.0)
PAGES: list[list[tuple]] = [
    [
        ("title", "VERORDNUNG (EU) 2099/1 DES EUROPÄISCHEN PARLAMENTS UND DES RATES", 120.0, 480.0),
        ("text", "vom 1. Januar 2099", 250.0, 345.0),
        ("text", "über synthetische Prüfmaschinen", 210.0, 385.0),
        ("text", "(Text von Bedeutung für den EWR)", 215.0, 380.0),
        ("text", "DAS EUROPÄISCHE PARLAMENT UND DER RAT DER EUROPÄISCHEN UNION —", MARGIN, 420.0),
        ("text", "gestützt auf den Vertrag über die Arbeitsweise der Europäischen Union, insbesondere auf Artikel 114,", MARGIN, RIGHT),
        ("text", "nach Stellungnahme des Prüfausschusses ( 1 ),", MARGIN, 300.0),
        ("text", "in Erwägung nachstehender Gründe:", MARGIN, 240.0),
        ("text", "(1) Synthetische Prüfmaschinen dienen ausschließlich der Erprobung von Software.", MARGIN, RIGHT),
        ("text", "(2) Diese Verordnung enthält keine verbindlichen Vorschriften. Sie dient nur als Testdokument.", MARGIN, RIGHT),
        ("footnote", "( 1 ) Stellungnahme vom 2. Februar 2098 (noch nicht im Amtsblatt veröffentlicht).", MARGIN, RIGHT, 90.0),
    ],
    [
        ("text", "HABEN FOLGENDE VERORDNUNG ERLASSEN:", MARGIN, 260.0),
        ("section_header", "KAPITEL I", *C),
        ("section_header", "ALLGEMEINE BESTIMMUNGEN", *C),
        ("section_header", "Artikel 1", *C),
        ("section_header", "Gegenstand", *C),
        ("text", "Diese Verordnung legt Anforderungen an synthetische Prüfmaschinen fest.", MARGIN, RIGHT),
        ("section_header", "Artikel 2", *C),
        ("section_header", "Begriffsbestimmungen", *C),
        ("text", "Im Sinne dieser Verordnung bezeichnet der Ausdruck:", MARGIN, RIGHT),
        ("text", "a) „Prüfmaschine“ eine Maschine, die nur in Tests vorkommt;", MARGIN, RIGHT),
        ("text", "b) „Prüfer“ eine Person, die Tests ausführt.", MARGIN, RIGHT),
        ("section_header", "KAPITEL II", *C),
        ("section_header", "PFLICHTEN", *C),
        ("section_header", "ABSCHNITT 1", *C),
        ("section_header", "Hersteller", *C),
        ("section_header", "Artikel 3", *C),
        ("section_header", "Pflichten der Hersteller", *C),
        ("text", "(1) Hersteller stellen sicher, dass Prüfmaschinen gekennzeichnet sind.", MARGIN, RIGHT),
        ("text", "(2) Hersteller bewahren die Unterlagen zehn Jahre auf. Sie legen sie auf Verlangen vor.", MARGIN, RIGHT),
        ("text", "Diese Verordnung ist in allen ihren Teilen verbindlich und gilt unmittelbar in jedem Mitgliedstaat.", MARGIN, RIGHT),
        ("text", "Geschehen zu Brüssel am 1. Januar 2099.", MARGIN, 260.0),
        ("table", [["Im Namen des Europäischen Parlaments", "Im Namen des Rates"], ["Die Präsidentin", "Der Präsident"],
                   ["A. MUSTER", "B. BEISPIEL"]], MARGIN, RIGHT),  # fmt: skip
    ],
    [
        ("section_header", "ANHANG I", *C),
        ("section_header", "GRUNDLEGENDE ANFORDERUNGEN", *C),
        ("section_header", "TEIL A", *C),
        ("section_header", "Allgemeine Grundsätze", *C),
        ("text", "1. ALLGEMEINES", MARGIN, 160.0),
        ("text", "1.1. Kennzeichnung", MARGIN, 170.0),
        ("text", "Jede Prüfmaschine trägt eine gut lesbare Kennzeichnung.", MARGIN, RIGHT),
        ("text", "1.2. Unterlagen", MARGIN, 160.0),
        ("text", "Die Unterlagen werden in deutscher Sprache abgefasst.", MARGIN, RIGHT),
    ],
]


def docling_json() -> dict:
    """The document in the subset of Docling's JSON schema that `docling_reader` reads."""
    texts, tables, body, furniture = [], [], [], []
    pages = {}
    for p, lines in enumerate(PAGES, start=1):
        pages[str(p)] = {"size": {"width": WIDTH, "height": HEIGHT}, "page_no": p}
        for label, text, left, right in HEADER:
            text = text.format(p=p)
            ref = f"#/texts/{len(texts)}"
            layer = "furniture" if label == "page_header" else "body"
            texts.append({"self_ref": ref, "label": label, "content_layer": layer, "text": text, "orig": text,
                          "prov": [{"page_no": p, "bbox": _box(left, 815.0, right), "charspan": [0, len(text)]}]})  # fmt: skip
            (furniture if layer == "furniture" else body).append({"$ref": ref})
        y = TOP
        for line in lines:
            label, content, left, right = line[:4]
            top = line[4] if len(line) > 4 else y
            if label == "table":
                ref = f"#/tables/{len(tables)}"
                grid = [[{"text": c} for c in row] for row in content]
                tables.append({"self_ref": ref, "label": "table", "content_layer": "body", "text": "",
                               "prov": [{"page_no": p, "bbox": _box(left, top, right, 3 * STEP), "charspan": [0, 0]}],
                               "data": {"num_rows": len(content), "num_cols": len(content[0]), "grid": grid}})  # fmt: skip
            else:
                ref = f"#/texts/{len(texts)}"
                texts.append({"self_ref": ref, "label": label, "content_layer": "body", "text": content, "orig": content,
                              "prov": [{"page_no": p, "bbox": _box(left, top, right), "charspan": [0, len(content)]}]})  # fmt: skip
            body.append({"$ref": ref})
            y -= 3 * STEP if label == "table" else STEP
    return {
        "schema_name": "DoclingDocument", "version": "1.7.0",
        "origin": {"filename": "synthetic_eu_regulation.pdf", "mimetype": "application/pdf", "binary_hash": 1},
        "body": {"children": body}, "furniture": {"children": furniture}, "groups": [],
        "texts": texts, "tables": tables, "pictures": [], "pages": pages,
    }  # fmt: skip


def _box(left: float, top: float, right: float, height: float = 10.0) -> dict:
    return {"l": left, "t": top, "r": right, "b": top - height, "coord_origin": "BOTTOMLEFT"}


def write(directory: Path) -> Path:
    """Write `docling_raw.json` into `directory` (deterministic bytes) and return its path."""
    path = Path(directory) / "docling_raw.json"
    path.write_text(json.dumps(docling_json(), ensure_ascii=False, indent=1), encoding="utf-8")
    return path
