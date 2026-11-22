"""Human review of extracted rules: the events in PostgreSQL, their validation and the approved export.

Needs the test database (see conftest: POSTGRES_* exported, database name ending in `_test`); the tests skip without it.
The extraction is faked (no request reaches AWS) and rules.json must stay byte-identical through every review action."""

import copy
import json
import threading
from unittest.mock import patch

import psycopg
import pytest
from conftest import SCHEMAS, fake_pipeline, upload, wait_for
from fastapi.testclient import TestClient
from test_rule_extraction_api import LEGAL, RULE, FakeBedrock, answer, api, start, use, wait_for_extraction  # noqa: F401 (api: fixture)

import odos.rule_reviews as rv
from odos.api import app
from odos.artifact_names import RULE_JSON
from odos.database import connect
from odos.pipeline import Outcome

RULE2 = {"schemaVersion": "2.0", "id": "par-6-abs-2",
         "source": {"elements": [{"elementId": "doc/par-6/abs-2", "sentenceId": "doc/par-6/abs-2/satz-1", "role": "primary"}]},
         "classification": {"type": "obligation", "summary": "Das Dach darf höchstens geneigt sein."},
         # an angle in metres: the automated checks flag it
         "requirements": [{"kind": "numeric", "fact": "roof_slope", "operator": "<=", "value": 30, "unit": "m"}],
         "review": {"status": "draft"}}
ID1, ID2 = "demo-bo-par-6-abs-1", "demo-bo-par-6-abs-2"


@pytest.fixture
def reviewed(db, tmp_path, monkeypatch):
    """A persistent API with one completed job whose rules.json holds two extracted rules (the second one is flagged)."""
    monkeypatch.setenv("ODOS_DATABASE_ENABLED", "1")
    monkeypatch.setenv("ODOS_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-key-not-real")
    use(monkeypatch, FakeBedrock(answer(RULE, RULE2)))
    with patch("odos.api.run_pipeline", side_effect=fake_pipeline(legal=LEGAL)):
        with TestClient(app) as client:
            job_id = wait_for(client, upload(client).json()["id"])["id"]
            start(client, job_id)
            assert wait_for_extraction(client, job_id)["status"] == "completed"
            yield Review(client, job_id, tmp_path / job_id / RULE_JSON)


class Review:
    def __init__(self, client, job_id, rules_path):
        self.client, self.job_id, self.rules_path = client, job_id, rules_path
        self.original = rules_path.read_bytes()

    url = property(lambda self: f"/api/jobs/{self.job_id}/rule-reviews")
    state = lambda self: self.client.get(self.url)  # noqa: E731
    rules = lambda self: json.loads(self.original)["rules"]  # noqa: E731

    def post(self, rule_id=ID1, action="accept", **extra):
        entry = self.state().json()
        known = entry.get("rules", {}).get(rule_id, {"ruleSha256": "0" * 64, "lastEventId": 0})  # no state: the storage is unavailable
        body = {"ruleId": rule_id, "extractionId": entry.get("extractionId", "x"), "expectedRuleSha256": known["ruleSha256"],
                "expectedLastEventId": known["lastEventId"], "action": action, "reviewer": "Dana Prüfer", **extra}
        return self.client.post(self.url, json=body)

    def unchanged(self):
        return self.rules_path.read_bytes() == self.original


def edited(review, rule_id=ID1, **changes):
    rule = copy.deepcopy(next(r for r in review.rules() if r["id"] == rule_id))
    for path, value in changes.items():
        node = rule
        *parents, last = path.split(".")
        for key in parents:
            node = node[int(key)] if key.isdigit() else node[key]
        node[int(last) if last.isdigit() else last] = value
    return rule


# ── state ─────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_every_rule_starts_pending_with_its_hash_and_the_automated_verdict(reviewed):
    state = reviewed.state().json()
    generated = json.loads(reviewed.original)["_generation"]["generatedAt"]
    assert state["extractionId"] == generated and state["criteriaVersion"] == 1
    assert state["counts"] == {"pending": 2, "accepted": 0, "rejected": 0, "edited": 0} and state["earlierExtractionEvents"] == 0
    first, second = state["rules"][ID1], state["rules"][ID2]
    assert (first["state"], first["lastEventId"], first["edited"], first["effectiveRule"]) == ("pending", 0, False, None)
    assert first["ruleSha256"] == rv.canonical_sha256(next(r for r in reviewed.rules() if r["id"] == ID1))
    assert (first["verification"], second["verification"]) == ("unverified", "flagged")  # checks_passed does not exist yet
    assert reviewed.unchanged()


def test_the_state_needs_a_completed_job_with_rules_and_known_ids(reviewed):
    assert reviewed.client.get("/api/jobs/nope/rule-reviews").status_code == 404
    reviewed.rules_path.rename(reviewed.rules_path.with_suffix(".bak"))
    assert reviewed.state().status_code == 404  # nothing was extracted
    reviewed.rules_path.with_suffix(".bak").rename(reviewed.rules_path)
    assert reviewed.post("no-such-rule").status_code == 404


# ── accept, reject, history ───────────────────────────────────────────────────────────────────────────────────────────


def test_accepting_records_who_and_when_and_leaves_rules_json_untouched(reviewed):
    response = reviewed.post(action="accept", reason="Matches § 6 Abs. 1")
    assert response.status_code == 201
    entry = response.json()
    assert (entry["state"], entry["reviewer"], entry["reason"], entry["edited"]) == ("accepted", "Dana Prüfer", "Matches § 6 Abs. 1", False)
    assert entry["lastEventId"] > 0 and entry["at"]
    state = reviewed.state().json()
    assert state["counts"] == {"pending": 1, "accepted": 1, "rejected": 0, "edited": 0}
    assert state["rules"][ID1]["state"] == "accepted" and state["rules"][ID2]["state"] == "pending"
    assert reviewed.unchanged()
    assert json.loads(reviewed.rules_path.read_bytes())["rules"][0]["review"]["status"] == "draft"  # the original stays a draft


def test_rejecting_needs_a_reason_and_keeps_the_rule_in_the_history(reviewed):
    assert reviewed.post(action="reject").status_code == 422
    assert reviewed.post(action="reject", reason="   ").status_code == 422
    assert reviewed.post(action="reject", reason="Wrong threshold").json()["state"] == "rejected"
    assert reviewed.state().json()["counts"]["rejected"] == 1
    history = reviewed.client.get(f"{reviewed.url}/history", params={"ruleId": ID1}).json()
    assert [(h["action"], h["decision"], h["reviewer"], h["reason"]) for h in history] == [("reject", "rejected", "Dana Prüfer", "Wrong threshold")]
    assert reviewed.unchanged()


def test_the_reviewer_is_required_and_validated(reviewed):
    for reviewer in ("", "   ", "x" * 101, "bad\nname"):
        assert reviewed.post(reviewer=reviewer).status_code == 422, reviewer
    assert reviewed.post(reviewer="  Dana  ").json()["reviewer"] == "Dana"
    body = {"ruleId": ID2, "extractionId": reviewed.state().json()["extractionId"], "expectedRuleSha256": "0" * 64, "expectedLastEventId": 0, "action": "accept"}
    assert reviewed.client.post(reviewed.url, json=body).status_code == 422  # no reviewer at all


def test_the_history_lists_every_event_oldest_first_and_needs_a_rule(reviewed):
    reviewed.post(action="accept")
    reviewed.post(action="reject", reason="On second thought")
    reviewed.post(action="reject", reason="Still no")
    history = reviewed.client.get(f"{reviewed.url}/history", params={"ruleId": ID1}).json()
    assert [h["decision"] for h in history] == ["accepted", "rejected", "rejected"]
    assert [h["id"] for h in history] == sorted(h["id"] for h in history)
    assert reviewed.client.get(f"{reviewed.url}/history", params={"ruleId": "nope"}).status_code == 404
    assert reviewed.client.get(f"{reviewed.url}/history").status_code == 422


# ── edit and reset ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_an_edit_is_validated_stored_beside_the_original_and_returns_the_rule_to_pending(reviewed):
    reviewed.post(action="accept")
    new = edited(reviewed, **{"classification.summary": "Gebäude halten mindestens 4 m Abstand.", "requirements.0.value": 4})
    entry = reviewed.post(action="edit", editedRule=new, reason="Corrected the distance").json()
    assert (entry["state"], entry["edited"]) == ("pending", True)  # an acceptance does not survive a change of content
    assert entry["effectiveRule"]["requirements"][0]["value"] == 4
    assert entry["ruleSha256"] == rv.canonical_sha256(next(r for r in reviewed.rules() if r["id"] == ID1))  # still bound to the original
    assert reviewed.unchanged() and next(r for r in reviewed.rules() if r["id"] == ID1)["requirements"][0]["value"] == 3
    assert reviewed.post(action="accept").json()["effectiveRule"]["requirements"][0]["value"] == 4  # decided on the edited content
    reset = reviewed.post(action="reset").json()
    assert (reset["state"], reset["edited"], reset["effectiveRule"]) == ("pending", False, None)
    assert reviewed.state().json()["counts"]["edited"] == 0 and reviewed.unchanged()


def test_an_edit_recomputes_the_automated_notes(reviewed):
    assert reviewed.state().json()["rules"][ID2]["verification"] == "flagged"
    fixed = edited(reviewed, ID2, **{"requirements.0.unit": "deg"})
    fixed["review"].pop("ambiguities", None)
    entry = reviewed.post(ID2, "edit", editedRule=fixed).json()
    assert entry["verification"] == "unverified"
    assert not any(a.startswith("ODOS check:") for a in entry["effectiveRule"]["review"].get("ambiguities", []))
    wrong = edited(reviewed, ID2, **{"requirements.0.unit": "m"})
    wrong["review"]["ambiguities"] = ["ODOS check: forged note that is not true"]  # notes are not taken from the client
    again = reviewed.post(ID2, "edit", editedRule=wrong).json()
    assert again["verification"] == "flagged"
    assert not any("forged" in a for a in again["effectiveRule"]["review"]["ambiguities"])


@pytest.mark.parametrize("change, message", [
    ({"classification": None}, "not valid Rule JSON 2.0"),
    ({"requirements.0.operator": "approximately"}, "not valid Rule JSON 2.0"),
    ({"id": "another-id"}, "'id' cannot be changed"),
    ({"schemaVersion": "1.0"}, "not valid Rule JSON 2.0"),
    ({"source.elements.0.elementId": "doc/par-6/abs-2"}, "'source' cannot be changed"),
    ({"review.status": "approved"}, "review.status cannot be changed"),
    ({"requirements.0.fact": "distanceToBoundary"}, "naming rules"),
    ({"requirements.0.fact": "größe_ä"}, "fails ODOS's checks"),
])
def test_an_invalid_edit_is_refused_with_the_reason_and_nothing_is_stored(reviewed, change, message):
    new = edited(reviewed)
    for path, value in change.items():
        node = new
        *parents, last = path.split(".")
        for key in parents:
            node = node[int(key)] if key.isdigit() else node[key]
        if value is None:
            node.pop(last)
        else:
            node[int(last) if last.isdigit() else last] = value
    response = reviewed.post(action="edit", editedRule=new)
    assert response.status_code == 422 and message in response.json()["detail"]
    assert reviewed.state().json()["counts"] == {"pending": 2, "accepted": 0, "rejected": 0, "edited": 0}
    assert reviewed.unchanged()


def test_an_oversized_edit_and_a_misplaced_edited_rule_are_refused(reviewed):
    big = edited(reviewed)
    big["review"]["notes"] = ["x" * 1000] * 250
    assert "larger than" in reviewed.post(action="edit", editedRule=big).json()["detail"]
    assert reviewed.post(action="edit").status_code == 422  # edit without a record
    assert reviewed.post(action="accept", editedRule=edited(reviewed)).status_code == 422  # a record with another action
    assert reviewed.post(action="reset").status_code == 422  # nothing to reset


# ── conflicts ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_decision_on_stale_data_is_refused(reviewed):
    entry = reviewed.state().json()
    sha = entry["rules"][ID1]["ruleSha256"]
    body = {"ruleId": ID1, "extractionId": entry["extractionId"], "expectedRuleSha256": sha, "expectedLastEventId": 0, "action": "accept", "reviewer": "A"}
    assert reviewed.client.post(reviewed.url, json=body).status_code == 201
    assert reviewed.client.post(reviewed.url, json=body).status_code == 409  # somebody decided in the meantime
    assert reviewed.client.post(reviewed.url, json={**body, "expectedRuleSha256": "f" * 64, "expectedLastEventId": 1}).status_code == 409
    assert reviewed.client.post(reviewed.url, json={**body, "extractionId": "2000-01-01T00:00:00+00:00", "expectedLastEventId": 1}).status_code == 409
    assert reviewed.state().json()["counts"]["accepted"] == 1


def test_two_reviewers_deciding_at_once_one_wins_and_the_other_is_told(reviewed):
    entry = reviewed.state().json()
    body = {"ruleId": ID1, "extractionId": entry["extractionId"], "expectedRuleSha256": entry["rules"][ID1]["ruleSha256"], "expectedLastEventId": 0}
    codes, barrier = [], threading.Barrier(2)

    def decide(action, name):
        barrier.wait()
        codes.append(reviewed.client.post(reviewed.url, json={**body, "action": action, "reviewer": name, "reason": "r"}).status_code)

    threads = [threading.Thread(target=decide, args=("accept", "A")), threading.Thread(target=decide, args=("reject", "B"))]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(codes) == [201, 409]
    assert len(reviewed.client.get(f"{reviewed.url}/history", params={"ruleId": ID1}).json()) == 1


def test_rules_cannot_be_reviewed_while_an_extraction_runs(reviewed, monkeypatch):
    gate = threading.Event()
    use(monkeypatch, FakeBedrock(answer(RULE), gate=gate))
    assert start(reviewed.client, reviewed.job_id).status_code == 202
    assert reviewed.post().status_code == 409
    gate.set()
    wait_for_extraction(reviewed.client, reviewed.job_id)


# ── re-extraction ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_new_extraction_starts_pending_and_the_old_decisions_stay_as_history(reviewed):
    reviewed.post(action="accept")
    first_state = reviewed.state().json()
    # a re-extraction replaces rules.json with a new run (new generatedAt), here with the same record content
    new_file = json.loads(reviewed.original)
    new_file["_generation"]["generatedAt"] = "2099-01-01T00:00:00+00:00"
    reviewed.rules_path.write_text(json.dumps(new_file), encoding="utf-8")
    state = reviewed.state().json()
    assert state["extractionId"] != first_state["extractionId"]
    assert state["counts"] == {"pending": 2, "accepted": 0, "rejected": 0, "edited": 0}  # no carry-over, even for identical records
    assert state["earlierExtractionEvents"] == 1
    assert reviewed.post(action="reject", reason="new run").status_code == 201
    history = reviewed.client.get(f"{reviewed.url}/history", params={"ruleId": ID1}).json()
    assert [(h["decision"], h["extractionId"]) for h in history] == [("accepted", first_state["extractionId"]), ("rejected", state["extractionId"])]
    stale = {"ruleId": ID1, "extractionId": first_state["extractionId"], "expectedRuleSha256": first_state["rules"][ID1]["ruleSha256"],
             "expectedLastEventId": 1, "action": "accept", "reviewer": "A"}
    assert reviewed.client.post(reviewed.url, json=stale).status_code == 409  # a page of the old extraction cannot decide


# ── export ────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_export_has_only_accepted_rules_with_status_approved_and_never_touches_rules_json(reviewed):
    export = f"{reviewed.url}/approved-export"
    assert reviewed.client.get(export).json()["rules"] == []
    reviewed.post(ID1, "accept")
    new = edited(reviewed, ID2, **{"requirements.0.unit": "deg"})
    reviewed.post(ID2, "edit", editedRule=new)
    reviewed.post(ID2, "accept")
    reviewed.post(ID1, "reject", reason="changed my mind")  # rejected: out of the export, kept in the history
    body = reviewed.client.get(export).json()
    assert [r["id"] for r in body["rules"]] == [ID2]
    rule = body["rules"][0]
    assert rule["review"]["status"] == "approved" and rule["requirements"][0]["unit"] == "deg"  # the edited content
    assert rule["review"]["notes"][-1].startswith("Approved by Dana Prüfer on ")
    assert body["_review"]["source"] == "human-accepted" and body["_review"]["count"] == 1
    assert list(rv.rule_validator().iter_errors(rule)) == []
    download = reviewed.client.get(export, params={"download": "true"})
    assert download.headers["content-disposition"].startswith("attachment; filename*=UTF-8''")
    assert ".approved.rules.json" in download.headers["content-disposition"]
    assert reviewed.unchanged() and all(r["review"]["status"] == "draft" for r in json.loads(reviewed.rules_path.read_bytes())["rules"])


# ── storage ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_deleting_the_document_deletes_its_review_history(reviewed):
    reviewed.post(action="accept")
    with connect() as conn:
        assert conn.execute("SELECT count(*) FROM rule_reviews").fetchone()[0] == 1
    assert reviewed.client.delete(f"/api/jobs/{reviewed.job_id}").status_code == 204
    with connect() as conn:
        assert conn.execute("SELECT count(*) FROM rule_reviews").fetchone()[0] == 0


def test_the_database_itself_refuses_a_reject_without_reason_and_an_unknown_action(reviewed):
    with connect() as conn:
        for action, decision, reason in (("reject", "rejected", None), ("reject", "rejected", "  "), ("delete", "pending", None)):
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute("INSERT INTO rule_reviews (document_id, extraction_id, rule_id, rule_sha256, action, decision, reviewer, reason) "
                             "VALUES (%s, 'e', 'r', 'h', %s, %s, 'x', %s)", (reviewed.job_id, action, decision, reason))
                conn.rollback()
            conn.rollback()


def test_the_migration_is_idempotent_and_additive(db):
    with connect() as conn:
        before = conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'documents' ORDER BY ordinal_position").fetchall()
        for _ in range(2):
            for schema in SCHEMAS:
                conn.execute(schema.read_text(encoding="utf-8"))
        assert conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'documents' ORDER BY ordinal_position").fetchall() == before


def test_without_the_table_the_review_endpoints_say_how_to_create_it_and_the_rest_works(reviewed):
    try:
        with connect() as conn:
            conn.execute("DROP TABLE rule_reviews")
        for response in (reviewed.state(), reviewed.post(), reviewed.client.get(f"{reviewed.url}/approved-export")):
            assert response.status_code == 503 and "002_rule_reviews.sql" in response.json()["detail"]
        assert reviewed.client.get(f"/api/jobs/{reviewed.job_id}").status_code == 200
        assert reviewed.client.get(f"/api/jobs/{reviewed.job_id}/files/{RULE_JSON}").status_code == 200
    finally:
        with connect() as conn:
            conn.execute(SCHEMAS[1].read_text(encoding="utf-8"))


def test_without_the_database_review_is_unavailable(api):  # noqa: F811
    client, job_id = api
    use_rules = client.get(f"/api/jobs/{job_id}/rule-reviews")
    assert use_rules.status_code == 503 and "ODOS_DATABASE_ENABLED" in use_rules.json()["detail"]


# ── not ready: no results, no identity ────────────────────────────────────────────────────────────────────────────────


def test_a_job_without_results_cannot_be_reviewed_through_any_route(db, tmp_path, monkeypatch):
    monkeypatch.setenv("ODOS_DATABASE_ENABLED", "1")
    monkeypatch.setenv("ODOS_STORAGE_DIR", str(tmp_path))
    with patch("odos.api.run_pipeline", side_effect=fake_pipeline(Outcome.UNSUPPORTED)):
        with TestClient(app) as client:
            job = wait_for(client, upload(client).json()["id"])
            assert job["status"] == "unsupported"
            url = f"/api/jobs/{job['id']}/rule-reviews"
            body = {"ruleId": ID1, "extractionId": "x", "expectedRuleSha256": "0" * 64, "expectedLastEventId": 0, "action": "accept", "reviewer": "A"}
            assert client.get(url).status_code == 409
            assert client.post(url, json=body).status_code == 409
            assert client.get(f"{url}/history", params={"ruleId": ID1}).status_code == 409
            assert client.get(f"{url}/approved-export").status_code == 409


def test_rules_without_a_generation_stamp_get_an_identity_bound_to_the_file_content(reviewed):
    bare = {"rules": json.loads(reviewed.original)["rules"]}  # a hand-made file: no _generation.generatedAt
    reviewed.rules_path.write_text(json.dumps(bare), encoding="utf-8")
    first = reviewed.state().json()["extractionId"]
    assert first.startswith("sha256:")
    assert reviewed.post(action="accept").status_code == 201
    reviewed.rules_path.write_text(json.dumps({**bare, "rules": list(reversed(bare["rules"]))}), encoding="utf-8")  # other bytes: another identity
    second = reviewed.state().json()
    assert second["extractionId"] != first
    assert second["counts"]["accepted"] == 0 and second["earlierExtractionEvents"] == 1
