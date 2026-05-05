#!/usr/bin/env python3
"""
Before Shell Execution Hook - Record commands before they run.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conversation_recorder import ConversationRecorder, read_hook_input, safe_output, capture_common_fields, truncate, resolve_session_id


def main():
    payload = read_hook_input()
    conversation_id = resolve_session_id(payload)
    command = payload.get("command", "")
    cwd = payload.get("cwd", "")
    sandbox = payload.get("sandbox", False)
    model = payload.get("model", "")
    tool_use_id = payload.get("tool_use_id", "")

    recorder = ConversationRecorder()

    recorder.add_event(
        conversation_id,
        "shell_command",
        {
            **capture_common_fields(payload),
            "command": command,
            "cwd": cwd,
            "sandbox": sandbox,
            "tool_use_id": tool_use_id,
            "phase": "before",
        },
    )

    print(
        f"[conversation-recorder] Recorded shell command: {conversation_id} "
        f"-> {command[:80]}{'...' if len(command) > 80 else ''} (model={model})",
        file=sys.stderr,
    )

    safe_output({"permission": "allow"})


if __name__ == "__main__":
    main()
