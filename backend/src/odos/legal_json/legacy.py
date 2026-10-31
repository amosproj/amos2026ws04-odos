"""Legacy `document.json` schema 1.0: the downgrade of a 1.1 document and what it loses.

ODOS writes only schema 1.1 (`legal_json.view`). 1.0 (`schemas/odos-legal-json/1.0/`, frozen and hash-pinned) is
served to 1.0 consumers through `downgrade_to_1_0`, which every JSON validation report checks against the frozen
schema, and `downgrade_information_loss` reports what such a consumer does not get. Nothing here is used to export.
"""

from __future__ import annotations

# fields added in 1.1 (all optional): dropped by `downgrade_to_1_0`, which gives a document valid against the frozen 1.0 schema
ADDED_IN_1_1 = {"document": ("tableOfContentsEntries", "sentences"), "footnote": ("anchorElementIds", "references"),
                "cell": ("source",)}  # fmt: skip


def downgrade_to_1_0(data: dict) -> dict:
    """A 1.0 document from a 1.1 one: the 1.1 additions removed, every 1.0 field unchanged."""
    out = {k: v for k, v in data.items() if k not in ADDED_IN_1_1["document"]}
    out["schemaVersion"] = "1.0"
    out["footnotes"] = [{k: v for k, v in f.items() if k not in ADDED_IN_1_1["footnote"]} for f in data["footnotes"]]

    def nodes(ns):
        res = []
        for n in ns:
            n = dict(n)
            if "rows" in n:
                n["rows"] = [[{"text": c["text"]} for c in row] for row in n["rows"]]
            if "children" in n:
                n["children"] = nodes(n["children"])
            res.append(n)
        return res

    for key in ("frontMatter", "tableOfContents", "structure"):
        out[key] = nodes(data[key])
    out["footnotes"] = [{**f, "content": nodes(f["content"])} if "content" in f else f for f in out["footnotes"]]
    return out


def downgrade_information_loss(data: dict) -> dict:
    """What a 1.0 consumer of `downgrade_to_1_0(data)` no longer sees: for each 1.1 field, the number of values
    dropped and the first JSON paths. `footnotes_with_several_anchors`: footnotes whose anchors 1.0 can only give as
    `anchorElementId = null` (a single anchor survives as `anchorElementId`, so it is not lost)."""
    dropped: dict[str, dict] = {}

    def note(field_: str, path: str, n: int) -> None:
        d = dropped.setdefault(field_, {"values": 0, "first_paths": []})
        d["values"] += n
        if len(d["first_paths"]) < 5:
            d["first_paths"].append(path)

    def walk(ns: list, path: str) -> None:
        for i, n in enumerate(ns):
            for r, row in enumerate(n.get("rows") or []):
                for c, cell in enumerate(row):
                    for k in ADDED_IN_1_1["cell"]:
                        if cell.get(k) is not None:
                            note(f"cell.{k}", f"{path}/{i}/rows/{r}/{c}/{k}", 1)
            walk(n.get("children") or [], f"{path}/{i}/children")

    for k in ADDED_IN_1_1["document"]:
        if data.get(k):
            note(k, k, len(data[k]))
    footnotes = data.get("footnotes") or []
    for i, f in enumerate(footnotes):
        for k in ADDED_IN_1_1["footnote"]:
            if f.get(k):
                note(f"footnote.{k}", f"footnotes/{i}/{k}", len(f[k]))
    for key in ("frontMatter", "tableOfContents", "structure"):
        walk(data.get(key) or [], key)
    for i, f in enumerate(footnotes):
        walk(f.get("content") or [], f"footnotes/{i}/content")
    several = [f["id"] for f in footnotes if len(f.get("anchorElementIds") or []) > 1]
    return {"lossless": not dropped, "dropped": dropped, "footnotes_with_several_anchors": several}
