#!/usr/bin/env python3
"""
Before Read File Hook - Record which files the agent reads.

Handles both beforeReadFile (agent) and beforeTabFileRead (tab inline completion) events.
Detects the source from payload.hook_event_name and records all reads as "file_read"
with a "source" field to distinguish "agent" vs "tab".
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
    hook_event_name = payload.get("hook_event_name", "")

    source = "tab" if hook_event_name == "beforeTabFileRead" else "agent"

    event_data = {
        **capture_common_fields(payload),
        "file_path": file_path,
        "content": content,
        "content_size": len(content),
        "source": source,
    }

    # Agent reads include attachment metadata; tab reads do not
    if source == "agent":
        attachments = payload.get("attachments", [])
        attachment_types = []
        for att in attachments:
            attachment_types.append({
                "type": att.get("type", ""),
                "file_path": att.get("file_path", ""),
            })
        event_data["attachment_types"] = attachment_types

    recorder = ConversationRecorder()
    recorder.add_event(conversation_id, "file_read", event_data)

    print(
        f"[conversation-recorder] Recorded file read ({source}): {conversation_id} "
        f"-> {Path(file_path).name} ({len(content)} chars)",
        file=sys.stderr,
    )

    safe_output({"permission": "allow"})


if __name__ == "__main__":
    main()
