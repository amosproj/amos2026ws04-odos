"""Shared tree pruning; retained text, IDs, offsets and page references never change."""
from copy import deepcopy


def walk(nodes):
    for node in nodes:
        yield node
        yield from walk(node.get("children", []))


def prune_document(document, exclude):
    result = deepcopy(document)
    removed = []

    def prune(nodes):
        kept = []
        for node in nodes:
            reason = exclude(node)
            if reason:
                removed.append({"id": node.get("id"), "type": node.get("type"),
                                "number": node.get("number"), "title": node.get("title"), "reason": reason})
                continue
            if "children" in node:
                had_children = bool(node["children"])
                node["children"] = prune(node["children"])
                if had_children and not node["children"] and not node.get("text") and not node.get("rows"):
                    continue  # empty structural heading after exclusions
            kept.append(node)
        return kept

    for key in ("structure", "frontMatter", "tableOfContents"):
        if key in result:
            result[key] = prune(result[key])
    ids = {n.get("id") for key in ("structure", "frontMatter", "tableOfContents") for n in walk(result.get(key, []))}
    if "sentences" in result:
        result["sentences"] = [s for s in result["sentences"] if s.get("ranges")
                               and all(x.get("elementId") in ids for x in s["ranges"])]
    if "footnotes" in result:
        notes = []
        for note in result["footnotes"]:
            anchors = note.get("anchorElementIds", [])
            if anchors and not any(a in ids for a in anchors):
                continue
            if anchors:
                note["anchorElementIds"] = [a for a in anchors if a in ids]
            if "references" in note:
                note["references"] = [x for x in note["references"] if x.get("elementId") in ids]
            notes.append(note)
        result["footnotes"] = notes
    if "tableOfContentsEntries" in result:
        result["tableOfContentsEntries"] = [x for x in result["tableOfContentsEntries"] if x.get("targetElementId") in ids]
    return result, removed
