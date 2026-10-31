"""Validation against the unmodified official OASIS Akoma Ntoso XSD: AKN 3.1 (OASIS Standard, 2 October 2026).

AKN 3.1 keeps the namespace ``http://docs.oasis-open.org/legaldocml/ns/akn/3.0`` and the file name
``akomantoso30.xsd``. It is the base of AKN4EU 5.x. The earlier AKN 3.0 schema (OASIS Standard 2018) is no
longer used: every ODOS export and all 60 official AKN4EU samples validate against AKN 3.1.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from lxml import etree
from pydantic import BaseModel

SCHEMA_DIR = Path(__file__).resolve().parents[3] / "schemas" / "akn-3.1-os"
SCHEMA_FILE = "akomantoso30.xsd"
SCHEMA_SOURCE_URL = "https://docs.oasis-open.org/legaldocml/akn-core/v2.0/os/part2-specs/schemas/"
PINNED_SHA256 = {  # = the digests in the OASIS release manifest (schemas/akn-3.1-os/manifest.json)
    "akomantoso30.xsd": "8f1fe3e187ee5e6f5bc9dfb013f7d9195de6516f077ce10726bedf6260f8b70a",
    "xml.xsd": "61960fb3131e38022caad5360e2f33a3382578ab3c80cd58bd74320ede61b20c",
}
SCHEMA_VERSION = "OASIS Akoma Ntoso Version 2.0, Part 2: Specifications of AKN 3.1, OASIS Standard, 2 October 2026 (namespace akn/3.0)"  # fmt: skip


class SchemaIntegrityError(RuntimeError):
    pass


class XmlIssue(BaseModel):
    line: int
    column: int
    level: str
    domain: str
    type: str
    message: str


class ValidationResult(BaseModel):
    schema_version: str
    schema_files: list[dict]
    validator: dict
    xml_sha256: str
    xml_bytes: int
    well_formed: bool
    valid: bool
    errors: list[XmlIssue]
    warnings: list[XmlIssue]


def verify_schema_files(schema_dir: Path = SCHEMA_DIR) -> list[dict]:
    out = []
    for name, expected in PINNED_SHA256.items():
        actual = hashlib.sha256((schema_dir / name).read_bytes()).hexdigest()
        if actual != expected:
            raise SchemaIntegrityError(f"{name}: sha256 {actual} != pinned {expected}")
        out.append({"file": name, "sha256": actual, "source": SCHEMA_SOURCE_URL + name})
    return out


def load_schema(schema_dir: Path = SCHEMA_DIR) -> etree.XMLSchema:
    verify_schema_files(schema_dir)
    return etree.XMLSchema(etree.parse(str(schema_dir / SCHEMA_FILE)))


def _issue(e) -> XmlIssue:
    return XmlIssue(line=e.line, column=e.column, level=e.level_name, domain=e.domain_name, type=e.type_name, message=e.message)  # fmt: skip


def validate_xml(xml: bytes, schema_dir: Path = SCHEMA_DIR) -> ValidationResult:
    files = verify_schema_files(schema_dir)  # refuses to validate against a modified schema
    schema = load_schema(schema_dir)
    meta = {
        "name": "lxml.etree.XMLSchema",
        "lxml": etree.LXML_VERSION and ".".join(map(str, etree.LXML_VERSION)),
        "libxml2": ".".join(map(str, etree.LIBXML_VERSION)),
    }
    base = dict(
        schema_version=SCHEMA_VERSION, schema_files=files, validator=meta,
        xml_sha256=hashlib.sha256(xml).hexdigest(), xml_bytes=len(xml),
    )  # fmt: skip
    try:
        doc = etree.fromstring(xml)
    except etree.XMLSyntaxError as exc:
        errs = [_issue(e) for e in exc.error_log]
        return ValidationResult(**base, well_formed=False, valid=False, errors=errs, warnings=[])
    valid = schema.validate(doc)
    log = list(schema.error_log)
    return ValidationResult(
        **base, well_formed=True, valid=bool(valid),
        errors=[_issue(e) for e in log if e.level_name in ("ERROR", "FATAL")],
        warnings=[_issue(e) for e in log if e.level_name == "WARNING"],
    )  # fmt: skip
