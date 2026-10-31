"""Table-of-contents normalization: logical TOC entries rebuilt from Docling's raw TOC items.

Docling splits or merges TOC lines ("§ 1 Anwendungsbereich § 2 Begriffe" in one item; "§", "46" and
"Blitzschutzanlagen" in different table rows of one visual line; "§ 3 § 4" in one cell). The raw TOC elements stay
untouched (ids, text, accounting); ``model.toc_entries`` adds one entry per printed TOC line:

1. lines: each table cell and each multi-heading item is cut into its visual PDF lines (``region_lines`` evidence:
   the text layer clipped to the cell/item box); cells on the same visual line are joined left to right. The
   characters always come from the canonical text (Docling + recorded repairs); the PDF lines only give the
   boundaries. Without evidence, a cell or item is one line.
2. entries: a line starting with a heading marker of the document's profile (German: §, Teil/Kapitel/Abschnitt/
   Unterabschnitt incl. ordinal and letter-spaced forms, Anlage, Artikel) starts an entry; further inline markers
   ("§ n") in the same line start further entries unless they are citations ("nach § 65 Absatz 2"); lines without
   a marker continue the current title.
3. links: ``target_id`` only when kind and number occur exactly once in the body, the titles are equal (letter
   spacing, whitespace and case ignored) and the TOC's enclosing container numbers (Teil/Kapitel/Abschnitt) equal
   the body element's ancestors. Anything less is a ``candidate`` (for review) or ``unmatched``; nothing is invented.

The vocabulary (kinds, levels, containers, markers) is the profile's ``TocVocabulary``; the steps are shared.
TOC entries are navigation, not legal provisions: they never enter the legal structure or the sentences.
"""

from __future__ import annotations

import re

from odos.document_model import BoundingBox, DocumentModel, Element, ParserWarning, TocEntry, TocSpan
from odos.document_model import ElementType as T
from odos.parsing.profiles import TocVocabulary, for_model


# Docling's ASCII normalisation of printed characters, folded 1:1 so offsets stay exact (cells are not restored)
_FOLD = str.maketrans({**dict.fromkeys("„“”‟″", '"'), **dict.fromkeys("‘’‚‛′", "'"), **dict.fromkeys("–—‑‒−", "-"), "⁄": "/", "•": "·"})


def _compact(s: str) -> str:
    return re.sub(r"[\s\x02￾\xad]", "", s).translate(_FOLD)


def _norm_title(s: str | None) -> str:
    return re.sub(r"[\W_]", "", (s or "")).casefold()


# ---- 1. lines --------------------------------------------------------------------------------------------------------
class _Line:
    def __init__(self):
        self.chars: list[tuple[str, int | None, int | None]] = []  # (char, span index, offset in the span's source)
        self.spans: list[TocSpan] = []
        self.texts: list[str] = []  # source text of each span

    def add(self, span: TocSpan, source: str) -> None:
        if self.chars:
            self.chars.append((" ", None, None))
        k = len(self.spans)
        self.spans.append(span)
        self.texts.append(source)
        for o in range(span.start, span.end):
            self.chars.append((source[o], k, o))


def _cut(text: str, lines) -> list[tuple[int, int, object]] | None:
    """Offsets of each PDF line in `text`, or None. A line matches where its non-whitespace characters occur in
    the text; lines not found belong to neighbouring text (a centred heading crossing a cell) and are skipped.
    Docling's text order may differ from the printed order ("§ 52 … § 56 Bauleiter Siebenter Abschnitt …" while the
    page prints the Abschnitt heading first), so a line may match anywhere, but each position only once and all
    of the text must be covered by exactly one line."""
    idx = [i for i, c in enumerate(text) if not c.isspace() and c != "\xad"]
    compact = "".join(text[i] for i in idx).translate(_FOLD)
    used = [False] * len(compact)
    out, cursor = [], 0
    for ln in lines:
        part = _compact(ln.text)
        if not part:
            continue
        hits = [m.start() for m in re.finditer(re.escape(part), compact) if not any(used[m.start() : m.start() + len(part)])]
        if not hits:
            continue
        nxt = [h for h in hits if h >= cursor]
        if nxt and nxt[0] == cursor:
            p = cursor  # the printed order continues Docling's text: the usual case
        elif len(hits) == 1:
            p = hits[0]  # printed elsewhere in Docling's text (Docling's item order differs from the page)
        else:
            return None  # the same line text at several places: its position is not proven
        cursor = p + len(part)
        for k in range(p, p + len(part)):
            used[k] = True
        out.append((idx[p], idx[p + len(part) - 1] + 1, ln))
    return out if out and all(used) else None


def _box(ln) -> BoundingBox:
    return BoundingBox(l=ln.left, t=ln.top, r=ln.right, b=ln.bottom, coord_origin="BOTTOMLEFT")


def _lines(model: DocumentModel, toc: Element, evidence) -> tuple[list[_Line], list[str]]:
    index = model.by_id()
    region = getattr(evidence, "region_lines", None) or {}
    out: list[_Line] = []
    notes: list[str] = []
    for cid in toc.children_ids:
        el = index[cid]
        if el.type not in (T.TOC_ENTRY, T.TABLE) or not el.source_refs:
            continue
        ref = el.source_refs[0]
        page = el.pages[0] if el.pages else None
        if el.type == T.TABLE and el.table is not None:
            strips = []  # (top, bottom, left, TocSpan, source text)
            by_cell: dict[tuple[int, int], list] = {}
            for ln in region.get(ref, []):
                if ln.cell is not None:
                    by_cell.setdefault((ln.cell[0], ln.cell[1]), []).append(ln)
            for c in el.table.cells or []:
                if not c.text.strip():
                    continue
                cut = _cut(c.text, by_cell.get((c.row, c.col), [])) if by_cell.get((c.row, c.col)) else None
                if cut:
                    for s, e, ln in cut:
                        strips.append((ln.top, ln.bottom, ln.left, TocSpan(element_id=el.id, cell=[c.row, c.col], start=s, end=e,
                                       page=ln.page, bbox=_box(ln), bbox_scope="text_line"), c.text))  # fmt: skip
                elif c.bbox is not None:
                    strips.append((c.bbox.t, c.bbox.b, c.bbox.l, TocSpan(element_id=el.id, cell=[c.row, c.col], start=0,
                                   end=len(c.text), page=c.page_no, bbox=c.bbox, bbox_scope="table_cell"), c.text))  # fmt: skip
                else:
                    notes.append(f"{el.id}: cell {c.row},{c.col} has no box; not placed")
            rows: list[list] = []
            for st in sorted(strips, key=lambda s: (-s[0], s[2])):
                top, bottom = st[0], st[1]
                row = next((r for r in rows if min(top, r[0][0]) - max(bottom, r[0][1]) > 0.5 * min(top - bottom, r[0][0] - r[0][1])), None)  # fmt: skip
                if row is None:
                    rows.append([st])
                else:
                    row.append(st)
            for row in rows:
                line = _Line()
                for st in sorted(row, key=lambda s: s[2]):
                    line.add(st[3], st[4])
                out.append(line)
            continue
        text = el.content_text
        cut = _cut(text, region[ref]) if region.get(ref) else None
        prov = el.provenance[0].bbox if el.provenance else None
        for s, e, ln in cut or [(0, len(text), None)]:
            line = _Line()
            line.add(TocSpan(element_id=el.id, start=s, end=e, page=ln.page if ln else page, bbox=_box(ln) if ln else prov,
                             bbox_scope="text_line" if ln else "docling_item"), text)  # fmt: skip
            out.append(line)
    return out, notes


def _reading_order(lines: list[_Line]) -> list[_Line]:
    """The printed order: by page, then column, then top to bottom. Docling's item order inside a TOC page is not
    reliable (BDSG: "Kapitel 6" comes after § 25 although it is printed between § 19 and § 20). Two columns are
    assumed only when at least three lines lie entirely left of the middle at the same height as a line entirely
    right of it; otherwise the page is one column (centred headings included)."""

    def geo(line: _Line):
        b = next((s.bbox for s in line.spans if s.bbox is not None), None)
        p = next((s.page for s in line.spans if s.page is not None), 0)
        return p, b

    by_page: dict[int, list[tuple[_Line, object]]] = {}
    for ln in lines:
        p, b = geo(ln)
        by_page.setdefault(p, []).append((ln, b))
    out: list[_Line] = []
    for page in sorted(by_page):
        rows = by_page[page]
        boxes = [b for _, b in rows if b is not None]
        if len(boxes) != len(rows):  # a line without a box: keep Docling's order on this page
            out.extend(ln for ln, _ in rows)
            continue
        mid = (min(b.l for b in boxes) + max(b.r for b in boxes)) / 2
        left = [b for b in boxes if b.r < mid]
        right = [b for b in boxes if b.l > mid]
        pairs = sum(1 for a in left if any(min(a.t, c.t) - max(a.b, c.b) > 0 for c in right))
        two = pairs >= 3

        def key(row):
            b = row[1]
            return (1 if two and b.l > mid else 0, -b.t, b.l)

        out.extend(ln for ln, _ in sorted(rows, key=key))
    return out


# ---- 2. entries -------------------------------------------------------------------------------------------------------
def _markers(compact: str, voc: TocVocabulary) -> list[tuple[int, int, str, str | None]]:
    """(start, end, kind, number) of every heading marker that starts an entry in a compact line (markers are
    matched on the whitespace-free line: robust to letter spacing "Ka p i t e l 1" and lost spaces)."""
    found = []
    m = voc.ordinal.match(compact) if voc.ordinal else None
    if m:
        found.append((0, m.end(), m.group(2).lower(), str(voc.ordinal_numbers[m.group(1)])))
    else:
        for kind, rx, number in voc.markers:
            m = rx.match(compact)
            if m:
                found.append((0, m.end(), kind, number(m.group(1))))
                break
    inline = next(((rx, number) for kind, rx, number in voc.markers if kind == voc.inline_marker), None)
    for m in inline[0].finditer(compact) if inline else ():  # further "§ n" in the same line
        if m.start() == 0 or (found and m.start() < found[0][1]):
            continue
        if (voc.inline_citation and voc.inline_citation.match(compact[m.end() :])) or compact[m.start() - 1] == compact[m.start()]:
            continue  # a citation ("§ 65 Absatz 2") or a plural marker ("§§ 3 und 4")
        found.append((m.start(), m.end(), voc.inline_marker, inline[1](m.group(1))))
    return found


def _entries(lines: list[_Line], voc: TocVocabulary) -> list[dict]:
    entries: list[dict] = []
    for line in lines:
        keep = [(i, c) for i, c in enumerate(line.chars) if not (c[0].isspace() or c[0] in "\x02￾\xad")]
        compact = "".join(c[0] for _, c in keep)
        marks = _markers(compact, voc)
        if not marks:
            if entries:
                entries[-1]["parts"].append((line, keep[0][0] if keep else 0, len(line.chars)))
            else:
                entries.append({"kind": None, "number": None, "marker": None, "parts": [(line, 0, len(line.chars))]})
            continue
        bounds = [*marks, (len(compact), len(compact), None, None)]
        if marks[0][0] > 0 and entries:  # text before the first marker continues the previous entry
            entries[-1]["parts"].append((line, keep[0][0], keep[marks[0][0]][0]))
        for (s, e, kind, number), nxt in zip(marks, bounds[1:]):
            ls, me = keep[s][0], keep[e - 1][0] + 1
            le = keep[nxt[0]][0] if nxt[0] < len(keep) else len(line.chars)
            marker = "".join(c[0] for c in line.chars[ls:me])
            entries.append({"kind": kind, "number": number, "marker": re.sub(r"\s+", " ", marker).strip(),
                            "parts": [(line, ls, le)], "title_from": me})  # fmt: skip
    return entries


def _spans(parts) -> list[TocSpan]:
    out = []
    for line, a, b in parts:
        by: dict[int, list[int]] = {}
        for ch, k, o in line.chars[a:b]:
            if k is not None and not ch.isspace():
                by.setdefault(k, []).append(o)
        for k, offs in by.items():
            sp = line.spans[k]
            out.append(sp.model_copy(update={"start": min(offs), "end": max(offs) + 1}))
    return out


def _title(entry) -> str | None:
    pieces = []
    for n, (line, a, b) in enumerate(entry["parts"]):
        start = entry.get("title_from", a) if n == 0 else a
        pieces.append("".join(c[0] for c in line.chars[start:b]))
    t = re.sub(r"\s+", " ", " ".join(pieces)).strip()
    return t or None


# ---- 3. links ---------------------------------------------------------------------------------------------------------
def _ancestors(model: DocumentModel, el: Element, voc: TocVocabulary) -> dict[str, str]:
    out = {}
    for a in model.path(el.id)[:-1]:
        if a.type in voc.kinds and voc.kinds[a.type] in voc.containers:
            out[voc.kinds[a.type]] = a.number
    return out


def normalize_toc(model: DocumentModel, evidence=None) -> dict:
    index = model.by_id()
    toc = index.get("doc/toc")
    model.toc_entries = []
    if toc is None:
        return {"toc": False}
    voc = for_model(model).toc
    KIND, LEVEL, CONTAINERS = voc.kinds, voc.levels, voc.containers
    lines, notes = _lines(model, toc, evidence)
    raw = _entries(_reading_order(lines), voc)
    body: dict[tuple[str, str], list[Element]] = {}
    for e in model.elements:
        if e.region == "body" and e.type in KIND and e.number:
            body.setdefault((KIND[e.type], e.number), []).append(e)
    context: dict[str, str] = {}
    seen: dict[str, int] = {}
    for r in raw:
        kind, number = r["kind"], r["number"]
        title = _title(r)
        spans = _spans(r["parts"])
        src = list(dict.fromkeys(s.element_id for s in spans))
        if kind is None:
            base = "toc/line"
        else:
            base = f"toc/{kind}-{number}" if number else f"toc/{kind}"
        seen[base] = seen.get(base, 0) + 1
        eid = base if seen[base] == 1 else f"{base}~{seen[base]}"
        if kind in CONTAINERS:  # a container entry opens a new scope for the entries below it
            lvl = LEVEL[kind]
            context = {k: v for k, v in context.items() if LEVEL[k] < lvl}
            context[kind] = number
        if kind is None:
            model.toc_entries.append(TocEntry(id=eid, kind="text", marker="", title=title, level=9, source_element_ids=src,
                                              source_spans=spans, status="ambiguous", evidence="a TOC line without a heading marker before the first entry"))  # fmt: skip
            continue
        cands = body.get((kind, number), []) if number else []
        expect = {k: v for k, v in context.items() if LEVEL[k] < LEVEL[kind]}
        fits = [c for c in cands if all(_ancestors(model, c, voc).get(k) == v for k, v in expect.items())]
        status, target, why = "unmatched", None, "no body element with this kind and number"
        if len(fits) > 1:
            status, why = "candidate", f"{len(fits)} body elements share kind, number and enclosing headings"
        elif len(fits) == 1:
            c = fits[0]
            if bool(title) and _norm_title(title) == _norm_title(c.title):
                status, target, why = "linked", c.id, "kind, number, title and enclosing headings agree"
            else:
                status, why = "candidate", f"title differs ({title!r} vs {c.title!r})"
            cands = fits
        elif cands:
            status = "candidate"
            why = f"hierarchy differs (TOC {expect} vs body {[_ancestors(model, c, voc) for c in cands]})"
        entry = TocEntry(id=eid, kind=kind, marker=r["marker"] or "", number=number, title=title, level=LEVEL[kind],
                         source_element_ids=src, source_spans=spans, target_id=target,
                         candidate_ids=[c.id for c in cands] if status == "candidate" else [], status=status, evidence=why)  # fmt: skip
        model.toc_entries.append(entry)
        if status != "linked":
            model.warnings.append(ParserWarning(code="TOC_ENTRY_UNRESOLVED", severity="info", element_id=src[0] if src else None,
                                                message=f"TOC entry {r['marker']!r} {title!r}: {status}, {why}."))  # fmt: skip
    linked = {e.target_id for e in model.toc_entries if e.target_id}
    headings = [e for e in model.elements if e.region == "body" and e.type in voc.provisions]
    return {
        "toc": True,
        "entries": len(model.toc_entries),
        "linked": sum(e.status == "linked" for e in model.toc_entries),
        "candidate": sum(e.status == "candidate" for e in model.toc_entries),
        "unmatched": sum(e.status == "unmatched" for e in model.toc_entries),
        "ambiguous": sum(e.status == "ambiguous" for e in model.toc_entries),
        "body_sections_without_toc_link": [e.id for e in headings if e.id not in linked],
        "notes": notes,
    }


def regenerate_after_corrections(model: DocumentModel, corrected_ids: set[str]) -> None:
    """Review: entries built from a corrected raw TOC element are derived data, so they are rebuilt from the
    reviewed text (no PDF line evidence any more: the corrected element counts as one line per item/cell), never
    edited. Linking uses the same rules; entries of other raw elements stay exactly as they were."""
    affected = [e for e in model.toc_entries if set(e.source_element_ids) & corrected_ids]
    if not affected:
        return
    tmp = model.model_copy(deep=True)
    tmp.warnings = []
    normalize_toc(tmp, None)
    fresh = [e for e in tmp.toc_entries if set(e.source_element_ids) & corrected_ids]
    keep = [e for e in model.toc_entries if e not in affected]
    taken = {e.id for e in keep}
    for e in fresh:
        if e.id in taken:
            e.id = f"{e.id}~reviewed"
        taken.add(e.id)
        e.evidence = f"regenerated from reviewed text: {e.evidence}"
    at = model.toc_entries.index(affected[0])
    before = [e for e in model.toc_entries[:at] if e not in affected]
    after = [e for e in model.toc_entries[at:] if e not in affected]
    model.toc_entries = [*before, *fresh, *after]
