"""Synthetic Docling JSON for parser tests: invented legal text, laid out page by page.

`build(pages, items)` writes a minimal but valid Docling export (texts, body and furniture trees, page sizes, boxes) so
the real parsing lifecycle (hygiene, recognizer, footnotes, sentences, TOC) runs on it without Docling or a PDF. Boxes are
in PDF points with a bottom-left origin on A4 pages, as Docling reports them; `where` places an item on its page:

* "top"    the first lines of a page (as the continuation of a text cut by the previous page break),
* "full"   a text that starts at the top of a page and runs to its foot (cut at both ends),
* "above_notes" the last lines of the body text, above the page-foot notes ("note1", "note2": the notes themselves),
* "bottom" the last lines above the page foot (as the text that is cut by the page break),
* "middle" anywhere else.

Running page numbers (`page_numbers`) are the furniture Docling labels `page_footer` on one machine and `text` on another
(the rendering of non-embedded fonts differs): `label` chooses which of the two the "Docker" or the "macOS" extraction gave.
"""

from __future__ import annotations

import json
from pathlib import Path

WIDTH, HEIGHT = 595.0, 842.0
BOXES = {"above_notes": (230.0, 190.0), "note1": (110.0, 92.0), "note2": (88.0, 70.0), "full": (780.0, 70.0), "top": (780.0, 740.0), "middle": (500.0, 460.0), "bottom": (110.0, 70.0)}  # (t, b) from the page bottom


def item(label: str, text: str, page: int, where: str = "middle", *, marker: str | None = None, enumerated: bool | None = None,
         left: float = 57.0, right: float = 538.0) -> dict:  # fmt: skip
    top, bottom = BOXES[where]
    return {"label": label, "text": text, "page": page, "t": top, "b": bottom, "l": left, "r": right,
            "marker": marker, "enumerated": enumerated}  # fmt: skip


def page_numbers(pages: int, label: str = "text") -> list[dict]:
    """The page number printed in the foot of every page. label="page_footer" is furniture for Docling; "text" is the
    same number mislabelled as body text (it is still found as running furniture by the hygiene layer)."""
    return [{"label": label, "text": str(p), "page": p, "t": 40.0, "b": 28.0, "l": 290.0, "r": 305.0, "marker": None,
             "enumerated": None} for p in range(1, pages + 1)]  # fmt: skip


def build(path: Path, pages: int, items: list[dict], *, footers: str = "text") -> Path:
    """Write the Docling JSON of `items` (document order, pages ascending) plus the page numbers; returns `path`.
    Each page number stands at the end of its page in reading order, between the last item of that page and the first
    of the next, exactly where a mislabelled page number interrupts a text that continues on the next page."""
    numbers = page_numbers(pages, footers)
    ordered = [it for p in range(1, pages + 1) for it in [*(i for i in items if i["page"] == p), numbers[p - 1]]]
    texts, body, furniture = [], [], []
    for it in ordered:
        ref = f"#/texts/{len(texts)}"
        furn = it["label"] == "page_footer"
        texts.append({
            "self_ref": ref, "label": it["label"], "content_layer": "furniture" if furn else "body",
            "orig": it["text"], "text": it["text"], "marker": it["marker"], "enumerated": it["enumerated"],
            "prov": [{"page_no": it["page"], "bbox": {"l": it["l"], "t": it["t"], "r": it["r"], "b": it["b"], "coord_origin": "BOTTOMLEFT"},
                      "charspan": [0, len(it["text"])]}],
        })  # fmt: skip
        (furniture if furn else body).append({"$ref": ref})
    doc = {
        "schema_name": "DoclingDocument", "version": "1.10.0",
        "origin": {"filename": "synthetic.pdf", "mimetype": "application/pdf", "binary_hash": 1},
        "body": {"children": body}, "furniture": {"children": furniture}, "groups": [], "tables": [], "pictures": [],
        "texts": texts,
        "pages": {str(p): {"size": {"width": WIDTH, "height": HEIGHT}, "page_no": p} for p in range(1, pages + 1)},
    }  # fmt: skip
    Path(path).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return Path(path)
