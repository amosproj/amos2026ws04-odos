# Rule JSON 1.0 vs 2.0 — Detailed Comparison

## Structural Overview

| Aspect | 1.0 | 2.0 | Change |
|---|---|---|---|
| Top-level organization | Flat fields | Grouped into sections | **Reorganized** |
| Schema version | `"1.0"` | `"2.0"` | **Breaking** |
| Root required fields | `schemaVersion, id, type, documentReference, source, status, summary` | `schemaVersion, id, source, classification, review` | **Changed** |

## Field-by-Field Mapping

### Source Provenance

| 1.0 Field | 2.0 Field | Status |
|---|---|---|
| `documentReference.documentId` | `source.documentId` | **Moved** |
| `documentReference.title` | `source.documentTitle` | **Renamed** (clarity) |
| `documentReference.version` | `source.documentVersion` | **Renamed** (clarity) |
| `documentReference.citation` | `source.citation` | **Moved** |
| `documentReference.language` | `source.language` | **Moved** |
| `source[].elementId` | `source.elements[].elementId` | **Moved** into unified source |
| `source[].sentenceNumber` | `source.elements[].sentenceId` | **Renamed**: number → Legal JSON sentence ID |
| `source[].role` | `source.elements[].role` | **Preserved** (simplified enum: `primary_normative_text` → `primary`) |
| `source[].description` | `source.elements[].description` | **Preserved** |
| — | `source.elements[].pdfPages` | **New**: PDF page numbers from Legal JSON |

**Justification:** Unifying `documentReference` and `source[]` into a single `source` object eliminates the split between document-level and element-level provenance. Adding `pdfPages` enables direct navigation to the original PDF. Renaming `sentenceNumber` to `sentenceId` aligns with Legal JSON 2.0's sentence ID system.

### Classification

| 1.0 Field | 2.0 Field | Status |
|---|---|---|
| `type` | `classification.type` | **Moved** into classification section |
| `summary` | `classification.summary` | **Moved** into classification section |
| — | `classification.normativeCategory` | **New**: substantive, procedural, definitional, transitional, organizational, informational |
| — | `classification.type: "procedural_requirement"` | **New** type value |

**Justification:** Grouping `type`, `normativeCategory` and `summary` provides clearer semantics. The new `normativeCategory` allows filtering rules by their legal nature beyond the simple obligation/prohibition distinction.

### Applicability

| 1.0 Field | 2.0 Field | Status |
|---|---|---|
| `applicability` (predicate) | `applicability.conditions` | **Moved** into applicability section |
| `actors[]` | `applicability.actors[]` | **Moved** into applicability section |
| `scopeExclusions[]` | `applicability.scopeExclusions[]` | **Moved** into applicability section |
| — | `applicability.targets[]` | **New**: explicit target entities |
| `actors[].reference` | `applicability.actors[].definedIn` | **Renamed** for clarity |

**Justification:** Grouping targets, actors, conditions and exclusions reflects the presentations' `applies_to` concept. Adding explicit `targets[]` avoids encoding target entities as predicate comparisons.

### Requirements

| 1.0 Field | 2.0 Field | Status |
|---|---|---|
| `requirements[]` | `requirements[]` | **Preserved** |
| `requirementExpression` | `requirementExpression` | **Preserved** |
| All `*.property` fields | All `*.fact` fields | **Renamed**: property → fact |
| All requirement kinds | All requirement kinds | **Preserved** (boolean, numeric, text, formula, temporal, unresolved) |

**Justification:** The rename from `property` to `fact` follows the sprint-proposal terminology and better describes the semantic role (a piece of evidence needed for evaluation). All requirement structures are preserved.

### Definition

| 1.0 Field | 2.0 Field | Status |
|---|---|---|
| `definition.term` | `definition.term` | **Preserved** |
| `definition.text` | `definition.text` | **Preserved** |
| `definition.meaning` | `definition.meaning` | **Preserved** |
| `definition.condition` | `definition.condition` | **Preserved** |
| `definition.references[]` | `definition.references[]` | **Preserved** (uses CrossReference) |

### Exceptions and References

| 1.0 Field | 2.0 Field | Status |
|---|---|---|
| `exceptions[]` | `exceptions[]` | **Preserved** |
| `references[]` (ProvisionReference) | `references[]` (CrossReference) | **Renamed** type (same fields) |

**Justification:** `CrossReference` is a clearer name than `ProvisionReference` since references can point to external standards, not only legal provisions.

### Review

| 1.0 Field | 2.0 Field | Status |
|---|---|---|
| `status` | `review.status` | **Moved** into review section |
| `reviewNotes[]` | `review.notes[]` | **Moved** and renamed |
| — | `review.machineCheckable` | **New**: boolean flag |
| — | `review.checkMethods[]` | **New**: ids, shacl, sparql, llm_comparison, manual |
| — | `review.ambiguities[]` | **New**: specific ambiguity descriptions |

### New in 2.0

| Field | Purpose |
|---|---|
| `source.elements[].pdfPages` | PDF page provenance from Legal JSON |
| `source.elements[].sentenceId` | Legal JSON sentence ID |
| `classification.normativeCategory` | Broader legal classification |
| `classification.type: "procedural_requirement"` | New rule type |
| `applicability.targets[]` | Explicit target entities |
| `review.machineCheckable` | Whether the rule can be automatically checked |
| `review.checkMethods[]` | Potential validation methods |
| `review.ambiguities[]` | Structured ambiguity recording |
| `externalMappings[]` | Optional IFC/RDF/IDS mapping metadata |

## Breaking Changes

| Change | Impact | Migration |
|---|---|---|
| `schemaVersion: "2.0"` | All records need version bump | Automated |
| `documentReference` → `source` | Field restructured | Merge document + element data into one `source` object |
| `type` → `classification.type` | Moved into nested object | Wrap in `classification` with a `summary` |
| `status` → `review.status` | Moved into nested object | Wrap in `review` object |
| `property` → `fact` (everywhere) | All predicates and requirements renamed | Find-and-replace |
| `actors[]` → `applicability.actors[]` | Moved into nested object | Move inside `applicability` |
| `ProvisionReference` → `CrossReference` | Type renamed | Rename only (same fields) |
| Operators `eq/ne/gt/gte/lt/lte` → `==/!=/>/>=/</<=` | Symbols in comparison and numeric requirements (`in`, `not_in`, `contains` unchanged) | Value replacement |
| `source[].role: "primary_normative_text"` → `"primary"` | Simplified enum value | String replace |

## Compatibility Considerations

1. **No automatic migration** — 1.0 and 2.0 are separate schema versions. Both schemas can coexist.
2. **Semantic preservation** — every 1.0 rule can be converted to 2.0 with structural reorganization and field renaming. No semantic loss.
3. **Forward compatibility** — 2.0 adds fields (pdfPages, normativeCategory, machineCheckable, externalMappings) that are all optional except where they fill genuine gaps.
4. **Existing tests** — all 1.0 test patterns have direct 2.0 equivalents in the proposal test suite.

## What Was NOT Changed

- Predicate tree structure (`all`/`any`/`not`/`comparison`/`unresolved`)
- Requirement types (boolean, numeric, text, formula, temporal, unresolved)
- RequirementExpression nesting logic
- Exception model (kind, condition, effect)
- Typed value validation with `valueType`
- `additionalProperties: false` on all objects
- Duration model (value + unit)
- Cross-reference relationship labels
