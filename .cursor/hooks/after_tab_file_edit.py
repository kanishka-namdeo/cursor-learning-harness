#!/usr/bin/env python3
"""
After Tab File Edit Hook - Record Tab inline completion edits.

Cursor provides: file_path, edits[] with old_string, new_string, range, old_line, new_line
This records the full edit detail including range metadata that Agent hooks don't have.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conversation_recorder import ConversationRecorder, read_hook_input, safe_output, capture_common_fields, resolve_session_id


def main():
    payload = read_hook_input()
    conversation_id = resolve_session_id(payload)
    file_path = payload.get("file_path", "")
    edits = payload.get("edits", [])

    recorder = ConversationRecorder()

    for i, edit in enumerate(edits):
        old_string = edit.get("old_string", "")
        new_string = edit.get("new_string", "")

        event_data = {
            **capture_common_fields(payload),
            "file_path": file_path,
            "edit_index": i,
            "chars_added": len(new_string),
            "chars_removed": len(old_string),
            "net_change": len(new_string) - len(old_string),
            "edit_source": "tab",
        }

        # Tab hooks provide range, old_line, new_line metadata
        range_info = edit.get("range", {})
        old_line = edit.get("old_line", "")
        new_line = edit.get("new_line", "")

        if range_info:
            event_data["start_line"] = range_info.get("start_line_number")
            event_data["start_column"] = range_info.get("start_column")
            event_data["end_line"] = range_info.get("end_line_number")
            event_data["end_column"] = range_info.get("end_column")

        if old_line:
            event_data["old_line"] = old_line
        if new_line:
            event_data["new_line"] = new_line

        # Store full content
        event_data["full_old_string"] = old_string
        event_data["full_new_string"] = new_string

        recorder.add_event(conversation_id, "tab_file_edit", event_data)

    total_added = sum(len(e.get("new_string", "")) for e in edits)
    total_removed = sum(len(e.get("old_string", "")) for e in edits)

    print(
        f"[conversation-recorder] Recorded Tab file edits: {conversation_id} "
        f"{len(edits)} edit(s) to {Path(file_path).name} "
        f"(+{total_added}/-{total_removed} chars)",
        file=sys.stderr,
    )

    safe_output({"permission": "allow"})


if __name__ == "__main__":
    main()
