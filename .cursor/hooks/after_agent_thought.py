#!/usr/bin/env python3
"""
After Agent Thought Hook - Record agent's reasoning/thinking process.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conversation_recorder import ConversationRecorder, read_hook_input, safe_output, capture_common_fields, resolve_session_id


def main():
    payload = read_hook_input()
    conversation_id = resolve_session_id(payload)
    thought_text = payload.get("text", "")
    duration_ms = payload.get("duration_ms", 0)

    word_count = len(thought_text.split()) if thought_text else 0

    recorder = ConversationRecorder()

    recorder.add_event(
        conversation_id,
        "thought",
        {
            **capture_common_fields(payload),
            "text": thought_text,
            "duration_ms": duration_ms,
            "duration_seconds": duration_ms / 1000 if duration_ms else 0,
            "word_count": word_count,
        },
    )

    print(
        f"[conversation-recorder] Recorded thought: {conversation_id} "
        f"({word_count} words, {duration_ms}ms)",
        file=sys.stderr,
    )

    safe_output({"permission": "allow"})


if __name__ == "__main__":
    main()
