#!/usr/bin/env python3
"""
Summarize Sessions CLI - Manual/on-demand session summarization.

Usage:
    python summarize_sessions.py                    # Summarize all sessions lacking a narrative
    python summarize_sessions.py --structured       # Summarize all sessions lacking structured output
    python summarize_sessions.py <session_id>       # Summarize specific session
    python summarize_sessions.py --regenerate <id>  # Force full regenerate for a session
    python summarize_sessions.py --all              # Regenerate ALL sessions
    python summarize_sessions.py --status           # Show summary status for all sessions
    python summarize_sessions.py --show-structured <session_id>  # Display structured summary
    python summarize_sessions.py --validate-structured  # Validate all structured summaries
    python summarize_sessions.py --merge-conversation <conv_id>  # Merge structured summaries
    python summarize_sessions.py --summarize-conversation <conv_id>  # Generate conversation-level summary
    python summarize_sessions.py --summarize-all-conversations  # Summarize all conversations lacking a summary
    python summarize_sessions.py --show-conversation <conv_id>  # Display conversation narrative + structured summary
    python summarize_sessions.py --list-conversations-with-stats  # List conversations with session counts, summary status
"""

import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conversation_recorder import ConversationRecorder

HOOKS_DIR = Path(__file__).parent.resolve()
STATE_DIR = HOOKS_DIR / "state"
SESSIONS_DIR = STATE_DIR / "sessions"
INDEX_FILE = STATE_DIR / "sessions_index.json"


def load_session_ids():
    """Load all session IDs from the index file."""
    if not INDEX_FILE.exists():
        return []
    try:
        index = json.loads(INDEX_FILE.read_text())
        return list(index.keys())
    except (json.JSONDecodeError, OSError):
        return []


def get_session_status():
    """Get summary status for all sessions."""
    # Load narratives from SQLite once
    try:
        from narratives_db import NarrativesDB
        with NarrativesDB() as db:
            db_narratives = {row["session_id"]: bool(row.get("narrative", "").strip())
                            for row in db.list_sessions()
                            if db.get_narrative(row["session_id"])}
    except Exception:
        db_narratives = {}

    statuses = []
    for sid in load_session_ids():
        session_file = SESSIONS_DIR / sid / "session.json"
        if not session_file.exists():
            statuses.append({"session_id": sid, "status": "missing_file"})
            continue

        try:
            session = json.loads(session_file.read_text())
            summary = session.get("summary", {})
            has_narrative = sid in db_narratives
            event_count = len(session.get("events", []))
            statuses.append({
                "session_id": sid[:12] + "...",
                "has_narrative": has_narrative,
                "event_count": event_count,
                "strategy": summary.get("strategy", ""),
                "generated_at": summary.get("generated_at", ""),
            })
        except (json.JSONDecodeError, OSError):
            statuses.append({"session_id": sid[:12] + "...", "status": "corrupted"})

    return statuses


def show_status():
    """Display summary status for all sessions."""
    statuses = get_session_status()

    if not statuses:
        print("No sessions found.")
        return

    print(f"\n{'Session ID':<40} {'Events':<8} {'Narrative':<10} {'Strategy':<18} {'Generated At'}")
    print("-" * 120)

    for s in statuses:
        if "status" in s:
            print(f"{s['session_id']:<40} {'':<8} {s['status']:<10}")
        else:
            print(
                f"{s['session_id']:<40} "
                f"{s['event_count']:<8} "
                f"{'Yes' if s['has_narrative'] else 'No':<10} "
                f"{s['strategy']:<18} "
                f"{s['generated_at']}"
            )

    total = len(statuses)
    with_narrative = sum(1 for s in statuses if isinstance(s, dict) and s.get("has_narrative"))
    print(f"\nTotal: {total} sessions, {with_narrative} with narrative summary\n")


def summarize_session(session_id: str, force_regenerate: bool = False, structured_only: bool = False):
    """Summarize a single session by invoking the graph directly."""
    from summarizer_agent import acquire_lock, release_lock, graph

    if not acquire_lock(session_id):
        print(f"Session {session_id}: already being summarized, skipping", file=sys.stderr)
        return False

    try:
        session_file = SESSIONS_DIR / session_id / "session.json"
        if not session_file.exists():
            print(f"Session {session_id}: file not found, skipping", file=sys.stderr)
            return False

        try:
            session = json.loads(session_file.read_text())
        except json.JSONDecodeError:
            print(f"Session {session_id}: corrupted JSON, skipping", file=sys.stderr)
            return False

        events = session.get("events", [])
        if not events:
            print(f"Session {session_id}: no events to summarize", file=sys.stderr)
            return False

        action_label = "structured" if structured_only else "summarizing"
        print(f"{action_label.capitalize()} session {session_id[:12]}... ", end="", flush=True)

        result = graph.invoke({
            "session_id": session_id,
            "force": True,
            "regenerate": force_regenerate,
            "structured_only": structured_only,
        })

        strategy = result.get("strategy", "unknown")
        if result.get("error"):
            print(f"ERROR: {result['error']}")
            return False

        has_structured = bool(result.get("structured_summary"))
        has_narrative = bool(result.get("narrative_summary"))
        print(f"Done (strategy={strategy}, events={len(events)}, "
              f"structured={'yes' if has_structured else 'no'}, "
              f"narrative={'yes' if has_narrative else 'no'})")
        return True

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return False
    finally:
        release_lock(session_id)


def main():
    args = sys.argv[1:]

    # --structured: structured-only mode for default and --all
    structured_only = "--structured" in args

    if "--show-structured" in args:
        idx = args.index("--show-structured")
        if idx + 1 < len(args):
            show_structured_summary(args[idx + 1])
        else:
            print("Usage: summarize_sessions.py --show-structured <session_id>", file=sys.stderr)
            sys.exit(1)
        return

    if "--validate-structured" in args:
        validate_all_structured_summaries()
        return

    if "--merge-conversation" in args:
        idx = args.index("--merge-conversation")
        if idx + 1 < len(args):
            merge_conversation_structured(args[idx + 1])
        else:
            print("Usage: summarize_sessions.py --merge-conversation <conversation_id>", file=sys.stderr)
            sys.exit(1)
        return

    if "--summarize-conversation" in args:
        idx = args.index("--summarize-conversation")
        if idx + 1 < len(args):
            force = "--force" in args
            summarize_conversation(args[idx + 1], force=force)
        else:
            print("Usage: summarize_sessions.py --summarize-conversation <conversation_id> [--force]", file=sys.stderr)
            sys.exit(1)
        return

    if "--summarize-all-conversations" in args:
        force = "--force" in args
        summarize_all_conversations(force=force)
        return

    if "--show-conversation" in args:
        idx = args.index("--show-conversation")
        if idx + 1 < len(args):
            show_conversation(args[idx + 1])
        else:
            print("Usage: summarize_sessions.py --show-conversation <conversation_id>", file=sys.stderr)
            sys.exit(1)
        return

    if "--list-conversations-with-stats" in args:
        list_conversations_with_stats()
        return

    if not args:
        # Default: summarize all sessions without a narrative (or structured) in SQLite
        mode_label = "structured" if structured_only else "narrative"
        print(f"Summarizing all sessions without a {mode_label} summary...\n")
        session_ids = load_session_ids()
        count = 0

        # Pre-load SQLite state for checking
        try:
            from narratives_db import NarrativesDB
            with NarrativesDB() as db:
                sessions_in_db = {row["session_id"]: row for row in db.list_sessions()}
                narrative_sids = {sid for sid in sessions_in_db if db.get_narrative(sid)}
                structured_sids = {sid for sid in sessions_in_db if db.get_structured_summary(sid)}
        except Exception:
            narrative_sids = set()
            structured_sids = set()

        for sid in session_ids:
            session_file = SESSIONS_DIR / sid / "session.json"
            if not session_file.exists():
                continue

            try:
                needs_summary = False
                if structured_only:
                    needs_summary = sid not in structured_sids
                else:
                    needs_summary = sid not in narrative_sids

                if needs_summary:
                    summarize_session(sid, structured_only=structured_only)
                    count += 1
            except (json.JSONDecodeError, OSError):
                continue

        print(f"\nSummarized {count} sessions.")

    elif "--status" in args:
        show_status()

    elif "--all" in args:
        action_label = "structured" if structured_only else "full"
        print(f"Regenerating ALL session {action_label} summaries...\n")
        session_ids = load_session_ids()
        count = 0

        for sid in session_ids:
            if summarize_session(sid, force_regenerate=True, structured_only=structured_only):
                count += 1

        print(f"\nRegenerated {count}/{len(session_ids)} sessions.")

    elif "--regenerate" in args:
        idx = args.index("--regenerate")
        if idx + 1 < len(args):
            session_id = args[idx + 1]
            summarize_session(session_id, force_regenerate=True, structured_only=structured_only)
        else:
            print("Usage: summarize_sessions.py --regenerate <session_id> [--structured]", file=sys.stderr)
            sys.exit(1)

    else:
        # Treat first arg as session_id
        session_id = args[0]
        summarize_session(session_id, structured_only=structured_only)


def show_structured_summary(session_id: str):
    """Display structured summary for a session."""
    from narratives_db import NarrativesDB

    # SQLite only — summaries are no longer stored in JSON files
    with NarrativesDB() as db:
        result = db.get_structured_summary(session_id)
        if result and result.get("structured_data"):
            print(f"\nStructured Summary for {session_id[:12]}...\n")
            print(json.dumps(result["structured_data"], indent=2))
        else:
            print(f"No structured summary found for session: {session_id[:12]}...")


def validate_all_structured_summaries():
    """Run verification on all existing structured summaries."""
    from narratives_db import NarrativesDB
    from conversation_recorder import ConversationRecorder

    print("Validating all structured summaries...\n")
    session_ids = load_session_ids()
    valid_count = 0
    warning_count = 0
    error_count = 0

    with NarrativesDB() as db:
        for sid in session_ids:
            session_file = SESSIONS_DIR / sid / "session.json"
            if not session_file.exists():
                continue

            try:
                session = json.loads(session_file.read_text())
            except (json.JSONDecodeError, OSError):
                error_count += 1
                continue

            # Read structured summary from SQLite
            result = db.get_structured_summary(sid)
            if not result or not result.get("structured_data"):
                continue

            structured = result["structured_data"]
            events = session.get("events", [])
            # Simple verification: check files_modified against actual edits
            actual_files = set()
            for ev in events:
                if ev.get("type") == "file_edit":
                    fp = ev.get("file_path", "")
                    if fp:
                        actual_files.add(fp)

            warnings = []
            for f in structured.get("files_modified", []):
                if f and f not in actual_files:
                    warnings.append(f"file '{f}' not in actual edits")

            if warnings:
                warning_count += 1
                print(f"  {sid[:12]}... WARNINGS: {', '.join(warnings)}")
            else:
                valid_count += 1

    total = valid_count + warning_count + error_count
    print(f"\nValidation complete: {valid_count} valid, {warning_count} warnings, {error_count} errors (out of {total})")


def merge_conversation_structured(conversation_id: str):
    """Merge structured summaries across all sessions in a conversation."""
    from narratives_db import NarrativesDB

    with NarrativesDB() as db:
        merged = db.merge_structured_summaries(conversation_id)

    if not merged:
        print(f"No structured summaries found for conversation: {conversation_id[:12]}...")
        return

    print(f"\nMerged Structured Summary for conversation {conversation_id[:12]}...")
    print(f"  Merged from {len(merged.get('_merged_from_sessions', []))} sessions\n")
    print(json.dumps(merged, indent=2))


def summarize_conversation(conversation_id: str, force: bool = False):
    """Generate a conversation-level summary."""
    summarizer_script = Path(__file__).parent / "conversation_summarizer_agent.py"
    if not summarizer_script.exists():
        print(f"Conversation summarizer script not found at {summarizer_script}", file=sys.stderr)
        return False

    import subprocess

    cmd = [sys.executable, str(summarizer_script), conversation_id]
    if force:
        cmd.append("--force")

    print(f"Summarizing conversation {conversation_id[:12]}... ", end="", flush=True)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            print("Done")
            if result.stderr:
                for line in result.stderr.strip().split("\n"):
                    print(f"  {line}")
            return True
        else:
            print(f"Failed (exit code {result.returncode})")
            if result.stderr:
                print(f"  {result.stderr[:200]}")
            return False
    except subprocess.TimeoutExpired:
        print("Timeout (120s)")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False


def summarize_all_conversations(force: bool = False):
    """Summarize all conversations lacking a summary."""
    from narratives_db import NarrativesDB

    print("Checking conversations for missing summaries...\n")

    with NarrativesDB() as db:
        conversations = db.list_conversations()

    if not conversations:
        print("No conversations found.")
        return

    count = 0
    total = 0
    for conv in conversations:
        conv_id = conv["conversation_id"]
        total += 1

        # Check if already has a conversation narrative
        try:
            with NarrativesDB() as db:
                existing = db.get_conversation_narrative(conv_id)
                if existing and existing.get("narrative", "").strip() and not force:
                    print(f"  {conv_id[:12]}... — already has summary (skip)")
                    continue
        except Exception:
            pass

        if summarize_conversation(conv_id, force=force):
            count += 1

    print(f"\nSummarized {count}/{total} conversations.")


def show_conversation(conversation_id: str):
    """Display conversation narrative and structured summary."""
    from narratives_db import NarrativesDB

    print(f"\nConversation: {conversation_id}\n")

    # Show sessions
    with NarrativesDB() as db:
        sessions = db.get_sessions_by_conversation(conversation_id)
        stats = db.aggregate_conversation_stats(conversation_id)
        conv_narr = db.get_conversation_narrative(conversation_id)
        conv_struct = db.get_conversation_structured(conversation_id)

    print(f"  Sessions: {stats.get('session_count', len(sessions))} "
          f"({stats.get('main_session_count', '?')} main, "
          f"{stats.get('subagent_session_count', '?')} subagent)")
    print(f"  Total events: {stats.get('total_events', 0)}")
    print(f"  Total file edits: {stats.get('total_file_edits', 0)}")
    print()

    # Show sessions list
    print("Sessions:")
    for s in sessions:
        print(f"  {s['session_id'][:12]}...  status={s['status']}  created={s['created_at']}")
    print()

    # Show narrative
    if conv_narr:
        print("Conversation Narrative Summary:")
        print("-" * 60)
        print(conv_narr.get("narrative", ""))
        print("-" * 60)
        print()
    else:
        print("No conversation narrative summary found.")
        print()

    # Show structured
    if conv_struct:
        print("Conversation Structured Summary:")
        print("-" * 60)
        data = conv_struct.get("structured_data", {})
        print(json.dumps(data, indent=2))
        print("-" * 60)
    else:
        print("No conversation structured summary found.")


def list_conversations_with_stats():
    """List conversations with session counts and summary status."""
    from narratives_db import NarrativesDB

    with NarrativesDB() as db:
        conversations = db.list_conversations()

    if not conversations:
        print("No conversations found.")
        return

    print(f"\n{'Conversation ID':<40} {'Sessions':<10} {'Status':<15} {'Summary':<10} {'Generated At'}")
    print("-" * 120)

    for conv in conversations:
        conv_id = conv["conversation_id"]
        status = conv.get("status", "unknown")

        try:
            with NarrativesDB() as db:
                sessions = db.get_sessions_by_conversation(conv_id)
                session_count = len(sessions)
                narr = db.get_conversation_narrative(conv_id)
        except Exception:
            session_count = "?"
            narr = None

        has_summary = "Yes" if (narr and narr.get("narrative", "").strip()) else "No"
        generated = narr.get("generated_at", "") if narr else ""
        status_str = status or "unknown"

        print(f"{conv_id[:38]:<40} {session_count:<10} {status_str:<15} {has_summary:<10} {generated}")

    print()


if __name__ == "__main__":
    main()
