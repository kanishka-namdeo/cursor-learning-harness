#!/usr/bin/env python3
"""
Pre-Compact Hook - Record context window compaction events.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conversation_recorder import ConversationRecorder, read_hook_input, safe_output, get_conversation_id, capture_common_fields


def main():
    payload = read_hook_input()
    conversation_id = get_conversation_id(payload)
    trigger = payload.get("trigger", "")
    context_usage_percent = payload.get("context_usage_percent", 0)
    context_tokens = payload.get("context_tokens", 0)
    context_window_size = payload.get("context_window_size", 0)
    message_count = payload.get("message_count", 0)
    messages_to_compact = payload.get("messages_to_compact", 0)
    is_first_compaction = payload.get("is_first_compaction", False)

    recorder = ConversationRecorder()

    recorder.add_event(
        conversation_id,
        "compaction",
        {
            **capture_common_fields(payload),
            "trigger": trigger,
            "context_usage_percent": context_usage_percent,
            "context_tokens": context_tokens,
            "context_window_size": context_window_size,
            "message_count": message_count,
            "messages_to_compact": messages_to_compact,
            "is_first_compaction": is_first_compaction,
        },
    )

    print(
        f"[conversation-recorder] Recorded compaction: {conversation_id} "
        f"(trigger={trigger}, usage={context_usage_percent}%, "
        f"compacting {messages_to_compact}/{message_count} messages)",
        file=sys.stderr,
    )

    safe_output({"permission": "allow"})


if __name__ == "__main__":
    main()
