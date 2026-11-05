"""PostgreSQL connection for ODOS."""

import os

import psycopg

# the variables connect() needs; POSTGRES_HOST and POSTGRES_PORT have local defaults (see compose.yaml)
REQUIRED_SETTINGS = ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")


def connect():
    """Connect to the ODOS PostgreSQL database."""
    missing = [name for name in REQUIRED_SETTINGS if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"Database settings missing from the environment: {', '.join(missing)} (see .env.example).")
    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
        port=int(os.getenv("POSTGRES_PORT", "5433")),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        connect_timeout=5,  # fail fast instead of hanging a request when the database is down
    )
