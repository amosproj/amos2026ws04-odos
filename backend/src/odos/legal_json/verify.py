"""Checks `document.json` against the canonical model it was serialized from."""

from __future__ import annotations

from collections import Counter

from odos.legal_json.exporter import own_text
from odos.legal_json.view import LegalDocument, Node
from odos.document_model import DocumentModel


def _preorder(nodes: list[Node]) -> list[Node]:
    out: list[Node] = []
    stack = list(reversed(nodes))
    while stack:
        n = stack.pop()
        out.append(n)
        stack.extend(reversed(n.children))
    return out


def verify_export(model: DocumentModel, doc: LegalDocument) -> dict:
    index = model.by_id()
    position = {e.id: i for i, e in enumerate(model.elements)}
    areas = {
        "frontMatter": _preorder(doc.frontMatter),
        "tableOfContents": _preorder(doc.tableOfContents),
        "structure": _preorder(doc.structure),
        "footnotes": [x for f in doc.footnotes for x in [f, *_preorder(f.content)]],
    }
    exported = [x.id for xs in areas.values() for x in xs]
    expected = [e.id for e in model.elements if e.id != model.root_id]
    missing = sorted(set(expected) - set(exported))
    extra = sorted(set(exported) - set(expected))
    duplicated = sorted(i for i, n in Counter(exported).items() if n > 1)
    mismatches = []
    for xs in areas.values():
        for x in xs:
            el = index.get(x.id)
            if el is None:
                continue
            want = {"marker": el.marker, "title": el.title, "text": own_text(el), "pages": list(el.pages)}
            got = {"marker": x.marker, "title": x.title, "text": x.text, "pages": list(x.pages)}
            if want != got:
                mismatches.append({"id": x.id, "expected": want, "exported": got})
    # each area lists its elements in the model's document order
    order = {area: all(position[a.id] < position[b.id] for a, b in zip(xs, xs[1:])) for area, xs in areas.items() if xs}
    # the JSON carries no source references: each exported id leads to its model element, which holds them
    refs = {r for e in [*model.elements, *model.furniture] for r in e.source_refs}
    exported_refs = {r for i in exported if i in index for r in index[i].source_refs}
    untraceable = [i for i in exported if i in index and not _traceable(index[i], index)]
    furniture_refs = {r for e in model.furniture for r in e.source_refs}
    unaccounted = sorted(refs - exported_refs - furniture_refs)
    return {
        "elements_expected": len(expected),
        "elements_exported": len(exported),
        "missing_elements": missing,
        "unexpected_elements": extra,
        "duplicated_elements": duplicated,
        "field_mismatches": mismatches,
        "document_order_preserved": order,
        "source_items": len(refs),
        "source_items_exported": len(exported_refs & refs),
        "source_items_excluded_as_page_furniture": len(furniture_refs - exported_refs),
        "source_items_unaccounted": unaccounted,
        # exported elements that neither themselves nor through their children lead to a Docling item
        "elements_without_source": untraceable[:50],
        "characters_exported": sum(len(x.text or "") + len(x.title or "") + len(x.marker or "") for xs in areas.values() for x in xs),
        "identical_to_model": not (missing or extra or duplicated or mismatches or unaccounted or untraceable) and all(order.values()),
    }


def _traceable(el, index) -> bool:
    """A container without text of its own (an EU preamble) is located through its children."""
    stack = [el]
    while stack:
        e = stack.pop()
        if e.source_refs:
            return True
        stack.extend(index[c] for c in e.children_ids if c in index)
    return False
