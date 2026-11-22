# ODOS Rule JSON

Rule JSON is a source-traceable representation of an interpreted requirement or definition from a legal or technical normative document. There is one schema, [rule.schema.json](../backend/schemas/rule-json/rule.schema.json), written in JSON Schema Draft 2020-12. Every record declares `"schemaVersion": "2.0"`. Any Rule Interpreter validates against this file; nothing in it is simulation-specific.

**Language policy:** Human-readable Rule JSON content follows the original document language by default. Schema keys and enum values remain language-neutral technical identifiers.

The schema is document-neutral. Legal JSON 2.0 preserves source structure and text; Rule JSON records an interpretation and points back to exact Legal JSON element IDs. Rule JSON does not replace or amend Legal JSON. The schema does not extract rules: no Rule JSON is shipped as application data. The LLM extractor ([bedrock-rule-extraction.md](bedrock-rule-extraction.md)) stores a job's `rules.json` artifact, which the **LLM Rule Extraction & Review** page and the Artifacts viewer display; both show an empty state until one exists. They show records with `schemaVersion` `2.0` and map them to the selected element through `source.elements[].elementId`.

## Objective

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
Rule JSON
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

### 1. Unified Source Object

A single `source` object combines document metadata and element pointers. Each element can carry `pdfPages` (from Legal JSON 2.0's `pages` field) and an optional `sentenceId` for sentence-level precision. The examples give a `sentenceId` only where the Legal JSON's sentence split matches the source.

### 2. Classification Section

The `classification` object groups `type`, `normativeCategory` and `summary`. The `procedural_requirement` type covers administrative processes. The `normativeCategory` (substantive, procedural, definitional, transitional, organizational, informational) aids filtering and analysis.

### 3. Structured Applicability

The `applicability` object groups `targets[]` (physical entities), `actors[]` (persons/organizations), `conditions` (triggering predicate) and `scopeExclusions[]`. This matches the presentation's `applies_to.entity` + `applies_to.when` pattern while keeping expressive predicate trees.

### 4. `fact` Instead of `property`

Requirements and predicates name a `fact`: a piece of evidence needed to evaluate the rule, not necessarily a software property. The term follows the sprint proposal and aligns with the IFC/RDF mapping workflow where facts are extracted from building models.

### 4b. Comparison operators and value types

Comparison and numeric requirement operators use mathematical symbols: `==`, `!=`, `>`, `>=`, `<`, `<=`. The set operators are `in`, `not_in` and `contains`.

`valueType` is required on every comparison predicate. It decides how `value` is checked and which operators apply, so a predicate cannot skip type checking by leaving it out:

| Operator | Meaning | Allowed `valueType` | `value` |
|---|---|---|---|
| `==`, `!=` | equal / not equal | `string`, `integer`, `number`, `boolean` | a scalar of that type |
| `>`, `>=`, `<`, `<=` | ordering | `integer`, `number` | a number |
| `in`, `not_in` | the fact is / is not one of the listed values | `string_array`, `integer_array`, `number_array`, `boolean_array` | a non-empty array of unique items of that type |
| `contains` | the fact (a list or a text) contains the value | `string`, `integer`, `number` | a scalar of that type |

`unit` is allowed only with `integer`, `number`, `integer_array` and `number_array`. Units are written without whitespace (`m`, `m2`, `kN/m2`, `%`). UCUM-style codes are recommended but not enforced. `1` marks an explicitly dimensionless quantity, e.g. a count in a numeric requirement, which always needs a unit.

Text requirements use the same vocabulary as predicates: `==` takes a non-empty string, `in` a non-empty array of unique strings, `contains` a non-empty string.

This predicate is rejected, because a string cannot be ordered:

```json
{ "kind": "comparison", "fact": "building.height", "operator": ">", "value": "tall" }
```

The valid form names the type and the unit:

```json
{ "kind": "comparison", "fact": "building.height", "operator": ">", "value": 7, "valueType": "number", "unit": "m" }
```

### 4c. Structured Arithmetic Expressions

Formula requirements use structured calculation objects instead of free-text expressions. This allows formulas to be parsed and processed programmatically without interpreting mathematical strings.

#### Arithmetic Node Types

`FormulaRequirement.expression` supports three recursively defined node types:

| Kind | Purpose | Required fields |
|---|---|---|
| `literal` | Numeric constant | `kind`, `value` |
| `fact` | Reference to an input fact | `kind`, `name` |
| `operation` | Mathematical operation | `kind`, `operator`, `operands` |

Both `literal` and `fact` may include an optional `unit` field. An omitted unit means the quantity is dimensionless, such as the factor `0.4` or a count.

#### Supported Operators

| Operator | Meaning | Operand count |
|---|---|---|
| `add` | Addition | 2 or more |
| `subtract` | First operand minus second | Exactly 2 |
| `multiply` | Multiplication | 2 or more |
| `divide` | First operand divided by second | Exactly 2; a literal `0` divisor is rejected |
| `min` | Minimum value | 2 or more |
| `max` | Maximum value | 2 or more |

Operations can be nested to represent complex calculations. The expression of a formula must reference at least one fact. A bound made only of constants (`3 m`, `max(3 m, 2 m)`) is a numeric requirement, so each threshold has one representation.

#### Calculated value or minimum/maximum

`setback_depth = 0.4 × H` and `setback_depth ≥ 0.4 × H` are different statements. The first determines a value, the second sets a lower bound for a measured value. A formula therefore states the relation explicitly. `operator` and `unit` are required, and the requirement reads `fact <operator> expression`, both in `unit`:

| `operator` | Reading |
|---|---|
| `==` | calculated value: the fact is determined by the formula |
| `>=`, `>` | minimum: the fact must reach the calculated value |
| `<=`, `<` | maximum: the fact must not exceed the calculated value |

The operator comes from the wording of the source. A formula is never assumed to be a minimum.

#### Example: MBO § 6 Abs. 5 — Setback Depth

The source reads "Die Tiefe der Abstandsflächen beträgt 0,4 H, mindestens 3 m." The depth is a calculated value (`==`) of `max(0.4 × H, 3 m)`:

```json
{
  "kind": "formula",
  "fact": "setback_depth",
  "operator": "==",
  "expression": {
    "kind": "operation",
    "operator": "max",
    "operands": [
      {
        "kind": "operation",
        "operator": "multiply",
        "operands": [
          { "kind": "literal", "value": 0.4 },
          { "kind": "fact", "name": "measure_h", "unit": "m" }
        ]
      },
      { "kind": "literal", "value": 3, "unit": "m" }
    ]
  },
  "unit": "m"
}
```

Whether a building complies is a separate rule: the setback areas must lie on the plot itself (§ 6 Abs. 2 Satz 1), e.g. `distance_to_boundary >= setback_depth`. Recording that rule with `>=` while keeping this one at `==` preserves the distinction. In the example file, Satz 2 (`max(0.2 × H, 3 m)` in commercial and industrial zones), Satz 3 (3 m for small residential buildings) and Satz 4 (override by a local statute) are exceptions of the same rule.

#### Validation Scope

JSON Schema validation ensures:

- Expressions use valid node types and operators.
- Numeric literals contain numbers rather than strings.
- Operations contain the required number of operands.
- Nested expressions follow the defined recursive structure.
- Free-text formula expressions are rejected.
- A formula states its relation (`operator`) and its unit, and references at least one fact.
- A literal zero divisor is rejected at any depth.

JSON Schema validation does **not** execute calculations, resolve input facts, convert units, check dimensional consistency, or determine legal applicability. A divisor that only evaluates to zero, such as `3 m − 3 m`, is not detected.

### 4d. Temporal Relations

A temporal requirement states when an action takes place relative to an event or a calendar date. Each relation has exactly one anchor shape, so the same deadline cannot be written in two ways:

| Relation | Meaning | Anchor fields |
|---|---|---|
| `within` | at the latest `duration` after `startEvent` | `startEvent` + `duration` |
| `for_at_least` | maintained for at least `duration` from `startEvent` | `startEvent` + `duration` |
| `after` | not before `startEvent` (plus `duration`, if given) | `startEvent`, optional `duration` |
| `before` | earlier than `endEvent` (minus `duration`, if given) or `deadline` | `endEvent` (+ optional `duration`) **or** `deadline` |
| `no_later_than` | at the latest at `endEvent` (minus `duration`, if given) or `deadline` | `endEvent` (+ optional `duration`) **or** `deadline` |
| `until` | continuing up to `endEvent` or `deadline` | `endEvent` **or** `deadline`, optional `startEvent` |

A `duration` counts forward from `startEvent` and backward from `endEvent`. A `deadline` is a calendar date and never combines with a `duration`. Forward deadlines ("spätestens einen Monat nach …") use `within`. `no_later_than` and `before` end at an event or a date: `no_later_than` includes the end point, `before` does not. There is no `by` relation; it would duplicate `no_later_than`.

The relation carries no modality. The rule's `classification.type` supplies it: an obligation means the action must take place in the period, a permission that it may, a prohibition that it must not.

#### Example: MBO § 62 Abs. 3 Satz 2 — Earliest Start

The source reads "Mit dem Bauvorhaben darf einen Monat nach Eingang der erforderlichen Unterlagen bei der Gemeinde begonnen werden." This is a permission with an earliest start, not a deadline. Recording it as a `procedural_requirement` with a `duty_holder` and `relation: "within"` would read as "must begin within one month". The example records it as:

```json
"classification": { "type": "permission", "normativeCategory": "procedural", "summary": "Mit dem Bauvorhaben darf einen Monat nach Eingang der erforderlichen Unterlagen bei der Gemeinde begonnen werden." },
"applicability": { "actors": [{ "role": "beneficiary", "entity": "Bauherr" }, { "role": "authority", "entity": "Gemeinde" }] },
"requirementExpression": {
  "kind": "requirement",
  "requirement": {
    "kind": "temporal",
    "action": "mit dem Bauvorhaben beginnen",
    "startEvent": "Eingang der erforderlichen Unterlagen bei der Gemeinde",
    "relation": "after",
    "duration": { "value": 1, "unit": "month" }
  }
}
```

Satz 3 allows an earlier start once the Gemeinde has given notice. It is recorded as an `alternative` exception with `relation: "after"` and the notice as `startEvent`.

### 4e. Permissions Are Not Obligations

The `requirements` of a permission describe what is allowed, not what is owed. The permitted party is the `beneficiary` and is not a `duty_holder`. The schema rejects a `permission` rule that lists a `duty_holder` actor. If a provision grants a permission and imposes a duty, split it into two rules.

### 5. Explicit Review and Machine-Checkability

The `review` section holds `status`, `notes[]`, `machineCheckable` (boolean), `checkMethods[]` (ids, shacl, sparql, llm_comparison, manual) and `ambiguities[]`. This distinguishes between "schema-valid rule" and "actually executable against evidence."

### 6. Optional External Mappings

IFC, RDF and other data model mappings live in an optional `externalMappings[]` array. This is not part of the normative representation — it records which external standard, entity class and property path a requirement's fact maps to. This preserves the presentations' IFC mapping workflow without making it mandatory.

### 7. Universal Applicability

The schema is document-neutral:
- No IFC, MBO or EU-specific mandatory fields.
- Works for German laws, EU regulations/directives, ISO/EN standards and other normative documents.
- Preserves the distinction between: a normative legal requirement, a machine-checkable representation, and a mapping to a specific external data model.

## Representable Patterns

- Definitions with conditional predicates
- Obligations, prohibitions, permissions
- Conditional and procedural requirements
- Nested AND/OR/NOT predicate trees
- Typed comparison values with validation
- Temporal requirements (duration, deadline, event-based)
- Boolean, numeric and text requirements
- Formula requirements with structured, recursively nested arithmetic expressions
- Unresolved predicates and requirements
- Exceptions with effects (disapplies, modifies, alternatives)
- Cross-references with relationship labels
- Scope exclusions

## Ideas Adopted from Presentations

| Idea | Source | How adopted |
|---|---|---|
| Clause splitting into individual checks | Sprint Scope, slide 2 | Each rule represents one split requirement |
| `source / applies_to / check` structure | Sprint Scope, slides 4–5 | `source` / `applicability` / `requirements` sections |
| `fact / operator / value / unit` naming | Sprint Scope, slide 4 | `fact` in all requirement and predicate types |
| `entity` and `when` in applicability | Sprint Scope, slide 5 | `applicability.targets[]` + `applicability.conditions` |
| `anyOf` for alternative requirements | Sprint Scope, slide 5 | `requirementExpression` with `kind: "any"` |
| PDF page numbers in source | Sprint Scope, slide 4 | `source.elements[].pdfPages` |
| IFC/RDF mapping as separate step | IFC v6, slides 10–13 | `externalMappings[]` as optional, non-core |
| Multiple validation methods | IFC v6, slides 6–9 | `review.checkMethods[]` |
| LLM comparison as validation option | IFC v6, slides 6, 9 | `llm_comparison` in checkMethods |
| Human review for unresolved rules | Both | `review` section with status, ambiguities, notes |

## Schema History and Migration

The schema was consolidated from two versioned schemas. The Rule JSON 1.0 schema (`backend/schemas/rule-json/1.0/`), its tests and its fixture were removed, and the hardened 2.0 schema moved from `backend/schemas/rule-json/2.0/` to `backend/schemas/rule-json/rule.schema.json`. Records still declare `schemaVersion` `2.0`; a record with `schemaVersion` `1.0` is rejected, and the Artifacts viewer no longer shows records in the 1.0 shape. A coverage review of the 1.0 schema against the full MBO and EU Legal JSON trees is kept in the git history of this file; it has not been repeated for the current schema.

### Migrating a Rule JSON 1.0 record

There is no automatic migration. A 1.0 record converts without semantic loss, but a converted formula must state its relation and a temporal requirement must use the canonical anchor shape of its relation:

| 1.0 | Current | Migration |
|---|---|---|
| `schemaVersion: "1.0"` | `schemaVersion: "2.0"` | change the value |
| `documentReference` + `source[]` | `source` with `documentId`, `documentTitle`, `documentVersion`, `citation`, `language` and `elements[]` | merge document and element data into one `source` object |
| `source[].sentenceNumber` | `source.elements[].sentenceId` | use the Legal JSON sentence ID |
| `source[].role: "primary_normative_text"` | `source.elements[].role: "primary"` | rename the value |
| `type`, `summary` | `classification.type`, `classification.summary` | wrap in `classification` |
| `applicability` (predicate), `actors[]`, `scopeExclusions[]` | `applicability.conditions`, `applicability.actors[]`, `applicability.scopeExclusions[]` | move inside `applicability` |
| `actors[].reference` | `applicability.actors[].definedIn` | rename |
| `status`, `reviewNotes[]` | `review.status`, `review.notes[]` | wrap in `review` |
| `property` (everywhere) | `fact` | rename |
| `ProvisionReference` | `CrossReference` | same fields |
| operators `eq`, `ne`, `gt`, `gte`, `lt`, `lte` | `==`, `!=`, `>`, `>=`, `<`, `<=` | replace the symbol (`in`, `not_in`, `contains` unchanged) |
| optional comparison `valueType` | required `valueType` | add the type of `value` |
| text operators `equals`, `one_of`, `contains` | `==`, `in`, `contains` | rename the operator |
| formula `expression` string | structured arithmetic tree with `operator` and `unit` | rewrite the expression; state the relation |
| temporal relation `by` | `no_later_than` | rename; use the relation table |
| permission with a `duty_holder` | permission with a `beneficiary` | change the role, or split the rule |

### Hardening of the 2.0 schema

Before the consolidation, the 2.0 schema was hardened. It rejects some records that the earlier 2.0 schema accepted:

| Change | Records that become invalid | Migration |
|---|---|---|
| `valueType` required on comparison predicates | predicates without `valueType` | add the type of `value` |
| operator ↔ `valueType` compatibility, unique array items | e.g. `>` with a string, `contains` with a boolean, duplicate `in` values | fix the operator or the type |
| `unit` without whitespace | units such as `"3 m"` or `" m"` | write the bare unit (`m`) |
| Text requirement operators `equals` / `one_of` → `==` / `in` | text requirements using the old names | rename the operator |
| Text requirement value typed per operator | `==` with an array, `in` with a string or non-string items | use a string for `==` / `contains`, an array of strings for `in` |
| Formula `operator` and `unit` required | formulas without them | add `operator` (`==` for a calculated value, `>=` / `<=` for a bound) and the result `unit` |
| Formula must reference a fact | formulas that are constants | use a numeric requirement |
| Literal zero divisor rejected | `divide` by `{ "kind": "literal", "value": 0 }` | fix the formula |
| Temporal anchor shape per relation; `by` removed | e.g. `before` counted from `startEvent`, `until` with `duration`, `by` | use the canonical form of the relation table, `no_later_than` for `by` |
| `permission` without `duty_holder` | permission rules naming a duty holder | use `beneficiary`, or split the rule |

Both example files validate against the schema.

## What Needs Semantic Validation

A record that passes the schema is well-formed, not legally correct. The schema cannot check:

- whether a rule matches the meaning of its source text, including its modality and its operator (`==` vs `>=`);
- dimensional consistency of formulas (adding metres to square metres, a result unit that differs from the expression's), and unit conversion;
- divisors that evaluate to zero at runtime;
- whether fact names are defined, consistent across rules, or available in the evidence (IFC, digital twin);
- period computation (calendar months, whether the boundary day counts, public holidays) and whether `startEvent`/`endEvent` describe real events;
- that `elementId`, `sentenceId` and `pdfPages` exist in and agree with the Legal JSON document (the opt-in reference test below checks this for the examples; `citation` text is not checked);
- consistency between the `requirements` of a rule and of its exceptions, or between rules that conflict.

## Running Tests

From `backend/`:

```bash
python3 -m pytest tests/test_rule_json_schema.py --noconftest -v
```

To also check the example element IDs, `pdfPages` and sentence IDs against the Legal JSON of a processed MBO and EU job (otherwise these checks are skipped):

```bash
ODOS_MBO_LEGAL_JSON_PATH=/path/to/mbo/document.json ODOS_EU_LEGAL_JSON_PATH=/path/to/eu/document.json \
  python3 -m pytest tests/test_rule_json_schema.py --noconftest -v
```

## Future Rule Interpreter

The schema itself does no extraction. A first LLM extractor on Amazon Bedrock exists ([bedrock-rule-extraction.md](bedrock-rule-extraction.md)): it sends Legal JSON to the model, rewrites the provenance from the Legal JSON and stores validated `draft` records as `rules.json`. An interpreter can receive the relevant Legal JSON source nodes, this schema or a constrained structured-output equivalent, and extraction instructions to preserve modality, actors, conditions, exceptions, references and unresolved meaning. It should cite only IDs from the supplied document, treat recitals as context unless supported by operative provisions, and emit `draft` records for human review.

## Files

| File | Description |
|---|---|
| [backend/schemas/rule-json/rule.schema.json](../backend/schemas/rule-json/rule.schema.json) | The Rule JSON schema (Draft 2020-12, `schemaVersion` `2.0`) |
| [backend/tests/test_rule_json_schema.py](../backend/tests/test_rule_json_schema.py) | Schema tests, example validation and the opt-in Legal JSON reference check |
| [dev-fixtures/rule-json-examples/](../dev-fixtures/rule-json-examples/README.md) | Simulated, labeled EU and MBO Rule JSON examples (also used by the schema tests) |
