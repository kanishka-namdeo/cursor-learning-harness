#!/usr/bin/env python3
"""
Session End Hook - Finalize and summarize recorded conversation.
"""

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conversation_recorder import ConversationRecorder, ConversationLinker, read_hook_input, safe_output, get_conversation_id, debug_log, resolve_session_id
from learning_rules_agent import QUICK_DECIDE_TIMEOUT_SECONDS

# Import summarizer lock to prevent concurrent writes with summarizer agent
from summarizer_agent import acquire_lock as summarizer_acquire_lock
from summarizer_agent import release_lock as summarizer_release_lock

# ---------------------------------------------------------------------------
# Conversation-level summary trigger
# ---------------------------------------------------------------------------

# Summarization architecture:
#
# Two independent paths serve different purposes:
#
# Path A (session-level, daemon-based):
#   afterAgentResponse/stop -> summarizer_trigger.py -> trigger file
#   -> summarizer_daemon.py (polling every POLL_INTERVAL seconds)
#   -> summarizer_agent.py (LangGraph) -> writes SQLite only
#
# Path B (conversation-level, session_end-based):
#   session_end.py -> checks all sessions completed + all have narratives (SQLite)
#   -> launches conversation_summarizer_agent.py (detached subprocess, 120s timeout)
#   -> writes conversation_narratives + conversation_structured_summaries in SQLite
#
# Path A triggers on stop with --force, but the daemon's acquire_lock() prevents
# duplicate work. Path B checks narrative readiness BEFORE launching, so it will
# wait until Path A has finished processing if the daemon is still running.
# If Path A hasn't finished by the time session_end fires, Path B will skip
# and the conversation summary will need to be triggered manually or on the
# next session_end.

CONV_SUMMARIZER_DEBOUNCE_SECONDS = 30


def _try_generate_conversation_summary(conversation_id: str):
    """Attempt to generate a conversation-level summary when a session ends.

    This runs as a detached subprocess to avoid blocking the 30s hook timeout.
    It checks:
    1. All sessions in the conversation have completed_at set
    2. All sessions have narratives
    3. No recent conversation summary (debounce)
    4. More than 1 session in the conversation
    """
    if not conversation_id:
        return

    try:
        from narratives_db import NarrativesDB

        with NarrativesDB() as db:
            sessions = db.get_sessions_by_conversation(conversation_id)

            if not sessions or len(sessions) < 2:
                debug_log(f"session_end: conversation {conversation_id[:12]}... has <2 sessions, skipping")
                return

            # Check if all sessions are completed
            all_completed = all(s.get("completed_at") for s in sessions)
            if not all_completed:
                debug_log(
                    f"session_end: conversation {conversation_id[:12]}... has incomplete sessions, skipping"
                )
                return

            # Check if all sessions have narratives (SQLite only)
            from summarizer_daemon import TRIGGER_DIR
            missing_narratives = 0
            daemon_still_working = False
            for s in sessions:
                sid = s["session_id"]
                has_narrative = False
                # Check SQLite only — narratives are no longer stored in session.json
                try:
                    narr = db.get_narrative(sid)
                    if narr and narr.get("narrative", "").strip():
                        has_narrative = True
                except Exception:
                    pass
                # If no narrative found, check if daemon is still processing
                if not has_narrative and (TRIGGER_DIR / f"{sid}.json").exists():
                    daemon_still_working = True
                    debug_log(
                        f"session_end: daemon still processing session {sid[:12]}..., "
                        f"deferring conversation summary"
                    )
                if not has_narrative:
                    missing_narratives += 1

            if daemon_still_working:
                debug_log(
                    f"session_end: daemon is still processing, "
                    f"deferring conversation summary for {conversation_id[:12]}..."
                )
                return

            if missing_narratives > 0:
                debug_log(
                    f"session_end: conversation {conversation_id[:12]}... has "
                    f"{missing_narratives} sessions without narratives, skipping"
                )
                return

            # Check debounce
            conv_narr = db.get_conversation_narrative(conversation_id)
            if conv_narr:
                generated = conv_narr.get("generated_at", "")
                if generated:
                    try:
                        gen_dt = datetime.fromisoformat(generated)
                        if (datetime.now() - gen_dt).total_seconds() < CONV_SUMMARIZER_DEBOUNCE_SECONDS:
                            debug_log(
                                f"session_end: conversation {conversation_id[:12]}... summary is recent, skipping"
                            )
                            return
                    except ValueError:
                        pass
    except Exception as e:
        debug_log(f"session_end: conversation summary readiness check failed: {e}")
        return

    # All checks passed — launch summarizer as detached subprocess
    try:
        summarizer_script = Path(__file__).parent / "conversation_summarizer_agent.py"
        if summarizer_script.exists():
            subprocess_kwargs = {
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if sys.platform == "win32":
                subprocess_kwargs["creationflags"] = (
                    subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
                )

            subprocess.Popen(
                [sys.executable, str(summarizer_script), conversation_id],
                **subprocess_kwargs,
            )
            debug_log(
                f"session_end: launched conversation summarizer for {conversation_id[:12]}..."
            )
    except Exception as e:
        debug_log(f"session_end: failed to launch conversation summarizer: {e}")


def generate_summary(session):
    events = session.get("events", [])
    responses = session.get("responses", [])
    thoughts = session.get("thoughts", [])
    file_edits = session.get("file_edits", [])
    shell_commands = session.get("shell_commands", [])
    shell_results = session.get("shell_results", [])
    tool_uses = session.get("tool_uses", [])
    tool_results = session.get("tool_results", [])
    tool_failures = session.get("tool_failures", [])
    file_reads = session.get("file_reads", [])
    user_prompts = session.get("user_prompts", [])
    compactions = session.get("compactions", [])

    total_thought_duration = sum(t.get("duration_ms", 0) for t in thoughts)
    total_chars_added = sum(e.get("chars_added", 0) for e in file_edits)
    total_chars_removed = sum(e.get("chars_removed", 0) for e in file_edits)

    edited_files = list(set(e.get("file_path", "") for e in file_edits))

    tool_counts = {}
    for t in tool_uses:
        name = t.get("tool_name", "unknown")
        tool_counts[name] = tool_counts.get(name, 0) + 1

    # Tool success/failure tracking
    tool_success_counts = {}
    for t in tool_results:
        name = t.get("tool_name", "unknown")
        tool_success_counts[name] = tool_success_counts.get(name, 0) + 1

    tool_failure_counts = {}
    for t in tool_failures:
        name = t.get("tool_name", "unknown")
        failure_type = t.get("failure_type", "unknown")
        tool_failure_counts[f"{name}:{failure_type}"] = tool_failure_counts.get(f"{name}:{failure_type}", 0) + 1

    # Distinguish actual errors from other failure types (timeout, cancellation, etc.)
    total_tool_errors = sum(1 for t in tool_failures if t.get("failure_type") == "error")

    # Shell success/failure tracking
    shell_success_count = sum(1 for s in shell_results if s.get("is_success"))
    shell_failure_count = sum(1 for s in shell_results if s.get("is_success") is False)

    # Tool duration tracking (from post_tool_use.py)
    tool_durations = [t.get("duration_ms", 0) for t in tool_results if t.get("duration_ms", 0) > 0]
    total_tool_duration_ms = sum(tool_durations)
    avg_tool_duration_ms = total_tool_duration_ms / len(tool_durations) if tool_durations else 0

    # Per-model breakdown across all events
    model_usage = {}
    for ev in events:
        m = ev.get("model", "")
        if m:
            model_usage[m] = model_usage.get(m, 0) + 1

    return {
        "finalized_at": datetime.now().isoformat(),
        "total_events": len(events),
        "total_responses": len(responses),
        "total_thoughts": len(thoughts),
        "total_thinking_time_ms": total_thought_duration,
        "total_thinking_time_seconds": total_thought_duration / 1000,
        "total_file_edits": len(file_edits),
        "unique_files_edited": edited_files,
        "total_shell_commands": len(shell_commands),
        "total_shell_results": len(shell_results),
        "shell_success_count": shell_success_count,
        "shell_failure_count": shell_failure_count,
        "total_tool_uses": len(tool_uses),
        "total_tool_results": len(tool_results),
        "total_tool_failures": len(tool_failures),
        "total_file_reads": len(file_reads),
        "total_user_prompts": len(user_prompts),
        "total_compactions": len(compactions),
        "tool_usage_breakdown": tool_counts,
        "tool_success_breakdown": tool_success_counts,
        "tool_failure_breakdown": tool_failure_counts,
        "net_code_change": total_chars_added - total_chars_removed,
        "total_chars_added": total_chars_added,
        "total_chars_removed": total_chars_removed,
        "total_tool_duration_ms": total_tool_duration_ms,
        "avg_tool_duration_ms": round(avg_tool_duration_ms, 1),
        "total_tool_errors": total_tool_errors,
        "model_usage_breakdown": model_usage,
    }


def _try_quick_scan_learning(session_id: str):
    """Run learning signal extraction on the just-completed session transcript.

    Runs synchronously to avoid race conditions with the summarizer daemon.
    Writes extracted signals to JSON instead of .mdc rule files.
    """
    if not session_id:
        return

    hooks_dir = Path(__file__).parent
    learning_analyzer = hooks_dir / "learning_analyzer.py"
    if not learning_analyzer.exists():
        return

    try:
        venv_python = hooks_dir.parent.parent / ".venv" / "Scripts" / "python.exe"
        if not venv_python.exists():
            venv_python = sys.executable

        # Run synchronously to ensure summarizer has finished writing structured data
        subprocess.run(
            [str(venv_python), str(learning_analyzer), "--quick-scan", session_id],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        debug_log(f"session_end: completed quick-scan for session {session_id[:12]}...")
    except subprocess.TimeoutExpired:
        debug_log(f"session_end: quick-scan timed out for session {session_id[:12]}...")
    except Exception as e:
        debug_log(f"session_end: quick-scan failed: {e}")


def _try_quick_learning_rules_decision(session_id: str):
    """Run rule-based check on whether learning-critical.mdc needs updating.

    Sync call within the session_end hook timeout budget. Skipped if
    the hook is already near timeout (caller checks this).
    """
    if not session_id:
        return

    hooks_dir = Path(__file__).parent
    learning_rules_agent = hooks_dir / "learning_rules_agent.py"
    if not learning_rules_agent.exists():
        return

    try:
        venv_python = hooks_dir.parent.parent / ".venv" / "Scripts" / "python.exe"
        if not venv_python.exists():
            venv_python = sys.executable

        subprocess.run(
            [str(venv_python), str(learning_rules_agent), "--quick-decide", session_id],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=QUICK_DECIDE_TIMEOUT_SECONDS,
        )
        debug_log(f"session_end: completed quick-decide for session {session_id[:12]}...")
    except subprocess.TimeoutExpired:
        debug_log(f"session_end: quick-decide timed out for session {session_id[:12]}...")
    except Exception as e:
        debug_log(f"session_end: quick-decide failed: {e}")


def _try_full_learning_rules_agent():
    """Launch the full LangGraph learning rules agent as a detached subprocess.

    Runs independently of the hook timeout. Uses CREATE_NEW_PROCESS_GROUP
    on Windows so it survives the daemon kill at session end.
    """
    hooks_dir = Path(__file__).parent
    learning_rules_agent = hooks_dir / "learning_rules_agent.py"
    if not learning_rules_agent.exists():
        return

    try:
        venv_python = hooks_dir.parent.parent / ".venv" / "Scripts" / "python.exe"
        if not venv_python.exists():
            venv_python = sys.executable

        subprocess_kwargs = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            subprocess_kwargs["creationflags"] = (
                subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            )

        subprocess.Popen(
            [str(venv_python), str(learning_rules_agent), "--full"],
            **subprocess_kwargs,
        )
        debug_log("session_end: launched detached learning rules agent")
    except Exception as e:
        debug_log(f"session_end: failed to launch learning rules agent: {e}")


def main():
    payload = read_hook_input()
    raw_id = get_conversation_id(payload)
    reason = payload.get("reason", "unknown")
    duration_ms = payload.get("duration_ms", 0)
    final_status = payload.get("final_status", "unknown")
    error_message = payload.get("error_message", "")
    is_background = payload.get("is_background_agent", False)

    # Resolve the canonical session_id (same ID that session_start.py uses as
    # the session.json key). This MUST match the key used by summarizer_agent.py
    # for its per-session lock -- otherwise concurrent writes can corrupt data.
    session_id = resolve_session_id(payload)

    # Acquire summarizer lock using the SAME session_id key that the summarizer
    # uses (not the conversation_id). This prevents race conditions between
    # session_end.py and summarizer_agent.py writing to the same session.json.
    acquired = False
    for _ in range(6):
        if summarizer_acquire_lock(session_id):
            acquired = True
            break
        time.sleep(0.5)

    recorder = ConversationRecorder()
    session = recorder.load_session(session_id)

    # Preserve any existing summary fields from the summarizer agent
    existing_summary = session.get("summary", {})

    summary = generate_summary(session)
    summary.update({
        "end_reason": reason,
        "session_duration_ms": duration_ms,
        "session_duration_seconds": duration_ms / 1000,
        "final_status": final_status,
        "error_message": error_message,
    })

    # Merge into existing summary rather than replacing it entirely.
    # This preserves fields like last_summary_event_count written by summarizer_agent.py
    # that may have been written between our load_session and this point.
    merged = dict(existing_summary)
    merged.update(summary)

    session["summary"] = merged
    recorder.save_session(session_id, session)

    # Release lock now that all writes are complete
    if acquired:
        summarizer_release_lock(session_id)

    # Resolve conversation_id from session metadata for SQLite writes
    conversation_id = session.get("conversation_id", "") or session_id

    # Persist stats to SQLite (fail-open)
    try:
        from narratives_db import NarrativesDB
        with NarrativesDB() as db:
            # Persist session completion with is_background_agent
            # Use the actual session_id (not conversation_id) so narratives
            # can be linked correctly via session_id.
            db.upsert_session(
                session_id=session_id,
                completed_at=datetime.now().isoformat(),
                status=final_status,
                duration_ms=duration_ms,
                end_reason=reason,
                is_background_agent=1 if is_background else 0,
                conversation_id=conversation_id or None,
            )

            stats = {
                "total_events": summary.get("total_events", 0),
                "total_responses": summary.get("total_responses", 0),
                "total_thoughts": summary.get("total_thoughts", 0),
                "total_thinking_time_ms": summary.get("total_thinking_time_ms", 0),
                "total_file_edits": summary.get("total_file_edits", 0),
                "unique_files_edited": summary.get("unique_files_edited", []),
                "total_shell_commands": summary.get("total_shell_commands", 0),
                "total_shell_failures": summary.get("shell_failure_count", 0),
                "total_tool_uses": summary.get("total_tool_uses", 0),
                "total_tool_successes": summary.get("total_tool_results", 0),
                "total_tool_failures": summary.get("total_tool_failures", 0),
                "model_usage_breakdown": summary.get("model_usage_breakdown", {}),
                "tool_usage_breakdown": summary.get("tool_usage_breakdown", {}),
                "net_code_change": summary.get("net_code_change", 0),
                "total_chars_added": summary.get("total_chars_added", 0),
                "total_chars_removed": summary.get("total_chars_removed", 0),
            }
            db.upsert_stats(session_id, stats)

            # Persist new tool-level stats
            tool_stats = {
                "total_tool_calls": summary.get("total_tool_results", 0),
                "total_tool_successes": summary.get("total_tool_results", 0),
                "total_tool_failures": summary.get("total_tool_failures", 0),
                "total_tool_errors": summary.get("total_tool_errors", 0),
                "tool_usage_breakdown": summary.get("tool_usage_breakdown", {}),
                "tool_failure_breakdown": summary.get("tool_failure_breakdown", {}),
                "avg_tool_duration_ms": summary.get("avg_tool_duration_ms", 0),
            }
            db.upsert_tool_stats(session_id, tool_stats)

            # Update conversation-level aggregates (conversation may continue)
            if conversation_id:
                db.aggregate_conversation_stats(conversation_id)
                debug_log(f"session_end: updated conversation aggregates for {conversation_id}")
    except Exception as e:
        debug_log(f"session_end SQLite write failed: {e}")

    # Trigger conversation-level summary generation
    if conversation_id:
        _try_generate_conversation_summary(conversation_id)

    # Hermes-style: quick-scan session transcript for immediate learning updates
    quick_scan_start = time.time()
    _try_quick_scan_learning(session_id)
    quick_scan_elapsed = time.time() - quick_scan_start

    # Quick rule-based learning rules decision (sync, within hook timeout)
    # Skip if quick-scan consumed most of the 30s hook budget
    if quick_scan_elapsed < 20:
        _try_quick_learning_rules_decision(session_id)

    # Full LangGraph agent for learning rules (async, detached)
    _try_full_learning_rules_agent()

    print(
        f"[conversation-recorder] Session finalized: {conversation_id} "
        f"({len(session['events'])} events, {len(session['file_edits'])} file edits, "
        f"{summary.get('total_thinking_time_seconds', 0):.1f}s thinking)",
        file=sys.stderr,
    )

    safe_output({"permission": "allow"})

    try:
        from summarizer_daemon import stop_daemon
        stop_daemon()
    except Exception as e:
        debug_log(f"session_end hook daemon shutdown failed: {e}")


if __name__ == "__main__":
    main()
