#!/usr/bin/env python3
"""
Before Tab File Read Hook - Record Tab inline completion file reads.

Cursor provides: file_path, content
This records metadata and full content (Tab doesn't use attachments like Agent does).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conversation_recorder import ConversationRecorder, read_hook_input, safe_output, capture_common_fields, resolve_session_id


def main():
    payload = read_hook_input()
    conversation_id = resolve_session_id(payload)
    file_path = payload.get("file_path", "")
    content = payload.get("content", "")

    recorder = ConversationRecorder()

    event_data = {
        **capture_common_fields(payload),
        "file_path": file_path,
        "content": content,
        "content_size": len(content),
    }

    recorder.add_event(conversation_id, "tab_file_read", event_data)

    print(
        f"[conversation-recorder] Recorded Tab file read: {conversation_id} "
        f"-> {Path(file_path).name} ({len(content)} chars)",
        file=sys.stderr,
    )

    safe_output({"permission": "allow"})


if __name__ == "__main__":
    main()
