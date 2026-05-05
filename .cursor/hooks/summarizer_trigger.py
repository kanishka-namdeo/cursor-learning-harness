#!/usr/bin/env python3
"""
Summarizer Trigger Hook - Lightweight hook that writes a trigger file.

Attached to afterAgentResponse and stop events. Instead of spawning the
summarizer_agent.py as a subprocess, it writes a trigger file to the
trigger directory and the daemon picks it up on the next poll cycle.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conversation_recorder import read_hook_input, safe_output, get_conversation_id, debug_log, resolve_session_id
from summarizer_daemon import write_trigger
from summarizer_daemon_launcher import ensure_daemon_running


def main():
    payload = read_hook_input()
    session_id = resolve_session_id(payload)

    if not session_id or session_id == "unknown":
        debug_log(f"[summarizer-trigger] No session_id in payload, skipping")
        safe_output({"permission": "allow"})
        return

    force = "--force" in sys.argv[1:]

    # Ensure daemon is running (starts it if not)
    ensure_daemon_running()

    # Write trigger file (milliseconds, no subprocess overhead)
    write_trigger(session_id, force=force)
    debug_log(f"[summarizer-trigger] Triggered summarizer for {session_id} (force={force})")

    safe_output({"permission": "allow"})


if __name__ == "__main__":
    main()
