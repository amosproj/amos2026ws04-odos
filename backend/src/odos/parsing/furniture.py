"""Lifecycle stage 5 (`engine.finalize_structure`): a running page number / header that Docling labelled as body
text (detected by the hygiene layer) leaves the legal structure for ``model.furniture``. Ids are unchanged.
"""

from __future__ import annotations

from odos.document_model import DocumentModel, ElementType as T


def detach_page_furniture(model: DocumentModel) -> list[str]:
    index = model.by_id()
    moved = []
    for el in list(model.elements):
        if "furniture_labelled_as_body_by_docling" not in el.hygiene_flags or el.children_ids or not el.parent_id:
            continue
        parent = index[el.parent_id]
        parent.children_ids.remove(el.id)
        model.elements.remove(el)
        el.type = T.PAGE_HEADER if "running_header" in el.hygiene_flags else T.PAGE_FOOTER
        el.region = "furniture"
        el.parent_id = None
        el.hygiene_flags.append("moved_out_of_structure_as_page_furniture")
        model.furniture.append(el)
        moved.append(el.id)
    model.furniture.sort(key=lambda e: e.pages[0] if e.pages else 0)  # stable: document order within a page
    return moved
