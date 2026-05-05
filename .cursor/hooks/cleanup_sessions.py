#!/usr/bin/env python3
"""
Session Cleanup Utility - Remove old sessions to prevent unbounded disk growth.

Usage:
    python cleanup_sessions.py                  # Dry run (show what would be removed)
    python cleanup_sessions.py --apply          # Actually delete old sessions
    python cleanup_sessions.py --days 7         # Remove sessions older than 7 days
    python cleanup_sessions.py --empty-only     # Remove sessions with no events
    python cleanup_sessions.py --size           # Show current disk usage
"""

import json
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

HOOKS_DIR = Path(__file__).parent.resolve()
STATE_DIR = HOOKS_DIR / "state"
SESSIONS_DIR = STATE_DIR / "sessions"
INDEX_FILE = STATE_DIR / "sessions_index.json"
LINKS_FILE = STATE_DIR / "conversation_links.json"
DB_PATH = STATE_DIR / "narratives.db"


def get_storage_usage():
    """Calculate total storage used by sessions in MB."""
    total_size = 0
    if SESSIONS_DIR.exists():
        for f in SESSIONS_DIR.rglob("*"):
            if f.is_file():
                total_size += f.stat().st_size
    return total_size / (1024 * 1024)


def load_index():
    """Load the sessions index."""
    if INDEX_FILE.exists():
        try:
            return json.loads(INDEX_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_index(index):
    """Save the sessions index."""
    INDEX_FILE.write_text(json.dumps(index, indent=2))


def load_links():
    """Load conversation links."""
    if LINKS_FILE.exists():
        try:
            return json.loads(LINKS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_links(links):
    """Save conversation links."""
    LINKS_FILE.write_text(json.dumps(links, indent=2))


def cleanup_old_sessions(max_age_days=30, apply=False):
    """Remove sessions older than max_age_days."""
    index = load_index()
    links = load_links()
    cutoff = datetime.now() - timedelta(days=max_age_days)

    to_remove = []
    for session_id, metadata in index.items():
        created_at = metadata.get("created_at", "")
        if not created_at:
            continue
        try:
            created_dt = datetime.fromisoformat(created_at)
            if created_dt < cutoff:
                to_remove.append(session_id)
        except ValueError:
            continue

    if not to_remove:
        print(f"No sessions older than {max_age_days} days found.")
        return

    action = "Would delete" if not apply else "Deleting"
    print(f"\n{action} {len(to_remove)} sessions older than {max_age_days} days:")

    for sid in sorted(to_remove):
        session_dir = SESSIONS_DIR / sid
        if session_dir.exists():
            size = sum(f.stat().st_size for f in session_dir.rglob("*") if f.is_file())
            print(f"  {sid[:12]}... ({size / 1024:.1f} KB, created={index[sid].get('created_at', '?')})")

            if apply:
                shutil.rmtree(session_dir)

            # Clean up from links file
            if sid in links:
                del links[sid]

        # Remove from index
        del index[sid]

    if apply:
        save_index(index)
        save_links(links)
        print(f"\nDone. {len(to_remove)} sessions removed.")
        print(f"Current disk usage: {get_storage_usage():.2f} MB")
    else:
        print(f"\nAdd --apply to actually delete these sessions.")


def cleanup_empty_sessions(apply=False):
    """Remove sessions with no events."""
    index = load_index()
    links = load_links()

    to_remove = []
    for session_id, metadata in index.items():
        if metadata.get("event_count", 0) == 0:
            to_remove.append(session_id)

    if not to_remove:
        print("No empty sessions found.")
        return

    action = "Would delete" if not apply else "Deleting"
    print(f"\n{action} {len(to_remove)} empty sessions:")

    for sid in sorted(to_remove):
        session_dir = SESSIONS_DIR / sid
        print(f"  {sid[:12]}...")

        if apply and session_dir.exists():
            shutil.rmtree(session_dir)

        if sid in links:
            del links[sid]
        del index[sid]

    if apply:
        save_index(index)
        save_links(links)
        print(f"\nDone. {len(to_remove)} empty sessions removed.")


def cleanup_db_orphans(apply=False):
    """Remove session directories that have no corresponding SQLite row."""
    try:
        from narratives_db import NarrativesDB

        with NarrativesDB() as db:
            db_sessions = {s["session_id"] for s in db.list_sessions()}
    except Exception:
        print("Could not open narratives.db, skipping orphan cleanup.")
        return

    to_remove = []
    if SESSIONS_DIR.exists():
        for session_dir in SESSIONS_DIR.iterdir():
            if session_dir.is_dir() and session_dir.name not in db_sessions:
                session_file = session_dir / "session.json"
                if not session_file.exists():
                    to_remove.append(session_dir.name)

    if not to_remove:
        print("No orphan session directories found.")
        return

    action = "Would delete" if not apply else "Deleting"
    print(f"\n{action} {len(to_remove)} orphan session directories (no SQLite row):")

    for sid in sorted(to_remove):
        print(f"  {sid[:12]}...")

        if apply:
            shutil.rmtree(SESSIONS_DIR / sid)


def main():
    args = sys.argv[1:]
    apply = "--apply" in args
    days = 30
    empty_only = "--empty-only" in args

    # Parse --days
    if "--days" in args:
        idx = args.index("--days")
        if idx + 1 < len(args):
            try:
                days = int(args[idx + 1])
            except ValueError:
                print(f"Invalid --days value: {args[idx + 1]}")
                sys.exit(1)

    if "--size" in args:
        print(f"Current session storage: {get_storage_usage():.2f} MB")
        return

    if not apply:
        print("DRY RUN MODE - no changes will be made")
        print("Add --apply to actually delete sessions\n")

    if empty_only:
        cleanup_empty_sessions(apply=apply)
    else:
        cleanup_old_sessions(max_age_days=days, apply=apply)

    if not empty_only:
        cleanup_empty_sessions(apply=apply)
        cleanup_db_orphans(apply=apply)


if __name__ == "__main__":
    main()
