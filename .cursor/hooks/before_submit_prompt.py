#!/usr/bin/env python3
"""
Before Submit Prompt Hook - Record user prompts before they are submitted.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conversation_recorder import ConversationRecorder, read_hook_input, safe_output, capture_common_fields, resolve_session_id


def main():
    payload = read_hook_input()
    conversation_id = resolve_session_id(payload)
    prompt_text = payload.get("prompt", "")
    attachments = payload.get("attachments", [])

    attachment_paths = []
    attachment_types = []
    for att in attachments:
        attachment_paths.append(att.get("file_path", ""))
        attachment_types.append(att.get("type", ""))

    recorder = ConversationRecorder()

    recorder.add_event(
        conversation_id,
        "user_prompt",
        {
            **capture_common_fields(payload),
            "prompt_text": prompt_text,
            "prompt_length": len(prompt_text),
            "attachment_paths": attachment_paths,
            "attachment_types": attachment_types,
            "attachment_count": len(attachments),
        },
    )

    preview = prompt_text[:100] + "..." if len(prompt_text) > 100 else prompt_text
    print(
        f"[conversation-recorder] Recorded user prompt: {conversation_id} "
        f"-> \"{preview}\" ({len(attachments)} attachments)",
        file=sys.stderr,
    )

    safe_output({"permission": "allow"})


if __name__ == "__main__":
    main()
