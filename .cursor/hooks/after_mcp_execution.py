#!/usr/bin/env python3
"""
After MCP Execution Hook - Record MCP tool results after execution.
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
    result_json = payload.get("result_json", "")
    duration = payload.get("duration", 0)
    tool_use_id = payload.get("tool_use_id", "")
    model = payload.get("model", "")

    recorder = ConversationRecorder()

    recorder.add_event(
        conversation_id,
        "mcp_result",
        {
            **capture_common_fields(payload),
            "tool_name": tool_name,
            "tool_input": str(tool_input),
            "result": str(result_json),
            "result_size": len(str(result_json)),
            "duration_ms": duration,
            "tool_use_id": tool_use_id,
            "phase": "after",
        },
    )

    print(
        f"[conversation-recorder] Recorded MCP result: {conversation_id} "
        f"<- {tool_name} ({duration}ms, {len(str(result_json))} chars, model={model})",
        file=sys.stderr,
    )

    safe_output({"permission": "allow"})


if __name__ == "__main__":
    main()
