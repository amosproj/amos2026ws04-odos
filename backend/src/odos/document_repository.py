"""Database operations for ODOS documents."""

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from odos.database import connect


def create_document(
    document_id: str,
    filename: str,
    pdf_storage_key: str,
):
    """Register a new document in PostgreSQL."""
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO documents
                (id, filename, status, pdf_storage_key)
            VALUES (%s, %s, 'queued', %s)
            """,
            (document_id, filename, pdf_storage_key),
        )


def get_document(document_id: str) -> dict | None:
    """Retrieve a stored document, or None."""
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, filename, document_type, status, stage, message,
                       summary, legal_json, pdf_storage_key, created_at, updated_at
                FROM documents
                WHERE id = %s
                """,
                (document_id,),
            )
            return cur.fetchone()


def list_documents():
    """Load stored jobs for API startup."""
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT id, filename, status, stage, message, summary
                FROM documents
                ORDER BY created_at
            """)
            return cur.fetchall()


def update_document_status(document_id: str, status: str, stage=None):
    """Update processing status."""
    with connect() as conn:
        conn.execute(
            """
            UPDATE documents
            SET status = %s,
                stage = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (status, stage, document_id),
        )


def finish_document(document_id, status, summary, legal_json, message):
    """Persist the final processing result."""
    document_type = (legal_json or {}).get("documentType")  # Legal JSON 2.0: "de_legislation", "eu_regulation", ...
    with connect() as conn:
        conn.execute(
            """
            UPDATE documents
            SET status = %s,
                stage = NULL,
                summary = %s,
                legal_json = %s,
                document_type = %s,
                message = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (
                status,
                Jsonb(summary),
                Jsonb(legal_json) if legal_json is not None else None,
                document_type if isinstance(document_type, str) else None,
                message,
                document_id,
            ),
        )


def delete_document(document_id: str):
    """Remove document metadata from PostgreSQL."""
    with connect() as conn:
        conn.execute(
            "DELETE FROM documents WHERE id = %s",
            (document_id,),
        )


def mark_interrupted_jobs():
    """Mark unfinished jobs as interrupted after an API restart."""
    with connect() as conn:
        conn.execute(
            """
            UPDATE documents
            SET status = 'failed',
                stage = NULL,
                message = 'Processing was interrupted by a server restart.',
                updated_at = NOW()
            WHERE status IN ('queued', 'processing')
            """
        )
