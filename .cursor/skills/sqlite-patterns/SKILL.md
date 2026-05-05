---
name: sqlite-patterns
description: Raw SQLite patterns for this project — schema migrations, WAL mode, dual-write JSON+SQLite consistency, and safe CRUD operations. Use when modifying narratives_db.py, writing new SQLite code, or evolving the schema (v1→v7+).
disable-model-invocation: false
---

# SQLite Patterns — Narratives DB

This project uses raw `sqlite3` (Python stdlib) with **no ORM**. All patterns below are extracted from the existing codebase at `.cursor/hooks/narratives_db.py` (2032 lines, schema v7, 9 tables).

## When to Use This Skill

- Adding new tables, columns, or indexes to `narratives.db`
- Writing new upsert/read/delete methods
- Implementing schema migrations (version bump in `MIGRATIONS` dict)
- Handling SQLite concurrency, WAL mode, or corruption recovery
- Maintaining dual-write consistency between JSON files and SQLite mirror

## Current Schema

- **Schema version:** 7 (defined by `CURRENT_SQLITE_SCHEMA_VERSION`)
- **Tables:** `sessions`, `narratives`, `session_stats`, `schema_versions`, `session_tool_stats`, `hook_events`, `conversations`, `conversation_narratives`, `structured_summaries`, `conversation_structured_summaries`
- **DB path:** `.cursor/hooks/state/narratives.db`

## Pattern 1: Schema Migrations

Migrations are stored in a `MIGRATIONS` dict keyed by version number. Each version maps to a list of SQL statements executed atomically within `BEGIN IMMEDIATE`.

```python
MIGRATIONS = {
    1: [
        "CREATE TABLE IF NOT EXISTS sessions (...)",
        "CREATE TABLE IF NOT EXISTS narratives (...)",
        # ... more statements
    ],
    2: [
        "ALTER TABLE sessions ADD COLUMN cursor_version TEXT",
        # ...
    ],
    # Add new versions sequentially — NEVER skip a version number
}
```

To add a new migration:

1. Add a new entry to `MIGRATIONS` dict with the next version number
2. Increment `CURRENT_SQLITE_SCHEMA_VERSION` constant
3. Each migration runs in `ensure_schema()` via:
   ```python
   for version in range(current + 1, CURRENT_SQLITE_SCHEMA_VERSION + 1):
       self._conn.execute("BEGIN IMMEDIATE")
       for sql in statements:
           self._conn.execute(sql)
       self._conn.execute(
           "INSERT INTO schema_versions (version, applied_at, description) VALUES (?, ?, ?)",
           (version, datetime.now().isoformat(), f"Migration v{version}")
       )
       self._conn.commit()
   ```

**Critical rules:**
- **NEVER modify existing migration entries** — they are already applied to production DBs
- Use `ALTER TABLE ... ADD COLUMN` for additive changes (SQLite limitation)
- For structural changes (drop column, change type), create a new table + data migration pattern
- Each version must be **idempotent** — `CREATE TABLE IF NOT EXISTS` is safe, `ALTER TABLE` on existing column will fail (acceptable)

## Pattern 2: Connection Setup with PRAGMAs

Every connection must apply these PRAGMAs in order:

```python
conn = sqlite3.connect(str(db_path), check_same_thread=False)
conn.row_factory = sqlite3.Row           # Dict-like access via row["column"]
conn.execute("PRAGMA journal_mode=WAL")   # Write-ahead logging for concurrent readers
conn.execute("PRAGMA busy_timeout=5000")  # Retry for 5s on locked DB
conn.execute("PRAGMA foreign_keys=ON")    # Enforce FK constraints (OFF by default in SQLite)
conn.execute("PRAGMA synchronous=NORMAL") # Balanced durability/performance for WAL mode
```

**Why these settings:**
- `WAL` mode allows concurrent readers while a single writer proceeds — critical for the daemon polling + CLI access pattern
- `busy_timeout=5000` prevents `database is locked` errors under concurrent access
- `foreign_keys=ON` must be set per-connection — SQLite does not persist this setting

## Pattern 3: Corrupt DB Recovery

The project auto-detects and recovers from database corruption:

```python
def _connect(self) -> None:
    try:
        # ... normal connection setup
        self.ensure_schema()
    except sqlite3.DatabaseError:
        self._handle_corrupt_db()

def _handle_corrupt_db(self) -> None:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    corrupt_path = self._db_path.with_suffix(f".db.corrupt.{ts}")
    if self._db_path.exists():
        self._db_path.rename(corrupt_path)
    # Create fresh DB
    self._conn = sqlite3.connect(str(self._db_path), ...)
    self.ensure_schema()
```

When adding new code that opens the DB, always wrap in try/except for `sqlite3.DatabaseError`.

## Pattern 4: Upsert with COALESCE for Partial Updates

The project uses `INSERT ... ON CONFLICT ... DO UPDATE SET` with `COALESCE` to merge partial updates:

```python
conn.execute("""
    INSERT INTO sessions (
        session_id, created_at, completed_at, status, duration_ms
    ) VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(session_id) DO UPDATE SET
        completed_at = COALESCE(excluded.completed_at, sessions.completed_at),
        status       = COALESCE(excluded.status, sessions.session_id.status),
        duration_ms  = COALESCE(excluded.duration_ms, sessions.duration_ms),
        last_updated = CURRENT_TIMESTAMP
""", (session_id, created_at, completed_at, status, duration_ms))
conn.commit()
```

**Rules:**
- `COALESCE(excluded.col, sessions.col)` means "use the new value if provided, otherwise keep the old"
- `last_updated = CURRENT_TIMESTAMP` always updates to track freshness
- Always `commit()` after each write — no long-running transactions in hooks context

## Pattern 5: Fail-Open Design

All DB operations return `False` or empty results on failure — they never raise exceptions to callers:

```python
def _require_conn(self) -> bool:
    if self._conn is None or self._closed:
        debug_log("DB connection unavailable, operation skipped")
        return False
    if self._schema_too_new:
        debug_log("Schema version too new for this code, writes disabled")
        return False
    return True

def upsert_session(self, session_id, ...) -> bool:
    if not self._require_conn():
        return False
    try:
        # ... SQL execution
        return True
    except sqlite3.Error as e:
        debug_log(f"upsert_session({session_id}) failed: {e}")
        return False
```

This ensures hooks never block the agent workflow due to DB errors.

## Pattern 6: FK Constraint Enforcement with Helper Methods

SQLite FKs require explicit parent row existence. Use helper methods:

```python
def _ensure_session_row(self, session_id: str) -> None:
    """Insert a minimal sessions row if it doesn't exist (FK helper)."""
    self._conn.execute(
        "INSERT OR IGNORE INTO sessions (session_id, created_at) VALUES (?, CURRENT_TIMESTAMP)",
        (session_id,),
    )
    self._conn.commit()
```

Call this before inserting child rows (narratives, stats) when the parent might not exist yet.

## Pattern 7: Dual-Write JSON+SQLite Consistency

The project writes to both JSON files (primary) and SQLite (queryable mirror). To maintain consistency:

1. JSON writes happen first (in `conversation_recorder.py`)
2. SQLite writes happen asynchronously (best-effort in hooks)
3. Backfill CLI commands repopulate SQLite from JSON:
   ```bash
   python narratives_db.py --backfill          # Populate from JSON sessions
   python narratives_db.py --backfill-events    # Populate hook_events table
   ```
4. When adding a new table, also add backfill logic in `backfill_from_json_sessions()` and `_backfill_single()`

## Pattern 8: Text Encoding and NULL Byte Handling

All text stored to SQLite must be sanitized:

```python
# Strip NULL bytes — SQLite stores them but they break JSON parsing
narrative = narrative.replace("\x00", "\ufffd")
# Handle invalid UTF-8
try:
    narrative = narrative.encode("utf-8", errors="replace").decode("utf-8")
except Exception:
    narrative = "[Narrative encoding failed]"
```

## Pattern 9: JSON Column Storage

JSON data is stored as text columns with `json.dumps()`:

```python
conn.execute(
    "INSERT INTO session_stats (..., unique_files_edited, tool_usage_breakdown) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    (..., json.dumps(unique_files), json.dumps(tool_breakdown))
)
```

When reading back, parse with `json.loads()` and handle `JSONDecodeError`:

```python
try:
    files = json.loads(row["unique_files_edited"])
except (json.JSONDecodeError, TypeError):
    files = []
```

## Pattern 10: Schema Version Too New Detection

If a newer code version creates the DB, older code detects this and goes read-only:

```python
if current > CURRENT_SQLITE_SCHEMA_VERSION:
    debug_log(f"DB schema version {current} > code version {CURRENT_SQLITE_SCHEMA_VERSION}; proceeding read-only")
    self._schema_too_new = True
    return
```

This prevents older hooks from corrupting a schema with newer columns.

## SQLite-Specific Gotchas

1. **No ALTER COLUMN** — SQLite cannot modify existing columns (before 3.35.0). Use `CREATE TABLE ... AS SELECT` pattern for structural changes.
2. **DROP COLUMN** — Only available in SQLite 3.35.0+. Use batch mode (`batch_alter_table`) for compatibility.
3. **Indexes on JSON columns** — SQLite cannot index inside JSON text. Extract scalar columns for frequently queried fields (see `structured_summaries` table pattern).
4. **`row_factory = sqlite3.Row`** — Access columns by name (`row["column"]`), not by index. Convert to dict with `dict(row)`.
5. **`check_same_thread=False`** — Required because hooks run in multiple threads (daemon + CLI). Protect with `BEGIN IMMEDIATE` for write operations.
6. **WAL checkpoint** — Periodically run `PRAGMA wal_checkpoint(PASSIVE)` to prevent unbounded WAL file growth.
