# session-analytics

Session data analysis via SQLite for the Cursor Hooks summarizer. The `narratives_db.py` module provides a SQLite-backed storage layer with 3 tables, coexisting with the JSON file-based session system.

## File Locations

- Database module: `.cursor/hooks/narratives_db.py`
- CLI viewer: `.cursor/hooks/view.py` (queries DB and renders results)
- Database file: `.cursor/hooks/state/narratives.db`
- Session JSON: `.cursor/hooks/state/sessions/{session_id}/session.json`

## Schema

### 3 Tables

**sessions** — one row per conversation session
```sql
session_id TEXT PRIMARY KEY,
created_at TEXT NOT NULL,
completed_at TEXT,
status TEXT DEFAULT 'unknown',
duration_ms INTEGER DEFAULT 0,
end_reason TEXT,
composer_mode TEXT,
model TEXT,
last_updated TEXT DEFAULT CURRENT_TIMESTAMP
```

**narratives** — one row per generated summary
```sql
session_id TEXT PRIMARY KEY,
narrative TEXT NOT NULL,
generated_at TEXT NOT NULL,
strategy TEXT DEFAULT '',       -- "full_regenerate" | "delta_update"
word_count INTEGER DEFAULT 0,
event_count_at_summary INTEGER DEFAULT 0,
FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
```

**session_stats** — aggregated event statistics
```sql
session_id TEXT PRIMARY KEY,
total_events INTEGER DEFAULT 0,
total_responses INTEGER DEFAULT 0,
total_thoughts INTEGER DEFAULT 0,
total_thinking_time_ms INTEGER DEFAULT 0,
total_file_edits INTEGER DEFAULT 0,
unique_files_edited TEXT DEFAULT '[]',  -- JSON array
total_shell_commands INTEGER DEFAULT 0,
total_tool_uses INTEGER DEFAULT 0,
tool_usage_breakdown TEXT DEFAULT '{}', -- JSON object
net_code_change INTEGER DEFAULT 0,
total_chars_added INTEGER DEFAULT 0,
total_chars_removed INTEGER DEFAULT 0,
FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
```

**schema_versions** — migration tracking
```sql
version INTEGER PRIMARY KEY,
applied_at TEXT NOT NULL,
description TEXT
```

### Schema Design Notes

- All tables use `session_id` as PRIMARY KEY (no surrogate IDs)
- Foreign keys enforce referential integrity (ON DELETE CASCADE)
- `unique_files_edited` and `tool_usage_breakdown` store JSON as TEXT (cap: 500 files)
- Narratives have a soft cap of 100,000 characters (warning logged if exceeded)
- Current schema version: 1 (migratable via `MIGRATIONS` dict in `narratives_db.py`)

## Database Connection

### Usage Pattern

```python
from narratives_db import NarrativesDB

with NarrativesDB() as db:
    db.upsert_session("abc123", created_at="2026-04-29T10:00:00")
    db.upsert_narrative("abc123", narrative="Fixed a bug...", strategy="full_regenerate")
```

### Connection Configuration

- Default path: `.cursor/hooks/state/narratives.db`
- WAL journal mode for concurrent read/write
- Busy timeout: 5000ms (handles SQLite locking)
- Foreign keys: ON
- Custom db path: `NarrativesDB(db_path=Path("/custom/path.db"))`

### Fail-Open Design

All DB methods return `False` or `None` on failure instead of raising exceptions. The JSON file system remains the source of truth; SQLite is a secondary query layer.

## Query Patterns

### Sessions by Date Range

```python
with NarrativesDB() as db:
    all_sessions = db.list_sessions(limit=50)
    # Filter client-side for date range (no built-in date filter)
    from datetime import datetime
    after = datetime(2026, 4, 29).isoformat()
    recent = [s for s in all_sessions if s["created_at"] >= after]
```

### Sessions with Narratives

```python
with NarrativesDB() as db:
    # Join sessions + narratives to find sessions that have been summarized
    sessions = db.list_sessions(limit=100)
    for s in sessions:
        narrative = db.get_narrative(s["session_id"])
        if narrative:
            print(f"{s['session_id']}: {narrative['word_count']} words ({narrative['strategy']})")
```

### Searching Narratives

```python
with NarrativesDB() as db:
    results = db.search_narratives("authentication")
    # Returns narratives + session status, ordered by generated_at DESC
    for r in results:
        print(f"[{r['created_at']}] {r['session_id']}: {r['narrative'][:100]}...")
```

### Aggregating Statistics

```python
with NarrativesDB() as db:
    sessions = db.list_sessions()
    total_thinking = sum(
        db.get_stats(s["session_id"])["total_thinking_time_ms"]
        for s in sessions
        if db.get_stats(s["session_id"])
    )
    avg_events = sum(s.get("total_events", 0) for s in
        [db.get_stats(s["session_id"]) or {} for s in sessions]
    ) / max(len(sessions), 1)
```

### Most-Used Tools

```python
import json
with NarrativesDB() as db:
    sessions = db.list_sessions()
    tool_totals = {}
    for s in sessions:
        stats = db.get_stats(s["session_id"])
        if stats:
            breakdown = json.loads(stats.get("tool_usage_breakdown", "{}"))
            for tool, count in breakdown.items():
                tool_totals[tool] = tool_totals.get(tool, 0) + count
    # tool_totals = {"Read": 45, "Shell": 32, "StrReplace": 28, ...}
```

## Backfill Operations

### Populating DB from JSON Sessions

```bash
cd .cursor/hooks
python narratives_db.py --backfill
```

This reads all `session.json` files from `.cursor/hooks/state/sessions/` and upserts into the 3 SQLite tables. Safe to run multiple times (upserts are idempotent).

### When to Backfill

- After upgrading `narratives_db.py` with new fields
- When migrating from JSON-only to JSON+SQLite
- After manually editing session JSON files
- After deleting and recreating the database

## Data Quality Checks

### Detecting Duplicate Sessions

```python
with NarrativesDB() as db:
    sessions = db.list_sessions()
    ids = [s["session_id"] for s in sessions]
    duplicates = {id for id in ids if ids.count(id) > 1}
    # PRIMARY KEY constraint prevents true duplicates in SQLite
```

### Orphaned Records

```python
with NarrativesDB() as db:
    # Check narratives without a parent session
    import sqlite3
    db._conn.execute(
        "SELECT n.session_id FROM narratives n "
        "LEFT JOIN sessions s ON n.session_id = s.session_id "
        "WHERE s.session_id IS NULL"
    ).fetchall()
```

### Incomplete Summaries

Sessions that have stats but no narrative:
```python
with NarrativesDB() as db:
    sessions = db.list_sessions()
    incomplete = []
    for s in sessions:
        has_narrative = db.get_narrative(s["session_id"]) is not None
        has_stats = db.get_stats(s["session_id"]) is not None
        if has_stats and not has_narrative:
            incomplete.append(s["session_id"])
```

### Schema Version Mismatch

If `narratives_db.py` code has `CURRENT_SCHEMA_VERSION = 1` but the DB has version 2:
- The DB opens in read-only mode
- All writes are skipped with a debug log
- This protects against data corruption from older code against newer schemas

## CLI Usage

```bash
# Backfill DB from JSON sessions
python narratives_db.py --backfill

# List all sessions in DB
python narratives_db.py --list

# Get narrative for a session
python narratives_db.py --get <session_id>

# Search narratives by text
python narratives_db.py --search <query>
```

## view.py Integration

The CLI viewer (`view.py`) reads session data and displays it. It queries the DB for:
- Session lists with status and created_at
- Individual narratives by session_id
- Stats aggregation for summary displays

When extending `view.py`, use `NarrativesDB` context manager for all queries:
```python
with NarrativesDB() as db:
    sessions = db.list_sessions(limit=20)
    # Render sessions with narrative word counts
```

## Migration Patterns

### Adding a New Table

Add a new migration version to the `MIGRATIONS` dict:

```python
CURRENT_SCHEMA_VERSION = 2

MIGRATIONS = {
    1: [...],  # existing
    2: [
        """
        CREATE TABLE IF NOT EXISTS new_table (
            session_id TEXT PRIMARY KEY,
            new_field TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
        """,
    ],
}
```

### Adding a Column

```python
MIGRATIONS = {
    2: [
        "ALTER TABLE sessions ADD COLUMN new_column TEXT DEFAULT ''",
    ],
}
```

### Backward Compatibility

- Code with lower schema version than DB opens read-only
- Code with higher version applies migrations on first connect
- Always increment `CURRENT_SCHEMA_VERSION` when adding migrations
- Never modify existing migration entries (append new versions instead)

## Related Skills

- `langgraph-summarizer` — StateGraph agent that writes narratives to this DB
- `cursor-hooks-state-mgmt` — ConversationRecorder, session.json schema
- `python-hook-debugging` — Debugging SQLite `database is locked` errors
