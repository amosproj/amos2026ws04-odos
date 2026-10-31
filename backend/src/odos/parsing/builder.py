"""Building the canonical element tree: shared by every legal profile.

A profile's recognizer decides *what* an item is; the builder turns that decision into an Element with a stable id,
the source evidence of its items (spans, repairs, highlight geometry, uncertainty from preprocessing) and its
place in the open-container stack. Element ids are `<parent id>/<local>`; a collision gets `~2`, `~3`, ... and a
DUPLICATE_ID_RESOLVED warning, so ids never silently change meaning.
"""

from __future__ import annotations

from odos.normalization.docling_reader import SourceItem
from odos.normalization.hygiene import search_normalize
from odos.document_model import Element, ElementType as T, ParserWarning, SourceSpan

ROOT_ID = "doc"


class StructureBuilder:
    """Element factory, id allocation and the stack of open containers. `levels` orders the profile's units."""

    def __init__(self, levels: dict[T, int | float]):
        self.levels = levels
        self.elements: list[Element] = []
        self.furniture: list[Element] = []
        self.warnings: list[ParserWarning] = []
        self.index: dict[str, Element] = {}
        self.counters: dict[tuple[str, str], int] = {}
        self.stack: list[Element] = []  # open structural containers, root excluded
        self.root = Element(id=ROOT_ID, type=T.DOCUMENT, region="document")
        self.index[ROOT_ID] = self.root
        self.elements.append(self.root)

    def warn(self, code, message, el=None, item=None, severity="warning"):
        self.warnings.append(
            ParserWarning(
                code=code, message=message, severity=severity,
                element_id=el.id if el else None,
                source_ref=item.ref if item else (el.source_refs[0] if el and el.source_refs else None),
            )
        )  # fmt: skip

    def unique_id(self, parent: Element, local: str) -> str:
        base = f"{parent.id}/{local}"
        if base not in self.index:
            return base
        n = 2
        while f"{base}~{n}" in self.index:
            n += 1
        return f"{base}~{n}"

    def add(self, item: SourceItem | None, type_: T, parent: Element, region: str, *,
            local: str, number=None, marker=None, title=None, content=None,
            reasons: list[str] | None = None, merge: list[SourceItem] | None = None) -> Element:  # fmt: skip
        eid = self.unique_id(parent, local)
        if eid.split("/")[-1] != local:
            self.warn("DUPLICATE_ID_RESOLVED",
                      f"'{parent.id}/{local}' already exists; used '{eid}'", severity="warning")  # fmt: skip
        el = Element(
            id=eid, type=type_, region=region, parent_id=parent.id, number=number,
            marker=marker, title=title,
            original_text=item.orig if item else "",
            content_text=content if content is not None else (item.orig if item else ""),
            table=item.table if item else None,
            source_refs=[item.ref] if item else [],
            docling_label=item.label if item else None,
            pages=item.pages if item else [],
            provenance=list(item.provenance) if item else [],
            uncertain=bool(reasons), uncertainty_reasons=reasons or [],
        )  # fmt: skip
        for extra in merge or []:  # e.g. a heading whose title Docling put into the next item
            el.source_refs.append(extra.ref)
            el.provenance.extend(extra.provenance)
            el.pages = sorted({*el.pages, *extra.pages})
            el.original_text += "\n" + extra.orig
        if item is not None:
            apply_source_fields(el, [item, *(merge or [])])
            for r in el.text_repairs:
                if r.status == "unresolved":
                    self.warn("LINE_END_HYPHEN_UNRESOLVED", f"Page {r.page}: the PDF prints a hyphen at a line end and "
                              f"neither the rules nor the document decide whether it belongs to the word; the printed "
                              f"hyphen is kept ({r.evidence}).", el, severity="info")  # fmt: skip
        self.index[eid] = el
        parent.children_ids.append(eid)
        self.elements.append(el)
        return el

    def seq_local(self, parent: Element, kind: str) -> str:
        n = self.counters.get((parent.id, kind), 0) + 1
        self.counters[(parent.id, kind)] = n
        return f"{kind}-{n}"

    def level(self, el: Element) -> int | float:
        return self.levels[el.type]

    def pop_to_below(self, level: int | float) -> None:
        while self.stack and self.level(self.stack[-1]) >= level:
            self.stack.pop()


def furniture_element(item: SourceItem, eid: str, type_: T) -> Element:
    """A page header/footer/decoration kept outside the legal tree (the id scheme belongs to the profile)."""
    el = Element(id=eid, type=type_, region="furniture", original_text=item.orig, content_text=item.orig,
                 source_refs=[item.ref], docling_label=item.label, pages=item.pages, provenance=item.provenance)  # fmt: skip
    apply_source_fields(el, [item])
    return el


def apply_source_fields(el: Element, parts: list[SourceItem]) -> None:
    """Carry the preprocessing evidence of the element's source items over to the element (never its text)."""
    if any(p.span is not None or p.parts for p in parts):
        for p in parts:
            if p.parts:  # reading-order repair: the verbatim slices this text is made of (p.orig joins them by " ")
                el.source_spans.extend(p.parts)
                el.source_refs += [s.ref for s in p.parts if s.ref not in el.source_refs]
                pieces, pos = [], 0
                for s in p.parts:
                    pieces.append(p.orig[pos : pos + s.end - s.start])
                    pos += s.end - s.start + 1
                el.original_text = "\n".join(pieces)  # like merged items: the source pieces, one per line
                continue
            s, e = p.span if p.span is not None else (0, len(p.orig))
            prov = p.provenance[0] if p.provenance else None
            el.source_spans.append(SourceSpan(ref=p.ref, start=s, end=e, page_no=prov.page_no if prov else None,
                                              bbox=prov.bbox if prov else None))  # fmt: skip
    for p in parts:
        for f in p.boundary_flags:
            el.uncertain = True
            el.uncertainty_reasons.append(f"segment_boundary_uncertain:{f}")
        for f in p.order_flags:
            if f"reading_order_uncertain:{f}" not in el.uncertainty_reasons:
                el.uncertain = True
                el.uncertainty_reasons.append(f"reading_order_uncertain:{f}")
    flags: list[str] = []
    for p in parts:
        flags += [f for f in p.hygiene_flags if f not in flags]
    el.hygiene_flags = flags
    # exact rectangles only when every partial source piece of the element has them
    if any(p.span is not None or p.parts for p in parts) and all(p.highlight_boxes for p in parts):
        el.highlight_boxes = [b for p in parts for b in p.highlight_boxes]
    # source-text restoration (odos.normalization.source_text): keep Docling's text and every repair's evidence
    el.text_repairs = [r for p in parts for r in p.text_repairs]
    if any(p.docling_orig is not None for p in parts) and not any(p.parts for p in parts):
        el.docling_text = "\n".join(p.docling_orig if p.docling_orig is not None else p.orig for p in parts)
    for r in el.text_repairs:
        if r.status == "unresolved" and f"source_text_uncertain:{r.rule}" not in el.uncertainty_reasons:
            el.uncertain = True
            el.uncertainty_reasons.append(f"source_text_uncertain:{r.rule}")
    st, _ = search_normalize(el.original_text)
    el.search_text = st if st != el.original_text else None
