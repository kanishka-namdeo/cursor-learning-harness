#!/usr/bin/env python3
"""
Before MCP Execution Hook - Record MCP tool calls before they execute.
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
    model = payload.get("model", "")

    # MCP servers are identified by either url or command
    server_info = ""
    if "url" in payload:
        server_info = payload["url"]
    elif "command" in payload:
        server_info = payload["command"]

    recorder = ConversationRecorder()

    recorder.add_event(
        conversation_id,
        "mcp_call",
        {
            **capture_common_fields(payload),
            "tool_name": tool_name,
            "tool_input": str(tool_input),
            "server_url_or_command": server_info,
            "tool_use_id": tool_use_id,
            "phase": "before",
        },
    )

    print(
        f"[conversation-recorder] Recorded MCP call: {conversation_id} "
        f"-> {tool_name} ({server_info[:60]}, model={model})",
        file=sys.stderr,
    )

    safe_output({"permission": "allow"})


if __name__ == "__main__":
    main()
