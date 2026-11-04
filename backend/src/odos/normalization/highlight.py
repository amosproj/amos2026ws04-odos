"""Exact highlight rectangles for elements that cover only part of a Docling item (split or repaired items).

Docling gives one box per item; when an item holds several paragraphs, that box is only an approximation for
each of them. Here the item's text is aligned with the PDF's glyphs (``reading_order`` evidence ``glyph_lines``)
and every element gets one rectangle per text line it actually occupies. Proven only when all of this holds,
otherwise nothing is set and the approximate item box stays in use:

* the item's lines are whole PDF lines inside the item's box, taken top to bottom; lines of other items in the
  same box (overlapping layout) are skipped, but only if their text is not also the next text of this item;
* every non-space character of the item is matched, in order, by exactly one glyph (whitespace, hyphens and soft
  hyphens are ignored on both sides; a ligature glyph counts for its letters);
* no line text that the item uses occurs on another unused line of the box (repeated lines: not provable).
"""

from __future__ import annotations

from odos.document_model import BoundingBox, Provenance
from odos.normalization.source_text import LIGATURES

IGNORE = set("-\xad\x02￾")


def _compact_glyphs(line) -> list[tuple[str, float, float]]:
    out = []
    for ch, (left, right) in zip(line.text, line.xs):
        if ch.isspace() or ch in IGNORE:
            continue
        for c in LIGATURES.get(ch, ch):
            out.append((c, left, right))
    return out


def glyph_map(text: str, boxes: list[tuple[int, BoundingBox]], glyph_lines) -> dict[int, tuple[int, int, float, float]] | None:
    """text index -> (page, line index, left, right) for every counted character of `text`, or None (not provable)."""
    keep = [i for i, c in enumerate(text) if not c.isspace() and c not in IGNORE]
    want = "".join(text[i] for i in keep)
    if not want:
        return None
    cands = []  # (page, line index, line, compact glyphs)
    for page, b in boxes:
        lines = glyph_lines.get(page) or glyph_lines.get(str(page))  # type: ignore[call-overload]
        if not lines or b is None or b.coord_origin.upper() != "BOTTOMLEFT":
            return None
        for k, ln in enumerate(lines):
            mid = (ln.top + ln.bottom) / 2
            if b.b - 1 <= mid <= b.t + 1 and ln.xs and min(x[0] for x in ln.xs) >= b.l - 2 and max(x[1] for x in ln.xs) <= b.r + 2:
                g = _compact_glyphs(ln)
                if g:
                    cands.append((page, k, ln, g))
    out: dict[int, tuple[int, int, float, float]] = {}
    pos, used = 0, set()
    for page, k, ln, g in cands:
        s = "".join(c for c, _, _ in g)
        if want[pos : pos + len(s)] != s:
            continue  # a line of another item in the same box
        for n, (_, left, right) in enumerate(g):
            out[keep[pos + n]] = (page, k, left, right)
        pos += len(s)
        used.add((page, k))
        if pos == len(want):
            break
    if pos != len(want):
        return None
    texts = {"".join(c for c, _, _ in g) for p, k, _, g in cands if (p, k) in used}
    if any("".join(c for c, _, _ in g) in texts for p, k, _, g in cands if (p, k) not in used):
        return None  # the same line text also stands elsewhere in the box: which one is ours is not proven
    return out


def boxes_for(text: str, start: int, end: int, mapping, glyph_lines) -> list[Provenance] | None:
    """One rectangle per PDF line for text[start:end], or None if a counted character has no glyph."""
    rows: dict[tuple[int, int], list[float]] = {}
    for i in range(start, end):
        c = text[i]
        if c.isspace() or c in IGNORE:
            continue
        hit = mapping.get(i)
        if hit is None:
            return None
        page, k, left, right = hit
        r = rows.setdefault((page, k), [left, right])
        r[0], r[1] = min(r[0], left), max(r[1], right)
    out = []
    for (page, k), (left, right) in sorted(rows.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        ln = (glyph_lines.get(page) or glyph_lines.get(str(page)))[k]  # type: ignore[index]
        out.append(Provenance(page_no=page, bbox=BoundingBox(l=left, t=ln.top, r=right, b=ln.bottom, coord_origin="BOTTOMLEFT")))
    return out or None
