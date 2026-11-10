"""The published Legal JSON 2.0 schema accepts what the exporter writes, without breaking earlier documents.

The exporter writes the source-language term of a node as `germanType` (view.Node); the published schema had only
declared `nativeType`, so every exported document failed schema validation (`'germanType' was unexpected`). The
schema is an interface contract for downstream consumers: it now declares `germanType` in addition to `nativeType`
(documents written before the rename stay valid) and still rejects undeclared properties.
"""

import json

import pytest
from jsonschema import Draft202012Validator

from odos.legal_json.artifacts import published_schema, serialize
from odos.legal_json.view import Identifiers, LegalDocument, Node, Version, json_schema


def schema_errors(data: dict) -> list[str]:
    return [e.message for e in Draft202012Validator(published_schema()).iter_errors(data)]


def exported_document() -> dict:
    """A document as build_legal_json_artifacts writes it: § 1 (1) with one Nummer."""
    absatz = Node(id="doc/par-1/abs-1", type="subsection", germanType="Absatz", number="1", marker="(1)",
                  text="Dieses Gesetz gilt für", pages=[1],
                  children=[Node(id="doc/par-1/abs-1/nr-1", type="number", germanType="Nummer", number="1", marker="1.",
                                 text="bauliche Anlagen.", pages=[1])])
    doc = LegalDocument(id="test", title="TESTGESETZ", documentType="de_legislation", legalSystem="de", language="de",
                        version=Version(), identifiers=Identifiers(), pageCount=1, frontMatter=[], tableOfContents=[],
                        structure=[Node(id="doc/par-1", type="section", germanType="Paragraph", number="1", marker="§ 1",
                                        title="Anwendungsbereich", pages=[1], children=[absatz])],
                        footnotes=[])
    return json.loads(serialize(doc))


def nodes(data: dict) -> list[dict]:
    found, todo = [], list(data["structure"])
    while todo:
        node = todo.pop()
        found.append(node)
        todo += node.get("children", [])
    return found


@pytest.mark.parametrize("definition", sorted(json_schema()["$defs"]) + ["LegalDocument"])
def test_published_schema_declares_every_exported_field(definition):
    generated, published = json_schema(), published_schema()
    exported = generated if definition == "LegalDocument" else generated["$defs"][definition]
    declared = published if definition == "LegalDocument" else published["$defs"][definition]
    assert set(exported["properties"]) <= set(declared["properties"])


def test_exported_document_is_valid():
    data = exported_document()
    assert {n["germanType"] for n in nodes(data)} == {"Paragraph", "Absatz", "Nummer"}
    assert schema_errors(data) == []


def test_documents_with_native_type_stay_valid():
    data = json.loads(json.dumps(exported_document()).replace('"germanType"', '"nativeType"'))
    assert {n["nativeType"] for n in nodes(data)} == {"Paragraph", "Absatz", "Nummer"}
    assert schema_errors(data) == []


def test_undeclared_node_properties_are_still_rejected():
    data = exported_document()
    data["structure"][0]["sourceSpans"] = []
    assert schema_errors(data) == ["Additional properties are not allowed ('sourceSpans' was unexpected)"]
