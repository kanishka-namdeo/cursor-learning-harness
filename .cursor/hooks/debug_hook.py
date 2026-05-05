#!/usr/bin/env python3
"""Debug Hook v3 - Strips double-encoded UTF-8 BOM from stdin."""

import json
import sys
import os
from datetime import datetime

def main():
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
    os.makedirs(log_dir, exist_ok=True)
    debug_file = os.path.join(log_dir, "hooks-debug.log")

    raw_bytes = sys.stdin.buffer.read()

    # Strip double-encoded BOM: c3 af c2 bb c2 bf
    if raw_bytes.startswith(b"\xc3\xaf\xc2\xbb\xc2\xbf"):
        raw_bytes = raw_bytes[5:]

    # Also handle single-encoded BOM: ef bb bf
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        raw_bytes = raw_bytes[3:]

    raw_stdin = raw_bytes.decode("utf-8")

    try:
        payload = json.loads(raw_stdin)
        event_name = payload.get("hook_event_name", "unknown")
        session_id = payload.get("session_id", payload.get("conversation_id", "unknown"))
        parsed = True
    except Exception as e:
        payload = {}
        event_name = "unknown"
        session_id = "unknown"
        parsed = False
        error_msg = str(e)

    timestamp = datetime.now().isoformat()
    cwd = os.getcwd()

    with open(debug_file, "a", encoding="utf-8") as f:
        f.write(f"\n{'=' * 80}\n")
        f.write(f"[{timestamp}] HOOK TRIGGERED: {event_name} (parsed={parsed})\n")
        f.write(f"Session/Conversation ID: {session_id}\n")
        f.write(f"CWD: {cwd}\n")
        f.write(f"Python: {sys.executable}\n")
        if not parsed:
            f.write(f"Parse error: {error_msg}\n")
            f.write(f"First 100 bytes hex: {raw_bytes[:100].hex()}\n")
            f.write(f"First 100 bytes: {repr(raw_stdin[:100])}\n")

    print(json.dumps({"permission": "allow"}))

if __name__ == "__main__":
    main()
