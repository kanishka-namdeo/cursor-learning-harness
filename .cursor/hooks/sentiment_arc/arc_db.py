"""
Database storage for sentiment arc analysis results.

Adds two tables to narratives.db:
- session_arc_features: per-session arc analysis results
- arc_analysis_stats: append-only history of batch analysis runs
"""

import json
import logging
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# DB path relative to this module's location
_HOOKS_DIR = Path(__file__).parent.parent
_STATE_DIR = _HOOKS_DIR / "state"
DB_PATH = _STATE_DIR / "narratives.db"

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS session_arc_features (
    session_id TEXT PRIMARY KEY,
    analyzed_at TEXT NOT NULL,
    archetype TEXT NOT NULL DEFAULT 'inconclusive',
    turn_count INTEGER NOT NULL DEFAULT 0,
    arc_slope REAL,
    arc_intercept REAL,
    late_volatility REAL,
    user_self_distance REAL,
    model_relevance_trend REAL,
    recovery_events INTEGER DEFAULT 0,
    avg_sentiment REAL,
    sentiment_range REAL,
    arc_etv REAL,
    arc_ecp REAL,
    mismatched_effort_signal INTEGER DEFAULT 0,
    smoothed_arc_json TEXT,
    per_turn_sentiments_json TEXT,
    model_used TEXT,
    error_message TEXT,
    archetype_confidence REAL,
    user_sentiment_trend REAL,
    assistant_sentiment_trend REAL,
    sentiment_gap REAL,
    avg_user_sentiment REAL,
    avg_assistant_sentiment REAL,
    max_sentiment_gap REAL
);

CREATE TABLE IF NOT EXISTS arc_analysis_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    total_sessions_analyzed INTEGER DEFAULT 0,
    last_analyzed_at TEXT,
    model_used TEXT,
    avg_arc_slope REAL,
    archetype_distribution TEXT
);
"""

# Migrations for existing databases that lack new columns.
_MIGRATIONS = [
    "ALTER TABLE session_arc_features ADD COLUMN archetype_confidence REAL",
    "ALTER TABLE session_arc_features ADD COLUMN user_sentiment_trend REAL",
    "ALTER TABLE session_arc_features ADD COLUMN assistant_sentiment_trend REAL",
    "ALTER TABLE session_arc_features ADD COLUMN sentiment_gap REAL",
    "ALTER TABLE session_arc_features ADD COLUMN avg_user_sentiment REAL",
    "ALTER TABLE session_arc_features ADD COLUMN avg_assistant_sentiment REAL",
    "ALTER TABLE session_arc_features ADD COLUMN max_sentiment_gap REAL",
    "ALTER TABLE session_arc_features ADD COLUMN task_completion_score REAL",
    "ALTER TABLE session_arc_features ADD COLUMN task_completion_label TEXT",
    "ALTER TABLE session_arc_features ADD COLUMN task_completion_explanation TEXT",
    "ALTER TABLE session_arc_features ADD COLUMN avg_model_confidence REAL",
    "ALTER TABLE session_arc_features ADD COLUMN mismatched_effort_score REAL",
    "ALTER TABLE session_arc_features ADD COLUMN mean_inter_arr REAL",
    "ALTER TABLE session_arc_features ADD COLUMN inter_arrival_cv REAL",
    "ALTER TABLE session_arc_features ADD COLUMN inter_arrival_trend REAL",
]


def migrate_arc_tables(conn: sqlite3.Connection) -> None:
    """Apply pending column migrations to session_arc_features.

    Safe to call on a fresh database — migrations that fail because the
    column already exists are silently ignored.
    """
    for migration in _MIGRATIONS:
        try:
            conn.execute(migration)
        except sqlite3.OperationalError:
            pass
    conn.commit()


def _sanitize_json_value(value: Any) -> Any:
    """Replace NaN/Inf with None so json.dumps succeeds."""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
    return value


def _sanitize_json_list(lst: list) -> list:
    """Recursively sanitize a list for JSON serialization."""
    return [_sanitize_json_value(x) for x in lst]


def init_arc_tables(db_path: Path | None = None) -> sqlite3.Connection:
    """
    Open a connection to narratives.db and create arc tables if they don't exist.

    Returns the open connection with WAL mode and busy_timeout set.
    """
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.executescript(_CREATE_TABLES)
    migrate_arc_tables(conn)
    logger.info("Arc tables initialized in %s", path)
    return conn


def store_arc_features(
    conn: sqlite3.Connection,
    session_id: str,
    analysis: dict[str, Any] | None,
    smoothed_arc: list[float] | None,
    raw_scores: list[float] | None,
    model_name: str,
    error: str | None = None,
) -> None:
    """
    Store arc analysis results for a session.

    Uses INSERT OR REPLACE for UPSERT behavior (supports --force re-analysis).

    If error is not None, stores error_message and sets archetype to 'error'.

    NOTE: Does NOT commit. Call conn.commit() explicitly to batch commits.
    """
    now = datetime.now(timezone.utc).isoformat()

    if error is not None:
        # Error case: store minimal record
        conn.execute(
            """
            INSERT OR REPLACE INTO session_arc_features (
                session_id, analyzed_at, archetype, turn_count,
                error_message, model_used
            ) VALUES (?, ?, 'error', 0, ?, ?)
            """,
            (session_id, now, error, model_name),
        )
        return

    if analysis is None:
        return

    # Sanitize JSON-serializable lists
    safe_smoothed = _sanitize_json_list(smoothed_arc or [])
    safe_raw = _sanitize_json_list(raw_scores or [])

    conn.execute(
        """
        INSERT OR REPLACE INTO session_arc_features (
            session_id, analyzed_at, archetype, turn_count,
            arc_slope, arc_intercept, late_volatility,
            user_self_distance, model_relevance_trend,
            recovery_events, avg_sentiment, sentiment_range,
            arc_etv, mismatched_effort_signal,
            smoothed_arc_json, per_turn_sentiments_json,
            model_used, archetype_confidence,
            user_sentiment_trend,
            task_completion_score, task_completion_label, task_completion_explanation,
            avg_model_confidence, mismatched_effort_score,
            mean_inter_arr, inter_arrival_cv, inter_arrival_trend
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            now,
            analysis.get("archetype", "inconclusive"),
            analysis.get("turn_count", 0),
            analysis.get("arc_slope"),
            analysis.get("arc_intercept"),
            analysis.get("late_volatility"),
            analysis.get("user_self_distance"),
            analysis.get("model_relevance_trend"),
            analysis.get("recovery_events", 0),
            analysis.get("avg_sentiment"),
            analysis.get("sentiment_range"),
            analysis.get("arc_etv"),
            1 if analysis.get("mismatched_effort_signal") else 0,
            json.dumps(safe_smoothed),
            json.dumps(safe_raw),
            model_name,
            analysis.get("archetype_confidence"),
            analysis.get("user_sentiment_trend"),
            analysis.get("task_completion_score"),
            analysis.get("task_completion_label"),
            analysis.get("task_completion_explanation"),
            analysis.get("avg_model_confidence"),
            analysis.get("mismatched_effort_score"),
            analysis.get("mean_inter_arrival"),
            analysis.get("inter_arrival_cv"),
            analysis.get("inter_arrival_trend"),
        ),
    )


def update_analysis_stats(
    conn: sqlite3.Connection,
    total_analyzed: int,
    model_name: str,
    avg_slope: float | None,
    archetype_dist: dict[str, int],
) -> None:
    """Append a new row to arc_analysis_stats (append-only history).

    NOTE: Does NOT commit. Call conn.commit() explicitly.
    """
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO arc_analysis_stats (
            total_sessions_analyzed, last_analyzed_at, model_used,
            avg_arc_slope, archetype_distribution
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (total_analyzed, now, model_name, avg_slope, json.dumps(archetype_dist)),
    )
    conn.commit()


def get_arc_features_for_session(conn: sqlite3.Connection, session_id: str) -> dict | None:
    """Return a single row as dict, or None if not found."""
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM session_arc_features WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def list_analyzed_session_ids(conn: sqlite3.Connection) -> set[str]:
    """Return set of session IDs that already have arc features."""
    rows = conn.execute("SELECT session_id FROM session_arc_features").fetchall()
    return {row[0] for row in rows}
