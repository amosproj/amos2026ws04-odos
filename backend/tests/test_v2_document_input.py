"""V2 regression tests on the actual chunked extraction path; no AWS calls."""
import copy
import json
import unittest
from odos.llm.bedrock import BedrockConfig, BedrockResponse
from odos.llm.document_extraction import check_document_request, extract_document, plan_chunks, prepare_chunk
from odos.llm.rule_extraction import InvalidScopeError, _walk
from odos.llm_input.artifacts import build_inputs


def document():
    return {"id": "mbo", "title": "MUSTERBAUORDNUNG", "documentType": "de_legislation", "language": "de",
            "frontMatter": [{"id": "cover", "type": "frontMatter", "text": "Cover"}], "tableOfContents": [],
            "structure": [{"id": f"doc/par-{n}", "type": "section", "number": str(n), "germanType": "Paragraph",
                           "marker": f"§ {n}", "pages": [2], "text": "Abstand mindestens 3 m. Siehe § 24 und § 7."}
                          for n in [6, 7, 24]], "sentences": [], "footnotes": []}


class V2DocumentTests(unittest.TestCase):
    def test_chunk_plan_and_preflight_use_v2_without_changing_original(self):
        d = document(); original = copy.deepcopy(d)
        scoped, chunks = plan_chunks(d)
        self.assertEqual(scoped, build_inputs(d)[1])
        self.assertEqual([c.id for c in chunks], ["doc/par-6", "doc/par-7"])
        check_document_request(d, BedrockConfig())
        self.assertEqual(d, original)
        with self.assertRaises(InvalidScopeError): plan_chunks(d, ["doc/par-24"])

    def test_context_and_target_are_reduced_and_excluded_context_stays_unresolved(self):
        d = document(); _, chunks = plan_chunks(d)
        req, findings = prepare_chunk(d, chunks[0], BedrockConfig())
        body = json.loads(req.user.split("\n", 1)[1]); refs = body["context"]["referencedProvisions"]
        self.assertEqual([c["elementId"] for c in refs], ["doc/par-7"])
        self.assertTrue(any(f["citation"] == "§ 24" and f["status"] == "unresolved" for f in findings))
        for doc in [body["target"], *[c["document"] for c in refs]]:
            self.assertEqual(doc.get("frontMatter", []), [])
            for n in _walk(doc["structure"]):
                self.assertNotIn("germanType", n); self.assertNotIn("marker", n)
                self.assertNotEqual(n["id"], "doc/par-24")

    def test_whole_extraction_uses_v2_payloads_and_retains_schema_valid_rules(self):
        class Model:
            config = BedrockConfig()
            def __init__(self): self.calls = []
            def converse(self, system, user, **kwargs):
                body = json.loads(user.split("\n", 1)[1]); self.calls.append(body)
                n = next(n for n in _walk(body["target"]["structure"]) if n.get("text"))
                rule = {"schemaVersion": "2.0", "id": n["id"].replace("/", "-"),
                        "source": {"documentId": "mbo", "elements": [{"elementId": n["id"]}]},
                        "classification": {"type": "obligation", "summary": "Abstand mindestens 3 m."},
                        "requirements": [{"kind": "numeric", "fact": "clearance", "operator": ">=", "value": 3, "unit": "m"}],
                        "review": {"status": "draft"}}
                return BedrockResponse(json.dumps({"rules": [rule]}), "end_turn", 100, 50, 1, self.config.model_id)
        model = Model(); result = extract_document(document(), client=model, max_workers=1)
        self.assertEqual(len(model.calls), 2); self.assertEqual(len(result.rules), 2)
        self.assertEqual(result.generation["inputView"], "llm_applicability_input_v2.json")
        self.assertFalse(result.report["integration"]["failedChunks"])
        self.assertTrue(result.report["checks"]["schemaValid"])
