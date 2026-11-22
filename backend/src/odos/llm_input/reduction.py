"""V1: omit navigation/front matter and recital material, never summarize operative text."""
from odos.llm_input.common import prune_document, walk

NON_OPERATIVE = {"preamble", "preambleFormula", "recital", "recitalsIntro", "citation", "enactingFormula"}


def reduce_document(document):
    """Return a separate Legal JSON-shaped value and a removal audit. Signatures and annexes stay."""
    def exclude(node):
        if node.get("type") in NON_OPERATIVE:
            return "Preamble/recital material, not operative provisions"
        return None

    # Navigation and duplicate cover metadata are removed by location, not text matching.
    # Keep their top-level keys for compatibility with the original document format.
    source = dict(document)
    source["frontMatter"] = []
    source["tableOfContents"] = []
    if "tableOfContentsEntries" in source:
        source["tableOfContentsEntries"] = []
    reduced, removed = prune_document(source, exclude)
    for node in walk(reduced.get("structure", [])):
        node.pop("germanType", None)
        node.pop("nativeType", None)
        # Printed structural labels only. Sentence offset markers and footnote markers stay.
        if isinstance(node.get("marker"), str) and node.get("type") and node.get("number") is not None:
            node.pop("marker")
    removed = [{"id": n.get("id"), "type": n.get("type"), "reason": "Front matter or table of contents"}
               for key in ("frontMatter", "tableOfContents") for n in document.get(key, [])] + removed
    return reduced, removed
