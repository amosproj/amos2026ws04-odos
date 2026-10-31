"""Document-specific structural rules for `document.json`, checked in addition to the JSON Schema.

For each legal system, a structural unit may only appear under the listed parents ("document" =
top level of `structure`; the table is the profile's `json_nesting`). The same English name can mean different units: a German `section` is a
§ (Paragraph), an EU `section` is an ABSCHNITT inside a chapter, and the rules keep them apart.
"""

from __future__ import annotations

from odos.legal_json.view import LegalDocument, Node
from odos.parsing.profiles import for_legal_system

# text-like blocks may stand in any unit (introductory text, text after a list, a table in an annex)
BLOCKS = {"text", "item", "table", "picture"}
LEAVES = BLOCKS | {"tocEntry"}

FRONT = {"frontMatter", "documentTitle"}
TOC = {"tableOfContents"}


def _walk(n: Node, parent: str, system: str, errors: list[str]) -> None:
    if n.type in BLOCKS:
        if parent in LEAVES:
            errors.append(f"{n.id}: '{n.type}' inside '{parent}', which cannot contain anything")
    else:
        allowed = for_legal_system(system).json_nesting.get(n.type)
        if allowed is None:
            errors.append(f"{n.id}: '{n.type}' is not a structural unit of {system} documents")
        elif parent not in allowed:
            errors.append(f"{n.id}: '{n.type}' not allowed under '{parent}' in {system} documents (allowed: {', '.join(sorted(allowed))})")
        elif n.type == "letter" and parent == "letter" and n.markerStyle != "alpha_lower_double":
            errors.append(f"{n.id}: a letter under a letter must be a double letter like 'aa)'")
    if n.type in LEAVES and n.children:
        errors.append(f"{n.id}: '{n.type}' must not have children")
    for c in n.children:
        _walk(c, n.type, system, errors)


def _all_nodes(doc: LegalDocument):
    stack = [*doc.frontMatter, *doc.tableOfContents, *doc.structure, *(c for f in doc.footnotes for c in f.content)]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(n.children)


def validate_structure(doc: LegalDocument) -> list[str]:
    errors: list[str] = []
    for n in doc.structure:
        _walk(n, "document", doc.legalSystem, errors)
    for area, allowed, children in (("frontMatter", FRONT, BLOCKS), ("tableOfContents", TOC, BLOCKS | {"tocEntry"})):
        for n in getattr(doc, area):
            if n.type not in allowed:
                errors.append(f"{n.id}: '{n.type}' does not belong in {area}")
            for c in n.children:
                if c.type not in children or c.children:
                    errors.append(f"{c.id}: '{c.type}' does not belong in {area}")
    for f in doc.footnotes:
        for c in f.content:
            if c.type not in BLOCKS or c.children:
                errors.append(f"{c.id}: footnote content must be text blocks, found '{c.type}'")
    ids = [n.id for n in _all_nodes(doc)] + [f.id for f in doc.footnotes]
    seen, dupes = set(), set()
    for i in ids:
        (dupes if i in seen else seen).add(i)
    errors += [f"duplicate id: {i}" for i in sorted(dupes)]
    anchorable = set()  # a footnote stands in the legal structure or in the front matter (e.g. a title line "…2024*")
    stack = [*doc.structure, *doc.frontMatter]
    while stack:
        n = stack.pop()
        anchorable.add(n.id)
        stack.extend(n.children)
    for f in doc.footnotes:
        if f.anchorElementId is not None and f.anchorElementId not in anchorable:
            errors.append(f"{f.id}: anchorElementId '{f.anchorElementId}' is not an element of the structure or front matter")
        if f.anchorElementId is not None and f.anchorElementIds and f.anchorElementIds != [f.anchorElementId]:
            errors.append(f"{f.id}: anchorElementId must be the only entry of anchorElementIds")
        if f.anchorElementId is None and len(f.anchorElementIds) == 1:
            errors.append(f"{f.id}: a single anchor must also be given as anchorElementId")
        for a in [*f.anchorElementIds, *(r.elementId for r in f.references)]:
            if a not in anchorable:
                errors.append(f"{f.id}: anchor '{a}' is not an element of the structure or front matter")
    errors += _check_sentences(doc) + _check_toc_entries(doc)
    return errors


def _texts(doc: LegalDocument) -> dict[str, str | None]:
    return {n.id: n.text for n in _all_nodes(doc)}


def _check_sentences(doc: LegalDocument) -> list[str]:
    import hashlib

    errors, texts, nodes_ids = [], _texts(doc), {n.id for n in _all_nodes(doc)}
    seen_ids: set[str] = set()
    taken: dict[str, list[tuple[int, int, str]]] = {}
    for s in doc.sentences:
        if s.id in seen_ids or s.id in nodes_ids:
            errors.append(f"sentence id '{s.id}' is not unique")
        seen_ids.add(s.id)
        if s.unitId not in nodes_ids:
            errors.append(f"{s.id}: unit '{s.unitId}' is not a node")
        if not s.ranges:
            errors.append(f"{s.id}: no text ranges")
        for r in [*s.ranges, *([s.marker] if s.marker else [])]:
            text = texts.get(r.elementId)
            if text is None:
                errors.append(f"{s.id}: range on '{r.elementId}', which has no text")
                continue
            if not (0 <= r.start < r.end <= len(text)):
                errors.append(f"{s.id}: range [{r.start}, {r.end}) outside the text of '{r.elementId}' ({len(text)} code points)")
            if hashlib.sha256(text.encode("utf-8")).hexdigest() != r.textSha256:
                errors.append(f"{s.id}: textSha256 does not match the text of '{r.elementId}'")
        for r in s.ranges:
            for a, b, other in taken.get(r.elementId, []):
                if r.start < b and a < r.end:
                    errors.append(f"{s.id}: overlaps sentence {other} in '{r.elementId}'")
            taken.setdefault(r.elementId, []).append((r.start, r.end, s.id))
        if s.marker and not any(r.elementId == s.marker.elementId and r.start <= s.marker.start < r.end for r in s.ranges):
            errors.append(f"{s.id}: the printed number lies outside the sentence")
    return errors


def _check_toc_entries(doc: LegalDocument) -> list[str]:
    errors = []
    structure = set()
    stack = list(doc.structure)
    while stack:
        n = stack.pop()
        structure.add(n.id)
        stack.extend(n.children)
    toc = {n.id: n for n in _all_nodes_of(doc.tableOfContents)}
    ids = [t.id for t in doc.tableOfContentsEntries]
    errors += [f"TOC entry id '{i}' is not unique" for i in sorted({i for i in ids if ids.count(i) > 1})]
    for t in doc.tableOfContentsEntries:
        if t.targetElementId is not None and t.targetElementId not in structure:
            errors.append(f"{t.id}: targetElementId '{t.targetElementId}' is not an element of the structure")
        for sp in t.sourceSpans:
            n = toc.get(sp.elementId)
            if n is None:
                errors.append(f"{t.id}: source '{sp.elementId}' is not a tableOfContents node")
                continue
            text = (n.rows[sp.cell[0]][sp.cell[1]].text if n.rows and sp.cell and sp.cell[0] < len(n.rows) and sp.cell[1] < len(n.rows[sp.cell[0]]) else None) if sp.cell else n.text  # fmt: skip
            if text is None or not (0 <= sp.start < sp.end <= len(text)):
                errors.append(f"{t.id}: source span [{sp.start}, {sp.end}) does not fit '{sp.elementId}'{' cell ' + str(sp.cell) if sp.cell else ''}")
    return errors


def _all_nodes_of(nodes):
    stack = list(nodes)
    while stack:
        n = stack.pop()
        yield n
        stack.extend(n.children)
