"""Parser regressions; also runnable with unittest without PDF/model dependencies."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from odos.llm_input.artifacts import build_inputs, write_input_artifacts
from odos.llm_input.applicability import EU_ARTICLES, MBO_SECTIONS


def node(kind, number, **extra):
    return {"id": f"doc/{kind}-{number}", "type": kind, "number": str(number),
            "text": f"Original provision {number}: minimum 3 m.", "pages": [1], **extra}


def document(identity="mbo"):
    eu = identity != "mbo"
    return {"id": identity, "title": "EU Machinery" if eu else "MUSTERBAUORDNUNG", "schemaVersion": "2.0",
            "documentType": "eu_regulation" if eu else "de_legislation", "identifiers": {},
            "frontMatter": [node("frontMatter", 1)], "tableOfContents": [node("toc", 1)],
            "structure": [node("article" if eu else "section", n) for n in range(1, 88)],
            "sentences": [], "footnotes": []}


class InputParserTests(unittest.TestCase):
    def test_original_is_not_mutated_and_retained_nodes_are_identical(self):
        d = document(); original = copy.deepcopy(d)
        v1, v2, _ = build_inputs(d)
        self.assertEqual(d, original)
        self.assertEqual(v2["structure"][0], original["structure"][0])
        self.assertEqual(v1["structure"], original["structure"])

    def test_reduction_removes_navigation_and_recitals_keeps_signature_and_technical_annex(self):
        d = document()
        kept = [node("signature", 1, text="Signed Name"), node("annex", 2, rows=[["min", "3 m"]])]
        d["structure"] += [node("preamble", 1, children=[node("recital", 1)])] + kept
        v1, _, _ = build_inputs(d)
        self.assertEqual(v1["frontMatter"], [])
        self.assertEqual(v1["tableOfContents"], [])
        self.assertNotIn("preamble", [n["type"] for n in v1["structure"]])
        self.assertEqual(v1["structure"][-2:], kept)

    def test_only_redundant_node_metadata_is_removed(self):
        d = document()
        d.update({"pageCount": 2, "version": {"date": None}, "subject": "", "identifiers": {}})
        d["structure"] = [node("section", 1, germanType="Paragraph", nativeType="Paragraph", marker="§ 1", title=None)]
        d["sentences"] = [{"id": "s1", "marker": {"elementId": "doc/section-1", "start": 0, "end": 1},
                           "ranges": [{"elementId": "doc/section-1", "start": 0, "end": 5}]}]
        d["footnotes"] = [{"id": "f1", "marker": "*", "text": "Footnote", "anchorElementIds": ["doc/section-1"]}]
        original = copy.deepcopy(d)
        v1, v2, _ = build_inputs(d)
        for view in (v1, v2):
            n = view["structure"][0]
            for key in ("germanType", "nativeType", "marker"):
                self.assertNotIn(key, n)
            self.assertEqual(n["pages"], [1])
            self.assertIsNone(n["title"])
            for key in ("pageCount", "version", "subject", "identifiers", "sentences", "footnotes"):
                self.assertEqual(view[key], original[key])
        self.assertEqual(d, original)

    def test_marker_with_no_structured_number_is_kept(self):
        d = document()
        d["structure"] = [{"id": "unusual", "type": "text", "marker": "*", "text": "Keep this label"}]
        self.assertEqual(build_inputs(d)[0]["structure"], d["structure"])

    def test_eu_exact_article_list(self):
        _, v2, report = build_inputs(document("verordnung-2023-1230"))
        self.assertEqual({str(n) for n in range(1, 88)} - {n["number"] for n in v2["structure"]}, EU_ARTICLES)
        self.assertEqual(report["applicability"]["policy"], "eu-machinery-2023-1230")

    def test_mbo_list_and_keep_rows(self):
        d = document()
        d["structure"] += [node("section", n) for n in ("65a", "65b", "65c", "65d", "85a")] + [node("annex", 1)]
        _, v2, report = build_inputs(d)
        self.assertEqual({x["number"] for x in report["applicability"]["removed"] if x["type"] == "section"}, MBO_SECTIONS)
        remaining = {n["number"] for n in v2["structure"]}
        self.assertTrue({"22", "23", "25", "53", "55", "58", "68", "74", "75", "77", "78", "79", "80", "85a"} <= remaining)
        self.assertFalse(any(n["type"] == "annex" for n in v2["structure"]))

    def test_unknown_document_does_not_get_mbo_or_eu_exclusions(self):
        d = document("unrelated-eu-regulation")
        v1, v2, report = build_inputs(d)
        self.assertEqual(v1, v2)
        self.assertIsNone(report["applicability"]["policy"])

    def test_sentences_and_footnotes_do_not_point_to_deleted_nodes(self):
        d = document()
        d["sentences"] = [{"id": f"s-{n}", "ranges": [{"elementId": f"doc/section-{n}", "start": 0, "end": 3}]} for n in (1, 24)]
        d["footnotes"] = [{"id": "f", "text": "Keep substantive footnote", "anchorElementIds": ["doc/section-1", "doc/section-24"],
                           "references": [{"elementId": "doc/section-1"}, {"elementId": "doc/section-24"}]}]
        _, v2, _ = build_inputs(d)
        self.assertEqual([s["id"] for s in v2["sentences"]], ["s-1"])
        self.assertEqual(v2["footnotes"][0]["anchorElementIds"], ["doc/section-1"])
        self.assertEqual(v2["footnotes"][0]["references"], [{"elementId": "doc/section-1"}])

    def test_parsers_are_idempotent(self):
        _, v2, _ = build_inputs(document())
        self.assertEqual(v2, build_inputs(v2)[1])

    def test_empty_containers_are_pruned_but_retained_numbers_are_not_renumbered(self):
        d = document()
        d["structure"] = [{"id": "chapter", "type": "chapter", "children": [node("section", 24)]}, node("section", 25)]
        _, v2, _ = build_inputs(d)
        self.assertEqual(v2["structure"], [node("section", 25)])

    def test_writing_artifacts_never_changes_original_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            raw = json.dumps(document(), indent=4).encode()
            (directory / "document.json").write_bytes(raw)
            write_input_artifacts(json.loads(raw), directory)
            self.assertEqual((directory / "document.json").read_bytes(), raw)
            self.assertTrue((directory / "llm_input_v1.json").is_file())
            self.assertTrue((directory / "llm_applicability_input_v2.json").is_file())
            self.assertTrue((directory / "llm_input_report.json").is_file())


if __name__ == "__main__":
    unittest.main()
