"""Flattens a Docling JSON export into reading-ordered source items.

Isolates the parser from the Docling schema.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, Field

from odos.document_model import BoundingBox, Provenance, SourceInfo, SourceSpan, TableCellSource, TableData, TextRepair

FURNITURE_LABELS = {"page_header", "page_footer"}


class SourceItem(BaseModel):
    ref: str
    label: str
    layer: str
    orig: str  # verbatim `orig` (falls back to `text`)
    text: str  # Docling's cleaned text (list markers stripped)
    marker: str | None = None
    enumerated: bool | None = None
    group_ref: str | None = None
    provenance: list[Provenance] = Field(default_factory=list)
    table: TableData | None = None
    # Set by odos.normalization.hygiene; the Docling fields above are never modified.
    span: tuple[int, int] | None = None  # this item is the slice orig[start:end] of the Docling item `ref`
    segment_index: int = 0
    segment_count: int = 1
    boundary_flags: list[str] = Field(default_factory=list)  # why a segment boundary is uncertain
    order_flags: list[str] = Field(default_factory=list)  # why the reading order around this item is uncertain
    # set by odos.normalization.reading_order: `orig` is these verbatim slices of Docling items, joined by " "
    parts: list[SourceSpan] = Field(default_factory=list)
    search_text: str | None = None
    hygiene_flags: list[str] = Field(default_factory=list)
    # set by odos.normalization.source_text: `orig`/`text` hold the PDF-faithful text, Docling's own `orig` is kept here
    docling_orig: str | None = None
    text_repairs: list[TextRepair] = Field(default_factory=list)
    # set by odos.normalization.highlight: one exact rectangle per PDF line of this (partial) item, where provable
    highlight_boxes: list[Provenance] = Field(default_factory=list)

    @property
    def is_furniture(self) -> bool:
        return self.layer == "furniture" or self.label in FURNITURE_LABELS

    @property
    def pages(self) -> list[int]:
        return sorted({p.page_no for p in self.provenance})


def _provenance(node: dict) -> list[Provenance]:
    out = []
    for p in node.get("prov") or []:
        bbox = p.get("bbox")
        out.append(
            Provenance(
                page_no=p["page_no"],
                bbox=BoundingBox(**bbox) if bbox else None,
                charspan=tuple(p["charspan"]) if p.get("charspan") else None,
            )
        )
    return out


def _table(node: dict, page_heights: dict[int, float] | None = None) -> TableData:
    data = node.get("data") or {}
    rows = [[c.get("text", "") for c in row] for row in data.get("grid") or []]
    prov = node.get("prov") or []
    page = prov[0]["page_no"] if len(prov) == 1 else None  # cell boxes are only placed for one-page tables
    h = (page_heights or {}).get(page) if page is not None else None
    cells = []
    for c in data.get("table_cells") or []:
        b = c.get("bbox")
        box = None
        if b and page is not None:
            if str(b.get("coord_origin", "")).upper().startswith("TOP"):
                if h is not None:  # Docling reports cell boxes top-left; the model uses bottom-left throughout
                    box = BoundingBox(l=b["l"], t=h - b["t"], r=b["r"], b=h - b["b"], coord_origin="BOTTOMLEFT")
            else:
                box = BoundingBox(**b)
        cells.append(TableCellSource(row=c.get("start_row_offset_idx", 0), col=c.get("start_col_offset_idx", 0),
                                     row_span=c.get("row_span", 1), col_span=c.get("col_span", 1), text=c.get("text", ""),
                                     page_no=page if box else None, bbox=box))  # fmt: skip
    return TableData(
        num_rows=data.get("num_rows", len(rows)),
        num_cols=data.get("num_cols", 0),
        rows=rows,
        cells=cells if any(c.bbox for c in cells) else [],
    )


def read_page_sizes(path: Path) -> dict[int, tuple[float, float]]:
    raw = json.loads(Path(path).read_bytes())
    return {int(k): (v["size"]["width"], v["size"]["height"]) for k, v in (raw.get("pages") or {}).items()}


def read_docling_json(path: Path) -> tuple[SourceInfo, list[SourceItem]]:
    raw_bytes = Path(path).read_bytes()
    raw = json.loads(raw_bytes)

    def resolve(ref: str) -> dict:
        _, kind, idx = ref.split("/")
        return raw[kind][int(idx)]

    items: list[SourceItem] = []
    heights = {int(k): v["size"]["height"] for k, v in (raw.get("pages") or {}).items()}

    def walk(node: dict, group_ref: str | None) -> None:
        for child in node.get("children", []):
            ref = child["$ref"]
            kind = ref.split("/")[1]
            n = resolve(ref)
            if kind == "groups":
                walk(n, ref)
                continue
            text = n.get("text", "")
            items.append(
                SourceItem(
                    ref=ref,
                    label=n.get("label", ""),
                    layer=n.get("content_layer", "body"),
                    orig=n.get("orig") or text,
                    text=text,
                    marker=n.get("marker") or None,
                    enumerated=n.get("enumerated"),
                    group_ref=group_ref,
                    provenance=_provenance(n),
                    table=_table(n, heights) if kind == "tables" else None,
                )
            )

    walk(raw["body"], None)
    walk(raw["furniture"], None)

    origin = raw.get("origin") or {}
    info = SourceInfo(
        filename=origin.get("filename"),
        mimetype=origin.get("mimetype"),
        docling_schema=raw.get("schema_name"),
        docling_version=raw.get("version"),
        docling_binary_hash=str(origin["binary_hash"]) if "binary_hash" in origin else None,
        docling_json_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        num_pages=len(raw.get("pages", {})),
    )
    return info, items
