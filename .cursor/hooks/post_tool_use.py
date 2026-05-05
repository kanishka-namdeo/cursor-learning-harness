#!/usr/bin/env python3
"""
Post Tool Use Hook - Record tool results after successful execution.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conversation_recorder import ConversationRecorder, read_hook_input, safe_output, capture_common_fields, resolve_session_id


def main():
    payload = read_hook_input()
    conversation_id = resolve_session_id(payload)
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})
    tool_output = payload.get("tool_output", "")
    tool_use_id = payload.get("tool_use_id", "")
    cwd = payload.get("cwd", "")
    duration = payload.get("duration", 0)

    recorder = ConversationRecorder()

    recorder.add_event(
        conversation_id,
        "tool_result",
        {
            **capture_common_fields(payload),
            "tool_use_id": tool_use_id,
            "tool_name": tool_name,
            "tool_input": json.dumps(tool_input) if isinstance(tool_input, (dict, list)) else str(tool_input),
            "tool_output": str(tool_output),
            "output_size": len(str(tool_output)),
            "duration_ms": duration,
            "cwd": cwd,
            "phase": "after",
        },
    )

    print(
        f"[conversation-recorder] Recorded tool result: {conversation_id} "
        f"<- {tool_name} ({duration}ms, {len(str(tool_output))} chars)",
        file=sys.stderr,
    )

    safe_output({"permission": "allow"})


if __name__ == "__main__":
    main()
