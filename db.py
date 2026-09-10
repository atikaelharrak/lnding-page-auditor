"""
db.py
-----
Persistence layer for the Landing Page Health Auditor.

Uses SQLite (via Python's built-in sqlite3 module, no extra dependency
needed) to store every audit that's ever been run. This unlocks:
  - Audit history per URL (has this page been checked before? when?)
  - Trend tracking (is the score improving over time?)
  - A cache the rate-limiting layer can check before re-crawling a URL

Schema design note: `categories_json` stores the full category/results
breakdown as a JSON blob rather than fully normalizing into separate
`categories` and `check_results` tables. For a project this size, a
fully normalized schema (3+ tables with foreign keys) would add real
complexity ' migrations, joins, more test surface ' for a benefit we
don't need yet (we never query "give me all failed checks named X
across all audits"). Storing the report as JSON keeps the schema simple
while still letting us query/sort on the fields that actually matter
for history and trends (url, score, timestamp). This is a deliberate
tradeoff, not an oversight, worth being able to explain in a review.
"""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "audits.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS audits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    final_url TEXT NOT NULL,
    overall_score INTEGER NOT NULL,
    fetch_error TEXT,
    categories_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audits_url ON audits(url);
CREATE INDEX IF NOT EXISTS idx_audits_created_at ON audits(created_at);
"""


def get_db_path() -> Path:
    return DB_PATH


@contextmanager
def get_connection(db_path: Path = None):
    """
    Context manager for a SQLite connection. Ensures the connection is
    always closed, even if an error occurs mid-query, a common source
    of "database is locked" bugs when connections are left open.
    """
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row  
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_path: Path = None) -> None:
    """Create the audits table if it doesn't already exist. Safe to call
    every time the app starts, CREATE TABLE IF NOT EXISTS is idempotent."""
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def save_audit(report, db_path: Path = None) -> int:
    """
    Save an AuditReport (from report.py) to the database.
    Returns the new row's id.
    """
    categories_data = [
        {
            "name": cat.name,
            "score": cat.score,
            "results": [asdict(r) for r in cat.results],
        }
        for cat in report.categories
    ]

    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO audits (url, final_url, overall_score, fetch_error, categories_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                report.url,
                report.final_url,
                report.overall_score,
                report.fetch_error,
                json.dumps(categories_data),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        return cursor.lastrowid


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "url": row["url"],
        "final_url": row["final_url"],
        "overall_score": row["overall_score"],
        "fetch_error": row["fetch_error"],
        "categories": json.loads(row["categories_json"]),
        "created_at": row["created_at"],
    }


def get_audit_by_id(audit_id: int, db_path: Path = None) -> dict | None:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM audits WHERE id = ?", (audit_id,)).fetchone()
        return _row_to_dict(row) if row else None


def get_audit_history(url: str, limit: int = 20, db_path: Path = None) -> list[dict]:
    """Return past audits for a given URL, most recent first."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM audits WHERE url = ? ORDER BY created_at DESC LIMIT ?",
            (url, limit),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def get_most_recent_audit(url: str, db_path: Path = None) -> dict | None:
    """
    Return the single most recent audit for a URL, or None if it's
    never been audited. Used by the caching layer to decide whether a
    fresh crawl is actually needed.
    """
    history = get_audit_history(url, limit=1, db_path=db_path)
    return history[0] if history else None


def get_recent_audits(limit: int = 20, db_path: Path = None) -> list[dict]:
    """Return the most recent audits across ALL urls, most recent first."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM audits ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def get_score_trend(url: str, db_path: Path = None) -> list[dict]:
    """
    Return a compact (timestamp, score) series for a URL, oldest first,
    exactly what a trend chart needs, without the full category detail.
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT created_at, overall_score FROM audits WHERE url = ? ORDER BY created_at ASC",
            (url,),
        ).fetchall()
        return [{"created_at": r["created_at"], "score": r["overall_score"]} for r in rows]
