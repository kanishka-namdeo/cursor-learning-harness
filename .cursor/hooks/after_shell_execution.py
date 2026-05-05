#!/usr/bin/env python3
"""
After Shell Execution Hook - Record command output after execution.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conversation_recorder import ConversationRecorder, read_hook_input, safe_output, capture_common_fields, resolve_session_id


def main():
    payload = read_hook_input()
    conversation_id = resolve_session_id(payload)
    command = payload.get("command", "")
    output = payload.get("output", "")
    duration = payload.get("duration", 0)
    sandbox = payload.get("sandbox", False)
    exit_code = payload.get("exit_code", None)

    recorder = ConversationRecorder()

    is_success = exit_code == 0 if exit_code is not None else None

    event_data = {
        **capture_common_fields(payload),
        "command": command,
        "output": output,
        "output_size": len(output),
        "duration_ms": duration,
        "sandbox": sandbox,
        "exit_code": exit_code,
        "is_success": is_success,
        "phase": "after",
    }

    recorder.add_event(conversation_id, "shell_result", event_data)

    exit_status = "exit=?" if exit_code is None else f"exit={exit_code}"
    print(
        f"[conversation-recorder] Recorded shell result: {conversation_id} "
        f"<- {command[:80]}{'...' if len(command) > 80 else ''} ({exit_status}, {duration}ms, {len(output)} chars)",
        file=sys.stderr,
    )

    safe_output({"permission": "allow"})


if __name__ == "__main__":
    main()
