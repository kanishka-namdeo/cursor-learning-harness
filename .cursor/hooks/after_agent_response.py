#!/usr/bin/env python3
"""
After Agent Response Hook - Record agent's conversational responses.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conversation_recorder import ConversationRecorder, read_hook_input, safe_output, capture_common_fields, resolve_session_id


def main():
    payload = read_hook_input()
    conversation_id = resolve_session_id(payload)
    response_text = payload.get("text", "")

    word_count = len(response_text.split())
    line_count = response_text.count("\n") + 1 if response_text else 0

    recorder = ConversationRecorder()

    recorder.add_event(
        conversation_id,
        "response",
        {
            **capture_common_fields(payload),
            "text": response_text,
            "word_count": word_count,
            "line_count": line_count,
            "char_count": len(response_text),
        },
    )

    print(
        f"[conversation-recorder] Recorded response: {conversation_id} "
        f"({word_count} words, {line_count} lines)",
        file=sys.stderr,
    )

    safe_output({"permission": "allow"})


if __name__ == "__main__":
    main()
