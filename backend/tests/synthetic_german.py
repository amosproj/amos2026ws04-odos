"""A small German law in Docling's JSON shape plus a matching generated PDF, written for the ODOS tests (original
text, freely redistributable).

It lets every test run exercise the German-law profile end to end without the partner documents: front matter and
metadata (title, short title, Ausfertigungsdatum, Vollzitat, Stand), a table of contents, Teil / Kapitel, § with
Absätze, Nummern and Buchstaben, Absätze with printed (superscript) Satz numbers, a page footnote whose superscript
reference mark sits in the text, running headers and footers, an Anlage with a table.

Unlike the synthetic EU regulation, this one has a real PDF text layer: ``pdf`` returns a PDF whose positioned
text runs (including raised, smaller superscript digits) are exactly what the Docling items say, so the PDF
evidence (`write_evidence`) proves footnote anchors and printed Satz numbers the way it does for real laws.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

WIDTH, HEIGHT = 595.276, 841.89
MARGIN, RIGHT = 56.0, 528.0
BODY, SMALL, FOOT = 10.0, 6.0, 8.0  # font sizes (pt); superscripts are SMALL, raised by RISE
RISE = 4.0
PITCH = 16.0  # distance between consecutive lines; boxes (12.5 pt high) never overlap

Run = tuple[str, float, float]  # (text, font size, rise)


def sup(text: str) -> Run:
    return (text, SMALL, RISE)


@dataclass
class Line:
    label: str
    runs: list[Run]
    page: int
    y: float
    x: float = MARGIN
    marker: str | None = None  # a list item's printed marker ("1.", "a)"): part of `orig`, not of `text`
    layer: str = "body"
    size: float = BODY
    table: list[list[str]] | None = None

    @property
    def orig(self) -> str:
        """Docling's text of the line. Docling puts a space between a superscript number and the word it is glued to
        in the PDF ("1Der" is printed, "1 Der" is extracted); the PDF text layer itself keeps no space."""
        out = ""
        for k, (text, _, rise) in enumerate(self.runs):
            out += text
            nxt = self.runs[k + 1][0] if k + 1 < len(self.runs) else ""
            if rise > 0 and nxt[:1].isalpha() and nxt[:1].isupper():
                out += " "
        return out

    @property
    def text(self) -> str:
        return self.orig[len(self.marker) + 1 :] if self.marker else self.orig


def _t(s: str, size: float = BODY) -> Run:
    return (s, size, 0.0)


def build() -> list[Line]:
    """The document as positioned lines: page, baseline, runs."""
    L: list[Line] = []
    y = {1: 770.0, 2: 770.0, 3: 770.0}

    def add(page, label, *runs, **kw):
        size = kw.get("size", BODY)
        rs = [r if isinstance(r, tuple) else _t(r, size) for r in runs]
        L.append(Line(label, rs, page, y[page], **kw))
        y[page] -= PITCH

    def gap(page, n=1.0):
        y[page] -= PITCH * n

    for p in (1, 2, 3):  # running furniture (page_header / page_footer are Docling's furniture layer)
        L.append(Line("page_header", [_t("Beispielgesetzblatt")], p, 815.0, x=360.0, layer="furniture"))
        L.append(Line("page_footer", [_t(f"- Seite {p} von 3 -")], p, 20.0, x=270.0, layer="furniture"))

    # ---- page 1: front matter and table of contents ---------------------------------------------------------
    add(1, "section_header", "Beispielgesetz über Prüfverfahren")
    add(1, "section_header", "BspG")
    add(1, "text", "Ausfertigungsdatum: 15.03.2099")
    add(1, "text", "Vollzitat:")
    add(1, "text", "\"Beispielgesetz über Prüfverfahren vom 15. März 2099 (BGBl. I S. 1)\"")
    add(1, "text", "Stand: Zuletzt geändert durch Art. 1 G v. 1.1.2100 I Nr. 1")
    gap(1)
    add(1, "section_header", "Inhaltsübersicht")
    add(1, "section_header", "Teil 1 Allgemeine Vorschriften")
    add(1, "section_header", "Kapitel 1 Grundlagen")
    add(1, "list_item", "§ 1 Anwendungsbereich")
    add(1, "list_item", "§ 2 Begriffsbestimmungen")
    add(1, "section_header", "Kapitel 2 Verfahren")
    add(1, "list_item", "§ 3 Antrag")
    add(1, "list_item", "§ 4 Entscheidung")
    add(1, "section_header", "Teil 2 Schlussvorschriften")
    add(1, "list_item", "§ 5 Inkrafttreten")
    add(1, "list_item", "Anlage 1 Prüfkatalog")

    # ---- page 2: Teil 1, Kapitel 1 ---------------------------------------------------------------------------
    add(2, "section_header", "Teil 1 Allgemeine Vorschriften")
    add(2, "section_header", "Kapitel 1 Grundlagen")
    add(2, "section_header", "§ 1 Anwendungsbereich")
    add(2, "text", "(1) Dieses Gesetz gilt für Prüfverfahren der Behörden des Bundes.")
    add(2, "text", "(2) Es gilt nicht für interne Erprobungen.")
    add(2, "section_header", "§ 2 Begriffsbestimmungen")
    add(2, "text", "(1) Im Sinne dieses Gesetzes ist")
    add(2, "list_item", "1. Prüfverfahren ein geordnetes Vorgehen zur Feststellung von Eigenschaften,", x=MARGIN + 12, marker="1.")
    add(2, "list_item", "2. Prüfstelle eine Stelle, die Prüfungen durchführt,", x=MARGIN + 12, marker="2.")
    add(2, "list_item", "3. Antragsteller eine Person, die", x=MARGIN + 12, marker="3.")
    add(2, "list_item", "a) ein Prüfverfahren beantragt oder", x=MARGIN + 24, marker="a)")
    add(2, "list_item", "b) ein Prüfverfahren durchführen lässt.", x=MARGIN + 24, marker="b)")
    add(2, "text", "(2) Behörden des Landes", sup("1"), _t(" gelten als Prüfstellen."))
    L.append(Line("footnote", [_t("1 siehe die Vorschriften der Länder.", FOOT)], 2, 70.0, size=FOOT))  # page footnote

    # ---- page 3: Kapitel 2, Teil 2, Anlage ----------------------------------------------------------------------
    add(3, "section_header", "Kapitel 2 Verfahren")
    add(3, "section_header", "§ 3 Antrag")
    add(3, "text", "(1) ", sup("1"), _t("Der Antrag ist schriftlich zu stellen. "), sup("2"), _t("Er enthält den Namen der antragstellenden Person."))
    add(3, "text", "(2) Die Behörde bestätigt den Eingang. Sie prüft den Antrag unverzüglich.")
    add(3, "section_header", "§ 4 Entscheidung")
    add(3, "text", "(1) Die Prüfstelle entscheidet über den Antrag, wenn")
    add(3, "list_item", "1. der Antrag vollständig ist und", x=MARGIN + 12, marker="1.")
    add(3, "list_item", "2. die Gebühren entrichtet sind.", x=MARGIN + 12, marker="2.")
    add(3, "section_header", "Teil 2 Schlussvorschriften")
    add(3, "section_header", "§ 5 Inkrafttreten")
    add(3, "text", "Dieses Gesetz tritt am Tag nach der Verkündung in Kraft.")
    add(3, "section_header", "Anlage 1 Prüfkatalog")
    L.append(Line("table", [], 3, y[3], table=[["Nr.", "Prüfgegenstand"], ["1", "Unterlagen"], ["2", "Verfahren"]]))
    return L


def _box(x: float, y: float, size: float, right: float = RIGHT, height: float | None = None) -> dict:
    h = height if height is not None else size + 2.5
    return {"l": x, "t": y + size, "r": right, "b": y + size - h, "coord_origin": "BOTTOMLEFT"}


def docling_json() -> dict:
    texts, tables, body, furniture = [], [], [], []
    for ln in build():
        if ln.table is not None:
            ref = f"#/tables/{len(tables)}"
            grid = [[{"text": c} for c in row] for row in ln.table]
            tables.append({"self_ref": ref, "label": "table", "content_layer": "body", "text": "",
                           "prov": [{"page_no": ln.page, "bbox": _box(MARGIN, ln.y, BODY, height=3 * PITCH), "charspan": [0, 0]}],
                           "data": {"num_rows": len(ln.table), "num_cols": 2, "grid": grid}})  # fmt: skip
            body.append({"$ref": ref})
            continue
        ref = f"#/texts/{len(texts)}"
        right = ln.x + 250 if ln.layer == "furniture" else RIGHT
        node = {"self_ref": ref, "label": ln.label, "content_layer": ln.layer, "text": ln.text, "orig": ln.orig,
                "prov": [{"page_no": ln.page, "bbox": _box(ln.x, ln.y, ln.size, right), "charspan": [0, len(ln.orig)]}]}  # fmt: skip
        if ln.marker:
            node |= {"marker": ln.marker, "enumerated": True}
        texts.append(node)
        (furniture if ln.layer == "furniture" else body).append({"$ref": ref})
    return {
        "schema_name": "DoclingDocument", "version": "1.7.0",
        "origin": {"filename": "synthetic_german_law.pdf", "mimetype": "application/pdf", "binary_hash": 2},
        "body": {"children": body}, "furniture": {"children": furniture}, "groups": [],
        "texts": texts, "tables": tables, "pictures": [],
        "pages": {str(p): {"size": {"width": WIDTH, "height": HEIGHT}, "page_no": p} for p in (1, 2, 3)},
    }  # fmt: skip


def _esc(s: str) -> bytes:
    return s.encode("cp1252", errors="replace").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def pdf() -> bytes:
    """A PDF whose text layer is the Docling items' text at the items' positions (superscripts raised and smaller)."""
    lines = build()
    n = 3
    objs: list[bytes] = [b"<</Type/Catalog/Pages 2 0 R>>",
                         f"<</Type/Pages/Kids[{' '.join(f'{3 + 2 * i} 0 R' for i in range(n))}]/Count {n}>>".encode()]
    font_id = 3 + 2 * n
    for p in range(1, n + 1):
        ops = []
        for ln in (l for l in lines if l.page == p and l.table is None):
            parts = [f"BT 1 0 0 1 {ln.x:.2f} {ln.y:.2f} Tm".encode()]
            for text, size, rise in ln.runs:
                parts.append(f"/F1 {size:g} Tf {rise:g} Ts".encode() + b" (" + _esc(text) + b") Tj")
            parts.append(b"0 Ts ET")
            ops.append(b" ".join(parts))
        body = b"\n".join(ops)
        page_id, cont_id = 3 + 2 * (p - 1), 4 + 2 * (p - 1)
        objs.append(f"<</Type/Page/Parent 2 0 R/MediaBox[0 0 {WIDTH} {HEIGHT}]/Contents {cont_id} 0 R/Resources<</Font<</F1 {font_id} 0 R>>>>>>".encode())
        objs.append(b"<</Length " + str(len(body)).encode() + b">>\nstream\n" + body + b"\nendstream")
    objs.append(b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer<</Size {len(objs) + 1}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def write(directory: Path) -> Path:
    """Write `original.pdf` and `docling_raw.json` (deterministic bytes) into `directory`, and the PDF text-layer
    evidence next to the JSON (`pdf_text_lines.json`); return the Docling JSON path."""
    from odos.normalization.reading_order import write_evidence

    directory = Path(directory)
    (directory / "original.pdf").write_bytes(pdf())
    raw = directory / "docling_raw.json"
    raw.write_text(json.dumps(docling_json(), ensure_ascii=False, indent=1), encoding="utf-8")
    write_evidence(directory / "original.pdf", raw)
    return raw
