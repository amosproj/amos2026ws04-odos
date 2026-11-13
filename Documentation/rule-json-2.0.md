# ODOS Rule JSON 2.0 — Design Proposal

> **Status:** Proposed schema, versioned under `backend/schemas/rule-json/2.0/`. Any Rule Interpreter validates against this file; nothing in it is simulation-specific.

## Objective

Redesign Rule JSON 1.0 into a clearer, more structured and universally applicable Rule JSON 2.0. The goals are:

1. **Human readability** — a rule should be understandable at a glance.
2. **Consistent categorization** — every rule is classified by type and normative category.
3. **Source traceability** — stable Legal JSON element IDs, sentence IDs and PDF page numbers.
4. **Future machine-checkability** — structured requirements that can later map to IFC, RDF, IDS or SHACL without making those mappings mandatory.

## Core Design Principle

A Rule JSON should answer these questions at a glance:

| Question | Section |
|---|---|
| Where does this requirement come from? | `source` |
| What type of rule is it? | `classification` |
| Who or what does it apply to? | `applicability` |
| Under which conditions? | `applicability.conditions` |
| What exactly is required or prohibited? | `requirements` / `requirementExpression` / `definition` |
| Are there exceptions? | `exceptions` |
| Can the requirement be checked automatically? | `review.machineCheckable` |
| What needs human review? | `review.ambiguities` / `review.notes` |

## Top-Level Structure

```
Rule JSON 2.0
├── schemaVersion: "2.0"
├── id
├── source                    ← WHERE it comes from
│   ├── documentId
│   ├── documentTitle
│   ├── documentVersion
│   ├── language
│   ├── citation
│   └── elements[]            ← Legal JSON element pointers with pdfPages
├── classification             ← WHAT KIND of rule
│   ├── type                  ← obligation, prohibition, permission, ...
│   ├── normativeCategory     ← substantive, procedural, definitional, ...
│   └── summary
├── applicability              ← WHO/WHAT it applies to, WHEN
│   ├── targets[]             ← entities (building, door, machine)
│   ├── actors[]              ← duty holders, authorities
│   ├── conditions            ← triggering conditions (predicate tree)
│   └── scopeExclusions[]    ← when it does NOT apply
├── definition                 ← for type=definition only
├── requirements[]             ← simple list of checks (OR)
├── requirementExpression      ← complex AND/OR/NOT tree (alternative to requirements[])
├── exceptions[]               ← exceptions, exemptions, alternatives
├── references[]               ← cross-references to other provisions
├── review                     ← REVIEW status and machine-checkability
│   ├── status
│   ├── machineCheckable
│   ├── checkMethods[]
│   ├── ambiguities[]
│   └── notes[]
└── externalMappings[]         ← OPTIONAL IFC/RDF mappings (not core)
```

## Key Design Decisions

### 1. Unified Source Object (was: separate documentReference + source[])

**Problem in 1.0:** Source provenance was split between `documentReference` (document-level) and `source[]` (element-level). PDF page information was absent.

**Solution in 2.0:** A single `source` object combines document metadata and element pointers. Each element can carry `pdfPages` (from Legal JSON 2.0's `pages` field) and an optional `sentenceId` for sentence-level precision.

### 2. Classification Section (was: top-level type + summary)

**Problem in 1.0:** `type` and `summary` were flat top-level fields with no broader categorization. Procedural requirements had no dedicated type.

**Solution in 2.0:** The `classification` object groups `type`, `normativeCategory` and `summary`. A new `procedural_requirement` type covers administrative processes. The `normativeCategory` (substantive, procedural, definitional, transitional, organizational, informational) aids filtering and analysis.

### 3. Structured Applicability (was: flat applicability predicate + actors[] + scopeExclusions[])

**Problem in 1.0:** Target entities were implicit in applicability predicates. Actors, conditions and exclusions were scattered across different top-level fields.

**Solution in 2.0:** The `applicability` object groups `targets[]` (physical entities), `actors[]` (persons/organizations), `conditions` (triggering predicate) and `scopeExclusions[]`. This matches the presentation's `applies_to.entity` + `applies_to.when` pattern while preserving 1.0's expressive predicate trees.

### 4. Renamed `property` → `fact`

**Rationale:** Adopts the sprint-proposal's terminology. `fact` better conveys that the field names a piece of evidence needed to evaluate the rule, not necessarily a software property. The term aligns with the IFC/RDF mapping workflow where facts are extracted from building models.

### 4b. Readable comparison operators

Comparison and numeric requirement operators use mathematical symbols: `==`, `!=`, `>`, `>=`, `<`, `<=`. The set operators `in`, `not_in` and `contains` are unchanged. Rule JSON 1.0 keeps `eq`, `ne`, `gt`, `gte`, `lt`, `lte`.

### 5. Explicit Review and Machine-Checkability (was: status + reviewNotes[])

**Problem in 1.0:** `status` and `reviewNotes` were minimal. No way to indicate whether a rule could be checked automatically.

**Solution in 2.0:** The `review` section adds `machineCheckable` (boolean), `checkMethods[]` (ids, shacl, sparql, llm_comparison, manual) and `ambiguities[]`. This distinguishes between "schema-valid rule" and "actually executable against evidence."

### 6. Optional External Mappings (new)

IFC, RDF and other data model mappings live in an optional `externalMappings[]` array. This is not part of the normative representation — it records which external standard, entity class and property path a requirement's fact maps to. This preserves the presentations' IFC mapping workflow without making it mandatory.

### 7. Universal Applicability

The schema is document-neutral:
- No IFC, MBO or EU-specific mandatory fields.
- Works for German laws, EU regulations/directives, ISO/EN standards and other normative documents.
- Preserves the distinction between: a normative legal requirement, a machine-checkable representation, and a mapping to a specific external data model.

## Preserved Capabilities from 1.0

All existing 1.0 capabilities remain representable:

- Definitions with conditional predicates
- Obligations, prohibitions, permissions
- Conditional requirements
- Nested AND/OR/NOT predicate trees
- Typed comparison values with validation
- Temporal requirements (duration, deadline, event-based)
- Boolean, numeric, text, formula requirements
- Unresolved predicates and requirements
- Exceptions with effects (disapplies, modifies, alternatives)
- Cross-references with relationship labels
- Scope exclusions

## Ideas Adopted from Presentations

| Idea | Source | How adopted |
|---|---|---|
| Clause splitting into individual checks | Sprint Scope, slide 2 | Each rule represents one split requirement |
| `source / applies_to / check` structure | Sprint Scope, slides 4–5 | `source` / `applicability` / `requirements` sections |
| `fact / operator / value / unit` naming | Sprint Scope, slide 4 | `fact` replaces `property` in all requirement and predicate types |
| `entity` and `when` in applicability | Sprint Scope, slide 5 | `applicability.targets[]` + `applicability.conditions` |
| `anyOf` for alternative requirements | Sprint Scope, slide 5 | `requirementExpression` with `kind: "any"` |
| PDF page numbers in source | Sprint Scope, slide 4 | `source.elements[].pdfPages` |
| IFC/RDF mapping as separate step | IFC v6, slides 10–13 | `externalMappings[]` as optional, non-core |
| Multiple validation methods | IFC v6, slides 6–9 | `review.checkMethods[]` |
| LLM comparison as validation option | IFC v6, slides 6, 9 | `llm_comparison` in checkMethods |
| Human review for unresolved rules | Both | `review` section with status, ambiguities, notes |

## Running tests

```bash
cd backend
python3 -m pytest tests/test_rule_json_v2_schema.py tests/test_rule_json_schema.py --noconftest -v
```

## Files

| File | Description |
|---|---|
| [backend/schemas/rule-json/2.0/rule.schema.json](../backend/schemas/rule-json/2.0/rule.schema.json) | Rule JSON 2.0 schema (Draft 2020-12), versioned beside 1.0 |
| [backend/schemas/rule-json/1.0/rule.schema.json](../backend/schemas/rule-json/1.0/rule.schema.json) | Rule JSON 1.0 schema (unchanged) |
| [backend/tests/test_rule_json_v2_schema.py](../backend/tests/test_rule_json_v2_schema.py) | 2.0 schema tests |
| [dev-fixtures/rule-json-examples/](../dev-fixtures/rule-json-examples/README.md) | Simulated, labeled EU and MBO Rule JSON 2.0 examples (also used by the schema tests) |
| [rule-json-1.0-to-2.0-comparison.md](rule-json-1.0-to-2.0-comparison.md) | Field-by-field 1.0 vs 2.0 comparison |
