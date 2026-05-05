#!/usr/bin/env python3
"""
Narratives SQLite Store — Agent session narratives and statistics.

Provides a SQLite-backed storage layer for agent narrative summaries and
session-level statistics in .cursor/hooks/state/, coexisting with the
existing JSON file-based system.

Zero external dependencies — uses Python stdlib sqlite3 only.

Usage:
    python narratives_db.py --backfill          # Populate DB from existing JSON sessions
    python narratives_db.py --list              # List all sessions in DB
    python narratives_db.py --get <session_id>  # Get narrative for a session
    python narratives_db.py --search <query>    # Search narratives
"""

import json
import shutil
import sqlite3
import sys
import traceback
from datetime import datetime
from pathlib import Path

HOOKS_DIR = Path(__file__).parent.resolve()
STATE_DIR = HOOKS_DIR / "state"
DEBUG_LOG = STATE_DIR / "hook-debug.log"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CURRENT_SQLITE_SCHEMA_VERSION = 8
STRUCTURED_SUMMARY_SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Debug logging
# ---------------------------------------------------------------------------

def debug_log(message: str) -> None:
    """Append a debug message to the hooks debug log."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().isoformat()
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] [narratives-db] {message}\n")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Schema migrations
# ---------------------------------------------------------------------------

MIGRATIONS = {
    1: [
        """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT DEFAULT 'unknown',
            duration_ms INTEGER DEFAULT 0,
            end_reason TEXT,
            composer_mode TEXT,
            model TEXT,
            last_updated TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS narratives (
            session_id TEXT PRIMARY KEY,
            narrative TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            strategy TEXT DEFAULT '',
            word_count INTEGER DEFAULT 0,
            event_count_at_summary INTEGER DEFAULT 0,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS session_stats (
            session_id TEXT PRIMARY KEY,
            total_events INTEGER DEFAULT 0,
            total_responses INTEGER DEFAULT 0,
            total_thoughts INTEGER DEFAULT 0,
            total_thinking_time_ms INTEGER DEFAULT 0,
            total_file_edits INTEGER DEFAULT 0,
            unique_files_edited TEXT DEFAULT '[]',
            total_shell_commands INTEGER DEFAULT 0,
            total_tool_uses INTEGER DEFAULT 0,
            tool_usage_breakdown TEXT DEFAULT '{}',
            net_code_change INTEGER DEFAULT 0,
            total_chars_added INTEGER DEFAULT 0,
            total_chars_removed INTEGER DEFAULT 0,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS schema_versions (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL,
            description TEXT
        )
        """,
    ],
    2: [
        """
        ALTER TABLE sessions ADD COLUMN cursor_version TEXT
        """,
        """
        ALTER TABLE sessions ADD COLUMN user_email TEXT
        """,
        """
        ALTER TABLE sessions ADD COLUMN workspace_roots TEXT
        """,
        """
        ALTER TABLE sessions ADD COLUMN git_branch TEXT
        """,
        """
        ALTER TABLE sessions ADD COLUMN git_commit TEXT
        """,
        """
        CREATE TABLE IF NOT EXISTS session_tool_stats (
            session_id TEXT PRIMARY KEY,
            total_tool_calls INTEGER DEFAULT 0,
            total_tool_successes INTEGER DEFAULT 0,
            total_tool_failures INTEGER DEFAULT 0,
            total_tool_errors INTEGER DEFAULT 0,
            tool_usage_breakdown TEXT DEFAULT '{}',
            tool_failure_breakdown TEXT DEFAULT '{}',
            avg_tool_duration_ms REAL DEFAULT 0,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
        )
        """,
    ],
    3: [
        """
        ALTER TABLE sessions ADD COLUMN is_background_agent INTEGER DEFAULT 0
        """,
        """
        ALTER TABLE session_stats ADD COLUMN total_shell_failures INTEGER DEFAULT 0
        """,
        """
        ALTER TABLE session_stats ADD COLUMN total_tool_successes INTEGER DEFAULT 0
        """,
        """
        ALTER TABLE session_stats ADD COLUMN total_tool_errors INTEGER DEFAULT 0
        """,
        """
        ALTER TABLE session_tool_stats ADD COLUMN avg_success_duration_ms REAL DEFAULT 0
        """,
        """
        ALTER TABLE session_tool_stats ADD COLUMN avg_failure_duration_ms REAL DEFAULT 0
        """,
    ],
    4: [
        """
        CREATE TABLE IF NOT EXISTS hook_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            model TEXT DEFAULT '',
            hook_event_name TEXT DEFAULT '',
            generation_id TEXT DEFAULT '',
            detail_json TEXT DEFAULT '{}',
            FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_hook_events_session ON hook_events(session_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_hook_events_type ON hook_events(event_type)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_hook_events_model ON hook_events(model)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_hook_events_generation ON hook_events(generation_id)
        """,
    ],
    5: [
        """
        CREATE TABLE IF NOT EXISTS conversations (
            conversation_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT DEFAULT 'active',
            git_branch TEXT,
            git_commit TEXT,
            workspace_roots TEXT,
            composer_mode TEXT,
            model TEXT,
            user_email TEXT,
            cursor_version TEXT,
            is_background_agent INTEGER DEFAULT 0,
            last_updated TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        ALTER TABLE sessions ADD COLUMN conversation_id TEXT REFERENCES conversations(conversation_id) ON DELETE SET NULL
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_sessions_conversation ON sessions(conversation_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS conversation_narratives (
            conversation_id TEXT PRIMARY KEY,
            narrative TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            session_count INTEGER DEFAULT 0,
            word_count INTEGER DEFAULT 0,
            FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
        )
        """,
    ],
    6: [
        """
        CREATE TABLE IF NOT EXISTS structured_summaries (
            session_id TEXT PRIMARY KEY,
            structured_json TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            schema_version INTEGER DEFAULT 1,
            objectives TEXT DEFAULT '[]',
            files_modified TEXT DEFAULT '[]',
            files_created TEXT DEFAULT '[]',
            files_deleted TEXT DEFAULT '[]',
            decisions_count INTEGER DEFAULT 0,
            errors_count INTEGER DEFAULT 0,
            session_type TEXT DEFAULT '',
            conversation_id TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_structured_session_type ON structured_summaries(session_type)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_structured_conversation ON structured_summaries(conversation_id)
        """,
    ],
    7: [
        """
        CREATE TABLE IF NOT EXISTS conversation_structured_summaries (
            conversation_id TEXT PRIMARY KEY,
            structured_json TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            session_count INTEGER DEFAULT 0,
            schema_version INTEGER DEFAULT 1,
            objectives TEXT DEFAULT '[]',
            files_modified TEXT DEFAULT '[]',
            files_created TEXT DEFAULT '[]',
            files_deleted TEXT DEFAULT '[]',
            decisions_count INTEGER DEFAULT 0,
            errors_count INTEGER DEFAULT 0,
            FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
        )
        """,
    ],
    8: [
        # Sentiment columns on structured_summaries (session-level)
        "ALTER TABLE structured_summaries ADD COLUMN sentiment_archetype TEXT DEFAULT ''",
        "ALTER TABLE structured_summaries ADD COLUMN sentiment_confidence REAL DEFAULT 0",
        "ALTER TABLE structured_summaries ADD COLUMN arc_slope REAL",
        "ALTER TABLE structured_summaries ADD COLUMN avg_sentiment REAL",
        "ALTER TABLE structured_summaries ADD COLUMN recovery_events INTEGER DEFAULT 0",
        "ALTER TABLE structured_summaries ADD COLUMN mismatched_effort_score REAL",
        "ALTER TABLE structured_summaries ADD COLUMN sentiment_gap REAL",
        "ALTER TABLE structured_summaries ADD COLUMN user_sentiment_trend REAL",
        "ALTER TABLE structured_summaries ADD COLUMN assistant_sentiment_trend REAL",
        # Sentiment columns on conversation_structured_summaries
        "ALTER TABLE conversation_structured_summaries ADD COLUMN dominant_archetype TEXT DEFAULT ''",
        "ALTER TABLE conversation_structured_summaries ADD COLUMN archetype_distribution TEXT DEFAULT '{}'",
        "ALTER TABLE conversation_structured_summaries ADD COLUMN avg_arc_slope REAL",
        "ALTER TABLE conversation_structured_summaries ADD COLUMN avg_sentiment REAL",
        "ALTER TABLE conversation_structured_summaries ADD COLUMN frustration_count INTEGER DEFAULT 0",
        "ALTER TABLE conversation_structured_summaries ADD COLUMN sentiment_trajectory TEXT DEFAULT '[]'",
        # Indexes for sentiment queries
        "CREATE INDEX IF NOT EXISTS idx_structured_sentiment_archetype ON structured_summaries(sentiment_archetype)",
        "CREATE INDEX IF NOT EXISTS idx_structured_arc_slope ON structured_summaries(arc_slope)",
    ],
}

# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class NarrativesDB:
    """Manages SQLite storage for agent narratives and session statistics.

    Usage:
        with NarrativesDB() as db:
            db.upsert_session("abc", "2026-04-29T00:00:00")
    """

    @staticmethod
    def default_db_path() -> Path:
        return STATE_DIR / "narratives.db"

    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or self.default_db_path()
        self._conn: sqlite3.Connection | None = None
        self._closed = False
        self._schema_too_new = False
        self._connect()

    # -- connection lifecycle ------------------------------------------------

    def _connect(self) -> None:
        """Open the DB connection, apply PRAGMAs, ensure schema."""
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            # Concurrency & integrity PRAGMAs
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self.ensure_schema()
        except sqlite3.DatabaseError:
            # Edge Case 2: corrupt DB — rename and create fresh
            self._handle_corrupt_db()

    def _handle_corrupt_db(self) -> None:
        """Rename corrupt DB and create a fresh one."""
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        corrupt_path = self._db_path.with_suffix(f".db.corrupt.{ts}")
        try:
            if self._db_path.exists():
                self._db_path.rename(corrupt_path)
                debug_log(f"Corrupt DB renamed to {corrupt_path.name}")
        except OSError:
            debug_log(f"Failed to rename corrupt DB at {self._db_path}")

        try:
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self.ensure_schema()
        except sqlite3.DatabaseError as e:
            debug_log(f"Failed to create fresh DB: {e}")
            self._conn = None

    def close(self) -> None:
        if self._conn and not self._closed:
            try:
                self._conn.close()
            except Exception:
                pass
            self._closed = True

    def __enter__(self) -> "NarrativesDB":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()

    def _require_conn(self) -> bool:
        """Return True if a valid connection exists, False otherwise."""
        if self._conn is None or self._closed:
            debug_log("DB connection unavailable, operation skipped")
            return False
        if self._schema_too_new:
            debug_log("Schema version too new for this code, writes disabled")
            return False
        return True

    # -- schema management ---------------------------------------------------

    def _current_version(self) -> int:
        try:
            cur = self._conn.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_versions"
            )
            return cur.fetchone()[0]
        except sqlite3.OperationalError:
            return 0

    def ensure_schema(self) -> None:
        """Create tables if they don't exist; run pending migrations."""
        if self._conn is None:
            return

        current = self._current_version()

        if current > CURRENT_SQLITE_SCHEMA_VERSION:
            debug_log(
                f"DB schema version {current} > code version {CURRENT_SQLITE_SCHEMA_VERSION}; "
                "proceeding read-only"
            )
            self._schema_too_new = True
            return

        for version in range(current + 1, CURRENT_SQLITE_SCHEMA_VERSION + 1):
            statements = MIGRATIONS.get(version, [])
            if not statements:
                continue
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    for sql in statements:
                        self._conn.execute(sql)
                    self._conn.execute(
                        "INSERT INTO schema_versions (version, applied_at, description) "
                        "VALUES (?, ?, ?)",
                        (version, datetime.now().isoformat(), f"Migration v{version}"),
                    )
                    self._conn.commit()
                    debug_log(f"Applied schema migration v{version}")
                except sqlite3.Error:
                    self._conn.rollback()
                    raise
            except sqlite3.Error as e:
                debug_log(f"Schema migration v{version} failed: {e}")
                raise

        # Apply column-level migrations (safe for existing columns)
        self._apply_column_migrations()

    def _apply_column_migrations(self) -> None:
        """Apply column ADD COLUMN migrations that may already exist.

        Uses try/except to skip columns that were already added by a prior run.
        """
        column_migrations = [
            "ALTER TABLE structured_summaries ADD COLUMN sentiment_archetype TEXT DEFAULT ''",
            "ALTER TABLE structured_summaries ADD COLUMN sentiment_confidence REAL DEFAULT 0",
            "ALTER TABLE structured_summaries ADD COLUMN arc_slope REAL",
            "ALTER TABLE structured_summaries ADD COLUMN avg_sentiment REAL",
            "ALTER TABLE structured_summaries ADD COLUMN recovery_events INTEGER DEFAULT 0",
            "ALTER TABLE structured_summaries ADD COLUMN mismatched_effort_score REAL",
            "ALTER TABLE structured_summaries ADD COLUMN sentiment_gap REAL",
            "ALTER TABLE structured_summaries ADD COLUMN user_sentiment_trend REAL",
            "ALTER TABLE structured_summaries ADD COLUMN assistant_sentiment_trend REAL",
            "ALTER TABLE conversation_structured_summaries ADD COLUMN dominant_archetype TEXT DEFAULT ''",
            "ALTER TABLE conversation_structured_summaries ADD COLUMN archetype_distribution TEXT DEFAULT '{}'",
            "ALTER TABLE conversation_structured_summaries ADD COLUMN avg_arc_slope REAL",
            "ALTER TABLE conversation_structured_summaries ADD COLUMN avg_sentiment REAL",
            "ALTER TABLE conversation_structured_summaries ADD COLUMN frustration_count INTEGER DEFAULT 0",
            "ALTER TABLE conversation_structured_summaries ADD COLUMN sentiment_trajectory TEXT DEFAULT '[]'",
        ]
        for sql in column_migrations:
            try:
                self._conn.execute(sql)
            except sqlite3.OperationalError:
                pass  # Column already exists
        # Try creating indexes (IF NOT EXISTS handles duplicates)
        try:
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_structured_sentiment_archetype ON structured_summaries(sentiment_archetype)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_structured_arc_slope ON structured_summaries(arc_slope)")
        except sqlite3.OperationalError:
            pass
        self._conn.commit()

    # -- session upserts -----------------------------------------------------

    def upsert_session(
        self,
        session_id: str,
        created_at: str | None = None,
        completed_at: str | None = None,
        status: str | None = None,
        duration_ms: int | None = None,
        end_reason: str | None = None,
        composer_mode: str | None = None,
        model: str | None = None,
        cursor_version: str | None = None,
        user_email: str | None = None,
        workspace_roots: str | None = None,
        git_branch: str | None = None,
        git_commit: str | None = None,
        is_background_agent: bool | None = None,
        conversation_id: str | None = None,
    ) -> bool:
        """Insert or update a session row using COALESCE for partial updates."""
        if not self._require_conn():
            return False

        if created_at is None:
            created_at = datetime.now().isoformat()

        # Convert bool to int for SQLite
        is_bg_int = None
        if is_background_agent is not None:
            is_bg_int = 1 if is_background_agent else 0

        try:
            self._conn.execute(
                """
                INSERT INTO sessions (
                    session_id, created_at, completed_at, status,
                    duration_ms, end_reason, composer_mode, model,
                    cursor_version, user_email, workspace_roots,
                    git_branch, git_commit, is_background_agent,
                    conversation_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    created_at   = COALESCE(excluded.created_at, sessions.created_at),
                    completed_at = COALESCE(excluded.completed_at, sessions.completed_at),
                    status       = COALESCE(excluded.status, sessions.status),
                    duration_ms  = COALESCE(excluded.duration_ms, sessions.duration_ms),
                    end_reason   = COALESCE(excluded.end_reason, sessions.end_reason),
                    composer_mode = COALESCE(excluded.composer_mode, sessions.composer_mode),
                    model        = COALESCE(excluded.model, sessions.model),
                    cursor_version = COALESCE(excluded.cursor_version, sessions.cursor_version),
                    user_email     = COALESCE(excluded.user_email, sessions.user_email),
                    workspace_roots = COALESCE(excluded.workspace_roots, sessions.workspace_roots),
                    git_branch     = COALESCE(excluded.git_branch, sessions.git_branch),
                    git_commit     = COALESCE(excluded.git_commit, sessions.git_commit),
                    is_background_agent = COALESCE(excluded.is_background_agent, sessions.is_background_agent),
                    conversation_id = COALESCE(excluded.conversation_id, sessions.conversation_id),
                    last_updated = CURRENT_TIMESTAMP
                """,
                (session_id, created_at, completed_at, status,
                 duration_ms, end_reason, composer_mode, model,
                 cursor_version, user_email, workspace_roots,
                 git_branch, git_commit, is_bg_int, conversation_id),
            )
            self._conn.commit()
            return True
        except sqlite3.Error as e:
            debug_log(f"upsert_session({session_id}) failed: {e}")
            return False

    def _ensure_session_row(self, session_id: str) -> None:
        """Insert a minimal sessions row if it doesn't exist (FK helper)."""
        if not self._require_conn():
            return
        try:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO sessions (session_id, created_at)
                VALUES (?, CURRENT_TIMESTAMP)
                """,
                (session_id,),
            )
            self._conn.commit()
        except sqlite3.Error as e:
            debug_log(f"_ensure_session_row({session_id}) failed: {e}")

    # -- narrative upserts ---------------------------------------------------

    def upsert_narrative(
        self,
        session_id: str,
        narrative: str,
        generated_at: str | None = None,
        strategy: str = "",
        event_count_at_summary: int = 0,
    ) -> bool:
        """Insert or update a narrative row."""
        if not self._require_conn():
            return False

        if generated_at is None:
            generated_at = datetime.now().isoformat()

        # Edge Case 6: strip NULL bytes and handle invalid UTF-8
        narrative = narrative.replace("\x00", "\ufffd")
        try:
            narrative = narrative.encode("utf-8", errors="replace").decode("utf-8")
        except Exception:
            narrative = "[Narrative encoding failed]"

        word_count = len(narrative.split())

        # Edge Case 11: ensure parent session row exists for FK constraint
        self._ensure_session_row(session_id)

        try:
            self._conn.execute(
                """
                INSERT INTO narratives (
                    session_id, narrative, generated_at, strategy,
                    word_count, event_count_at_summary
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    narrative              = excluded.narrative,
                    generated_at           = excluded.generated_at,
                    strategy               = excluded.strategy,
                    word_count             = excluded.word_count,
                    event_count_at_summary = excluded.event_count_at_summary
                """,
                (session_id, narrative, generated_at, strategy,
                 word_count, event_count_at_summary),
            )
            self._conn.commit()
            return True
        except sqlite3.Error as e:
            debug_log(f"upsert_narrative({session_id}) failed: {e}")
            return False

    # -- stats upserts -------------------------------------------------------

    def upsert_stats(self, session_id: str, stats: dict) -> bool:
        """Insert or update session statistics."""
        if not self._require_conn():
            return False

        unique_files = stats.get("unique_files_edited", [])

        tool_breakdown = stats.get("tool_usage_breakdown", {})

        # Edge Case 11: ensure parent session row exists
        self._ensure_session_row(session_id)

        try:
            self._conn.execute(
                """
                INSERT INTO session_stats (
                    session_id, total_events, total_responses, total_thoughts,
                    total_thinking_time_ms, total_file_edits, unique_files_edited,
                    total_shell_commands, total_tool_uses, tool_usage_breakdown,
                    net_code_change, total_chars_added, total_chars_removed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    total_events           = COALESCE(excluded.total_events, session_stats.total_events),
                    total_responses        = COALESCE(excluded.total_responses, session_stats.total_responses),
                    total_thoughts         = COALESCE(excluded.total_thoughts, session_stats.total_thoughts),
                    total_thinking_time_ms = COALESCE(excluded.total_thinking_time_ms, session_stats.total_thinking_time_ms),
                    total_file_edits       = COALESCE(excluded.total_file_edits, session_stats.total_file_edits),
                    unique_files_edited    = excluded.unique_files_edited,
                    total_shell_commands   = COALESCE(excluded.total_shell_commands, session_stats.total_shell_commands),
                    total_tool_uses        = COALESCE(excluded.total_tool_uses, session_stats.total_tool_uses),
                    tool_usage_breakdown   = excluded.tool_usage_breakdown,
                    net_code_change        = COALESCE(excluded.net_code_change, session_stats.net_code_change),
                    total_chars_added      = COALESCE(excluded.total_chars_added, session_stats.total_chars_added),
                    total_chars_removed    = COALESCE(excluded.total_chars_removed, session_stats.total_chars_removed)
                """,
                (
                    session_id,
                    stats.get("total_events", 0),
                    stats.get("total_responses", 0),
                    stats.get("total_thoughts", 0),
                    stats.get("total_thinking_time_ms", 0),
                    stats.get("total_file_edits", 0),
                    json.dumps(unique_files),
                    stats.get("total_shell_commands", 0),
                    stats.get("total_tool_uses", 0),
                    json.dumps(tool_breakdown),
                    stats.get("net_code_change", 0),
                    stats.get("total_chars_added", 0),
                    stats.get("total_chars_removed", 0),
                ),
            )
            self._conn.commit()
            return True
        except sqlite3.Error as e:
            debug_log(f"upsert_stats({session_id}) failed: {e}")
            return False

    def upsert_tool_stats(self, session_id: str, tool_stats: dict) -> bool:
        """Insert or update session-level tool statistics."""
        if not self._require_conn():
            return False

        self._ensure_session_row(session_id)

        try:
            self._conn.execute(
                """
                INSERT INTO session_tool_stats (
                    session_id, total_tool_calls, total_tool_successes,
                    total_tool_failures, total_tool_errors,
                    tool_usage_breakdown, tool_failure_breakdown,
                    avg_tool_duration_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    total_tool_calls       = COALESCE(excluded.total_tool_calls, session_tool_stats.total_tool_calls),
                    total_tool_successes   = COALESCE(excluded.total_tool_successes, session_tool_stats.total_tool_successes),
                    total_tool_failures    = COALESCE(excluded.total_tool_failures, session_tool_stats.total_tool_failures),
                    total_tool_errors      = COALESCE(excluded.total_tool_errors, session_tool_stats.total_tool_errors),
                    tool_usage_breakdown   = excluded.tool_usage_breakdown,
                    tool_failure_breakdown = excluded.tool_failure_breakdown,
                    avg_tool_duration_ms   = COALESCE(excluded.avg_tool_duration_ms, session_tool_stats.avg_tool_duration_ms)
                """,
                (
                    session_id,
                    tool_stats.get("total_tool_calls", 0),
                    tool_stats.get("total_tool_successes", 0),
                    tool_stats.get("total_tool_failures", 0),
                    tool_stats.get("total_tool_errors", 0),
                    json.dumps(tool_stats.get("tool_usage_breakdown", {})),
                    json.dumps(tool_stats.get("tool_failure_breakdown", {})),
                    tool_stats.get("avg_tool_duration_ms", 0),
                ),
            )
            self._conn.commit()
            return True
        except sqlite3.Error as e:
            debug_log(f"upsert_tool_stats({session_id}) failed: {e}")
            return False

    # -- per-event tracking --------------------------------------------------

    def insert_event(
        self,
        session_id: str,
        sequence: int,
        timestamp: str,
        event_type: str,
        model: str = "",
        hook_event_name: str = "",
        generation_id: str = "",
        detail: dict | None = None,
    ) -> bool:
        """Insert a single hook event into the hook_events table."""
        if not self._require_conn():
            return False

        detail_json = json.dumps(detail) if detail else "{}"

        try:
            self._conn.execute(
                """
                INSERT INTO hook_events (
                    session_id, sequence, timestamp, event_type,
                    model, hook_event_name, generation_id, detail_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, sequence, timestamp, event_type, model, hook_event_name, generation_id, detail_json),
            )
            self._conn.commit()
            return True
        except sqlite3.Error as e:
            # Don't spam debug_log for transient failures — this is best-effort
            debug_log(f"insert_event({session_id}, seq={sequence}) failed: {e}")
            return False

    def get_events_by_session(
        self,
        session_id: str,
        event_type: str | None = None,
    ) -> list[dict]:
        """Get all events for a session, optionally filtered by type."""
        if not self._require_conn():
            return []
        try:
            query = "SELECT * FROM hook_events WHERE session_id = ?"
            params: list = [session_id]
            if event_type is not None:
                query += " AND event_type = ?"
                params.append(event_type)
            query += " ORDER BY sequence ASC"
            cur = self._conn.execute(query, params)
            return [dict(row) for row in cur.fetchall()]
        except sqlite3.Error as e:
            debug_log(f"get_events_by_session({session_id}) failed: {e}")
            return []

    def get_events_by_model(
        self,
        model: str,
        limit: int = 100,
    ) -> list[dict]:
        """Get recent events for a specific model."""
        if not self._require_conn():
            return []
        try:
            cur = self._conn.execute(
                "SELECT * FROM hook_events WHERE model = ? ORDER BY timestamp DESC LIMIT ?",
                (model, limit),
            )
            return [dict(row) for row in cur.fetchall()]
        except sqlite3.Error as e:
            debug_log(f"get_events_by_model({model}) failed: {e}")
            return []

    def count_events_by_type(
        self,
        session_id: str | None = None,
    ) -> list[dict]:
        """Count events by type, optionally filtered by session."""
        if not self._require_conn():
            return []
        try:
            if session_id:
                cur = self._conn.execute(
                    "SELECT event_type, COUNT(*) as cnt FROM hook_events "
                    "WHERE session_id = ? GROUP BY event_type ORDER BY cnt DESC",
                    (session_id,),
                )
            else:
                cur = self._conn.execute(
                    "SELECT event_type, COUNT(*) as cnt FROM hook_events "
                    "GROUP BY event_type ORDER BY cnt DESC"
                )
            return [dict(row) for row in cur.fetchall()]
        except sqlite3.Error as e:
            debug_log(f"count_events_by_type failed: {e}")
            return []

    # -- reads ---------------------------------------------------------------

    def get_narrative(self, session_id: str) -> dict | None:
        """Retrieve a narrative by session ID. Returns dict or None."""
        if not self._require_conn():
            return None
        try:
            cur = self._conn.execute(
                "SELECT * FROM narratives WHERE session_id = ?",
                (session_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return dict(row)
        except sqlite3.Error as e:
            debug_log(f"get_narrative({session_id}) failed: {e}")
            return None

    def list_sessions(
        self,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """Query sessions with optional status filter. Returns list of dicts."""
        if not self._require_conn():
            return []
        try:
            query = "SELECT * FROM sessions"
            params: list = []
            if status is not None:
                query += " WHERE status = ?"
                params.append(status)
            query += " ORDER BY created_at DESC"
            if limit is not None:
                query += " LIMIT ?"
                params.append(limit)
            cur = self._conn.execute(query, params)
            return [dict(row) for row in cur.fetchall()]
        except sqlite3.Error as e:
            debug_log(f"list_sessions failed: {e}")
            return []

    def search_narratives(self, query: str) -> list[dict]:
        """Search narratives using LIKE. Returns list of dicts."""
        if not self._require_conn():
            return []
        try:
            cur = self._conn.execute(
                "SELECT n.*, s.status, s.created_at "
                "FROM narratives n "
                "LEFT JOIN sessions s ON n.session_id = s.session_id "
                "WHERE n.narrative LIKE ? "
                "ORDER BY n.generated_at DESC",
                (f"%{query}%",),
            )
            return [dict(row) for row in cur.fetchall()]
        except sqlite3.Error as e:
            debug_log(f"search_narratives failed: {e}")
            return []

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and all related rows (CASCADE)."""
        if not self._require_conn():
            return False
        try:
            self._conn.execute(
                "DELETE FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            self._conn.commit()
            return True
        except sqlite3.Error as e:
            debug_log(f"delete_session({session_id}) failed: {e}")
            return False

    # -- conversation management ----------------------------------------------

    def upsert_conversation(
        self,
        conversation_id: str,
        created_at: str | None = None,
        completed_at: str | None = None,
        status: str | None = None,
        git_branch: str | None = None,
        git_commit: str | None = None,
        workspace_roots: str | None = None,
        composer_mode: str | None = None,
        model: str | None = None,
        user_email: str | None = None,
        cursor_version: str | None = None,
        is_background_agent: bool | None = None,
    ) -> bool:
        """Insert or update a conversation row."""
        if not self._require_conn():
            return False

        if created_at is None:
            created_at = datetime.now().isoformat()

        is_bg_int = None
        if is_background_agent is not None:
            is_bg_int = 1 if is_background_agent else 0

        try:
            self._conn.execute(
                """
                INSERT INTO conversations (
                    conversation_id, created_at, completed_at, status,
                    git_branch, git_commit, workspace_roots,
                    composer_mode, model, user_email, cursor_version,
                    is_background_agent
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    created_at   = COALESCE(excluded.created_at, conversations.created_at),
                    completed_at = COALESCE(excluded.completed_at, conversations.completed_at),
                    status       = COALESCE(excluded.status, conversations.status),
                    git_branch   = COALESCE(excluded.git_branch, conversations.git_branch),
                    git_commit   = COALESCE(excluded.git_commit, conversations.git_commit),
                    workspace_roots = COALESCE(excluded.workspace_roots, conversations.workspace_roots),
                    composer_mode = COALESCE(excluded.composer_mode, conversations.composer_mode),
                    model        = COALESCE(excluded.model, conversations.model),
                    user_email   = COALESCE(excluded.user_email, conversations.user_email),
                    cursor_version = COALESCE(excluded.cursor_version, conversations.cursor_version),
                    is_background_agent = COALESCE(excluded.is_background_agent, conversations.is_background_agent),
                    last_updated = CURRENT_TIMESTAMP
                """,
                (conversation_id, created_at, completed_at, status,
                 git_branch, git_commit, workspace_roots,
                 composer_mode, model, user_email, cursor_version, is_bg_int),
            )
            self._conn.commit()
            return True
        except sqlite3.Error as e:
            debug_log(f"upsert_conversation({conversation_id}) failed: {e}")
            return False

    def get_conversation_id(self, session_id: str) -> str | None:
        """Get the conversation_id for a given session_id."""
        if not self._require_conn():
            return None
        try:
            cur = self._conn.execute(
                "SELECT conversation_id FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return row["conversation_id"]
        except sqlite3.Error as e:
            debug_log(f"get_conversation_id({session_id}) failed: {e}")
            return None

    def get_sessions_by_conversation(self, conversation_id: str) -> list[dict]:
        """Get all sessions belonging to a conversation."""
        if not self._require_conn():
            return []
        try:
            cur = self._conn.execute(
                "SELECT * FROM sessions WHERE conversation_id = ? ORDER BY created_at ASC",
                (conversation_id,),
            )
            return [dict(row) for row in cur.fetchall()]
        except sqlite3.Error as e:
            debug_log(f"get_sessions_by_conversation({conversation_id}) failed: {e}")
            return []

    def aggregate_conversation_stats(self, conversation_id: str) -> dict:
        """Roll up stats across all sessions in a conversation."""
        if not self._require_conn():
            return {}
        try:
            sessions = self.get_sessions_by_conversation(conversation_id)
            session_ids = [s["session_id"] for s in sessions]

            if not session_ids:
                return {
                    "session_count": 0,
                    "main_session_count": 0,
                    "subagent_session_count": 0,
                    "total_events": 0,
                    "total_responses": 0,
                    "total_thoughts": 0,
                    "total_thinking_time_ms": 0,
                    "total_file_edits": 0,
                    "unique_files_edited": [],
                    "total_shell_commands": 0,
                    "total_tool_uses": 0,
                    "total_chars_added": 0,
                    "total_chars_removed": 0,
                }

            placeholders = ",".join("?" for _ in session_ids)

            # Aggregate session_stats
            stats = self._conn.execute(
                f"""
                SELECT
                    COALESCE(SUM(total_events), 0) as total_events,
                    COALESCE(SUM(total_responses), 0) as total_responses,
                    COALESCE(SUM(total_thoughts), 0) as total_thoughts,
                    COALESCE(SUM(total_thinking_time_ms), 0) as total_thinking_time_ms,
                    COALESCE(SUM(total_file_edits), 0) as total_file_edits,
                    COALESCE(SUM(total_shell_commands), 0) as total_shell_commands,
                    COALESCE(SUM(total_tool_uses), 0) as total_tool_uses,
                    COALESCE(SUM(total_chars_added), 0) as total_chars_added,
                    COALESCE(SUM(total_chars_removed), 0) as total_chars_removed
                FROM session_stats
                WHERE session_id IN ({placeholders})
                """,
                session_ids,
            ).fetchone()

            # Merge unique_files_edited across sessions
            unique_files_rows = self._conn.execute(
                f"""
                SELECT unique_files_edited FROM session_stats
                WHERE session_id IN ({placeholders})
                AND unique_files_edited IS NOT NULL
                """,
                session_ids,
            ).fetchall()

            merged_files = []
            for row in unique_files_rows:
                try:
                    files = json.loads(row["unique_files_edited"])
                    merged_files.extend(files)
                except (json.JSONDecodeError, TypeError):
                    pass
            # Deduplicate while preserving order
            seen = set()
            deduped = []
            for f in merged_files:
                if f not in seen:
                    seen.add(f)
                    deduped.append(f)

            # Session counts
            main_count = 0
            subagent_count = 0
            for s in sessions:
                if s.get("is_background_agent", 0):
                    subagent_count += 1
                else:
                    main_count += 1

            return {
                "session_count": len(session_ids),
                "main_session_count": main_count,
                "subagent_session_count": subagent_count,
                "total_events": stats["total_events"],
                "total_responses": stats["total_responses"],
                "total_thoughts": stats["total_thoughts"],
                "total_thinking_time_ms": stats["total_thinking_time_ms"],
                "total_file_edits": stats["total_file_edits"],
                "unique_files_edited": deduped,
                "total_shell_commands": stats["total_shell_commands"],
                "total_tool_uses": stats["total_tool_uses"],
                "total_chars_added": stats["total_chars_added"],
                "total_chars_removed": stats["total_chars_removed"],
            }
        except sqlite3.Error as e:
            debug_log(f"aggregate_conversation_stats({conversation_id}) failed: {e}")
            return {}

    def get_conversation_timeline(self, conversation_id: str) -> list[dict]:
        """Unified event stream from all sessions in a conversation."""
        if not self._require_conn():
            return []
        try:
            sessions = self.get_sessions_by_conversation(conversation_id)
            if not sessions:
                return []

            session_ids = [s["session_id"] for s in sessions]
            placeholders = ",".join("?" for _ in session_ids)

            cur = self._conn.execute(
                f"""
                SELECT *, session_id FROM hook_events
                WHERE session_id IN ({placeholders})
                ORDER BY timestamp ASC, sequence ASC
                """,
                session_ids,
            )
            return [dict(row) for row in cur.fetchall()]
        except sqlite3.Error as e:
            debug_log(f"get_conversation_timeline({conversation_id}) failed: {e}")
            return []

    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation. NULLs conversation_id in sessions first."""
        if not self._require_conn():
            return False
        try:
            self._conn.execute(
                "UPDATE sessions SET conversation_id = NULL WHERE conversation_id = ?",
                (conversation_id,),
            )
            self._conn.execute(
                "DELETE FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            )
            self._conn.commit()
            return True
        except sqlite3.Error as e:
            debug_log(f"delete_conversation({conversation_id}) failed: {e}")
            return False

    # -- conversation narratives ----------------------------------------------

    def _ensure_conversation_row(self, conversation_id: str) -> None:
        """Insert a minimal conversations row if it doesn't exist (FK helper)."""
        if not self._require_conn():
            return
        try:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO conversations (conversation_id, created_at)
                VALUES (?, CURRENT_TIMESTAMP)
                """,
                (conversation_id,),
            )
            self._conn.commit()
        except sqlite3.Error as e:
            debug_log(f"_ensure_conversation_row({conversation_id}) failed: {e}")

    def upsert_conversation_narrative(
        self,
        conversation_id: str,
        narrative: str,
        generated_at: str | None = None,
        session_count: int = 0,
    ) -> bool:
        """Insert or update a conversation narrative row."""
        if not self._require_conn():
            return False

        if generated_at is None:
            generated_at = datetime.now().isoformat()

        # Strip NULL bytes and handle invalid UTF-8 (same pattern as upsert_narrative)
        narrative = narrative.replace("\x00", "\ufffd")
        try:
            narrative = narrative.encode("utf-8", errors="replace").decode("utf-8")
        except Exception:
            narrative = "[Conversation narrative encoding failed]"

        word_count = len(narrative.split())

        # Ensure parent conversation row exists for FK constraint
        self._ensure_conversation_row(conversation_id)

        try:
            self._conn.execute(
                """
                INSERT INTO conversation_narratives (
                    conversation_id, narrative, generated_at, session_count, word_count
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    narrative     = excluded.narrative,
                    generated_at  = excluded.generated_at,
                    session_count = excluded.session_count,
                    word_count    = excluded.word_count
                """,
                (conversation_id, narrative, generated_at, session_count, word_count),
            )
            self._conn.commit()
            return True
        except sqlite3.Error as e:
            debug_log(f"upsert_conversation_narrative({conversation_id}) failed: {e}")
            return False

    def get_conversation_narrative(self, conversation_id: str) -> dict | None:
        """Retrieve a conversation narrative by conversation ID. Returns dict or None."""
        if not self._require_conn():
            return None
        try:
            cur = self._conn.execute(
                "SELECT * FROM conversation_narratives WHERE conversation_id = ?",
                (conversation_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return dict(row)
        except sqlite3.Error as e:
            debug_log(f"get_conversation_narrative({conversation_id}) failed: {e}")
            return None

    def delete_conversation_narrative(self, conversation_id: str) -> bool:
        """Delete a conversation narrative."""
        if not self._require_conn():
            return False
        try:
            self._conn.execute(
                "DELETE FROM conversation_narratives WHERE conversation_id = ?",
                (conversation_id,),
            )
            self._conn.commit()
            return True
        except sqlite3.Error as e:
            debug_log(f"delete_conversation_narrative({conversation_id}) failed: {e}")
            return False

    # -- conversation structured summaries ------------------------------------

    def upsert_conversation_structured(
        self,
        conversation_id: str,
        structured_json: dict,
        generated_at: str | None = None,
        session_count: int = 0,
    ) -> bool:
        """Insert or update a conversation structured summary."""
        if not self._require_conn():
            return False

        if generated_at is None:
            generated_at = datetime.now().isoformat()

        self._ensure_conversation_row(conversation_id)

        # Extract indexed fields
        objectives = json.dumps(structured_json.get("objectives", []))
        files_modified = json.dumps(structured_json.get("files_modified", []))
        files_created = json.dumps(structured_json.get("files_created", []))
        files_deleted = json.dumps(structured_json.get("files_deleted", []))
        decisions_count = len(structured_json.get("decisions", []))
        errors_count = len(structured_json.get("errors_encountered", []))
        schema_version = structured_json.get("schema_version", 1)

        # Extract sentiment fields (Phase 2)
        dominant_archetype = structured_json.get("sentiment_archetype", "")
        archetype_distribution = json.dumps(structured_json.get("sentiment_archetype_distribution", {}))
        avg_arc_slope = structured_json.get("sentiment_avg_arc_slope")
        avg_sentiment = structured_json.get("sentiment_avg_sentiment")
        frustration_count = structured_json.get("sentiment_frustration_count", 0)
        sentiment_trajectory = json.dumps(structured_json.get("sentiment_trajectory", []))

        # Serialize full JSON (strip NULL bytes)
        full_json = json.dumps(structured_json, ensure_ascii=False)
        full_json = full_json.replace("\x00", "\ufffd")

        try:
            self._conn.execute(
                """
                INSERT INTO conversation_structured_summaries (
                    conversation_id, structured_json, generated_at, session_count,
                    schema_version, objectives, files_modified, files_created,
                    files_deleted, decisions_count, errors_count,
                    dominant_archetype, archetype_distribution, avg_arc_slope, avg_sentiment,
                    frustration_count, sentiment_trajectory
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    structured_json  = excluded.structured_json,
                    generated_at     = excluded.generated_at,
                    session_count    = excluded.session_count,
                    schema_version   = excluded.schema_version,
                    objectives       = excluded.objectives,
                    files_modified   = excluded.files_modified,
                    files_created    = excluded.files_created,
                    files_deleted    = excluded.files_deleted,
                    decisions_count  = excluded.decisions_count,
                    errors_count     = excluded.errors_count,
                    dominant_archetype = excluded.dominant_archetype,
                    archetype_distribution = excluded.archetype_distribution,
                    avg_arc_slope    = excluded.avg_arc_slope,
                    avg_sentiment    = excluded.avg_sentiment,
                    frustration_count = excluded.frustration_count,
                    sentiment_trajectory = excluded.sentiment_trajectory
                """,
                (
                    conversation_id, full_json, generated_at, session_count,
                    schema_version, objectives, files_modified, files_created,
                    files_deleted, decisions_count, errors_count,
                    dominant_archetype, archetype_distribution, avg_arc_slope, avg_sentiment,
                    frustration_count, sentiment_trajectory,
                ),
            )
            self._conn.commit()
            return True
        except sqlite3.Error as e:
            debug_log(f"upsert_conversation_structured({conversation_id}) failed: {e}")
            return False

    def get_conversation_structured(self, conversation_id: str) -> dict | None:
        """Retrieve a conversation structured summary by conversation ID."""
        if not self._require_conn():
            return None
        try:
            cur = self._conn.execute(
                "SELECT * FROM conversation_structured_summaries WHERE conversation_id = ?",
                (conversation_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            result = dict(row)
            try:
                result["structured_data"] = json.loads(result["structured_json"])
            except (json.JSONDecodeError, TypeError):
                result["structured_data"] = {}
            return result
        except sqlite3.Error as e:
            debug_log(f"get_conversation_structured({conversation_id}) failed: {e}")
            return None

    def list_conversations(
        self,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """List conversations with optional status filter."""
        if not self._require_conn():
            return []
        try:
            query = "SELECT * FROM conversations"
            params: list = []
            if status is not None:
                query += " WHERE status = ?"
                params.append(status)
            query += " ORDER BY created_at DESC"
            if limit is not None:
                query += " LIMIT ?"
                params.append(limit)
            cur = self._conn.execute(query, params)
            return [dict(row) for row in cur.fetchall()]
        except sqlite3.Error as e:
            debug_log(f"list_conversations failed: {e}")
            return []

    # -- structured summaries ------------------------------------------------

    def upsert_structured_summary(
        self,
        session_id: str,
        structured_json: dict,
        generated_at: str | None = None,
    ) -> bool:
        """Insert or update a structured summary."""
        if not self._require_conn():
            return False

        if generated_at is None:
            generated_at = datetime.now().isoformat()

        # Ensure parent session row exists
        self._ensure_session_row(session_id)

        # Extract indexed fields from the JSON blob
        objectives = json.dumps(structured_json.get("objectives", []))
        files_modified = json.dumps(structured_json.get("files_modified", []))
        files_created = json.dumps(structured_json.get("files_created", []))
        files_deleted = json.dumps(structured_json.get("files_deleted", []))
        decisions_count = len(structured_json.get("decisions", []))
        errors_count = len(structured_json.get("errors_encountered", []))
        session_type = structured_json.get("session_type", "")
        schema_version = structured_json.get("schema_version", 1)

        # Extract sentiment fields (Phase 2)
        sentiment_archetype = structured_json.get("sentiment_archetype", "")
        sentiment_confidence = structured_json.get("sentiment_confidence", 0.0)
        arc_slope = structured_json.get("arc_slope")
        avg_sentiment = structured_json.get("avg_sentiment")
        recovery_events = structured_json.get("recovery_events", 0)
        mismatched_effort_score = structured_json.get("mismatched_effort_score")
        sentiment_gap = structured_json.get("sentiment_gap")
        user_sentiment_trend = structured_json.get("user_sentiment_trend")
        assistant_sentiment_trend = structured_json.get("assistant_sentiment_trend")

        # Get conversation_id from sessions table
        try:
            conv_row = self._conn.execute(
                "SELECT conversation_id FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            conversation_id = conv_row["conversation_id"] if conv_row else None
        except sqlite3.Error:
            conversation_id = None

        # Serialize full JSON (strip NULL bytes)
        full_json = json.dumps(structured_json, ensure_ascii=False)
        full_json = full_json.replace("\x00", "\ufffd")

        try:
            self._conn.execute(
                """
                INSERT INTO structured_summaries (
                    session_id, structured_json, generated_at, schema_version,
                    objectives, files_modified, files_created, files_deleted,
                    decisions_count, errors_count, session_type, conversation_id,
                    sentiment_archetype, sentiment_confidence, arc_slope, avg_sentiment,
                    recovery_events, mismatched_effort_score, sentiment_gap,
                    user_sentiment_trend, assistant_sentiment_trend
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    structured_json  = excluded.structured_json,
                    generated_at     = excluded.generated_at,
                    schema_version   = excluded.schema_version,
                    objectives       = excluded.objectives,
                    files_modified   = excluded.files_modified,
                    files_created    = excluded.files_created,
                    files_deleted    = excluded.files_deleted,
                    decisions_count  = excluded.decisions_count,
                    errors_count     = excluded.errors_count,
                    session_type     = excluded.session_type,
                    conversation_id  = excluded.conversation_id,
                    sentiment_archetype = excluded.sentiment_archetype,
                    sentiment_confidence = excluded.sentiment_confidence,
                    arc_slope        = excluded.arc_slope,
                    avg_sentiment    = excluded.avg_sentiment,
                    recovery_events  = excluded.recovery_events,
                    mismatched_effort_score = excluded.mismatched_effort_score,
                    sentiment_gap    = excluded.sentiment_gap,
                    user_sentiment_trend = excluded.user_sentiment_trend,
                    assistant_sentiment_trend = excluded.assistant_sentiment_trend
                """,
                (
                    session_id, full_json, generated_at, schema_version,
                    objectives, files_modified, files_created, files_deleted,
                    decisions_count, errors_count, session_type, conversation_id,
                    sentiment_archetype, sentiment_confidence, arc_slope, avg_sentiment,
                    recovery_events, mismatched_effort_score, sentiment_gap,
                    user_sentiment_trend, assistant_sentiment_trend,
                ),
            )
            self._conn.commit()
            return True
        except sqlite3.Error as e:
            debug_log(f"upsert_structured_summary({session_id}) failed: {e}")
            return False

    def get_structured_summary(self, session_id: str) -> dict | None:
        """Retrieve a structured summary by session ID."""
        if not self._require_conn():
            return None
        try:
            cur = self._conn.execute(
                "SELECT * FROM structured_summaries WHERE session_id = ?",
                (session_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            result = dict(row)
            # Parse the JSON blob for convenience
            try:
                result["structured_data"] = json.loads(result["structured_json"])
            except (json.JSONDecodeError, TypeError):
                result["structured_data"] = {}
            return result
        except sqlite3.Error as e:
            debug_log(f"get_structured_summary({session_id}) failed: {e}")
            return None

    def search_structured_summaries(
        self,
        session_type: str | None = None,
        file_path: str | None = None,
        objective_keyword: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Search structured summaries by type, file path, or objective keyword."""
        if not self._require_conn():
            return []
        try:
            conditions = []
            params: list = []

            if session_type:
                conditions.append("session_type = ?")
                params.append(session_type)

            if file_path:
                conditions.append("files_modified LIKE ?")
                params.append(f"%{file_path}%")

            if objective_keyword:
                conditions.append("objectives LIKE ?")
                params.append(f"%{objective_keyword}%")

            query = "SELECT * FROM structured_summaries"
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY generated_at DESC LIMIT ?"
            params.append(limit)

            cur = self._conn.execute(query, params)
            results = []
            for row in cur.fetchall():
                r = dict(row)
                try:
                    r["structured_data"] = json.loads(r["structured_json"])
                except (json.JSONDecodeError, TypeError):
                    r["structured_data"] = {}
                results.append(r)
            return results
        except sqlite3.Error as e:
            debug_log(f"search_structured_summaries failed: {e}")
            return []

    def merge_structured_summaries(self, conversation_id: str) -> dict:
        """Merge structured summaries across all sessions in a conversation.

        Returns a combined structured summary dict with deduplicated lists
        and aggregated counts.
        """
        if not self._require_conn():
            return {}

        try:
            session_ids = [
                s["session_id"] for s in self.get_sessions_by_conversation(conversation_id)
            ]
        except Exception:
            return {}

        if not session_ids:
            return {}

        merged = {
            "schema_version": STRUCTURED_SUMMARY_SCHEMA_VERSION,
            "objectives": [],
            "files_modified": [],
            "files_created": [],
            "files_deleted": [],
            "decisions": [],
            "errors_encountered": [],
            "tool_usage_summary": {},
            "subagent_work": [],
            "code_patterns": [],
            "open_questions": [],
            "outcome": "",
            "session_type": "other",
            "_conversation_id": conversation_id,
            "_merged_from_sessions": session_ids,
        }

        seen_objectives = set()
        seen_files = set()
        seen_created = set()
        seen_deleted = set()
        seen_patterns = set()
        seen_questions = set()

        for sid in session_ids:
            row = self.get_structured_summary(sid)
            if not row or not row.get("structured_data"):
                continue

            data = row["structured_data"]

            # Merge objectives
            for obj in data.get("objectives", []):
                if obj not in seen_objectives:
                    seen_objectives.add(obj)
                    merged["objectives"].append(obj)

            # Merge files
            for f in data.get("files_modified", []):
                if f not in seen_files:
                    seen_files.add(f)
                    merged["files_modified"].append(f)
            for f in data.get("files_created", []):
                if f not in seen_created:
                    seen_created.add(f)
                    merged["files_created"].append(f)
            for f in data.get("files_deleted", []):
                if f not in seen_deleted:
                    seen_deleted.add(f)
                    merged["files_deleted"].append(f)

            # Append decisions and errors (no dedup)
            merged["decisions"].extend(data.get("decisions", []))
            merged["errors_encountered"].extend(data.get("errors_encountered", []))
            merged["subagent_work"].extend(data.get("subagent_work", []))

            # Merge tool usage (sum counts)
            for tool_name, stats in data.get("tool_usage_summary", {}).items():
                if tool_name not in merged["tool_usage_summary"]:
                    merged["tool_usage_summary"][tool_name] = {
                        "calls": 0, "failures": 0, "success_rate": 0.0,
                    }
                if isinstance(stats, dict):
                    merged["tool_usage_summary"][tool_name]["calls"] += stats.get("calls", 0)
                    merged["tool_usage_summary"][tool_name]["failures"] += stats.get("failures", 0)

            # Merge code patterns and open questions
            for p in data.get("code_patterns", []):
                if p not in seen_patterns:
                    seen_patterns.add(p)
                    merged["code_patterns"].append(p)
            for q in data.get("open_questions", []):
                if q not in seen_questions:
                    seen_questions.add(q)
                    merged["open_questions"].append(q)

            # Use the latest outcome and session type
            if data.get("outcome"):
                merged["outcome"] = data["outcome"]
            if data.get("session_type") and data.get("session_type") != "other":
                merged["session_type"] = data["session_type"]

        # Aggregate sentiment across sessions (Phase 2)
        from collections import Counter

        sentiment_archetypes = []
        slopes = []
        avg_sentiments = []
        frustration_count = 0
        sentiment_trajectory = []
        frustration_archetypes = {"escalating_frustration", "mismatched_effort", "looping", "abandoned"}

        for idx, sid in enumerate(session_ids):
            row = self.get_structured_summary(sid)
            if not row or not row.get("structured_data"):
                continue
            data = row["structured_data"]

            arch = data.get("sentiment_archetype", "")
            if arch:
                sentiment_archetypes.append(arch)
                sentiment_trajectory.append({
                    "session_index": idx,
                    "session_id": sid,
                    "archetype": arch,
                    "avg_sentiment": data.get("avg_sentiment"),
                    "arc_slope": data.get("arc_slope"),
                })
                if arch in frustration_archetypes:
                    frustration_count += 1

            slope = data.get("arc_slope")
            if slope is not None:
                slopes.append(slope)

            avg_s = data.get("avg_sentiment")
            if avg_s is not None:
                avg_sentiments.append(avg_s)

        archetype_dist = dict(Counter(sentiment_archetypes))
        dominant_archetype = Counter(sentiment_archetypes).most_common(1)[0][0] if sentiment_archetypes else ""

        merged["_sentiment_aggregates"] = {
            "dominant_archetype": dominant_archetype,
            "archetype_distribution": archetype_dist,
            "avg_arc_slope": round(sum(slopes) / len(slopes), 6) if slopes else None,
            "avg_sentiment": round(sum(avg_sentiments) / len(avg_sentiments), 4) if avg_sentiments else None,
            "frustration_count": frustration_count,
            "sentiment_trajectory": sentiment_trajectory,
        }

        return merged

    def backfill_conversations(self) -> dict:
        """Create conversation rows for sessions without conversation_id.

        For each session without a conversation_id, creates a conversation_id = session_id,
        upserts the conversation row, and updates the session.
        Writes session_conversation_map.json to disk.

        Returns a summary dict.
        """
        if not self._require_conn():
            return {"processed": 0, "skipped": 0, "errored": 0, "errors": []}

        results = {"processed": 0, "skipped": 0, "errored": 0, "errors": []}
        conv_map = {}

        try:
            cur = self._conn.execute(
                "SELECT session_id, created_at, status, composer_mode, model, "
                "git_branch, git_commit, workspace_roots, cursor_version, "
                "user_email, is_background_agent "
                "FROM sessions WHERE conversation_id IS NULL"
            )
            orphan_sessions = [dict(row) for row in cur.fetchall()]
        except sqlite3.Error as e:
            debug_log(f"backfill_conversations: failed to query orphans: {e}")
            return results

        for s in orphan_sessions:
            session_id = s["session_id"]
            conversation_id = session_id  # 1:1 fallback

            try:
                conv_map[session_id] = conversation_id
                if not self.upsert_conversation(
                    conversation_id=conversation_id,
                    created_at=s.get("created_at"),
                    status=s.get("status", "active"),
                    git_branch=s.get("git_branch"),
                    git_commit=s.get("git_commit"),
                    workspace_roots=s.get("workspace_roots"),
                    composer_mode=s.get("composer_mode"),
                    model=s.get("model"),
                    user_email=s.get("user_email"),
                    cursor_version=s.get("cursor_version"),
                    is_background_agent=bool(s.get("is_background_agent", 0)),
                ):
                    results["errored"] += 1
                    results["errors"].append(f"{session_id}: upsert_conversation failed")
                    continue

                self._conn.execute(
                    "UPDATE sessions SET conversation_id = ? WHERE session_id = ?",
                    (conversation_id, session_id),
                )
                self._conn.commit()
                results["processed"] += 1
            except Exception as e:
                debug_log(f"backfill_conversations: failed for {session_id}: {e}")
                results["errored"] += 1
                results["errors"].append(f"{session_id}: {e}")

        # Write session_conversation_map.json
        map_path = STATE_DIR / "session_conversation_map.json"
        try:
            map_path.write_text(json.dumps(conv_map, indent=2), encoding="utf-8")
            debug_log(f"Wrote session_conversation_map.json with {len(conv_map)} entries")
        except OSError as e:
            debug_log(f"Failed to write session_conversation_map.json: {e}")
            results["errors"].append(f"map write: {e}")

        debug_log(
            f"Conversation backfill complete: {results['processed']} processed, "
            f"{results['skipped']} skipped, {results['errored']} errored"
        )
        return results

    # -- backfill ------------------------------------------------------------

    def backfill_from_json_sessions(self) -> dict:
        """Populate SQLite from existing session.json files.

        Returns a summary dict with counts of processed/skipped/errored sessions.
        """
        from conversation_recorder import ConversationRecorder

        sessions_dir = ConversationRecorder.SESSIONS_DIR
        results = {"processed": 0, "skipped": 0, "errored": 0, "errors": []}

        if not sessions_dir.exists():
            debug_log("No sessions directory found for backfill")
            return results

        # Get already-in-DB session IDs to skip
        existing_ids = set()
        if self._require_conn():
            try:
                cur = self._conn.execute("SELECT session_id FROM sessions")
                existing_ids = {row[0] for row in cur.fetchall()}
            except sqlite3.Error as e:
                debug_log(f"Backfill: failed to query existing IDs: {e}")
                return results

        session_dirs = sorted(sessions_dir.glob("*/session.json"))
        total = len(session_dirs)
        debug_log(f"Backfill: found {total} session files, {len(existing_ids)} already in DB")

        for i, session_file in enumerate(session_dirs, 1):
            session_id = session_file.parent.name

            if session_id in existing_ids:
                results["skipped"] += 1
                continue

            try:
                raw = session_file.read_text(encoding="utf-8")
                session = json.loads(raw)
            except (json.JSONDecodeError, OSError) as e:
                # Edge Case 7: corrupt JSON — skip and log
                debug_log(f"Backfill: skipping {session_id}: {e}")
                results["errored"] += 1
                results["errors"].append(f"{session_id}: {e}")
                continue

            try:
                self._backfill_single(session_id, session)
                results["processed"] += 1
                if results["processed"] % 10 == 0:
                    debug_log(
                        f"Backfill progress: {results['processed']}/{total} processed"
                    )
            except Exception as e:
                debug_log(f"Backfill: failed to process {session_id}: {e}")
                results["errored"] += 1
                results["errors"].append(f"{session_id}: {e}")

        debug_log(
            f"Backfill complete: {results['processed']} processed, "
            f"{results['skipped']} skipped, {results['errored']} errored"
        )
        return results

    def _backfill_single(self, session_id: str, session: dict) -> None:
        """Insert a single session from JSON into all three tables."""
        summary = session.get("summary", {})

        # Upsert session row
        created_at = session.get("created_at", datetime.now().isoformat())
        self.upsert_session(
            session_id=session_id,
            created_at=created_at,
            completed_at=summary.get("finalized_at"),
            status=summary.get("final_status", "unknown"),
            duration_ms=summary.get("session_duration_ms", 0),
            end_reason=summary.get("end_reason"),
            composer_mode=session.get("metadata", {}).get("composer_mode"),
            model=None,
        )

        # Upsert narrative if present
        narrative = summary.get("narrative", "")
        if narrative and narrative.strip():
            self.upsert_narrative(
                session_id=session_id,
                narrative=narrative,
                generated_at=summary.get("generated_at", created_at),
                strategy=summary.get("strategy", ""),
                event_count_at_summary=summary.get("event_count_at_summary", 0),
            )

        # Upsert stats if present
        if summary.get("total_events") is not None:
            self.upsert_stats(session_id, summary)

    def backfill_events(self) -> dict:
        """Backfill per-event data from existing session.json files into hook_events.

        This is idempotent — events are identified by (session_id, sequence)
        and skipped if already present.

        Returns a summary dict with counts of processed/skipped/errored.
        """
        from conversation_recorder import ConversationRecorder

        sessions_dir = ConversationRecorder.SESSIONS_DIR
        results = {"sessions_processed": 0, "total_events_inserted": 0, "errored": 0, "errors": []}

        if not sessions_dir.exists():
            debug_log("No sessions directory found for event backfill")
            return results

        session_dirs = sorted(sessions_dir.glob("*/session.json"))
        total = len(session_dirs)
        debug_log(f"Event backfill: found {total} session files")

        for i, session_file in enumerate(session_dirs, 1):
            session_id = session_file.parent.name

            try:
                raw = session_file.read_text(encoding="utf-8")
                session = json.loads(raw)
            except (json.JSONDecodeError, OSError) as e:
                debug_log(f"Event backfill: skipping {session_id}: {e}")
                results["errored"] += 1
                results["errors"].append(f"{session_id}: {e}")
                continue

            try:
                inserted = self._backfill_session_events(session_id, session)
                results["total_events_inserted"] += inserted
                results["sessions_processed"] += 1
                if results["sessions_processed"] % 10 == 0:
                    debug_log(
                        f"Event backfill progress: {results['sessions_processed']}/{total} sessions, "
                        f"{results['total_events_inserted']} events"
                    )
            except Exception as e:
                debug_log(f"Event backfill: failed to process {session_id}: {e}")
                results["errored"] += 1
                results["errors"].append(f"{session_id}: {e}")

        debug_log(
            f"Event backfill complete: {results['sessions_processed']} sessions, "
            f"{results['total_events_inserted']} events, {results['errored']} errors"
        )
        return results

    def _backfill_session_events(self, session_id: str, session: dict) -> int:
        """Insert all events from a single session into hook_events.

        Returns the number of events inserted.
        """
        # Check if events already exist for this session
        if not self._require_conn():
            return 0

        try:
            existing = self._conn.execute(
                "SELECT COUNT(*) FROM hook_events WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
            if existing > 0:
                return 0  # Already backfilled
        except sqlite3.OperationalError:
            return 0  # Table doesn't exist yet

        inserted = 0
        for ev in session.get("events", []):
            self.insert_event(
                session_id=session_id,
                sequence=ev.get("sequence", 0),
                timestamp=ev.get("timestamp", ""),
                event_type=ev.get("type", "unknown"),
                model=ev.get("model", ""),
                hook_event_name=ev.get("hook_event_name", ""),
                generation_id=ev.get("generation_id", ""),
                detail=ev,
            )
            inserted += 1

        return inserted

    def clear_all(self) -> dict:
        """Delete all data from every table. Schema is preserved. Returns counts."""
        tables = [
            "conversation_structured_summaries",
            "structured_summaries",
            "conversation_narratives",
            "narratives",
            "session_tool_stats",
            "session_stats",
            "hook_events",
            "session_arc_features",
            "arc_analysis_stats",
            "sessions",
            "conversations",
        ]
        counts = {}
        for table in tables:
            try:
                cur = self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                counts[table] = cur[0]
                self._conn.execute(f"DELETE FROM {table}")
            except sqlite3.OperationalError:
                counts[table] = 0
        self._conn.commit()
        return counts


def clear_json_state() -> dict:
    """Delete all session JSON files and state metadata files. Returns counts."""
    deleted = {"session_dirs": 0, "files": []}

    sessions_dir = STATE_DIR / "sessions"
    if sessions_dir.exists():
        for d in sessions_dir.iterdir():
            if d.is_dir():
                shutil.rmtree(d)
                deleted["session_dirs"] += 1

    for f in ["sessions_index.json", "conversation_links.json",
              "conversation_fingerprint.json", "session_conversation_map.json"]:
        p = STATE_DIR / f
        if p.exists():
            p.unlink()
            deleted["files"].append(f)

    return deleted


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Narratives DB CLI")
    parser.add_argument("--backfill", action="store_true", help="Backfill from JSON sessions")
    parser.add_argument("--backfill-events", action="store_true", help="Backfill per-event data into hook_events table")
    parser.add_argument("--backfill-conversations", action="store_true", help="Create conversation rows for sessions without conversation_id")
    parser.add_argument("--list", action="store_true", dest="list_sessions_flag", help="List sessions in DB")
    parser.add_argument("--list-conversations", action="store_true", help="List conversations in DB")
    parser.add_argument("--get", type=str, metavar="SESSION_ID", help="Get narrative for a session")
    parser.add_argument("--get-conversation", type=str, metavar="CONVERSATION_ID", help="Get conversation and its sessions")
    parser.add_argument("--search", type=str, metavar="QUERY", help="Search narratives")
    parser.add_argument("--stats", action="store_true", help="Show DB-level aggregate stats")
    parser.add_argument("--aggregate-stats", type=str, metavar="CONVERSATION_ID", help="Show aggregate stats for a conversation")
    parser.add_argument("--events", type=str, metavar="SESSION_ID", help="List events for a session")
    parser.add_argument("--summarize-conversation", type=str, metavar="CONVERSATION_ID", help="Generate conversation-level summary via conversation_summarizer_agent")
    parser.add_argument("--get-conversation-narrative", type=str, metavar="CONVERSATION_ID", help="Get conversation narrative summary")
    parser.add_argument("--get-conversation-structured", type=str, metavar="CONVERSATION_ID", help="Get conversation structured summary")
    parser.add_argument("--clear", action="store_true", help="Delete ALL hooks/narratives data (SQLite + JSON). Schema preserved.")

    args = parser.parse_args()

    with NarrativesDB() as db:
        if args.backfill:
            results = db.backfill_from_json_sessions()
            print(f"Backfill complete: {results['processed']} processed, "
                  f"{results['skipped']} skipped, {results['errored']} errored")
            if results["errors"]:
                print("Errors:")
                for err in results["errors"]:
                    print(f"  {err}")

        elif args.backfill_events:
            results = db.backfill_events()
            print(f"Event backfill complete: {results['sessions_processed']} sessions, "
                  f"{results['total_events_inserted']} events, {results['errored']} errors")
            if results["errors"]:
                print("Errors:")
                for err in results["errors"]:
                    print(f"  {err}")

        elif args.events:
            events = db.get_events_by_session(args.events)
            if not events:
                print(f"No events found for session: {args.events}")
                return
            print(f"\nEvents for session {args.events} ({len(events)} total):\n")
            for ev in events:
                detail = json.loads(ev.get("detail_json", "{}"))
                model_tag = f" | model={ev['model']}" if ev.get("model") else ""
                hook_tag = f" | hook={ev['hook_event_name']}" if ev.get("hook_event_name") else ""
                print(f"  [{ev['sequence']}] {ev['timestamp']} - {ev['event_type']}{model_tag}{hook_tag}")
                # Show a brief detail preview
                if ev['event_type'] == 'thought':
                    text = detail.get('text', '')[:100]
                    if text:
                        print(f"    {text}")
                elif ev['event_type'] == 'tool_use':
                    tool = detail.get('tool_name', '')
                    msg = detail.get('agent_message', '')[:60]
                    if tool:
                        print(f"    Tool: {tool} - {msg}")
                elif ev['event_type'] == 'file_edit':
                    fpath = detail.get('file_path', '')
                    chars = detail.get('chars_added', 0)
                    if fpath:
                        print(f"    File: {fpath} (+{chars} chars)")

        elif args.list_sessions_flag:
            sessions = db.list_sessions()
            if not sessions:
                print("No sessions in DB.")
                return
            print(f"\nSessions in DB ({len(sessions)} total):\n")
            for s in sessions:
                print(f"  {s['session_id']}")
                print(f"    created={s['created_at']}  status={s['status']}  "
                      f"duration={s['duration_ms']}ms")
                print()

        elif args.get:
            result = db.get_narrative(args.get)
            if result is None:
                print(f"No narrative found for session: {args.get}")
            else:
                print(f"Session: {result['session_id']}")
                print(f"Generated: {result['generated_at']}")
                print(f"Strategy: {result['strategy']}")
                print(f"Words: {result['word_count']}")
                print(f"\n{result['narrative']}")

        elif args.search:
            results = db.search_narratives(args.search)
            if not results:
                print(f"No narratives matching '{args.search}'")
                return
            print(f"\nSearch results for '{args.search}' ({len(results)} matches):\n")
            for r in results:
                print(f"  {r['session_id']} (generated={r['generated_at']}, "
                      f"words={r['word_count']})")
                # Show brief preview
                text = r["narrative"]
                preview = text[:200] + "..." if len(text) > 200 else text
                print(f"    {preview}\n")

        elif args.stats:
            sessions = db.list_sessions()
            if not sessions:
                print("No sessions in DB.")
                return
            total = len(sessions)
            completed = sum(1 for s in sessions if s["status"] == "completed")
            print(f"\nDB Statistics:")
            print(f"  Total sessions: {total}")
            print(f"  Completed: {completed}")
            print(f"  In-progress/unknown: {total - completed}")

            # Narrative coverage
            narratives = 0
            for s in sessions:
                if db.get_narrative(s["session_id"]):
                    narratives += 1
            print(f"  Sessions with narratives: {narratives}/{total}")

        elif args.backfill_conversations:
            results = db.backfill_conversations()
            print(f"Conversation backfill complete: {results['processed']} processed, "
                  f"{results['skipped']} skipped, {results['errored']} errored")
            if results["errors"]:
                print("Errors:")
                for err in results["errors"]:
                    print(f"  {err}")

        elif args.list_conversations:
            conversations = db.list_conversations()
            if not conversations:
                print("No conversations in DB.")
                return
            print(f"\nConversations in DB ({len(conversations)} total):\n")
            for c in conversations:
                print(f"  {c['conversation_id']}")
                print(f"    created={c['created_at']}  status={c['status']}")
                print()

        elif args.get_conversation:
            sessions = db.get_sessions_by_conversation(args.get_conversation)
            if not sessions:
                print(f"No sessions found for conversation: {args.get_conversation}")
                return
            stats = db.aggregate_conversation_stats(args.get_conversation)
            print(f"\nConversation: {args.get_conversation}")
            print(f"  Sessions: {stats.get('session_count', len(sessions))} "
                  f"({stats.get('main_session_count', '?')} main, "
                  f"{stats.get('subagent_session_count', '?')} subagent)")
            print(f"  Total events: {stats.get('total_events', 0)}")
            print(f"  Total file edits: {stats.get('total_file_edits', 0)}")
            print(f"  Total tool uses: {stats.get('total_tool_uses', 0)}")
            print(f"\n  Sessions:")
            for s in sessions:
                print(f"    {s['session_id']}  status={s['status']}  "
                      f"created={s['created_at']}")

        elif args.aggregate_stats:
            stats = db.aggregate_conversation_stats(args.aggregate_stats)
            if not stats:
                print(f"No stats found for conversation: {args.aggregate_stats}")
                return
            print(f"\nAggregate stats for conversation {args.aggregate_stats}:")
            for key, val in stats.items():
                if key == "unique_files_edited":
                    print(f"  {key}: {len(val)} files")
                else:
                    print(f"  {key}: {val}")

        elif args.summarize_conversation:
            # Launch conversation_summarizer_agent.py
            import subprocess
            summarizer_script = Path(__file__).parent / "conversation_summarizer_agent.py"
            if not summarizer_script.exists():
                print(f"Conversation summarizer script not found at {summarizer_script}", file=sys.stderr)
                return
            force = "--force" in sys.argv
            cmd = [sys.executable, str(summarizer_script), args.summarize_conversation]
            if force:
                cmd.append("--force")
            print(f"Running conversation summarizer for {args.summarize_conversation}...")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.stderr:
                for line in result.stderr.strip().split("\n"):
                    print(f"  {line}")
            if result.returncode != 0:
                print(f"Summarizer exited with code {result.returncode}")
                if result.stderr:
                    print(f"Error: {result.stderr[:500]}")
            else:
                # Show the generated summary
                narr = db.get_conversation_narrative(args.summarize_conversation)
                if narr:
                    print(f"\nConversation Narrative (generated={narr.get('generated_at', '')}, words={narr.get('word_count', '?')}):")
                    print(f"  {narr.get('narrative', '')[:500]}...")

        elif args.get_conversation_narrative:
            result = db.get_conversation_narrative(args.get_conversation_narrative)
            if result is None:
                print(f"No conversation narrative found for: {args.get_conversation_narrative}")
            else:
                print(f"Conversation: {result['conversation_id']}")
                print(f"Generated: {result['generated_at']}")
                print(f"Sessions: {result['session_count']}")
                print(f"Words: {result['word_count']}")
                print(f"\n{result['narrative']}")

        elif args.get_conversation_structured:
            result = db.get_conversation_structured(args.get_conversation_structured)
            if result is None:
                print(f"No conversation structured summary found for: {args.get_conversation_structured}")
            else:
                print(f"Conversation: {result['conversation_id']}")
                print(f"Generated: {result['generated_at']}")
                print(f"Sessions: {result['session_count']}")
                print(f"\n{json.dumps(result.get('structured_data', {}), indent=2)}")

        elif args.clear:
            confirm = input("This will delete ALL hooks/narratives data from SQLite and JSON files. Continue? (y/N): ")
            if confirm.lower() != "y":
                print("Aborted.")
                return

            counts = db.clear_all()
            print("SQLite tables cleared:")
            for table, count in counts.items():
                print(f"  {table}: {count} rows deleted")

            result = clear_json_state()
            print(f"\nJSON cleared: {result['session_dirs']} session directories, files: {result['files']}")

            debug_log("All hooks/narratives data cleared via --clear")

        else:
            parser.print_help()


if __name__ == "__main__":
    main()
