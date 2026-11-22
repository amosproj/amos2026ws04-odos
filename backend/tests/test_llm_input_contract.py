"""Offline V2 -> model request -> Rule JSON schema/provenance regressions (no AWS calls)."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from odos.llm.bedrock import BedrockConfig, BedrockResponse
from odos.llm.rule_extraction import extract_rules, prepare_request, rule_validator, InvalidScopeError
from odos.llm.source_checks import SourceText
from odos.llm_input.artifacts import write_input_artifacts


def legal_document(eu):
    kind, kept, removed = ("article", "10", "50") if eu else ("section", "6", "24")
    element = f"doc/{kind}-{kept}"
    text = "1 The clearance must be at least 3 m."
    return {"schemaVersion": "2.0", "id": "verordnung-2023-1230" if eu else "mbo",
            "title": "EU Machinery" if eu else "MUSTERBAUORDNUNG", "language": "en",
            "documentType": "eu_regulation" if eu else "de_legislation", "identifiers": {},
            "pageCount": 5, "frontMatter": [], "tableOfContents": [], "footnotes": [],
            "structure": [{"id": element, "type": kind, "number": kept, "nativeType": "Artikel" if eu else "Paragraph",
                           "marker": "Article " + kept, "text": text, "pages": [2]},
                          {"id": "excluded", "type": kind, "number": removed, "text": "Excluded material", "pages": [3]}],
            "sentences": [{"id": element + "/s1", "unitId": element,
                           "marker": {"elementId": element, "start": 0, "end": 1},
                           "ranges": [{"elementId": element, "start": 0, "end": len(text)}]}]}


class FakeModel:
    config = BedrockConfig()

    def __init__(self, rules):
        self.rules = rules
        self.calls = []

    def converse(self, system, user, **kwargs):
        self.calls.append((system, user))
        return BedrockResponse(json.dumps({"rules": self.rules}), "end_turn", 100, 50, 1, self.config.model_id)


def candidate(document):
    element = document["structure"][0]["id"]
    return {"schemaVersion": "2.0", "id": "clearance", "source": {"documentId": "incorrect-model-id",
            "elements": [{"elementId": element, "sentenceId": element + "/s1", "pdfPages": [999]}]},
            "classification": {"type": "obligation", "summary": "Clearance at least 3 m."},
            "requirements": [{"kind": "numeric", "fact": "clearance", "operator": ">=", "value": 3, "unit": "m"}],
            "review": {"status": "draft"}}


class V2RuleContractTests(unittest.TestCase):
    def test_model_gets_saved_v2_and_result_validates_with_preserved_provenance(self):
        for eu in (False, True):
            with self.subTest(eu=eu), tempfile.TemporaryDirectory() as temp:
                document = legal_document(eu)
                original = copy.deepcopy(document)
                write_input_artifacts(document, temp)
                saved = json.loads((Path(temp) / "llm_applicability_input_v2.json").read_text())
                model = FakeModel([candidate(document)])
                result = extract_rules(document, client=model)
                sent = json.loads(model.calls[0][1].split("<legal_json>\n")[1].split("\n</legal_json>")[0])
                self.assertEqual(sent, saved)
                self.assertNotIn("Excluded material", model.calls[0][1])
                self.assertNotIn("nativeType", sent["structure"][0])
                self.assertNotIn("marker", sent["structure"][0])
                self.assertEqual(document, original)
                self.assertEqual(len(result.rules), 1, result.rejected)
                rule = result.rules[0]
                self.assertEqual(list(rule_validator().iter_errors(rule)), [])
                self.assertEqual(rule["source"]["documentId"], document["id"])
                self.assertEqual(rule["source"]["elements"][0]["pdfPages"], [2])
                self.assertEqual(rule["source"]["elements"][0]["sentenceId"], document["sentences"][0]["id"])
                source = SourceText.of(sent)
                self.assertTrue(next(iter(source.sentences.values())).startswith("The clearance"))
                self.assertEqual(result.generation["inputView"], "llm_applicability_input_v2.json")

    def test_source_cannot_point_to_an_excluded_provision(self):
        d = legal_document(True)
        rule = candidate(d)
        rule["source"]["elements"] = [{"elementId": "excluded"}]
        result = extract_rules(d, client=FakeModel([rule]))
        self.assertEqual(result.rules, [])
        self.assertEqual(len(result.rejected), 1)

    def test_explicit_scope_cannot_restore_excluded_text(self):
        with self.assertRaises(InvalidScopeError):
            prepare_request(legal_document(True), BedrockConfig(), ["excluded"])
