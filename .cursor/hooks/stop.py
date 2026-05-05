#!/usr/bin/env python3
"""
Stop Hook - Record when agent loop ends.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conversation_recorder import ConversationRecorder, read_hook_input, safe_output, get_conversation_id, capture_common_fields, resolve_session_id


def main():
    payload = read_hook_input()
    session_id = get_conversation_id(payload)
    resolved_id = resolve_session_id(payload)
    status = payload.get("status", "unknown")
    loop_count = payload.get("loop_count", 0)
    error_message = payload.get("error_message", "")
    model = payload.get("model", "")

    recorder = ConversationRecorder()
    session = recorder.load_session(resolved_id)
    conversation_id = session.get("conversation_id", "") or resolved_id

    # Record stop event to JSON (for loop count tracking and observability).
    # We intentionally do NOT write to SQLite here -- session_end.py handles
    # the proper session completion with completed_at, duration, and final status.
    # The stop hook fires at the end of every agent loop turn, so per-turn
    # SQLite upserts would be redundant.
    recorder.add_event(
        resolved_id,
        "stop",
        {
            **capture_common_fields(payload),
            "status": status,
            "loop_count": loop_count,
            "error_message": error_message,
        },
    )

    error_note = f", error={error_message[:50]}" if error_message else ""
    print(
        f"[conversation-recorder] Agent loop stopped: session={resolved_id}, "
        f"conversation={conversation_id} "
        f"(status={status}, loops={loop_count}, model={model}{error_note})",
        file=sys.stderr,
    )

    safe_output({"permission": "allow"})


if __name__ == "__main__":
    main()
