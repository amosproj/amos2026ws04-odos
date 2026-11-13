# ODOS Rule JSON 1.0

Rule JSON is a versioned, source-traceable representation of an interpreted requirement or definition from a legal or technical normative document. The standalone schema is [rule.schema.json](../backend/schemas/rule-json/1.0/rule.schema.json), written in JSON Schema Draft 2020-12. A restructured Rule JSON 2.0 ([schema](../backend/schemas/rule-json/2.0/rule.schema.json), [design](rule-json-2.0.md), [comparison](rule-json-1.0-to-2.0-comparison.md)) lives beside it; 1.0 is unchanged and both are displayed by the Artifacts viewer.

**Language policy:** Human-readable Rule JSON content follows the original document language by default. Schema keys and enum values remain language-neutral technical identifiers.

The schema is document-neutral. Legal JSON 2.0 preserves source structure and text; Rule JSON records an interpretation and points back to exact Legal JSON element IDs. Rule JSON does not replace or amend Legal JSON. The schema does not extract rules: no Rule JSON is shipped as application data, and the viewer displays an empty state until an extractor stores a job's `rules.json` artifact.

## Full-document review scope

The coverage review traversed every node under `structure` in both supplied Legal JSON 2.0 documents, including nested lists, preambles, recitals, tables, transitional provisions and annexes. Counts below are structural nodes, not inferred rules.

| Reference | Structure traversed |
|---|---|
| Musterbauordnung, `id: mbo` | 1,074 nodes: 6 parts, 96 paragraph sections, 330 subsections, 428 numbered items, 94 lettered items, 105 text nodes, 13 divisions, 1 item and 1 annex; maximum nesting depth 5; 673 sentence records |
| Regulation (EU) 2023/1230, `id: verordnung-2023-1230` | 1,715 nodes: preamble and 86 recitals, 9 chapters with all 54 articles, 12 annexes, 191 paragraphs, 606 points, 41 subpoints, 488 text nodes, 205 headings and 2 tables; maximum nesting depth 8; 517 sentence records and 26 footnotes |

The EU tree includes Annex III's nested safety requirements, Annexes IV and V documentation/declaration material, other conformity-assessment annexes, and Annex XII's correlation table (`doc/annex-12/table-1`). The MBO tree includes all six parts and its training-guideline annex. The sample IDs below are representative patterns found during that full-tree traversal, not a rule-by-rule extraction.

## Coverage assessment

“Fully supported” means the structure can be represented without a document-specific schema; it does not mean the legal meaning is automatically understood or validated.

| Semantic pattern | Representative source nodes | Coverage | Priority and remaining gap |
|---|---|---|---|
| Definitions and terminology | MBO § 2(2), `doc/teil-1/par-2/abs-2`; EU Art. 3 point 18 and alternatives a/b, `doc/chp-1/art-3/pt-18` | Fully supported for text plus conditional predicates | P1: the schema can encode conditions and references, but it cannot establish the legally correct concept boundaries. |
| Obligations, prohibitions and permissions | MBO § 5(2), `doc/teil-2/par-5/abs-2`; EU Art. 10(1), `doc/chp-2/art-10/para-1`; Annex III, `doc/annex-3/part-b/h-1/h-1.2/h-1.2.1` | Partially supported | P1: rule type and requirement expression distinguish modality and cumulative/alternative constraints; there is no formal deontic logic for conflicts, defeasibility or legal force. |
| Explicit duty holders and recipients | EU manufacturer duties in Art. 10(3), `doc/chp-2/art-10/para-3`; Art. 10(10) authority request, `doc/chp-2/art-10/para-10` | Fully supported structurally by optional actor references | P1: role labels are extracted concepts, not a globally defined actor ontology. |
| Quantitative and formula constraints | MBO § 6(5), `doc/teil-2/par-6/abs-5`; Annex III limits and thresholds across `doc/annex-3` | Fully supported for scalar thresholds, units and formula strings | P1: formulas are descriptive, and no unit conversion, rounding or dimensional analysis is defined. Typed comparison values are opt-in in 1.0 for compatibility. |
| Boolean and text/categorical constraints | MBO § 6(5) building use/class alternatives; EU Art. 2(2) exclusions, including `doc/chp-1/art-2/para-2/pt-a` | Fully supported as values | P2: the schema cannot validate domain-specific vocabularies or prove that a phrase was mapped to the correct property. |
| Nested AND/OR conditions and requirements | EU definition of “manufacturer,” Art. 3 point 18(a–b); cumulative and alternative safety conditions in Annex III point 1.2.1(a), `doc/annex-3/part-b/h-1/h-1.2/h-1.2.1/pt-a` | Fully supported structurally by predicate and requirement expressions | P1: order-sensitive procedures and interactions between separate rules still need explicit interpretation. |
| Temporal duties, deadlines and transitional dates | MBO § 62(3), `doc/teil-5/abschnitt-2/par-62/abs-3`; EU Art. 10(3) ten-year retention, Art. 34(5) objection periods, and Art. 54 application dates (`doc/chp-2/art-10/para-3`, `doc/chp-5/art-34/para-5`, `doc/chp-9/art-54/txt-1`) | Fully supported as an event, relation, duration or date | P1: relative phrases such as “without undue delay,” calendar-month arithmetic, business days and jurisdiction-specific date rules remain textual or unresolved. |
| Scope exclusions and partial applicability | MBO § 1(2), `doc/teil-1/par-1/abs-2`; EU Art. 2(2), `doc/chp-1/art-2/para-2` | Fully supported structurally by explicit scope exclusions | P1: complex scopes may depend on facts or other laws that are absent from the source document. |
| Exceptions, exemptions and alternative regimes | MBO § 6(5) sentence 4, `doc/teil-2/par-6/abs-5`; EU Art. 43 safeguard procedure, `doc/chp-6/art-43` | Partially supported | P1: individual exception conditions/effects can be represented, but cascading exceptions and interactions among regimes are not evaluated. |
| Overrides and legal precedence | MBO § 6(5) sentence 4 and deviation authority § 67(1), `doc/teil-2/par-6/abs-5`, `doc/teil-5/abschnitt-3/par-67/abs-1`; EU cross-references among Arts. 43–45 | Partially supported by provision references and relationship labels | P1: priority, jurisdiction, later-in-time effects and conflict resolution are not computed. |
| Evidence, records and documentation duties | EU Art. 10(3), Art. 10(10), Annex IV Part A (`doc/chp-2/art-10/para-3`, `doc/chp-2/art-10/para-10`, `doc/annex-4/part-a`) | Partially supported | P2: requirements, actors, timing and annex references can be recorded; the schema has no document/evidence taxonomy or sufficiency test. |
| Procedural duties and administrative decisions | MBO § 62(3), § 67, and § 87, `doc/teil-5/abschnitt-2/par-62/abs-3`, `doc/teil-5/abschnitt-3/par-67`, `doc/teil-6/par-87`; EU Arts. 34 and 43 | Partially supported | P2: a process can be split into sourced rules with actors and deadlines, but there is no workflow or state-transition engine. |
| Normative annexes and incorporated provisions | MBO Annex 1, `doc/anlage-1/txt-7`; EU Annex III and Annex IV, `doc/annex-3`, `doc/annex-4` | Partially supported | P1: exact element provenance and `depends_on`/`implements` links work; edition tracking for incorporated standards and table/cell semantics are not modeled. |
| Recitals and explanatory context | EU recital 33, `doc/preamble/rec-33`; contextual sources can use `source.role: context` | Partially supported | P2: recitals can be cited as context, but are not independently classified as binding rules by the schema. Extraction must not turn explanatory text into an obligation by itself. |
| Internal and external references | MBO § 6(5) and EU Art. 10(3) references to Annex III/IV | Partially supported | P2: a reference can be resolved to an ID or explicitly unresolved; external identifiers, version resolution and citation consistency are not checked by JSON Schema. |
| Non-machine-evaluable requirements | Open-text duties and unresolved conditions throughout both documents | Fully supported for explicit unresolved records | P1: “unresolved” records still need reviewer attention and are not executable. |
| Tables and structured annex data | EU Annex XII correlation table `doc/annex-12/table-1`; MBO Annex 1 nested study-subject lists | Partially supported | P2: a rule may cite a table node, but row/cell relationships and applicability across table dimensions require structured meaning or unresolved text. |

Examples of the discovered structures are kept only in the test suite. For instance, EU Art. 10(3) can be represented as a manufacturer duty with a ten-year duration triggered by placing on the market or putting into service. EU Art. 3 point 18 is a conditional definition with two AND branches joined by OR. Annex III point 1.2.1(a) is a nested technical condition. MBO § 6(5) has separate quantitative alternatives and a statutory override; it should not be collapsed into one unconditional threshold.

## Schema model and additions

Every record requires `schemaVersion`, `id`, `type`, `documentReference`, `source`, `status` and `summary`. Status is `draft`, `reviewed` or `approved`. Rule types are `definition`, `obligation`, `prohibition`, `permission` and `conditional_requirement`.

- `source` points to exact Legal JSON element IDs. Optional source roles distinguish primary normative text, definitions, context and cross-references. Sentence numbers and human-readable descriptions remain optional.
- `applicability` and `scopeExclusions` are separate. Conditions support typed comparisons, nested `all`/`any`, `not`, and explicit unresolved predicates. Comparison `valueType` is optional: when supplied, it validates the value; when absent, legacy 1.0 values retain their previous unrestricted JSON type.
- Non-definition records may use the legacy `requirements` array or the new recursive `requirementExpression` (`requirement`, `all`, `any`, `not`) to express cumulative and alternative obligations without ambiguity.
- Requirements support boolean, numeric, text/categorical, formula, temporal and unresolved forms. Temporal records capture an action, relation, triggering event, duration, end event or absolute date.
- Optional `actors` identify duty holders, recipients, authorities and other roles. Definition objects may include a condition for context-dependent terms.
- Exceptions and references remain separate from normal applicability. Provision references optionally state general relationships such as `depends_on`, `subject_to`, `overrides` or `supersedes`; these are descriptive links, not precedence calculations.

Objects reject unsupported extra fields. An unresolved value should be used when legal meaning or facts are not safely machine-evaluable. Requirements, formulas and condition vocabularies are not evaluated by the schema.

## Version compatibility

The additions are backward-compatible extensions to the current 1.0 validation contract: existing `requirements` arrays remain valid, the old comparison `value` remains accepted when `valueType` is absent, and all new actor, temporal, scope, source-role and reference-relationship properties are optional. A non-definition rule can use either the old array or the new expression, not both. No previously valid 1.0 test record is intentionally rejected. If a future release needs to require typed comparison values or change existing field semantics, publish a new schema version and keep the 1.0 schema available; do not silently tighten 1.0.

## Validation and reference checks

JSON Schema validation checks structural shape and basic types. It does not prove legal correctness, extraction completeness, cross-field semantic coherence, or whether a formula or deadline is legally interpreted correctly. Source-reference tests separately check that fixture IDs exist in each Legal JSON document. ID existence also does not prove that a rule is correctly interpreted from that source.

The tests use compact, manually modeled MBO and EU records only as fixtures; they are not application data. From `backend/` run:

```bash
.venv/bin/pytest tests/test_rule_json_schema.py
```

To run both reference consistency checks:

```bash
ODOS_MBO_LEGAL_JSON_PATH=/path/to/MusterBauVerordnung.legal-3.json \
ODOS_EU_LEGAL_JSON_PATH=/path/to/EuMaschinenbauverordnung.legal.json \
.venv/bin/pytest tests/test_rule_json_schema.py
```

The reference checks skip when their respective environment variable is unset.

## Future Rule Interpreter

LLM integration and rule extraction are out of scope. A future interpreter can receive the relevant Legal JSON source nodes, this schema or a constrained structured-output equivalent, and extraction instructions to preserve modality, actors, conditions, exceptions, references and unresolved meaning. It should cite only IDs from the supplied document, treat recitals as context unless supported by operative provisions, and emit `draft` records for human review. Testing complete MBO and EU documents improves coverage confidence but cannot establish compatibility with every jurisdiction, technical standard, drafting style or future schema profile.
