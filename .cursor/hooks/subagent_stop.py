#!/usr/bin/env python3
"""
Subagent Stop Hook - Record subagent (Task tool) completion.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conversation_recorder import ConversationRecorder, read_hook_input, safe_output, capture_common_fields, resolve_session_id


def main():
    payload = read_hook_input()
    conversation_id = resolve_session_id(payload)
    subagent_type = payload.get("subagent_type", "")
    status = payload.get("status", "")
    task = payload.get("task", "")
    description = payload.get("description", "")
    summary = payload.get("summary", "")
    duration_ms = payload.get("duration_ms", 0)
    message_count = payload.get("message_count", 0)
    tool_call_count = payload.get("tool_call_count", 0)
    loop_count = payload.get("loop_count", 0)
    modified_files = payload.get("modified_files", [])
    agent_transcript_path = payload.get("agent_transcript_path", "")

    recorder = ConversationRecorder()

    recorder.add_event(
        conversation_id,
        "subagent_stop",
        {
            **capture_common_fields(payload),
            "subagent_type": subagent_type,
            "status": status,
            "task": task,
            "description": description,
            "summary": summary,
            "duration_ms": duration_ms,
            "message_count": message_count,
            "tool_call_count": tool_call_count,
            "loop_count": loop_count,
            "modified_files": modified_files,
            "agent_transcript_path": agent_transcript_path,
        },
    )

    print(
        f"[conversation-recorder] Recorded subagent stop: {conversation_id} "
        f"<- {subagent_type} ({status}, {duration_ms}ms, {tool_call_count} tool calls)",
        file=sys.stderr,
    )

    safe_output({"permission": "allow"})


if __name__ == "__main__":
    main()
