#!/usr/bin/env python3
"""
Sentiment Arc Trigger Hook - Lightweight hook that writes a trigger file.

Attached to the sessionEnd event. Instead of spawning the sentiment arc
analyzer as a subprocess, it writes a trigger file to the trigger directory
and the summarizer daemon picks it up on the next poll cycle.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conversation_recorder import read_hook_input, safe_output, debug_log, resolve_session_id

STATE_DIR = Path(__file__).parent / "state"
SENTIMENT_ARC_TRIGGER_DIR = STATE_DIR / "sentiment_arc_triggers"


def write_sentiment_trigger(session_id: str):
    """Write a sentiment arc trigger file (idempotent -- overwrites existing)."""
    SENTIMENT_ARC_TRIGGER_DIR.mkdir(parents=True, exist_ok=True)
    trigger_file = SENTIMENT_ARC_TRIGGER_DIR / f"{session_id}.json"
    trigger_file.write_text(json.dumps({
        "session_id": session_id,
        "created_at": time.time(),
    }))


def main():
    payload = read_hook_input()
    session_id = resolve_session_id(payload)

    if not session_id or session_id == "unknown":
        debug_log("[sentiment-arc-trigger] No session_id in payload, skipping")
        safe_output({"permission": "allow"})
        return

    write_sentiment_trigger(session_id)
    debug_log(f"[sentiment-arc-trigger] Triggered sentiment arc analysis for {session_id}")

    safe_output({"permission": "allow"})


if __name__ == "__main__":
    main()
