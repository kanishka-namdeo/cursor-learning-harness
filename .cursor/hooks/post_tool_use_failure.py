#!/usr/bin/env python3
"""
Post Tool Use Failure Hook - Record tool failures.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conversation_recorder import ConversationRecorder, read_hook_input, safe_output, capture_common_fields, resolve_session_id


def main():
    payload = read_hook_input()
    conversation_id = resolve_session_id(payload)
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})
    tool_use_id = payload.get("tool_use_id", "")
    cwd = payload.get("cwd", "")
    error_message = payload.get("error_message", "")
    failure_type = payload.get("failure_type", "error")
    duration = payload.get("duration", 0)
    is_interrupt = payload.get("is_interrupt", False)

    recorder = ConversationRecorder()

    recorder.add_event(
        conversation_id,
        "tool_failure",
        {
            **capture_common_fields(payload),
            "tool_use_id": tool_use_id,
            "tool_name": tool_name,
            "tool_input": str(tool_input),
            "error_message": error_message,
            "failure_type": failure_type,
            "duration_ms": duration,
            "is_interrupt": is_interrupt,
            "cwd": cwd,
        },
    )

    print(
        f"[conversation-recorder] Recorded tool failure: {conversation_id} "
        f"x {tool_name} ({failure_type}, {duration}ms)",
        file=sys.stderr,
    )

    safe_output({"permission": "allow"})


if __name__ == "__main__":
    main()
