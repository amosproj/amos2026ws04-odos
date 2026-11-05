"""Shared test fixtures.

Database safety: every test runs with POSTGRES_DB set to the test database (ODOS_TEST_DATABASE, default `odos_test`),
whatever the shell exported (e.g. after sourcing .env). Names that do not end in `_test` are refused, and the `db`
fixture checks the server-side database name again before it empties the `documents` table. The regular `odos`
database is never connected to by the tests.
"""

import json
import os
import time
from pathlib import Path

import psycopg
import pytest

from odos.artifact_names import DOCUMENT_MODEL, LEGAL_JSON
from odos.pipeline import Outcome, PipelineResult

SCHEMA = Path(__file__).resolve().parents[1] / "db" / "001_documents.sql"
TEST_DATABASE = os.environ.get("ODOS_TEST_DATABASE", "odos_test")
MINIMAL_PDF = b"%PDF-1.4\n%%EOF\n"
LEGAL_DOCUMENT = {
    "documentType": "eu_regulation",
    "title": "Verordnung über Maschinen – Prüfung äöüß €",
    "structure": [{"id": "art-1", "nativeType": "Artikel", "number": "1", "children": [{"text": "Satz 1."}]}],
}


def require_test_database(name: str) -> str:
    """The database name, if it is safe for destructive tests."""
    if not name.endswith("_test"):
        raise RuntimeError(f"Refusing to run database tests against {name!r}: the name must end in '_test'.")
    return name


@pytest.fixture(autouse=True)
def _test_database_only(monkeypatch):
    monkeypatch.setenv("POSTGRES_DB", require_test_database(TEST_DATABASE))


@pytest.fixture
def db():
    """An empty `documents` table in the test database; skips when PostgreSQL is not configured or reachable."""
    if not (os.environ.get("POSTGRES_USER") and os.environ.get("POSTGRES_PASSWORD")):
        pytest.skip("POSTGRES_USER/POSTGRES_PASSWORD not set (export them from .env, see database-poc.md)")
    from odos.database import connect

    try:
        conn = connect()
    except psycopg.OperationalError as e:
        pytest.skip(f"test database {TEST_DATABASE!r} not reachable: {e}")
    with conn:
        actual = conn.execute("SELECT current_database()").fetchone()[0]
        require_test_database(actual)
        conn.execute(SCHEMA.read_text(encoding="utf-8"))
        conn.execute("TRUNCATE documents")
    yield actual
    with connect() as conn:
        require_test_database(conn.execute("SELECT current_database()").fetchone()[0])
        conn.execute("TRUNCATE documents")


def fake_pipeline(outcome: Outcome = Outcome.COMPLETED, legal: dict | None = None):
    """A stand-in for run_pipeline that reports progress and writes the result files the API serves."""

    def run(pdf, out_dir, progress):
        progress("extracting")
        progress("normalizing")
        if outcome == Outcome.COMPLETED:
            (out_dir / LEGAL_JSON).write_text(json.dumps(legal or LEGAL_DOCUMENT), encoding="utf-8")
            (out_dir / DOCUMENT_MODEL).write_text("{}", encoding="utf-8")
        return PipelineResult(outcome=outcome, summary={"pages": 1, "docling_warnings": ["at /private/path"]},
                              message=None if outcome == Outcome.COMPLETED else "unsupported")

    return run


def upload(client, content: bytes = MINIMAL_PDF, name: str = "test.pdf"):
    return client.post("/api/jobs", files={"file": (name, content, "application/pdf")})


def wait_for(client, job_id: str) -> dict:
    """The job once it has left queued/processing."""
    for _ in range(200):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] not in ("queued", "processing"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish: {job}")
