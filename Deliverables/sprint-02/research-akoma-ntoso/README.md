# Issue #10 — Akoma Ntoso and AKN4EU Research

## Research objective
Evaluate Akoma Ntoso / AKN4EU as representations of normative documents for ODOS; illustrate their document structure using MBO §6(5); and consider whether structured source documents are already available.

## Findings
- **Akoma Ntoso (OASIS LegalDocML)** is an XML-based standard for representing legal and legislative documents, including legal hierarchy, identifiers, metadata, and references.
- **AKN4EU** is an EU-oriented application of Akoma Ntoso for EU legislative document workflows. Availability of a specific document in AKN4EU format must be verified; a digital regulation is not automatically an AKN4EU document.
- Akoma Ntoso models **source documents**, not executable compliance rules. SHACL / pySHACL validates RDF data against reviewed formal constraints; it does not interpret the law by itself.
- The example in `mbo_section6_illustrative.xml` demonstrates a legal section/subsection structure using **one sentence** of German MBO §6(5). It is **not a complete Akoma Ntoso document**, has **not been validated against the OASIS XSD**, and does not represent the full provision or exceptions.

## Existing structured sources — investigation status
- **EU Machinery Regulation (EU) 2023/1230:** available from EUR-Lex with electronic text and metadata. The exact available downloadable structured formats/version should be checked before designing PDF conversion. **AKN4EU availability was not verified** in this research.
- **German Musterbauordnung (MBO):** an official model-code PDF is available. **An official Akoma Ntoso version was not verified** in this research. The MBO is a model code; binding requirements depend on applicable state building legislation.

## Proposed ODOS technology decision (agreed with Moritz)
**Use JSON + JSON Schema internally for the MVP. Consider Akoma Ntoso XML as an optional future export/import format.**

Reasons:
1. Docling can export structured JSON, reducing conversion work.
2. Introducing and maintaining AKN XML would add complexity that is not required for the present prototype.
3. The team finds JSON easier to work with in the current Python-centric workflow.

A possible future pipeline:
`PDF / official structured source → Docling or direct import → reviewed legal JSON → approved rule mapping → SHACL shapes → pySHACL validation of RDF digital twins`

A JSON-to-AKN exporter would require a documented mapping, complete original text and metadata, and **validation against the official Akoma Ntoso XSD**. It is not implemented here.

## Files
- `ODOS_Akoma_Ntoso_AKN4EU_Research.pptx`: research presentation and JSON-first decision.
- `mbo_section6_illustrative.xml`: **illustrative XML fragment only** (one sentence, no schema-validity claim).

## Scope and follow-up
- Verify and document the exact official download formats for the chosen versions of EU Regulation 2023/1230 and the MBO.
- If an AKN implementation is requested, create a complete schema-valid document with source/provenance metadata and all applicable text; review it against the authoritative source.
- Decide whether legal-document export compatibility is a concrete ODOS requirement before investing in conversion tooling.

## Sources
- [OASIS LegalDocML / Akoma Ntoso 1.0](https://docs.oasis-open.org/legaldocml/akn-core/v1.0/)
- [EU Publications Office — AKN4EU](https://op.europa.eu/en/web/eu-vocabularies/akn4eu)
- [EUR-Lex — Regulation (EU) 2023/1230](https://eur-lex.europa.eu/eli/reg/2023/1230/oj)
