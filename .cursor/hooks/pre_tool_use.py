#!/usr/bin/env python3
"""
Pre Tool Use Hook - Record tool usage before execution.
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
    tool_use_id = payload.get("tool_use_id", "")
    cwd = payload.get("cwd", "")
    agent_message = payload.get("agent_message", "")

    recorder = ConversationRecorder()

    recorder.add_event(
        conversation_id,
        "tool_use",
        {
            **capture_common_fields(payload),
            "tool_name": tool_name,
            "tool_input": json.dumps(tool_input) if isinstance(tool_input, (dict, list)) else str(tool_input),
            "tool_use_id": tool_use_id,
            "cwd": cwd,
            "agent_message": agent_message,
            "phase": "before",
        },
    )

    print(
        f"[conversation-recorder] Recorded tool use: {conversation_id} "
        f"-> {tool_name} ({agent_message[:50]})",
        file=sys.stderr,
    )

    safe_output({"permission": "allow"})


if __name__ == "__main__":
    main()
