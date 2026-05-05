# python-hook-debugging

Debugging and profiling Python hook scripts on Windows. Hook scripts run via Cursor's stdio JSON protocol, which creates unique debugging challenges compared to normal Python development.

## Project Layout

- Hook scripts: `.cursor/hooks/*.py` (17 Python files)
- Hook config: `.cursor/hooks.json` (8 event types, timeouts)
- Debug log: `.cursor/hooks/state/hook-debug.log`
- LLM config: `.cursor/llm.env`
- Shared utilities: `.cursor/hooks/conversation_recorder.py`

## Windows-Specific Issues

### File Locking

- `conversation_recorder.py` uses `msvcrt` for exclusive file locks on `session.json`
- Lock files: `session.json.lock` with PID ownership
- **Symptom**: `Lock timeout for session {session_id}, appending event without lock`
- **Fix**: Check `hook-debug.log` for lock contention patterns. Multiple hooks writing to the same session simultaneously can cause 10-second timeouts.
- **SQLite locking**: `narratives.db` uses Python stdlib `sqlite3` with default journal mode. Concurrent writes from `session_start.py` and `save_summary` in `summarizer_agent.py` can cause `sqlite3.OperationalError: database is locked`. All SQLite writes use fail-open try/except blocks.

### CRLF Line Endings

- Batch files (`.bat`) use CRLF; Python hooks use LF
- `run-hooks.bat` and `test-debug.bat` may have path escaping issues with backslashes
- **Symptom**: `python: can't open file 'd:\x0cest_agent\...'` (escaped characters)
- **Fix**: Use forward slashes or raw strings (`r"d:\test_agent\..."`) in batch files

### Python Path Resolution

- `hooks.json` uses absolute Python path: `C:\Users\kanis\AppData\Local\Python\pythoncore-3.13-64\python.exe`
- If Python is updated or moved, all hooks fail silently
- **Verify**: Run `where python` in PowerShell to confirm path matches `hooks.json`

## stdio Protocol Debugging

### How Hooks Communicate

Cursor sends JSON to hook stdin and expects JSON from hook stdout:

```
Cursor -> stdin: {"session_id": "...", "text": "...", "composer_mode": "agent", ...}
Hook -> stdout:  {"permission": "allow"}
Hook -> stderr:  "[conversation-recorder] Recorded response: abc123 (42 words)"
```

### Common Protocol Errors

- **Printing to stdout**: Any `print()` without `file=sys.stderr` corrupts the JSON response. Cursor will fail to parse the hook output.
- **Not outputting JSON**: Hooks must output valid JSON. The `safe_output()` helper in `conversation_recorder.py` handles this.
- **Exceptions before output**: If a hook crashes before calling `safe_output()`, Cursor receives empty stdout. This is treated as a hook failure.

### Debug Log

All hooks call `debug_log()` which appends to `.cursor/hooks/state/hook-debug.log`:

```
[2026-04-29T10:00:00.000000] Session started: abc123 (background=False, mode=agent)
[2026-04-29T10:00:01.000000] Recorded response: abc123 (42 words, 5 lines)
[2026-04-29T10:00:02.000000] session_start SQLite write failed: database is locked
```

Use `Get-Content .cursor\hooks\state\hook-debug.log -Tail 50` in PowerShell to view recent entries.

## Python Debugging Patterns

### pdb in Short-Lived Processes

Hooks are ephemeral (start, run, exit). Traditional `pdb.set_trace()` works but requires attaching stdin:

```python
# In a hook script:
import pdb; pdb.set_trace()  # Will block waiting for input from Cursor's hook runner
```

**Better approach**: Write to debug log and use `--force` flags:
```python
from conversation_recorder import debug_log
debug_log(f"DEBUG: payload keys = {list(payload.keys())}")
debug_log(f"DEBUG: session_id = {conversation_id}")
```

### Manual Hook Invocation

Test hooks directly with crafted JSON:
```powershell
# Create test payload
$payload = '{"session_id": "test-123", "text": "hello", "composer_mode": "agent"}'

# Run hook with stdin
$payload | C:\Users\kanis\AppData\Local\Python\pythoncore-3.13-64\python.exe d:\test_agent\learning_agent\.cursor\hooks\after_agent_response.py
```

### traceback Logging

All hooks should wrap main logic in try/except with traceback:
```python
import traceback
try:
    main()
except Exception as e:
    debug_log(f"Error: {e}\n{traceback.format_exc()}")
    print(json.dumps({"permission": "allow"}))  # fail-open
    sys.exit(0)
```

This pattern is already used in `narratives_db.py`.

## Performance Profiling

### Hook Timeouts

- `sessionEnd` has a 30-second timeout in `hooks.json`
- Other hooks have implicit Cursor timeouts (~60s)
- `summarizer_daemon.py` runs asynchronously (not subject to hook timeouts)

### Identifying Slow Operations

Add timing to hooks:
```python
import time
start = time.monotonic()
# ... operation ...
debug_log(f"DEBUG: operation took {time.monotonic() - start:.3f}s")
```

### Common Slow Operations

| Operation | Typical Time | Notes |
|---|---|---|
| File I/O (JSON read/write) | <10ms | Fast on SSD, but file locking adds 0-10s |
| SQLite insert | <5ms | May block if database locked by another process |
| LLM API call (summarizer) | 2-15s | Network dependent; has 60s timeout |
| Directory creation | <1ms | Negligible |

## Common Failure Modes

### Missing llm.env Variables

- **Symptom**: `[summarizer] ERROR: API_KEY not set in llm.env`
- **Fix**: Copy `.cursor/llm.env.example` to `.cursor/llm.env` and fill in credentials
- **Check**: `Get-Content .cursor\llm.env`

### SQLite Database Locked

- **Symptom**: `sqlite3.OperationalError: database is locked` in `hook-debug.log`
- **Cause**: `session_start.py` and `summarizer_agent.py` both write to `narratives.db` concurrently
- **Impact**: None — all SQLite writes are fail-open. JSON files remain the source of truth.
- **Fix**: Not critical. If frequent, consider increasing SQLite timeout in `NarrativesDB.__init__`.

### JSON Decode Errors

- **Symptom**: `JSON decode error` in `hook-debug.log`, hook returns `{"permission": "allow"}`
- **Cause**: Malformed stdin from Cursor (rare) or BOM encoding issues
- **Fix**: `read_hook_input()` already handles double-encoded and single-encoded BOM stripping

### Hook Not Triggering

- **Symptom**: No entries in `hook-debug.log` for a specific event type
- **Check**: `hooks.json` has the hook registered for that event
- **Check**: Python path in `hooks.json` is valid
- **Check**: No syntax errors in the hook script: `python -m py_compile .cursor\hooks\hook_name.py`

## Logging Strategy

### When to Use Which Log

| Log | Purpose | Location |
|---|---|---|
| `debug_hook.py` | Universal event data (payload structure, timing) | `state/hook-debug.log` |
| Per-hook `debug_log()` | Hook-specific errors and state | `state/hook-debug.log` (same file) |
| stderr `print()` | Human-readable status messages | Cursor's hook runner output |
| `summarizer_daemon.log` | Daemon lifecycle | `state/summarizer_daemon.log` |

### debug_hook.py

Attached to ALL 8 event types. Logs:
- Event type and timestamp
- Payload keys present
- Execution duration
- Hook script name

This is your first stop for "is this hook even firing?" questions.

## Related Skills

- `cursor-hooks-core` — Hook lifecycle, stdio JSON protocol, exit codes
- `cursor-hooks-observability` — Structured logging, HookLogger, HookTracer
- `cursor-hooks-testing-practical` — Testing patterns for hook scripts
