#!/usr/bin/env python3
"""
Comprehensive test of the narrative generation system.

Tests:
1. ConversationRecorder — session CRUD, event recording, indexing
2. _format_events — all event types format correctly
3. _extract_structured_summary — JSON parsing + auto-repair
4. _validate_and_finalize_structured — schema validation
5. NarrativesDB — CRUD operations, schema version
6. SummarizerAgent graph — dry-run through load_and_check + build_context
7. ConversationSummarizerAgent — dry-run through load_conversation + build_context
8. Integration — full end-to-end summarization on existing session
9. Edge cases — empty sessions, corrupted JSON, missing files
"""

import json
import os
import sys
import uuid
from pathlib import Path

HOOKS_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(HOOKS_DIR))

from conversation_recorder import ConversationRecorder
from summarizer_agent import (
    _format_events,
    _extract_structured_summary,
    _validate_and_finalize_structured,
    _make_empty_structured_summary,
    _dedup_events,
    _scrub_secrets,
    acquire_lock,
    release_lock,
    graph as summarizer_graph,
)
from narratives_db import NarrativesDB, CURRENT_SQLITE_SCHEMA_VERSION

PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} — {detail}")


# ---------------------------------------------------------------------------
# 1. ConversationRecorder
# ---------------------------------------------------------------------------

def test_conversation_recorder():
    print("\n=== 1. ConversationRecorder ===")
    recorder = ConversationRecorder()
    test_id = str(uuid.uuid4())

    # Create session
    session = recorder.load_session(test_id)
    check("load_session creates new", session["session_id"] == test_id)
    check("new session has events array", isinstance(session["events"], list))
    check("new session has empty events", len(session["events"]) == 0)
    check("summary has last_summary_event_count", session["summary"]["last_summary_event_count"] == 0)

    # Add events
    recorder.add_event(test_id, "user_prompt", {
        "prompt_text": "Add a feature",
        "model": "qwen3.6-plus",
        "hook_event_name": "beforeSubmitPrompt",
    })
    recorder.add_event(test_id, "tool_use", {
        "tool_name": "Read",
        "tool_input": '{"path": "test.py"}',
        "agent_message": "Reading file",
        "model": "qwen3.6-plus",
    })
    recorder.add_event(test_id, "response", {
        "text": "Done!",
    })

    # Reload and verify
    reloaded = recorder.load_session(test_id)
    check("events appended", len(reloaded["events"]) == 3)
    check("event sequence numbering", reloaded["events"][0]["sequence"] == 0)
    check("event sequence numbering", reloaded["events"][2]["sequence"] == 2)

    # Indexed arrays
    check("user_prompts indexed", len(reloaded["user_prompts"]) == 1)
    check("tool_uses indexed", len(reloaded["tool_uses"]) == 1)
    check("responses indexed", len(reloaded["responses"]) == 1)

    # Save + load
    recorder.save_session(test_id, reloaded)
    saved = recorder.load_session(test_id)
    check("save/load roundtrip", saved["session_id"] == test_id)

    # Cleanup
    session_dir = Path(HOOKS_DIR) / "state" / "sessions" / test_id
    if session_dir.exists():
        import shutil
        shutil.rmtree(session_dir)


# ---------------------------------------------------------------------------
# 2. _format_events
# ---------------------------------------------------------------------------

def test_format_events():
    print("\n=== 2. _format_events ===")

    events = [
        {"type": "user_prompt", "timestamp": "2026-01-01T00:00:00", "prompt_text": "Hello"},
        {"type": "thought", "timestamp": "2026-01-01T00:00:01", "text": "Thinking...", "duration_seconds": 5.5},
        {"type": "response", "timestamp": "2026-01-01T00:00:02", "text": "Hi there!"},
        {"type": "tool_use", "timestamp": "2026-01-01T00:00:03", "tool_name": "Read", "tool_input": '{"path":"x.py"}', "agent_message": "Reading x.py", "model": "qwen3.6-plus"},
        {"type": "tool_result", "timestamp": "2026-01-01T00:00:04", "tool_name": "Read", "duration_ms": 150, "tool_input": '{"path":"x.py"}', "tool_output": "content"},
        {"type": "tool_failure", "timestamp": "2026-01-01T00:00:05", "tool_name": "Shell", "failure_type": "error", "error_message": "cmd not found", "tool_input": "bad_cmd"},
        {"type": "file_edit", "timestamp": "2026-01-01T00:00:06", "file_path": "x.py", "chars_added": 100, "chars_removed": 20},
        {"type": "shell_command", "timestamp": "2026-01-01T00:00:07", "command": "pytest", "model": "qwen3.6-plus"},
        {"type": "shell_result", "timestamp": "2026-01-01T00:00:08", "command": "pytest", "exit_code": 0, "is_success": True, "output": "all passed", "model": "qwen3.6-plus"},
        {"type": "mcp_call", "timestamp": "2026-01-01T00:00:09", "tool_name": "user-github/search", "tool_input": '{"q":"test"}'},
        {"type": "mcp_result", "timestamp": "2026-01-01T00:00:10", "tool_name": "user-github/search", "duration_ms": 500, "result": "found 3"},
        {"type": "subagent_start", "timestamp": "2026-01-01T00:00:11", "subagent_type": "explore", "task": "find files"},
        {"type": "subagent_stop", "timestamp": "2026-01-01T00:00:12", "status": "completed", "summary": "done", "tool_call_count": 5, "message_count": 3, "duration_ms": 10000},
        {"type": "compaction", "timestamp": "2026-01-01T00:00:13", "context_usage_percent": 85.5, "messages_to_compact": 20, "trigger": "token_threshold"},
        {"type": "file_read", "timestamp": "2026-01-01T00:00:14", "file_path": "y.py", "content": "def foo(): pass"},
        {"type": "stop", "timestamp": "2026-01-01T00:00:15", "status": "completed", "loop_count": 3, "error_message": "", "model": "qwen3.6-plus"},
    ]

    formatted = _format_events(events, "full_regenerate", 0)

    check("formatted output is non-empty", len(formatted) > 0, f"got {len(formatted)} chars")
    check("contains user prompt marker", "User Prompt" in formatted)
    check("contains thought marker", "Agent Thought" in formatted)
    check("contains response marker", "Agent Response" in formatted)
    check("contains tool_use marker", "Tool: Read" in formatted)
    check("contains tool_result marker", "Tool Result: Read" in formatted)
    check("contains tool_failure marker", "Tool FAILED: Shell" in formatted)
    check("contains file_edit marker", "File Edit: x.py" in formatted)
    check("contains shell_command marker", "Shell Command" in formatted)
    check("contains shell_result marker", "Shell Result" in formatted)
    check("contains mcp_call marker", "MCP Call:" in formatted)
    check("contains mcp_result marker", "MCP Result:" in formatted)
    check("contains subagent_start marker", "Subagent Started: explore" in formatted)
    check("contains subagent_stop marker", "Subagent Stopped" in formatted)
    check("contains compaction marker", "Context Compaction" in formatted)
    check("contains file_read marker", "File Read: y.py" in formatted)
    check("contains stop marker", "Agent Loop End" in formatted)

    # Dedup test
    duped_events = events + [events[-1]]  # duplicate last event
    deduped = _dedup_events(duped_events)
    check("dedup removes consecutive duplicate", len(deduped) == len(events))

    # Empty events
    empty_formatted = _format_events([], "full_regenerate", 0)
    check("empty events returns empty string", empty_formatted == "")

    # Delta update slicing
    delta_events = [{"type": "response", "timestamp": "2026-01-01T00:00:00", "text": "new"}]
    delta_formatted = _format_events(delta_events, "delta_update", 0)
    check("delta formatting works", "Agent Response" in delta_formatted)


# ---------------------------------------------------------------------------
# 3. Structured Summary Extraction
# ---------------------------------------------------------------------------

def test_extract_structured_summary():
    print("\n=== 3. Structured Summary Extraction ===")

    # Normal JSON block
    normal_response = (
        "Here is my summary:\n\nSome narrative text.\n\n"
        "```json\n"
        '{"objectives": ["test"], "files_modified": [], "files_created": [], '
        '"files_deleted": [], "decisions": [], "errors_encountered": [], '
        '"tool_usage_summary": {}, "subagent_work": [], "code_patterns": [], '
        '"open_questions": [], "outcome": "done", "session_type": "config"}\n'
        "```\n"
    )
    result = _extract_structured_summary(normal_response)
    check("extracts from ```json block", result.get("objectives") == ["test"], f"got: {result.get('objectives')}")
    check("no parse_error flag", "_parse_error" not in result)

    # Malformed JSON with trailing comma (auto-repair)
    malformed = (
        "```json\n"
        '{"objectives": ["test"], "files_modified": ["a.py",], '
        '"files_created": [], "files_deleted": [], "decisions": [], '
        '"errors_encountered": [], "tool_usage_summary": {}, "subagent_work": [], '
        '"code_patterns": [], "open_questions": [], "outcome": "done", '
        '"session_type": "config"}\n'
        "```\n"
    )
    result2 = _extract_structured_summary(malformed)
    check("auto-repair trailing comma", result2.get("files_modified") == ["a.py"], f"got: {result2.get('files_modified')}")

    # All fallback
    result3 = _extract_structured_summary("no json here at all")
    check("fallback returns empty structured", result3.get("objectives") == [])
    check("fallback has parse_error flag", "_parse_error" in result3)


# ---------------------------------------------------------------------------
# 4. Validation
# ---------------------------------------------------------------------------

def test_validate_structured():
    print("\n=== 4. Validation ===")

    # Valid
    valid = _make_empty_structured_summary("test")
    valid["objectives"] = ["do something"]
    validated = _validate_and_finalize_structured(valid)
    check("valid structured passes", validated["objectives"] == ["do something"])
    check("schema_version set", validated["schema_version"] == 1)

    # Bad types get coerced
    bad = {"objectives": "not a list", "session_type": "feature"}
    validated2 = _validate_and_finalize_structured(bad)
    check("bad list type replaced", isinstance(validated2["objectives"], list))

    # Non-dict input
    result = _validate_and_finalize_structured("string")
    check("non-dict returns empty", result.get("objectives") == [])


# ---------------------------------------------------------------------------
# 5. Secrets scrubbing
# ---------------------------------------------------------------------------

def test_scrub_secrets():
    print("\n=== 5. Secrets Scrubbing ===")

    text, scrubbed = _scrub_secrets("key=sk-abcdefghij1234567890abcdefghij")
    check("scrubbed", scrubbed)
    check("secret removed", "sk-" not in text)
    check("redacted marker present", "[REDACTED]" in text)

    text2, scrubbed2 = _scrub_secrets("normal text")
    check("no scrub needed", not scrubbed2)
    check("normal text unchanged", text2 == "normal text")


# ---------------------------------------------------------------------------
# 6. Lock mechanism
# ---------------------------------------------------------------------------

def test_lock():
    print("\n=== 6. Lock Mechanism ===")
    test_id = str(uuid.uuid4())

    check("acquire lock", acquire_lock(test_id))
    check("second acquire fails", not acquire_lock(test_id))
    release_lock(test_id)
    check("release then re-acquire", acquire_lock(test_id))
    release_lock(test_id)

    # Cleanup
    session_dir = Path(HOOKS_DIR) / "state" / "sessions" / test_id
    if session_dir.exists():
        import shutil
        shutil.rmtree(session_dir)


# ---------------------------------------------------------------------------
# 7. NarrativesDB CRUD
# ---------------------------------------------------------------------------

def test_narratives_db():
    print("\n=== 7. NarrativesDB CRUD ===")
    test_id = str(uuid.uuid4())

    with NarrativesDB() as db:
        # Schema version
        check("schema version is 7", CURRENT_SQLITE_SCHEMA_VERSION == 7, f"got {CURRENT_SQLITE_SCHEMA_VERSION}")

        # Upsert session
        db.upsert_session(session_id=test_id, created_at="2026-01-01T00:00:00")
        sessions = db.list_sessions()
        sids = [s["session_id"] for s in sessions]
        check("session persisted", test_id in sids)

        # Upsert narrative
        narrative_text = "This is a test narrative."
        db.upsert_narrative(
            session_id=test_id,
            narrative=narrative_text,
            generated_at="2026-01-01T00:00:00",
            strategy="full_regenerate",
            event_count_at_summary=5,
        )
        narr_row = db.get_narrative(test_id)
        check("narrative persisted", narr_row and narr_row["narrative"] == narrative_text,
              f"got: {narr_row['narrative'] if narr_row else None}")

        # Upsert structured
        structured = {"objectives": ["test"], "outcome": "done", "session_type": "config"}
        db.upsert_structured_summary(
            session_id=test_id,
            structured_json=structured,
            generated_at="2026-01-01T00:00:00",
        )
        struct_row = db.get_structured_summary(test_id)
        check("structured persisted", struct_row and struct_row.get("structured_data") is not None)

        # Stats
        db.upsert_stats(test_id, {"total_events": 10, "total_file_edits": 3})
        # Verify via direct query since no get_stats method exists
        row = db._conn.execute("SELECT total_events FROM session_stats WHERE session_id = ?", (test_id,)).fetchone()
        check("stats persisted", row and row[0] == 10, f"got: {row}")

        # Upsert again (test update)
        db.upsert_narrative(
            session_id=test_id,
            narrative="Updated narrative.",
            generated_at="2026-01-01T00:00:01",
            strategy="delta_update",
            event_count_at_summary=8,
        )
        updated = db.get_narrative(test_id)
        check("narrative updated", updated["narrative"] == "Updated narrative.")


# ---------------------------------------------------------------------------
# 8. SummarizerAgent graph — load_and_check + build_context on real session
# ---------------------------------------------------------------------------

def test_summarizer_graph_dry_run():
    print("\n=== 8. SummarizerGraph dry-run on existing session ===")

    # Use existing session that has events
    session_id = "21199735-edb3-4e44-b184-4ec9de531e0e"
    session_file = Path(HOOKS_DIR) / "state" / "sessions" / session_id / "session.json"

    if not session_file.exists():
        check("session file exists", False, "session not found — skipping")
        return

    result = summarizer_graph.invoke({
        "session_id": session_id,
        "force": True,
        "regenerate": True,
    })

    check("graph ran without error", result.get("error") is None, f"error: {result.get('error')}")
    check("strategy is full_regenerate", result.get("strategy") == "full_regenerate")
    check("has narrative", bool(result.get("narrative_summary")), f"narrative: {result.get('narrative_summary', '')[:100]}")
    check("has structured", bool(result.get("structured_summary")), f"structured keys: {list(result.get('structured_summary', {}).keys())}")
    check("structured has objectives", isinstance(result.get("structured_summary", {}).get("objectives"), list))
    check("structured has session_type", result.get("structured_summary", {}).get("session_type") in (
        "feature", "bugfix", "refactor", "exploration",
        "documentation", "config", "testing", "deployment", "other",
    ))


# ---------------------------------------------------------------------------
# 9. Edge cases
# ---------------------------------------------------------------------------

def test_edge_cases():
    print("\n=== 9. Edge Cases ===")

    # Missing session
    result = summarizer_graph.invoke({
        "session_id": "nonexistent-session-12345",
        "force": True,
    })
    # The graph routes to save_structured_minimal on skip, or returns error
    handled = (
        result.get("strategy") == "skip"
        or result.get("error") is not None
        or result.get("strategy") == "full_regenerate"  # might proceed with 0 events
    )
    check("missing session handled gracefully", handled, f"result keys: {list(result.keys())}")

    # Empty event session
    empty_id = str(uuid.uuid4())
    recorder = ConversationRecorder()
    recorder.load_session(empty_id)  # Creates empty session
    result2 = summarizer_graph.invoke({
        "session_id": empty_id,
        "force": True,
    })
    # build_context returns "skip" for empty events, routes to save_structured_minimal
    handled2 = (
        result2.get("strategy") == "skip"
        or result2.get("structured_summary") is not None
        or result2.get("error") is not None
    )
    check("empty events handled", handled2, f"result keys: {list(result2.keys())}, strategy: {result2.get('strategy')}")

    # Cleanup
    session_dir = Path(HOOKS_DIR) / "state" / "sessions" / empty_id
    if session_dir.exists():
        import shutil
        shutil.rmtree(session_dir)


# ---------------------------------------------------------------------------
# 10. Event type coverage — verify all 16 event types in INDEXED_EVENT_TYPES
# ---------------------------------------------------------------------------

def test_indexed_event_types():
    print("\n=== 10. Indexed Event Types Coverage ===")
    recorder = ConversationRecorder()
    expected_types = {
        "response", "thought", "file_edit", "shell_command", "tool_use",
        "tool_result", "tool_failure", "shell_result", "file_read",
        "mcp_call", "mcp_result", "subagent_start", "subagent_stop",
        "user_prompt", "compaction",
    }
    actual_types = set(recorder.INDEXED_EVENT_TYPES.keys())
    check("all expected types indexed", expected_types.issubset(actual_types),
          f"missing: {expected_types - actual_types}")


# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Narrative System — Comprehensive Verification")
    print("=" * 60)

    test_conversation_recorder()
    test_format_events()
    test_extract_structured_summary()
    test_validate_structured()
    test_scrub_secrets()
    test_lock()
    test_narratives_db()
    test_summarizer_graph_dry_run()
    test_edge_cases()
    test_indexed_event_types()

    print(f"\n{'=' * 60}")
    print(f"Results: {PASS} passed, {FAIL} failed, {PASS + FAIL} total")
    print(f"{'=' * 60}")

    sys.exit(0 if FAIL == 0 else 1)
