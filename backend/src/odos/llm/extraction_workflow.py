"""Bounded extraction feedback with lossless candidate retention and per-run reports.

The single-round extractor remains available for isolated checks. This workflow is
the API/CLI entry point: at most three Converse calls, including JSON corrections.
Checks provide feedback, never permission to silently discard a candidate.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from odos.llm.bedrock import API_KEY_ENV, BedrockClient, BedrockError
from odos.llm.model_output import OutputParseError, parse_model_output, redact
from odos.llm.profiles import PROMPT_VERSION, profile_for
from odos.llm.rule_checks import add_flags, check_rule_set
from odos.llm.rule_extraction import (
    ExtractionResult, _context, describe_schema_error, estimate_tokens, finalize_rule, prepare_request, rule_schema, rule_validator, scoped_rule_id,
)
from odos.llm.source_checks import SourceText, check_quantities, coverage

MAX_MODEL_CALLS = 3


def _expression_issues(rule) -> list[str]:
    """Explain misplaced expression kinds without selecting an unrelated oneOf error branch."""
    schema = rule_schema()
    atoms = {schema["$defs"][branch["$ref"].split("/")[-1]]["properties"]["kind"]["const"]
             for branch in schema["$defs"]["Requirement"]["oneOf"]}
    issues = []

    def visit(node, path):
        if isinstance(node, dict):
            if node.get("kind") == "requirement" and isinstance(node.get("requirement"), dict):
                kind = node["requirement"].get("kind")
                if not isinstance(kind, str) or kind not in atoms:
                    issues.append(f"{path}/requirement/kind: {kind!r} is not an atomic requirement kind. "
                                  f"Allowed kinds: {', '.join(sorted(atoms))}. Logical all/any/not nodes belong "
                                  "directly in the expression tree; comparison predicates belong in conditions.")
            for key, value in node.items():
                visit(value, f"{path}/{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                visit(value, f"{path}/{i}")

    visit(rule, "")
    return issues


def _source_view(rule) -> dict:
    """Project malformed records into safe citation-only objects for coverage checks."""
    if not isinstance(rule, dict):
        return {}
    source = rule.get("source")
    elements = source.get("elements", []) if isinstance(source, dict) else []
    elements = [e for e in elements if isinstance(e, dict) and isinstance(e.get("elementId"), str)
                and (e.get("sentenceId") is None or isinstance(e.get("sentenceId"), str))] if isinstance(elements, list) else []
    return {"id": rule.get("id"), "source": {"elements": elements}}


def inspect_candidates(candidates: list, legal: dict, request, client) -> tuple[list, dict]:
    """Return every candidate plus advisory checks. No invalid/duplicate record disappears."""
    ctx = _context(legal, request.document)
    source = SourceText.of(request.target_document or request.document, None if request.scope == "document" else request.scope)
    retained, checks, valid = [], [], []
    taken: set[str] = set()
    repairs: dict = {}
    for index, candidate in enumerate(candidates):
        try:
            normalized, errors = finalize_rule(candidate, ctx, taken, "LLM extraction workflow", repairs)
        except (TypeError, ValueError, KeyError, AttributeError) as error:
            normalized, errors = None, [f"Record inspection failed: {type(error).__name__}"]
        if normalized is not None:
            retained.append(normalized)
            valid.append(normalized)
        else:
            kept = copy.deepcopy(candidate)
            if isinstance(kept, dict):
                base = scoped_rule_id(ctx.document_id, kept.get("id") or f"record-{index + 1}")
                identifier, suffix = base, 1
                while identifier in taken:
                    suffix += 1
                    identifier = f"{base}-{suffix}"
                kept["id"] = identifier
                taken.add(identifier)
                review = kept.get("review")
                kept["review"] = {**(review if isinstance(review, dict) else {}), "status": "draft"}
            retained.append(kept)
        schema_errors = list(rule_validator().iter_errors(retained[-1]))
        checks.append({"index": index, "id": retained[-1].get("id") if isinstance(retained[-1], dict) else None,
                       "validationPassed": normalized is not None,
                       "schemaValid": not schema_errors,
                       "schemaErrors": _expression_issues(retained[-1]) + [describe_schema_error(e) for e in schema_errors],
                       "errors": _expression_issues(candidate) + errors if errors else [], "flags": []})

    # Existing set/quantity checks run on structurally usable records only.
    _, duplicates, set_flags = check_rule_set(valid)
    quantity_flags = check_quantities(valid, source)
    duplicate_flags = {r["id"]: reason for r, reason in duplicates}
    for index, rule in enumerate(retained):
        check = checks[index]
        if check["validationPassed"]:
            flags = set_flags.get(rule["id"], []) + quantity_flags.get(rule["id"], [])
            if rule["id"] in duplicate_flags:
                flags.append(duplicate_flags[rule["id"]])
            add_flags(rule, flags)
            check["flags"] = [a for a in rule.get("review", {}).get("ambiguities", []) if isinstance(a, str)]
    cov = coverage([_source_view(r) for r in retained], source)
    # A citation is coverage evidence, not a proof that a legal requirement is faithfully represented.
    return retained, {"records": checks, "schemaValid": all(c["schemaValid"] for c in checks), "coverage": cov, "repairs": repairs,
                      "coverageMeaning": "Source citation coverage only, not verified semantic completeness."}


def _feedback(candidates: list, inspection: dict) -> tuple[str, set[int]]:
    targets = {c["index"] for c in inspection["records"] if not c["schemaValid"]}
    feedback = {"issues": [{"index": c["index"], "id": c["id"], "schemaErrors": c["schemaErrors"]}
                           for c in inspection["records"] if c["index"] in targets],
                "candidatesToRevise": [{"index": i, "rule": candidates[i]} for i in sorted(targets)],
                "existingRecords": [{"index": i, "id": r.get("id"), "source": r.get("source"),
                                     "classification": r.get("classification")}
                                    for i, r in enumerate(candidates) if isinstance(r, dict)]}
    prompt = (
        "Fix only the JSON Schema errors of the listed records, preserving all "
        "substantive requirements, thresholds, conditions, exceptions and citations. Do not remove content merely "
        "to pass schema checks. Content ambiguities and source-coverage findings are advisory only. "
        "Do not rewrite schema-valid records or add new rules for those findings. Keep additions empty. "
        "Return ONE JSON object: {\"replacements\": [{\"index\": 0, \"rule\": {}}], \"additions\": []}. "
        "Each replacement must use an index from candidatesToRevise. A rule is the complete revised Rule JSON "
        "record, not a JSON patch. Omitted indexes stay unchanged. There is no delete operation. "
        "If a problem cannot be resolved from the supplied source, keep the content and explain the ambiguity.\n"
        + json.dumps(feedback, ensure_ascii=False)
    )
    return prompt, targets


def _parse_patch(text: str) -> dict:
    stripped = text.strip()
    start = stripped.find("{")
    if start < 0:
        raise ValueError("Correction has no JSON object")
    envelope, _ = json.JSONDecoder().raw_decode(stripped, start)
    if not isinstance(envelope, dict) or not isinstance(envelope.get("replacements"), list) or not isinstance(envelope.get("additions", []), list):
        raise ValueError("Correction must contain replacements and additions lists")
    return {"replacements": envelope["replacements"], "additions": envelope.get("additions", [])}


def _merge(candidates: list, patch: dict, targets: set[int]) -> tuple[list, list]:
    merged, changes, seen = copy.deepcopy(candidates), [], set()
    for replacement in patch["replacements"]:
        index = replacement.get("index") if isinstance(replacement, dict) else None
        rule = replacement.get("rule") if isinstance(replacement, dict) else None
        if type(index) is not int or index not in targets or index in seen or not isinstance(rule, dict):
            changes.append({"action": "ignored", "reason": "Invalid, duplicate or non-target replacement index"})
            continue
        if not any(rule.get(k) for k in ("requirements", "requirementExpression", "definition")):
            changes.append({"action": "ignored", "index": index, "reason": "Replacement would erase the rule content"})
            continue
        changes.append({"action": "replace", "index": index, "before": copy.deepcopy(merged[index]), "after": copy.deepcopy(rule)})
        merged[index] = rule
        seen.add(index)
    for rule in patch["additions"]:
        changes.append({"action": "add", "index": len(merged), "rule": copy.deepcopy(rule)})
        merged.append(rule)
    return merged, changes


def extract_rules_workflow(legal_json: dict, *, client=None, element_ids=None,
                           diagnostics_dir: Path | None = None, accept_partial: bool = False,
                           prepared_request=None) -> ExtractionResult:
    """Generate, check and request at most two targeted revisions, then retain results with a report.

    Raw/unparseable and truncated responses survive in the report. Transport failures
    before any model response still raise normally; a failed correction retains earlier output.
    `accept_partial` is retained for call compatibility: recovery is always reported explicitly here.
    """
    import os

    client = client or BedrockClient()
    request = prepared_request or prepare_request(legal_json, client.config, element_ids)
    run_id = uuid4().hex
    report = {"runId": run_id, "documentId": legal_json.get("id"), "scope": request.scope,
              "modelId": client.config.model_id, "region": client.config.region, "promptVersion": PROMPT_VERSION,
              "inputDocument": copy.deepcopy(request.document),
              "workflowVersion": 2, "retryPolicy": "schema_only", "maxModelCalls": MAX_MODEL_CALLS,
              "maxFeedbackRounds": 2, "rounds": [], "notVerified":
              "Schema and citation checks do not establish legal correctness or complete extraction."}
    candidates, responses, rounds = [], [], report["rounds"]
    user, history, mode, targets = request.user, [], "initial", set()
    inspection = None
    incomplete = False
    for number in range(1, MAX_MODEL_CALLS + 1):
        system = request.system
        if mode == "patch":
            system += ('\nREVISION MODE: for this request only, the response envelope is '
                       '{"replacements": [{"index": 0, "rule": {}}], "additions": []}, replacing the initial '
                       '{"rules": [...]} envelope. The Rule JSON schema still applies to each replacement/addition record.')
        estimated = estimate_tokens(system) + estimate_tokens(user)
        estimated += sum(estimate_tokens(t) for _, t in history)
        if estimated + request.max_output_tokens > request.context_tokens:
            report["stoppedBecause"] = "Feedback request would exceed the configured context window"
            break
        try:
            response = client.converse(system, user, history=history or None)
        except BedrockError as error:
            if not responses:
                raise
            rounds.append({"round": number, "mode": mode, "requestFailed": type(error).__name__})
            report["stoppedBecause"] = f"Correction request failed: {type(error).__name__}"
            break
        responses.append(response)
        entry = {"round": number, "mode": mode, "rawResponse": response.text,
                 "inputTokens": response.input_tokens, "outputTokens": response.output_tokens,
                 "stopReason": response.stop_reason, "candidatesBefore": copy.deepcopy(candidates)}
        rounds.append(entry)
        parse_error = None
        try:
            if response.stop_reason == "malformed_model_output":
                raise ValueError("Bedrock reported malformed output")
            if mode == "patch":
                candidates, entry["changes"] = _merge(candidates, _parse_patch(response.text), targets)
            else:
                parsed = parse_model_output(response.text)
                if mode == "initial":
                    candidates = parsed.rules
                else:
                    # An initial JSON repair has no existing parsed records to overwrite.
                    candidates = parsed.rules
            if response.truncated:
                raise ValueError("Model response reached its output token limit")
        except (OutputParseError, ValueError, TypeError, KeyError) as error:
            parse_error = str(error)
            entry["parseError"] = parse_error
            if isinstance(error, OutputParseError) and error.salvaged and not candidates:
                candidates = error.salvaged
                entry["recoveredRecords"] = len(candidates)
            # A malformed correction does not invalidate an earlier complete extraction.
            incomplete = incomplete or mode != "patch" or response.truncated
        else:
            # A successful patch cannot certify that an earlier incomplete extraction recovered all content.
            if mode in ("initial", "json_repair"):
                incomplete = False
        entry["candidatesAfter"] = copy.deepcopy(candidates)
        retained, inspection = inspect_candidates(candidates, legal_json, request, client)
        entry["checks"] = copy.deepcopy(inspection)
        needs_feedback = bool(parse_error or not inspection["schemaValid"])
        if not needs_feedback or number == MAX_MODEL_CALLS:
            break
        if parse_error:
            if response.truncated and candidates and inspection["schemaValid"]:
                report["stoppedBecause"] = "Output was truncated; split this target into smaller provisions. Schema repair cannot recover missing content."
                break
            if mode == "patch" or candidates:
                user, targets = _feedback(candidates, inspection)
                user += "\nThe preceding correction could not be used: " + parse_error
                mode = "patch"
                history = [("user", request.user), ("assistant", response.text)]
            else:
                user = ("Your preceding response could not be read: " + parse_error +
                        '. Return the complete extraction as {"rules": [...]} with valid JSON, preserving all source content.')
                mode = "json_repair"
                history = [("user", request.user), ("assistant", response.text)]
        else:
            user, targets = _feedback(candidates, inspection)
            mode = "patch"
            history = [("user", request.user)]
        entry["feedback"] = user

    retained, inspection = inspect_candidates(candidates, legal_json, request, client)
    invalid = [c for c in inspection["records"] if c["errors"]]
    flagged = [c for c in inspection["records"] if c["flags"]]
    cov = inspection["coverage"]
    has_issues = bool(invalid or flagged or incomplete or cov["uncitedSentences"] or cov["uncitedElements"]
                      or report.get("stoppedBecause") or (rounds and rounds[-1].get("parseError")))
    report.update({"outcome": "completed_with_issues" if has_issues else "completed",
                   "checks": inspection, "finalCandidates": copy.deepcopy(candidates), "partial": incomplete,
                   "inputTokens": sum(r.input_tokens for r in responses),
                   "outputTokens": sum(r.output_tokens for r in responses),
                   "modelCalls": len(rounds), "feedbackRounds": max(0, len(rounds) - 1)})
    # Reports contain raw answers, never credentials from environment settings.
    report = json.loads(redact(json.dumps(report, ensure_ascii=False), secrets=(os.environ.get(API_KEY_ENV, ""),)))
    generation = {"provider": "aws-bedrock", "modelId": client.config.model_id, "region": client.config.region,
                  "documentId": legal_json.get("id"), "scope": request.scope, "runId": run_id,
                  "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "stopReason": responses[-1].stop_reason if responses else None,
                  "inputTokens": sum(r.input_tokens for r in responses), "outputTokens": sum(r.output_tokens for r in responses),
                  "rulesProposed": len(candidates), "rulesFlagged": len(flagged), "promptVersion": PROMPT_VERSION,
                  "profile": profile_for(legal_json).name, "coverage": cov,
                  "counts": {"proposed": len(candidates), "accepted": len(candidates) - len(invalid), "retained": len(retained),
                             "invalid": len(invalid), "rejected": 0, "flagged": len(flagged),
                             "repaired": len(inspection["repairs"].get("schemaRepairs", []))},
                  "modelOutput": {"requests": len(rounds), "parse": "workflow", "partial": incomplete, "diagnostics": []},
                  "workflow": {"outcome": report["outcome"], "modelCalls": len(rounds),
                               "schemaValid": inspection["schemaValid"], "workflowVersion": 2, "retryPolicy": "schema_only",
                               "feedbackRounds": max(0, len(rounds) - 1), "reportFile": "rule_extraction_report.json"},
                  "rulesWithIssues": invalid, "review": {"status": "draft", "humanReviewRequired": True,
                  "reason": "All candidates are retained. Checks are advisory and require human review."}}
    return ExtractionResult(rules=retained, generation=generation, report=report)
