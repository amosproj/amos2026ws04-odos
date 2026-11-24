# Issue #36 — Build the LLM rule interpreter and compare it with hand-written rules

**Project:** AMOS ODOS — Ontology-Driven Operating System
**Sprint:** 05
**Feature branch:** `feature/36-standard-evaluation`

## Overview

This deliverable contains a prototype for evaluating LLM-generated legal rules against manually defined reference calculations using the German Musterbauordnung (MBO) §6(5).

The prototype demonstrates how structured rules generated using AWS Bedrock can be evaluated against reference formulas and synthetic building scenarios.

## Implementation

- Arithmetic expression evaluation for structured Rule JSON.
- Comparison of LLM-generated formulas with manually defined reference calculations.
- Scenario-based evaluation of building setback requirements.
- Handling of missing facts, unresolved exceptions, and review-required conditions.
- Preservation of draft status and human-review requirements.

## Contents

- `src/rule_evaluator.py` — Prototype rule evaluator.
- `fixtures/mbo-6-5.rules.json` — Sample generated Rule JSON.
- `tests/test_issue36_llm_evaluation.py` — Rule structure and source-reference tests.
- `tests/test_issue36_llm_vs_manual.py` — LLM-generated versus manual formula comparisons.
- `tests/test_issue36_rule_calculations.py` — Reference calculation tests.
- `tests/test_issue36_rule_evaluator.py` — Scenario evaluation tests.

## Previous Test Results

The prototype was tested in its original backend location:

- **40 dedicated Issue #36 tests passed.**
- **599 backend tests passed, 47 skipped, 1 warning.**

These are historical test results from the development environment, not a fresh test run of the copied deliverable.

## Running the Tests

The copied files are intended as a reviewable prototype. They retain imports and fixture assumptions from the ODOS backend and are not independently executable without adjustment.

The original implementation remains under `backend/`, where the dedicated tests can be executed from the backend directory:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  .\tests\test_issue36_llm_evaluation.py `
  .\tests\test_issue36_llm_vs_manual.py `
  .\tests\test_issue36_rule_calculations.py `
  .\tests\test_issue36_rule_evaluator.py
```

## Limitations

- This is a proof of concept focused on MBO §6(5), not a general legal compliance engine.
- LLM-generated rules remain drafts requiring human review.
- Technical PASS/FAIL results do not constitute certified legal compliance.
- Certain statutory exceptions and applicability conditions remain unresolved.
- Integration into the current validation workflow requires additional review.

## Integration Status

The implementation is copied here for Sprint 5 review. The original backend files have been retained to preserve the working prototype.

No merge into `develop` is implied by this deliverable. Integration and any relocation of the original implementation remain subject to team review.
