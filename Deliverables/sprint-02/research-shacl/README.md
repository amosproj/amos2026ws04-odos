# SHACL and pySHACL research for ODOS

A reproducible demonstration for [AMOS ODOS issue #11](https://github.com/amosproj/amos2026ws04-odos/issues/11): checking RDF digital twins against explicitly modeled normative requirements.

Read the [research report](REPORT.md) for the background research, architecture, source interpretation, empirical results and adoption recommendation. The [team presentation](presentation/AMOS_SHACL_Research.pptx) summarizes the findings. See [HANDOFF.md](HANDOFF.md) for repository transfer guidance and [PUBLISH_REVIEW.md](PUBLISH_REVIEW.md) for the completed readiness review.

## Requirements and setup

Use Python 3.12 or later and [uv](https://docs.astral.sh/uv/). From this directory:

```bash
uv sync --locked
uv run --locked demo.py
```

The package disables automatic Python downloads in `uv.toml`. Supply an existing compatible interpreter if uv cannot find one, for example `uv sync --locked --python python3.12`.

The expected final line is `17/17 tests passed`. A failed conformance check is the correct outcome for a deliberately invalid test input. Dependency versions are pinned in `pyproject.toml` and resolved in `uv.lock`.

## Demonstration flow

```text
Supplied MBO PDF
    Text extraction and structural segmentation
Document JSON with page references
    Manually interpreted rule template plus source clauses
Rule JSON
    Programmatic constraint generation
SHACL shapes plus RDF digital-twin input
    pySHACL validation
Conformance result and violation reports
```

Text extraction, supported-rule compilation and validation are automatic. **Interpretation of normative prose is manual.** The rule template records the modeling assumptions. This is not an automatic legal-text-to-SHACL system or a complete MBO compliance checker.

## Package contents

| Path | Purpose |
|---|---|
| `demo.py` | Extraction, rule attachment, SHACL generation, validation and sample tests. |
| `collect_evidence.py` | Reproduce the test log, provenance checks and JSON threshold experiment. |
| `rules/template.json` | Manually interpreted rules and explicit assumptions. |
| `MusterBauVerordnung.pdf` | Supplied source fixture, with version and attribution in `THIRD_PARTY_NOTICES.md`. |
| `samples/` | Editable RDF examples and expected outcomes. |
| `output/document.json` | All 83 pages of extracted text and heuristic document structure. |
| `output/rules.json` | Source-linked rules with PDF fingerprint and selected clauses. |
| `output/window_shapes.ttl` | MBO section 37(5), under the documented mapping. |
| `output/setback_shapes.ttl` | Section 6(5), sentence 1, general-case arithmetic experiment. |
| `output/test_results.json` | Expected and observed results. |
| `output/reports/` | Readable, JSON and RDF validation reports. |
| `output/evidence/` | Test log, environment versions, file fingerprints and mutation evidence. |
| `presentation/` | Editable PowerPoint presentation for the team. |

## Check your own RDF input

Copy an example before editing it:

```bash
cp samples/valid_boundary.ttl my-window.ttl
uv run --locked demo.py validate --data my-window.ttl
```

For example:

```turtle
@prefix ex: <https://example.org/amos/mbo#> .

ex:MyWindow a ex:EscapeWindow ;
    ex:clearWidthM 0.90 ;
    ex:clearHeightM 1.20 ;
    ex:heightAboveFloorM 1.20 ;
    ex:inRoofSlopeOrRoofStructure false .
```

Change the width to `0.80` and rerun the same command. The result should change to `conforms: false`, with a finding for `clearWidthM`.

The current wrapper accepts RDF serialized as **Turtle (`.ttl`)**. Lengths use metres and strict `xsd:decimal` literals. In Turtle, `0.90` is decimal, `"0.90"` is a string and `1` is an integer. Use `1.00` for a decimal metre value. Supply the roof flag as a boolean, including `false` for ordinary windows.

Conforming input exits with status 0. Non-conforming input exits with status 1. Invalid input, invalid shapes or the absence of explicitly typed target objects raise an error. Ad-hoc reports overwrite `output/reports/custom.{json,txt,ttl}`.

## Edit the rule JSON

```bash
cp output/rules.json my-rules.json
# Edit the copied JSON, including the matching message text.
uv run --locked demo.py compile --rules my-rules.json
uv run --locked demo.py validate --data my-window.ttl
```

Changing the minimum width from `0.90` to `1.00` makes an otherwise valid 0.90 m-wide window fail. The compiler supports the demonstration's defined JSON rule vocabulary, not every possible rule language.

The default `all` command recreates generated JSON, shapes, samples and reports. It overwrites manual edits to those generated files. Keep personal experiments in separately named files such as `my-window.ttl` and `my-rules.json`.

## Individual stages

```bash
uv run --locked demo.py extract
uv run --locked demo.py compile
uv run --locked demo.py test
uv run --locked demo.py --help
```

`extract` only creates document JSON. `compile` uses the existing `output/rules.json`. `test` uses the current shapes and the fixed expected outcomes.

## Calculation experiment

The arithmetic comes from MBO section 6(5), sentence 1, independently of the window example:

```text
setbackDepthM >= max(0.4 * effectiveHeightHM, 3.0)
```

```bash
uv run --locked demo.py validate \
  --data samples/setback_too_small.ttl \
  --shapes output/setback_shapes.ttl
```

For H=10 m, a 3.99 m setback fails because the minimum is 4 m. For H=5 m, the absolute 3 m minimum controls. H must already have been calculated under section 6(4). Commercial/industrial factors, residential exceptions and local provisions are outside this experiment.

## Reproduce the research evidence

```bash
uv run --locked demo.py
uv run --locked collect_evidence.py
```

The collector checks all 17 expected outcomes, source fingerprints and source pages. It then holds RDF input constant, changes the minimum width in JSON to 1.00 m, generates shapes and records the changed result. It restores the original shapes byte for byte, including when the experiment fails. It discovers uv through `PATH` and stores no absolute interpreter path in the evidence metadata.

## Interpretation and coverage

- `ex:EscapeWindow` is a custom demonstration class for upstream-classified escape-route windows under section 33(2), sentence 2.
- The 0.90 x 1.20 m dimensions map to width then height. Rotation and measurement conventions require domain review.
- For roof windows, the lower edge or a qualifying step may meet the horizontal distance condition. Step suitability is an upstream assumption.
- Required datatypes, single-value cardinality and nonnegative bounds include data-contract checks in addition to the source thresholds.
- An input with no target objects is rejected. Unclassified objects in mixed data remain outside the selected target set.
- Passing establishes conformance to these selected constraints on supplied data. It does not establish complete MBO compliance or correspondence with physical reality.

The PDF parser retains all page text but segments headings heuristically. A known missing section sign before section 23 is repaired only for segmentation and recorded in the JSON. The selected source clauses were checked against their rendered PDF pages. Original German clauses are retained as source evidence; authored instructions, code comments, report and slides use English.

