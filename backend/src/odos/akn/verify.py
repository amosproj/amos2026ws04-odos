"""Compares the generated XML against the Internal Document Model."""

from __future__ import annotations

import re

from lxml import etree

from odos.akn.generator import GenerationResult
from odos.akn.mapping import AKN_NS
from odos.document_model import DocumentModel

A = f"{{{AKN_NS}}}"


def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


NOTE_TYPES = ("footnote", "footnote_heading")


def expected_atoms(model: DocumentModel, result: GenerationResult, notes: bool = False) -> list[tuple[str, str]]:
    """(eId, text) atoms in the order the Internal Document Model dictates.

    Footnotes live in meta/notes (before the body), so they are compared as a separate sequence."""
    by_id = {e.model_id: e for e in result.entries}
    atoms: list[tuple[str, str]] = []
    for mid in result.included_ids:
        t, el = by_id[mid], model.by_id()[mid]
        if (t.model_type in NOTE_TYPES) != notes:
            continue
        if t.model_type == "footnote_heading":
            atoms.append((t.heading_eId, el.title or el.original_text))
            continue
        if t.model_type == "table":
            continue
        if t.num_eId and el.marker:
            atoms.append((t.num_eId, el.marker))
        if t.heading_eId and el.title:
            atoms.append((t.heading_eId, el.title))
        if t.text_eId and t.role != "container_shell":
            atoms.append((t.text_eId, t.content_text if t.model_type != "paragraph" else el.content_text))
    return atoms


def actual_atoms(xml: bytes, eids: set[str]) -> list[tuple[str, str]]:
    root = etree.fromstring(xml)
    return [(n.get("eId"), n.text or "") for n in root.iter() if isinstance(n.tag, str) and n.get("eId") in eids and (n.text or "") != ""]  # fmt: skip


def verify_text(model: DocumentModel, result: GenerationResult) -> dict:
    exp = expected_atoms(model, result)
    act = actual_atoms(result.xml, {e for e, _ in exp})
    nexp = expected_atoms(model, result, notes=True)
    nact = actual_atoms(result.xml, {e for e, _ in nexp})
    # model order is preserved by the XML only if the two sequences are identical
    mismatches = [{"eId": e, "expected": t, "actual": dict(act).get(e)} for e, t in exp if dict(act).get(e) != t]  # fmt: skip
    # each element's marker + text reproduces Docling's verbatim `orig` (whitespace-normalised)
    orig_diffs = []
    index = model.by_id()
    for t in result.entries:
        if t.model_type in ("table", "footnote", "footnote_heading", "front_matter"):
            continue
        el = index[t.model_id]
        rebuilt = " ".join(x for x in (el.marker, el.title if el.title else el.content_text) if x)
        if collapse_ws(rebuilt) != collapse_ws(el.original_text):
            orig_diffs.append({"model_id": el.id, "rebuilt": rebuilt[:80], "original": el.original_text[:80]})
    return {
        "atoms_expected": len(exp),
        "atoms_in_xml": len(act),
        "same_order_and_text": exp == act and nexp == nact,
        "note_atoms_expected": len(nexp),
        "text_mismatches": mismatches,
        "original_text_reconstruction_diffs": orig_diffs,
        "characters_compared": sum(len(t) for _, t in exp),
    }
