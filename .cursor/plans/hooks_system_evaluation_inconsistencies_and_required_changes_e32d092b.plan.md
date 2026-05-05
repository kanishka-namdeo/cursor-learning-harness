---
name: "Hooks System Evaluation: Inconsistencies and Required Changes"
overview: ""
todos: []
isProject: false
---

# Hooks System Evaluation: Inconsistencies and Required Changes

## Architecture Overview

The system has 31 Python files spanning 16 configured hook events, 2 summarizer agents (session-level and conversation-level), a daemon for batch processing, a file-based trigger system, a SQLite database layer (7 schema migrations), a conversation linker for grouping sessions, and a debug infrastructure. Data flows through two parallel stores: JSON files (primary) and SQLite (secondary/index).

### Complete Hook Registry (from hooks.json)

| Hook Event | Scripts (in order) | Has Debug? |
|------------|--------------------|------------|
| sessionStart | debug_hook.py, session_start.py, summarizer_daemon.py --start | Yes |
| sessionEnd | debug_hook.py, session_end.py (30s timeout) | Yes |
| preToolUse | debug_hook.py, pre_tool_use.py | Yes |
| postToolUse | post_tool_use.py | No |
| postToolUseFailure | post_tool_use_failure.py | No |
| beforeShellExecution | test-debug.bat, debug_hook.py, before_shell_execution.py | Yes |
| afterShellExecution | after_shell_execution.py | No |
| beforeMCPExecution | before_mcp_execution.py | No |
| afterMCPExecution | after_mcp_execution.py | No |
| subagentStart | subagent_start.py | No |
| subagentStop | subagent_stop.py | No |
| beforeReadFile | before_read_file.py | No |
| afterFileEdit | debug_hook.py, after_file_edit.py | Yes |
| beforeSubmitPrompt | before_submit_prompt.py | No |
| preCompact | pre_compact.py | No |
| afterAgentResponse | debug_hook.py, after_agent_response.py, summarizer_trigger.py | Yes |
| afterAgentThought | debug_hook.py, after_agent_thought.py | Yes |
| stop | debug_hook.py, stop.py, summarizer_trigger.py --force | Yes |
| beforeTabFileRead | before_tab_file_read.py | No |
| afterTabFileEdit | after_tab_file_edit.py | No |

### Data Flow
```
Hook Events -> conversation_recorder.add_event() -> session.json (primary)
                                                   -> narratives.db (dual-write, fail-open)

Summarization (2 competing paths):
  Path A: afterAgentResponse/stop -> summarizer_trigger.py -> trigger file -> summarizer_daemon.py (polling) -> summarizer_agent.py (LangGraph)
  Path B: session_end.py -> conversation_summarizer_agent.py (detached subprocess, 120s timeout)

Conversation ID Resolution:
  session_start.py -> ConversationLinker (5-step heuristic) -> conversation_links.json + conversation_fingerprint.json
```

---

## Critical Issues (Must Fix)

### 1. session_id vs conversation_id Mismatch

**Files:** `stop.py:16`, `session_end.py:357`, `conversation_recorder.py:487-489`, `session_start.py:59-64`

The `get_conversation_id()` function in `conversation_recorder.py` line 489 returns `payload.get("session_id") or payload.get("conversation_id") or "unknown"` -- treating them as interchangeable. But `session_start.py` uses this value to `load_session()`, then resolves the real `conversation_id` via `ConversationLinker` and stores it in the session. Other hooks (`stop.py`, `after_*`, `subagent_stop.py`, `summarizer_trigger.py`) use the raw value directly without resolution.

**Impact:** Events recorded by hooks fired before `session_start` resolves the real conversation_id get stored under the wrong key. The `stop.py` hook writes to SQLite using the unresolved `session_id` (line 42) but writes to the `conversations` table using the resolved `conversation_id` (line 49-53) -- creating orphaned session rows. The `summarizer_trigger.py` (line 21) also uses the unresolved ID, so trigger files are named with raw session_ids that may not match the summarizer's lookup keys.

**Fix:** Create a single `resolve_session_id(payload)` function that reads the current session's `conversation_id` from `session.json` if it exists, falling back to the payload value. Use it consistently in ALL hooks. The `get_conversation_id` function should be renamed to `get_raw_session_id` and marked as internal.

### 2. Dual-Write Key Divergence Between JSON and SQLite

**Files:** `conversation_recorder.py:401-415`, `session_end.py:410-458`, `stop.py:38-63`

`add_event()` in `conversation_recorder.py` writes to JSON using the passed session_id but writes to SQLite using the same session_id without resolving it. However, `session_end.py` line 414 calls `db.upsert_session(session_id=conversation_id, ...)` where `conversation_id` has been resolved from the session metadata. This means the same session can have rows in SQLite under BOTH the raw session_id (from `add_event` dual-writes) AND the resolved conversation_id (from `session_end`).

**Fix:** All SQLite writes should use the same resolved session_id. Either resolve once in `add_event()` or pass the resolved ID explicitly from each hook.

### 3. Both stop.py AND summarizer_trigger.py Kill/Interfere with Daemon

**Files:** `stop.py:75-79`, `session_end.py:476-479`, `hooks.json:120-130`

Three separate mechanisms fight over the daemon:
- `stop.py` calls `stop_daemon()` directly (kills it)
- `summarizer_trigger.py` calls `ensure_daemon_running()` (starts it if dead)
- `session_end.py` calls `stop_daemon()` (kills it again)

The `stop` hook fires at the end of EACH agent loop turn. With the current hooks.json, `stop` runs `debug_hook.py` -> `stop.py` (kills daemon) -> `summarizer_trigger.py --force` (restarts daemon). This means the daemon is killed and restarted on every single turn, defeating the purpose of a persistent daemon.

**Fix:** Remove `stop_daemon()` from `stop.py` entirely. Move daemon lifecycle to `session_start.py` (start) and `session_end.py` (stop) only. Remove `summarizer_trigger.py` from the `stop` hook in hooks.json (it's redundant with afterAgentResponse).

### 4. session_end.py Lock Uses conversation_id but Summarizer Uses session_id

**Files:** `session_end.py:351`, `summarizer_agent.py:94-125`

`session_end.py` line 351 calls `summarizer_acquire_lock(conversation_id)` -- acquiring the lock under the conversation_id. But `summarizer_agent.py`'s `acquire_lock` (line 94) and the daemon's `check_lock` (summarizer_daemon.py:177) use session_id. This means the lock mechanism fails to prevent concurrent writes between session_end and the summarizer when they operate on the same session.

**Fix:** `session_end.py` should acquire the lock using the session_id (which equals conversation_id in this context since session_start uses conversation_id as the session key). Add a comment documenting this invariant.

---

## High-Priority Issues

### 5. debug_hook.py Runs on 8 Hook Events -- Significant Overhead

**Files:** `hooks.json` (8 entries), `debug_hook.py`

`debug_hook.py` is configured for: sessionStart, sessionEnd, preToolUse, beforeShellExecution, afterFileEdit, afterAgentResponse, afterAgentThought, stop. Each invocation reads stdin, parses JSON, and writes to a 9000+ line debug log. This adds latency to every hot-path hook, especially preToolUse which fires on every tool call.

**Fix:** Remove debug_hook.py from high-frequency hooks (preToolUse, afterAgentResponse, afterAgentThought, afterFileEdit). Keep only on lifecycle hooks (sessionStart, sessionEnd) if needed for debugging. Add a `DEBUG_HOOK_ENABLED` environment variable to toggle without editing hooks.json.

### 6. test-debug.bat in beforeShellExecution Chain

**Files:** `hooks.json:43-45`

`test-debug.bat` runs as the FIRST script in the beforeShellExecution chain. This is a leftover debugging artifact that adds unnecessary latency to every shell command.

**Fix:** Remove `test-debug.bat` from hooks.json. If debug logging is needed, rely on debug_hook.py which already runs after it.

### 7. Competing Summarization Paths (Daemon vs Direct Subprocess)

**Files:** `summarizer_trigger.py`, `session_end.py:110-131`, `hooks.json:101-110, 120-130`

Two independent summarization paths exist:
- **Path A (daemon):** afterAgentResponse and stop write trigger files -> daemon polls -> LangGraph summarizer
- **Path B (direct):** session_end.py launches conversation_summarizer_agent.py as a detached subprocess

The two paths serve different purposes (session-level vs conversation-level) but Path A is triggered on `stop` with `--force` flag, which may conflict with the daemon's debounce logic. Also, Path B checks for session narratives but the daemon may not have finished processing by the time session_end fires.

**Fix:** Make the relationship explicit. Either (a) have session_end.py wait for the daemon to finish processing before checking narrative readiness, or (b) have the daemon trigger conversation summarization after all session-level summaries are done. Document the intended interaction.

### 8. _truncate Function Duplicated in 8 Files

**Files:** `after_agent_response.py:16-19`, `after_agent_thought.py:16-19`, `after_shell_execution.py:16-19`, `after_mcp_execution.py:16-19`, `post_tool_use.py:16-19`, `before_read_file.py:16-19`, `subagent_stop.py:16-19`, `summarizer_agent.py:386-389`

Eight nearly identical `_truncate` functions exist across the codebase, each with slightly different constants. This is a maintenance burden.

**Fix:** Add a single `truncate(text, max_chars, marker="[...truncated]")` utility to `conversation_recorder.py` and import it in all hooks.

### 9. _is_process_alive Duplicated in Two Files

**Files:** `summarizer_agent.py:133-158`, `conversation_summarizer_agent.py:116-138`

The exact same `_is_process_alive` function is defined in both summarizer agents. The daemon launcher imports from `summarizer_agent` (line 30), but `conversation_summarizer_agent.py` has its own copy.

**Fix:** Move `_is_process_alive` to `conversation_recorder.py` and import it in both summarizers.

### 10. stop.py Marks Conversation as "completed" Prematurely

**Files:** `stop.py:48-53`

The `stop` hook marks the conversation as `status="completed"` and sets `completed_at` in SQLite. But `stop` fires at the end of every agent loop turn, not just at session end. This means the conversation is marked complete after the first turn, even if the session continues. `session_end.py` is the correct place for this.

**Impact:** The `session_end.py` conversation summary readiness check (line 51) checks `all_completed` -- which will already be true from the `stop` hook, even though the session hasn't truly ended.

**Fix:** Remove the conversation completion logic from `stop.py`. Keep only the stop event recording.

### 11. Tab and Agent Hooks Record Duplicate Event Types

**Files:** `before_tab_file_read.py:37`, `before_read_file.py:40`, `after_tab_file_edit.py:65`, `after_file_edit.py:44`

Both Tab and Agent file read hooks record `file_read` events. Both Tab and Agent file edit hooks record `file_edit` events. The Tab variants use `edit_source: "tab"` and different field structures, but they share the same event type and indexed array, making it impossible to distinguish Tab-originated events from Agent-originated events in queries without parsing the data.

**Fix:** Either (a) use distinct event types (`tab_file_read`, `tab_file_edit`) with separate indexed arrays, or (b) ensure all hooks record a consistent `source` field (`"agent"` or `"tab"`) and document the convention.

---

## Medium-Priority Issues

### 12. shell_command Formatter Branch is Dead Code

**Files:** `summarizer_agent.py:467-472`

The `_format_events()` function has a handler for `shell_command` type (lines 467-472), but `before_shell_execution.py` records `shell_command` events that get stored in the `shell_commands` indexed array. The formatter WILL match this branch when processing raw events. However, the inconsistency is that `shell_result` events are recorded separately, so the timeline shows commands without their results paired together.

**Fix:** The formatter code is actually correct. But consider pairing shell_command and shell_result events in the timeline output for readability.

### 13. ConversationLinker._resolve_from_recent_compaction Scans ALL Sessions

**Files:** `conversation_recorder.py:159-201`

For every new session, the compaction resolver iterates through ALL entries in `conversation_links.json`, reads each session file, and checks for recent compaction. As the number of sessions grows, this becomes O(n) file I/O on every session start.

**Fix:** Add a simple cache or limit the scan to the last N entries (e.g., 10 most recently updated sessions).

### 14. summarizer_daemon.py Rebuilds LangGraph on Every Batch

**Files:** `summarizer_daemon.py:235`

`process_batch()` calls `build_graph()` on every poll cycle, which recompiles the entire LangGraph StateGraph. This is expensive and unnecessary -- the graph is static.

**Fix:** Build the graph once at daemon startup and reuse it across batches.

### 15. Redundant Lock Check in summarizer_daemon.py

**Files:** `summarizer_daemon.py:177-195`, `summarizer_agent.py:94-125`

The daemon has its own `check_lock()` function that duplicates the lock checking logic from `summarizer_agent.acquire_lock()`. The daemon calls `check_lock()` (line 242) AND THEN calls `acquire_lock()` (line 247) -- the second call already does the same check internally.

**Fix:** Remove `check_lock()` from the daemon. Just call `acquire_lock()` directly.

### 16. session_end.py 30-Second Hook Timeout Risk

**Files:** `session_end.py:348-354`

The session_end hook has a 30-second timeout from Cursor. It attempts to acquire the summarizer lock with 6 retries at 0.5s intervals (3s total), then loads the session, generates summary stats, writes JSON, writes SQLite, and launches a detached subprocess. If the daemon's summarizer is running concurrently, the lock wait could exceed 30s.

**Fix:** The lock acquisition strategy is reasonable, but consider reducing the summary generation in session_end to only the fast statistical parts. The narrative summarization is already offloaded to the detached conversation summarizer subprocess.

### 17. No Retention Policy for Sessions

**Files:** No cleanup script exists

Sessions accumulate indefinitely in `state/sessions/`. With 20+ sessions already present and no automatic cleanup, disk usage grows unbounded. The `conversation_recorder.py` implements a 10MB soft cap per session but there's no session-level retention policy.

**Fix:** Implement a cleanup utility (e.g., `cleanup_sessions.py`) that removes sessions older than N days, and schedule it via a cron job or daemon periodic task.

### 18. beforeTabFileRead and beforeReadFile Have Different Content Policies

**Files:** `before_tab_file_read.py:32-35`, `before_read_file.py:44-46`

Tab file reads store `full_content` for files under 5000 chars but only `content_preview` for larger files. Agent file reads always store `content_preview` (truncated to 2000 chars) and never `full_content`. This means Tab file reads can expose more content in the session store than Agent file reads.

**Fix:** Align the content policies between the two hooks for consistent data exposure.

---

## Low-Priority Issues

### 19. CURRENT_SCHEMA_VERSION Defined in Two Places with Different Meanings

**Files:** `conversation_recorder.py:72` (value=4), `narratives_db.py:32` (value=7)

Both modules define `CURRENT_SCHEMA_VERSION` but they track different schemas (JSON vs SQLite). This is confusing when reading the code.

**Fix:** Rename to `CURRENT_JSON_SCHEMA_VERSION` and `CURRENT_SQLITE_SCHEMA_VERSION` respectively.

### 20. conversation_links.json Grows Without Bound

**Files:** `conversation_recorder.py:148-152`

Every session adds an entry to the links file, but entries are never removed. Over time this file grows and the `_resolve_from_recent_compaction` and `_resolve_from_fingerprint` methods scan all entries.

**Fix:** Implement periodic compaction of the links file, removing entries for sessions that have been completed for more than N days.

### 21. check_status.py Outdated File List

**Files:** `check_status.py:84-97`

The status checker's `key_files` list includes only 8 files but misses many current hooks: `after_mcp_execution.py`, `after_tab_file_edit.py`, `post_tool_use_failure.py`, `before_tab_file_read.py`, `before_read_file.py`, `before_submit_prompt.py`, `subagent_stop.py`, `summarizer_trigger.py`, etc.

**Fix:** Update the key files list to include all current hook scripts.

### 22. Debug Log Files Grow Without Bound

**Files:** `state/hooks-debug.log` (9000+ lines, ~500KB+), `state/summarizer_daemon.log`, `state/hook-debug.log`

No log rotation or size limits are implemented. The hooks-debug.log is particularly large because it logs every single hook invocation.

**Fix:** Add log rotation (e.g., max 1MB, keep 3 rotated copies) or periodic truncation. Consider reducing debug_hook.py to only log sessionStart/sessionEnd events.

### 23. view.py Does O(n) Narrative Lookups for Stats

**Files:** `view.py:354-356`

`db_show_stats()` calls `db.get_narrative(s["session_id"])` for every session in a loop -- each call opens and closes a new NarrativesDB context manager. This is O(n) database connections.

**Fix:** Use a single DB connection and a JOIN query to get narrative counts.

### 24. summarizer_trigger.py Uses Raw session_id from get_conversation_id

**Files:** `summarizer_trigger.py:21`

The trigger hook uses `get_conversation_id(payload)` which returns the raw payload value, not the resolved conversation_id. If the session_start.py has resolved a different conversation_id, the trigger file will be named with the wrong ID and the daemon won't find the matching session.

**Fix:** Use a resolved session_id for trigger file naming, or ensure the daemon resolves IDs before processing.

---

## Summary of Required Changes by Priority

| Priority | Issue | Files Affected | Effort |
|----------|-------|----------------|--------|
| Critical | session_id/conversation_id mismatch | conversation_recorder.py, all hooks | Medium |
| Critical | Dual-write key divergence | conversation_recorder.py, session_end.py, stop.py | Medium |
| Critical | Daemon killed/restarted on every stop | stop.py, summarizer_trigger.py, hooks.json | Low |
| Critical | Lock key mismatch (session_end vs summarizer) | session_end.py | Low |
| High | debug_hook.py on 8 hot-path events | hooks.json, debug_hook.py | Low |
| High | test-debug.bat in beforeShellExecution | hooks.json | Low |
| High | Competing summarization paths | summarizer_trigger.py, session_end.py, hooks.json | Medium |
| High | _truncate duplication (8 copies) | 8 hook files + conversation_recorder.py | Low |
| High | _is_process_alive duplication | summarizer_agent.py, conversation_summarizer_agent.py | Low |
| High | stop.py marks conversation completed prematurely | stop.py | Low |
| High | Tab/Agent duplicate event types | before_tab_file_read.py, after_tab_file_edit.py, etc. | Medium |
| Medium | ConversationLinker O(n) scan | conversation_recorder.py | Low |
| Medium | Daemon rebuilds LangGraph every batch | summarizer_daemon.py | Low |
| Medium | Redundant check_lock in daemon | summarizer_daemon.py | Low |
| Medium | Session timeout risk | session_end.py | Low |
| Medium | No retention policy | New cleanup script | Medium |
| Medium | Tab/Agent content policy mismatch | before_tab_file_read.py, before_read_file.py | Low |
| Low | Schema version naming confusion | conversation_recorder.py, narratives_db.py | Low |
| Low | conversation_links.json unbounded growth | conversation_recorder.py | Medium |
| Low | check_status.py outdated | check_status.py | Low |
| Low | Unbounded debug log growth | All hooks, conversation_recorder.py | Low |
| Low | view.py O(n) DB lookups | view.py | Low |
| Low | summarizer_trigger.py raw session_id | summarizer_trigger.py | Low |
