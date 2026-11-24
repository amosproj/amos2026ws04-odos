"""Human review of extracted rules: requests, validation, the state of a job's rules and the approved export.

The extracted `rules.json` is the model's artifact and is never written here: review decisions are events in the
database (`odos.rule_review_repository`), bound to one extraction (`extractionId`) and to the hash of the original record.
A decision applies to the exact record that was decided on; an edit returns the rule to `pending`, so an acceptance never
survives a change of content. Automated checks (`verification`) are advisory and never set a decision.

Nothing here puts rule text, reviewer names or reasons into a log or an error message beyond what the caller sent."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from odos import rule_review_repository as repo
from odos.artifact_names import RULE_JSON
from odos.llm.rule_checks import FLAG_PREFIX, add_flags, check_rule
from odos.llm.rule_extraction import rule_validator

CRITERIA_VERSION = 1  # of `verification`: only "flagged" and "unverified" exist until the criteria are calibrated
MAX_EDIT_BYTES = 200_000
NOT_INITIALISED = ("Review storage is not initialised: apply backend/db/002_rule_reviews.sql to the database "
                   "(see Documentation/database-poc.md).")
NEEDS_DATABASE = "Review decisions need the database: start the backend with ODOS_DATABASE_ENABLED=1."
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

Action = Literal["accept", "reject", "edit", "reset"]
DECISION_OF: dict[str, str] = {"accept": "accepted", "reject": "rejected", "edit": "pending", "reset": "pending"}


class ReviewRequest(BaseModel):
    """Body of `POST /api/jobs/{id}/rule-reviews`: one event on one rule of the job's current rules.json."""

    model_config = {"extra": "forbid"}
    ruleId: str = Field(min_length=1, max_length=300)
    extractionId: str = Field(min_length=1, max_length=120)
    expectedRuleSha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expectedLastEventId: int = Field(ge=0)  # the rule's latest event the client saw; 0 = none
    action: Action
    reviewer: str  # self-declared name, not authenticated
    reason: str | None = Field(default=None, max_length=2000)
    editedRule: dict | None = None

    @field_validator("reviewer")
    @classmethod
    def _reviewer(cls, v: str) -> str:
        v = v.strip()
        if not 1 <= len(v) <= 100 or CONTROL_CHARS.search(v):
            raise ValueError("The reviewer name must be 1 to 100 characters without control characters.")
        return v

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v is not None else None

    @model_validator(mode="after")
    def _combination(self) -> ReviewRequest:
        if self.action == "reject" and not self.reason:
            raise ValueError("A reason is required to reject a rule.")
        if (self.action == "edit") != (self.editedRule is not None):
            raise ValueError("editedRule is required for the action 'edit' and not allowed for any other action.")
        return self


def canonical_sha256(rule: dict) -> str:
    """Hash of a record independent of key order and formatting."""
    return hashlib.sha256(json.dumps(rule, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def require_storage(persistent: bool) -> None:
    """503 unless the database is on and has the review table."""
    if not persistent:
        raise HTTPException(503, NEEDS_DATABASE)
    try:
        ok = repo.table_exists()
    except Exception:  # noqa: BLE001 - psycopg.Error and a missing configuration alike: the caller maps the message
        raise HTTPException(503, "The ODOS database is not available. Check that PostgreSQL is running and try again.") from None
    if not ok:
        raise HTTPException(503, NOT_INITIALISED)


def load_rules(directory: Path) -> tuple[str, dict[str, dict]]:
    """The extraction ID and the original records (by ID, in file order) of the job's rules.json."""
    path = directory / RULE_JSON
    if not path.is_file():
        raise HTTPException(404, "No rules were extracted for this job.")
    raw = path.read_bytes()
    try:
        data = json.loads(raw)
    except ValueError:
        raise HTTPException(422, "The rules of this job cannot be read.") from None
    rules = data.get("rules") if isinstance(data, dict) else data if isinstance(data, list) else None
    if not isinstance(rules, list):
        raise HTTPException(422, "The rules of this job cannot be read.")
    generated = data.get("_generation", {}).get("generatedAt") if isinstance(data, dict) and isinstance(data.get("_generation"), dict) else None
    extraction_id = generated if isinstance(generated, str) and generated else "sha256:" + hashlib.sha256(raw).hexdigest()
    by_id: dict[str, dict] = {}
    for rule in rules:
        if isinstance(rule, dict) and isinstance(rule.get("id"), str) and rule["id"] not in by_id:
            by_id[rule["id"]] = rule
    return extraction_id, by_id


def verification_of(rule: dict) -> str:
    """"flagged" when an automated check flagged the record, else "unverified". Advisory only; never a decision."""
    review = rule.get("review") if isinstance(rule.get("review"), dict) else {}
    ambiguities = review.get("ambiguities") if isinstance(review.get("ambiguities"), list) else []
    return "flagged" if any(isinstance(a, str) and a.startswith(FLAG_PREFIX) for a in ambiguities) else "unverified"


def _entry(rule: dict, event: dict | None) -> dict:
    edited = event["edited_rule"] if event else None
    return {
        "ruleSha256": canonical_sha256(rule),
        "state": event["decision"] if event else "pending",
        "edited": edited is not None,
        "verification": verification_of(edited or rule),
        "lastEventId": event["id"] if event else 0,
        "reviewer": event["reviewer"] if event else None,
        "reason": event["reason"] if event else None,
        "at": event["created_at"].isoformat() if event else None,
        "effectiveRule": edited,
    }


def effective_events(document_id: str, directory: Path, extraction_id: str, rules: dict) -> dict:
    """Carry exact prior decisions into an additive revision; new events override them.

    Synthetic baseline IDs are zero, so append_event's optimistic concurrency
    check starts at zero for the new extraction. No new approval is invented.
    """
    raw = json.loads((directory / RULE_JSON).read_text(encoding="utf-8"))
    carried = raw.get("_generation", {}).get("carriedReviews", {}) if isinstance(raw, dict) else {}
    events = {}
    for rule_id, entry in carried.items():
        if rule_id not in rules or entry.get("ruleSha256") != canonical_sha256(rules[rule_id]):
            continue
        if entry.get("state") not in ("accepted", "pending", "rejected"):
            continue
        if not entry.get("at"):
            continue
        events[rule_id] = {"id": 0, "decision": entry["state"], "edited_rule": entry.get("effectiveRule"),
            "reviewer": entry.get("reviewer"), "reason": entry.get("reason"),
            "created_at": datetime.fromisoformat(entry["at"]), "rule_sha256": entry["ruleSha256"]}
    events.update(repo.latest_events(document_id, extraction_id))
    return events


def review_state(document_id: str, directory: Path) -> dict:
    """The review state of every rule of the job's current rules.json."""
    extraction_id, rules = load_rules(directory)
    events = effective_events(document_id, directory, extraction_id, rules)
    entries = {rule_id: _entry(rule, events.get(rule_id)) for rule_id, rule in rules.items()}
    counts = {state: sum(e["state"] == state for e in entries.values()) for state in ("pending", "accepted", "rejected")}
    counts["edited"] = sum(e["edited"] for e in entries.values())
    return {"extractionId": extraction_id, "criteriaVersion": CRITERIA_VERSION, "counts": counts, "rules": entries,
            "earlierExtractionEvents": repo.earlier_event_count(document_id, extraction_id)}


def validate_edit(original: dict, edited: dict) -> dict:
    """The edited record as it is stored (the `ODOS check:` notes recomputed), or a 422 that says what is wrong.

    The edit must be valid Rule JSON 2.0, keep what the system owns (`schemaVersion`, `id`, `source`, `review.status`) and
    pass ODOS's checks as written: a check that would rename a fact or drop a reference is an error, never a silent rewrite."""
    if len(json.dumps(edited, ensure_ascii=False).encode("utf-8")) > MAX_EDIT_BYTES:
        raise HTTPException(422, f"The edited rule is larger than {MAX_EDIT_BYTES // 1000} KB.")
    errors = sorted(rule_validator().iter_errors(edited), key=lambda e: [str(p) for p in e.absolute_path])
    if errors:
        shown = "; ".join(f"{'/'.join(map(str, e.absolute_path)) or '(rule)'}: {e.message[:200]}" for e in errors[:5])
        raise HTTPException(422, f"The edited rule is not valid Rule JSON 2.0: {shown}")
    for key in ("schemaVersion", "id", "source"):
        if edited.get(key) != original.get(key):
            raise HTTPException(422, f"'{key}' cannot be changed: it is set by the system from the document.")
    status = lambda r: (r.get("review") or {}).get("status")  # noqa: E731
    if status(edited) != status(original):
        raise HTTPException(422, "review.status cannot be changed by an edit; accept or reject the rule instead.")
    probe = copy.deepcopy(edited)
    check = check_rule(probe, (original.get("source") or {}).get("language"))
    if check.errors:
        raise HTTPException(422, "The edited rule fails ODOS's checks: " + "; ".join(check.errors[:5]))
    if check.renamed or check.self_references_removed:
        renames = ", ".join(f"{a!r} -> {b!r}" for a, b in check.renamed.items())
        raise HTTPException(422, "The edited rule does not follow ODOS's naming rules"
                                 + (f" (use {renames})" if renames else "") + (" and references its own source element" if check.self_references_removed else "") + ".")
    stored = copy.deepcopy(edited)
    review = stored["review"]
    kept = [a for a in review.get("ambiguities", []) if not a.startswith(FLAG_PREFIX)]
    if kept:
        review["ambiguities"] = kept
    else:
        review.pop("ambiguities", None)
    add_flags(stored, check.flags)
    return stored


def record_review(document_id: str, directory: Path, request: ReviewRequest) -> dict:
    """Validate the request against the job's current rules.json and append the event; returns the rule's new entry."""
    extraction_id, rules = load_rules(directory)
    original = rules.get(request.ruleId)
    if original is None:
        raise HTTPException(404, "Unknown rule.")
    if request.extractionId != extraction_id or request.expectedRuleSha256 != canonical_sha256(original):
        raise HTTPException(409, "The rules of this job changed since they were loaded. Reload the page.")
    current = effective_events(document_id, directory, extraction_id, rules).get(request.ruleId)
    current_edit = current["edited_rule"] if current else None
    if request.action == "edit":
        edited: dict | None = validate_edit(original, request.editedRule)
    elif request.action == "reset":
        if current_edit is None:
            raise HTTPException(422, "This rule has no edit to reset.")
        edited = None
    else:
        edited = current_edit  # the decision is on exactly the content that is in force now
    try:
        event = repo.append_event(document_id, extraction_id, request.ruleId, request.expectedRuleSha256, request.expectedLastEventId,
                                  request.action, DECISION_OF[request.action], request.reviewer, request.reason, edited)
    except repo.StaleReview:
        raise HTTPException(409, "Someone else changed this rule's review in the meantime. Reload the page.") from None
    return _entry(original, event)


def rule_history(document_id: str, directory: Path, rule_id: str) -> list[dict]:
    """The audit trail of one rule ID, oldest first, across all extractions of the document."""
    _, rules = load_rules(directory)
    events = repo.history(document_id, rule_id)
    if rule_id not in rules and not events:
        raise HTTPException(404, "Unknown rule.")
    return [{"id": e["id"], "extractionId": e["extraction_id"], "action": e["action"], "decision": e["decision"],
             "reviewer": e["reviewer"], "reason": e["reason"], "at": e["created_at"].isoformat(),
             "edited": e["edited_rule"] is not None, "ruleSha256": e["rule_sha256"]} for e in events]


def approved_export(document_id: str, directory: Path) -> dict:
    """The effective record of every accepted rule of the current extraction, each with `review.status: "approved"`.
    Rejected and pending rules are left out. Built on request; rules.json is not modified."""
    extraction_id, rules = load_rules(directory)
    events = effective_events(document_id, directory, extraction_id, rules)
    out = []
    for rule_id, original in rules.items():
        event = events.get(rule_id)
        if not event or event["decision"] != "accepted":
            continue
        record = copy.deepcopy(event["edited_rule"] or original)
        review = record.setdefault("review", {})
        review["status"] = "approved"
        review["notes"] = [*review.get("notes", []), f"Approved by {event['reviewer']} on {event['created_at'].date().isoformat()} (ODOS review)."]
        problems = list(rule_validator().iter_errors(record))
        if problems:
            raise HTTPException(500, f"The approved rule {rule_id!r} is not valid Rule JSON 2.0 and was not exported.")
        out.append(record)
    return {"_review": {"extractionId": extraction_id, "exportedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "source": "human-accepted", "count": len(out)}, "rules": out}
