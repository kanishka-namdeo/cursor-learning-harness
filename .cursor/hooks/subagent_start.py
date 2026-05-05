#!/usr/bin/env python3
"""
Subagent Start Hook - Record subagent (Task tool) spawning.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conversation_recorder import ConversationRecorder, ConversationLinker, read_hook_input, safe_output, get_conversation_id, capture_common_fields, resolve_session_id


def main():
    payload = read_hook_input()
    conversation_id = resolve_session_id(payload)
    subagent_id = payload.get("subagent_id", "")
    subagent_type = payload.get("subagent_type", "")
    task = payload.get("task", "")
    parent_conversation_id = payload.get("parent_conversation_id", "")
    tool_call_id = payload.get("tool_call_id", "")
    subagent_model = payload.get("subagent_model", "")
    is_parallel_worker = payload.get("is_parallel_worker", False)
    git_branch = payload.get("git_branch", "")

    recorder = ConversationRecorder()

    recorder.add_event(
        conversation_id,
        "subagent_start",
        {
            **capture_common_fields(payload),
            "subagent_id": subagent_id,
            "subagent_type": subagent_type,
            "task": task,
            "parent_conversation_id": parent_conversation_id,
            "tool_call_id": tool_call_id,
            "subagent_model": subagent_model,
            "is_parallel_worker": is_parallel_worker,
            "git_branch": git_branch,
        },
    )

    # Link subagent session to parent conversation
    parent_link_tag = ""
    if parent_conversation_id:
        linker = ConversationLinker()
        linker.link_subagent_session(conversation_id, parent_conversation_id)
        parent_link_tag = f" (parent: {parent_conversation_id})"

        # Also record in the session's SQLite: associate session with parent conversation
        from narratives_db import NarrativesDB
        with NarrativesDB() as db:
            db.upsert_session(conversation_id, conversation_id=parent_conversation_id)

    print(
        f"[conversation-recorder] Recorded subagent start: {conversation_id}"
        f" -> {subagent_type} ({task[:60]}){parent_link_tag}",
        file=sys.stderr,
    )

    safe_output({"permission": "allow"})


if __name__ == "__main__":
    main()
