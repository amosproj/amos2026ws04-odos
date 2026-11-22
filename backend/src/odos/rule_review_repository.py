"""Database operations for human rule review decisions (table `rule_reviews`, backend/db/002_rule_reviews.sql).

Events are only ever inserted: nothing here updates or deletes a row, so the table is the audit trail. All SQL is
parameterized. The stored rules.json files are not touched."""

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from odos.database import connect

EVENT_COLUMNS = "id, extraction_id, rule_id, rule_sha256, action, decision, reviewer, reason, edited_rule, created_at"


class StaleReview(Exception):
    """Someone else decided the rule since the client read it."""


def table_exists() -> bool:
    with connect() as conn:
        return conn.execute("SELECT to_regclass('public.rule_reviews') IS NOT NULL").fetchone()[0]


def latest_events(document_id: str, extraction_id: str) -> dict[str, dict]:
    """The latest event of every decided rule of one extraction, by rule ID."""
    with connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""SELECT DISTINCT ON (rule_id) {EVENT_COLUMNS}
                FROM rule_reviews WHERE document_id = %s AND extraction_id = %s
                ORDER BY rule_id, id DESC""",
            (document_id, extraction_id),
        )
        return {row["rule_id"]: row for row in cur.fetchall()}


def earlier_event_count(document_id: str, extraction_id: str) -> int:
    """Events of other (earlier or later) extractions of the document: kept as history, never applied."""
    with connect() as conn:
        return conn.execute("SELECT count(*) FROM rule_reviews WHERE document_id = %s AND extraction_id <> %s",
                            (document_id, extraction_id)).fetchone()[0]


def history(document_id: str, rule_id: str) -> list[dict]:
    """Every event of one rule ID across all extractions of the document, oldest first."""
    with connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {EVENT_COLUMNS} FROM rule_reviews WHERE document_id = %s AND rule_id = %s ORDER BY id",
                    (document_id, rule_id))
        return cur.fetchall()


def append_event(document_id: str, extraction_id: str, rule_id: str, rule_sha256: str, expected_last_event_id: int,
                 action: str, decision: str, reviewer: str, reason: str | None, edited_rule: dict | None) -> dict:
    """Insert one event if the rule's latest event of this extraction is still `expected_last_event_id` (0 = none);
    raises StaleReview otherwise. The check and the insert are atomic (advisory lock per document and rule)."""
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{document_id}\x1f{rule_id}",))
        last = conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM rule_reviews WHERE document_id = %s AND extraction_id = %s AND rule_id = %s",
            (document_id, extraction_id, rule_id),
        ).fetchone()[0]
        if last != expected_last_event_id:
            raise StaleReview
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""INSERT INTO rule_reviews
                        (document_id, extraction_id, rule_id, rule_sha256, action, decision, reviewer, reason, edited_rule)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING {EVENT_COLUMNS}""",
                (document_id, extraction_id, rule_id, rule_sha256, action, decision, reviewer, reason,
                 Jsonb(edited_rule) if edited_rule is not None else None),
            )
            return cur.fetchone()
