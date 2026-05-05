# cursor-hooks-testing-practical

Testing patterns for Cursor hook scripts in this project. This project uses Python 3.13 hooks that communicate via stdio JSON protocol.

## Project Layout

- Hook scripts: `.cursor/hooks/*.py`
- Shared utilities: `.cursor/hooks/conversation_recorder.py`
- Hook config: `.cursor/hooks.json` (8 event types, 2-3 hooks each)
- LLM config: `.cursor/llm.env`
- State storage: `.cursor/hooks/state/sessions/` (JSON) + `.cursor/hooks/state/narratives.db` (SQLite)

## Test Infrastructure Setup

### pytest Configuration

Create `d:\test_agent\learning_agent\.cursor\hooks\conftest.py`:

```python
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

# Hook module imports for testing
HOOKS_DIR = Path(__file__).parent.resolve()

@pytest.fixture
def hooks_dir():
    """Return the absolute path to the hooks directory."""
    return HOOKS_DIR

@pytest.fixture
def mock_stdin():
    """Factory fixture to create mock JSON stdin payloads."""
    def _make_payload(event_type="afterAgentResponse", session_id="test-session-001", **kwargs):
        payload = {
            "session_id": session_id,
            "event_type": event_type,
            "composer_mode": "agent",
            "is_background_agent": False,
        }
        payload.update(kwargs)
        return json.dumps(payload)
    return _make_payload

@pytest.fixture
def temp_state_dir(tmp_path):
    """Create a temporary state directory mimicking .cursor/hooks/state/."""
    state_dir = tmp_path / "state" / "sessions"
    state_dir.mkdir(parents=True)
    return tmp_path

@pytest.fixture
def temp_session(temp_state_dir):
    """Create a minimal session.json for testing."""
    session_dir = temp_state_dir / "test-session-001"
    session_dir.mkdir(parents=True)
    session_file = session_dir / "session.json"
    session = {
        "session_id": "test-session-001",
        "created_at": "2026-04-29T10:00:00",
        "last_updated": "2026-04-29T10:00:00",
        "schema_version": 1,
        "events": [],
        "file_edits": [],
        "thoughts": [],
        "responses": [],
        "shell_commands": [],
        "tool_uses": [],
        "summary": {
            "narrative": "",
            "generated_at": "",
            "strategy": "",
            "event_count_at_summary": 0,
            "last_summary_event_count": 0,
        },
    }
    session_file.write_text(json.dumps(session, indent=2))
    return session_file

@pytest.fixture
def mock_llm_env(tmp_path):
    """Create a fake llm.env file to avoid real API calls during tests."""
    env_file = tmp_path / "llm.env"
    env_file.write_text("API_KEY=test-key-123\nBASE_URL=https://api.example.com/v1\nREASONING_MODEL=test-model\n")
    return env_file
```

### pyproject.toml (in `.cursor/hooks/`)

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
markers = [
    "unit: Unit tests for individual functions/classes",
    "integration: Integration tests that invoke hooks via subprocess",
    "slow: Tests that require LLM mocking or complex setup",
]
```

## Testing Patterns by Hook Type

### Pattern 1: Testing ConversationRecorder (Unit Tests)

The `ConversationRecorder` class in `conversation_recorder.py` is the core shared utility. Test it in isolation with `tmp_path`.

```python
import sys
sys.path.insert(0, str(hooks_dir))
from conversation_recorder import ConversationRecorder

def test_load_session_creates_new(temp_state_dir):
    """Loading a non-existent session creates a fresh session.json."""
    recorder = ConversationRecorder()
    # Override directories for isolation
    recorder.STATE_DIR = temp_state_dir / "state"
    recorder.STATE_DIR.mkdir(parents=True, exist_ok=True)
    recorder.SESSIONS_DIR = recorder.STATE_DIR / "sessions"
    recorder.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    recorder.INDEX_FILE = recorder.STATE_DIR / "sessions_index.json"

    session = recorder.load_session("new-session")

    assert session["session_id"] == "new-session"
    assert session["events"] == []
    assert session["schema_version"] == 1
    assert "created_at" in session

def test_add_event_appends_to_session(temp_session, hooks_dir):
    """Adding an event appends to the events list and updates index."""
    recorder = ConversationRecorder()
    recorder.STATE_DIR = temp_session.parent.parent
    recorder.SESSIONS_DIR = temp_session.parent.parent / "sessions"
    recorder.INDEX_FILE = recorder.STATE_DIR / "sessions_index.json"

    recorder.add_event("test-session-001", "response", {"text_preview": "hello", "word_count": 1})

    session = recorder.load_session("test-session-001")
    assert len(session["events"]) == 1
    assert session["events"][0]["type"] == "response"
    assert len(session["responses"]) == 1

def test_update_index_tracks_stats(temp_session, hooks_dir):
    """_update_index writes session stats to sessions_index.json."""
    recorder = ConversationRecorder()
    recorder.STATE_DIR = temp_session.parent.parent
    recorder.SESSIONS_DIR = temp_session.parent.parent / "sessions"
    recorder.INDEX_FILE = recorder.STATE_DIR / "sessions_index.json"

    session = recorder.load_session("test-session-001")
    recorder._update_index(session)

    assert recorder.INDEX_FILE.exists()
    index = json.loads(recorder.INDEX_FILE.read_text())
    assert "test-session-001" in index
    assert index["test-session-001"]["event_count"] == 0
```

### Pattern 2: Testing Hooks via Mocked stdin/stdout

Hook scripts read JSON from stdin and write JSON to stdout. Mock `sys.stdin` and capture `sys.stdout`.

```python
import json
import sys
from io import StringIO
from unittest.mock import patch

def _run_hook_with_payload(hook_module_name, payload):
    """Run a hook module with a mocked stdin payload, return stdout."""
    stdin_str = json.dumps(payload)

    with patch.object(sys, "stdin", StringIO(stdin_str)):
        stdout_capture = StringIO()
        stderr_capture = StringIO()

        with patch.object(sys, "stdout", stdout_capture):
            with patch.object(sys, "stderr", stderr_capture):
                # Import and run the hook's main()
                import importlib
                mod = importlib.import_module(hook_module_name)
                try:
                    mod.main()
                except SystemExit as e:
                    if e.code != 0:
                        raise

        return stdout_capture.getvalue(), stderr_capture.getvalue()

def test_after_agent_response_records_event(mock_stdin, temp_session, hooks_dir):
    """after_agent_response.py records response events to session.json."""
    sys.path.insert(0, str(hooks_dir))

    payload = {
        "session_id": "test-session-001",
        "text": "Hello world, this is a test response",
        "composer_mode": "agent",
    }
    stdout, stderr = _run_hook_with_payload("after_agent_response", payload)

    # Hook should output permission JSON to stdout
    output = json.loads(stdout.strip())
    assert output.get("permission") == "allow"

    # Verify event was recorded
    session = json.loads(temp_session.read_text())
    assert len(session["responses"]) == 1
    assert "word_count" in session["responses"][0]

def test_session_start_initializes_metadata(mock_stdin, temp_state_dir, hooks_dir):
    """session_start.py initializes session metadata."""
    sys.path.insert(0, str(hooks_dir))

    payload = {
        "session_id": "new-session-001",
        "composer_mode": "edit",
        "is_background_agent": False,
    }
    # Override STATE_DIR in ConversationRecorder before running
    from conversation_recorder import ConversationRecorder
    recorder = ConversationRecorder()
    recorder.STATE_DIR = temp_state_dir / "state"
    recorder.STATE_DIR.mkdir(parents=True, exist_ok=True)
    recorder.SESSIONS_DIR = recorder.STATE_DIR / "sessions"
    recorder.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    recorder.INDEX_FILE = recorder.STATE_DIR / "sessions_index.json"

    stdout, stderr = _run_hook_with_payload("session_start", payload)

    output = json.loads(stdout.strip())
    assert output.get("permission") == "allow"
    assert "Session started" in stderr
```

### Pattern 3: Testing narratives_db.py (SQLite CRUD)

Use in-memory SQLite or `tmp_path` for isolated database tests.

```python
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

def test_narratives_db_upsert_session(hooks_dir, tmp_path):
    """NarrativesDB.upsert_session creates and updates session records."""
    sys.path.insert(0, str(hooks_dir))

    # Override STATE_DIR for the module
    import narratives_db
    test_db = tmp_path / "test_narratives.db"

    with patch.object(narratives_db, "STATE_DIR", tmp_path):
        with patch.object(narratives_db.NarrativesDB, "_db_path", test_db):
            with narratives_db.NarrativesDB() as db:
                db.upsert_session(
                    session_id="test-001",
                    created_at="2026-04-29T10:00:00",
                    composer_mode="agent",
                )

            # Verify in a fresh connection
            conn = sqlite3.connect(str(test_db))
            cursor = conn.execute("SELECT session_id, composer_mode FROM sessions WHERE session_id=?", ("test-001",))
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == "test-001"
            assert row[1] == "agent"
            conn.close()

def test_narratives_db_search_narratives(hooks_dir, tmp_path):
    """NarrativesDB.search_narratives finds narratives by text content."""
    sys.path.insert(0, str(hooks_dir))
    import narratives_db

    test_db = tmp_path / "test_narratives.db"
    with patch.object(narratives_db.NarrativesDB, "_db_path", test_db):
        with narratives_db.NarrativesDB() as db:
            db.upsert_session("search-test", "2026-04-29T10:00:00", "agent")
            db.upsert_narrative(
                "search-test",
                narrative="Fixed a bug in the authentication module",
                generated_at="2026-04-29T10:05:00",
                strategy="full_regenerate",
                event_count_at_summary=10,
            )

        with narratives_db.NarrativesDB() as db:
            results = db.search_narratives("authentication")
            assert len(results) == 1
            assert results[0]["session_id"] == "search-test"
```

### Pattern 4: Integration Tests (subprocess Hook Invocation)

Test hooks end-to-end by spawning real Python processes with sample stdin.

```python
import json
import subprocess
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).parent.parent.resolve()  # .cursor/hooks/

def _run_hook_subprocess(hook_script: str, payload: dict) -> subprocess.CompletedProcess:
    """Run a hook script as a subprocess with JSON stdin."""
    python_exe = sys.executable
    result = subprocess.run(
        [python_exe, str(HOOKS_DIR / hook_script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result

def test_debug_hook_accepts_any_payload():
    """debug_hook.py should not crash regardless of payload content."""
    payload = {"session_id": "test-123", "custom_field": "value"}
    result = _run_hook_subprocess("debug_hook.py", payload)
    assert result.returncode == 0

def test_read_hook_input_strips_bom():
    """read_hook_input handles UTF-8 BOM in stdin."""
    from conversation_recorder import read_hook_input
    from io import BytesIO
    from unittest.mock import patch

    # Double-encoded BOM: c3 af c2 bb c2 bf
    raw = b"\xc3\xaf\xc2\xbb\xc2\xbf" + b'{"session_id": "bom-test"}'
    with patch.object(sys, "stdin", BytesIO(raw)):
        payload = read_hook_input()
    assert payload["session_id"] == "bom-test"
```

## Common Test Pitfalls

- **File locking**: On Windows, `_lock_file` uses `msvcrt`. In tests, use `tmp_path` to avoid lock contention between parallel tests.
- **LLM calls**: Always mock `ChatOpenAI.invoke` with `@patch("langchain_openai.ChatOpenAI.invoke")` to avoid real API calls and costs.
- **Module path resolution**: Hooks use `sys.path.insert(0, str(Path(__file__).parent))`. In tests, ensure the hooks directory is on `sys.path`.
- **SQLite concurrent access**: Use `tmp_path` for each test to avoid `database is locked` errors.
- **Daemon tests**: `summarizer_daemon.py` writes a PID file. Mock `os.getpid()` to avoid stale PID conflicts.

## Running Tests

```bash
# All tests
cd d:\test_agent\learning_agent\.cursor\hooks
python -m pytest tests/ -v

# Unit tests only
python -m pytest tests/ -v -m unit

# Integration tests only
python -m pytest tests/ -v -m integration

# With coverage
python -m pytest tests/ -v --cov=. --cov-report=html
```

## Related Skills

- `cursor-hooks-testing` — Conceptual testing patterns and test philosophy
- `cursor-hooks-core` — Hook lifecycle, stdio JSON protocol, exit codes
- `python-hook-debugging` — Debugging and profiling hook scripts on Windows
