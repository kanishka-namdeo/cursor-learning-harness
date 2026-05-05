#!/usr/bin/env python3
"""
Conversation Recording Viewer - CLI tool to review recorded agent conversations.

Usage:
    python .cursor/hooks/view.py                    # List all sessions
    python .cursor/hooks/view.py <session_id>       # View session details
    python .cursor/hooks/view.py --search "query"   # Search across sessions
    python .cursor/hooks/view.py --stats            # Show aggregate statistics
    python .cursor/hooks/view.py --recent 5         # Show last N sessions
    python .cursor/hooks/view.py --db               # List sessions from SQLite DB
    python .cursor/hooks/view.py --db --search "q"  # Search narratives in SQLite DB
    python .cursor/hooks/view.py --db --stats       # Show DB-level statistics
    python .cursor/hooks/view.py --conversations    # List conversations with session counts
    python .cursor/hooks/view.py --get-conversation <conv_id>  # Show sessions + stats + timeline
    python .cursor/hooks/view.py --aggregate-stats <conv_id>   # Show rolled-up conversation stats
"""

import json
import sys
import argparse
from datetime import datetime
from pathlib import Path

HOOKS_DIR = Path(__file__).parent.resolve()
STATE_DIR = HOOKS_DIR / "state"
SESSIONS_DIR = STATE_DIR / "sessions"
INDEX_FILE = STATE_DIR / "sessions_index.json"

sys.path.insert(0, str(HOOKS_DIR))


def list_sessions(recent=None):
    """List all recorded sessions."""
    if not INDEX_FILE.exists():
        print("No recorded sessions found.")
        return

    index = json.loads(INDEX_FILE.read_text())
    sessions = sorted(
        index.items(),
        key=lambda x: x[1].get("last_updated", ""),
        reverse=True,
    )

    if recent:
        sessions = sessions[:recent]

    print(f"\n{'=' * 80}")
    print(f"Recorded Agent Conversations ({len(index)} total, showing {len(sessions)})")
    print(f"{'=' * 80}\n")

    for session_id, info in sessions:
        created = info.get("created_at", "unknown")
        events = info.get("event_count", 0)
        edits = info.get("file_edits", 0)
        responses = info.get("responses", 0)
        thoughts = info.get("thoughts", 0)

        print(f"Session: {session_id}")
        print(f"  Created: {created}")
        print(f"  Events: {events} | Responses: {responses} | Thoughts: {thoughts} | File Edits: {edits}")
        print()


def view_session(session_id):
    """View detailed information about a specific session."""
    session_file = SESSIONS_DIR / session_id / "session.json"
    if not session_file.exists():
        print(f"Session not found: {session_id}")
        return

    session_text = session_file.read_text(encoding="utf-8")
    try:
        session = json.loads(session_text)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error reading session {session_id}: {e}")
        return

    print(f"\n{'=' * 80}")
    print(f"Session: {session_id}")
    print(f"Created: {session.get('created_at')}")
    print(f"Last Updated: {session.get('last_updated')}")
    print(f"{'=' * 80}\n")

    # Print summary if available
    if session.get("summary"):
        print("## Session Summary ##")
        summary = session["summary"]
        print(f"Duration: {summary.get('session_duration_seconds', 0):.1f}s")
        print(f"Total Events: {summary.get('total_events', 0)}")
        print(f"Agent Responses: {summary.get('total_responses', 0)}")
        print(f"Agent Thoughts: {summary.get('total_thoughts', 0)}")
        print(f"Thinking Time: {summary.get('total_thinking_time_seconds', 0):.1f}s")
        print(f"File Edits: {summary.get('total_file_edits', 0)}")
        print(f"Files Modified: {', '.join(summary.get('unique_files_edited', []))}")
        print(f"Tool Uses: {summary.get('total_tool_uses', 0)}")
        print()

    # Print timeline of events
    print("## Event Timeline ##")
    for i, event in enumerate(session.get("events", [])):
        timestamp = event.get("timestamp", "")
        event_type = event.get("type", "unknown")
        model = event.get("model", "")
        generation_id = event.get("generation_id", "")
        hook_event_name = event.get("hook_event_name", "")
        model_tag = f" | model={model}" if model else ""
        gen_tag = f" | gen={generation_id[:8]}..." if generation_id else ""
        hook_tag = f" | hook={hook_event_name}" if hook_event_name else ""
        detail_tags = f"{model_tag}{gen_tag}{hook_tag}"
        print(f"[{i + 1}] {timestamp} - {event_type}{detail_tags}")

        if event_type == "response":
            preview = event.get("text", "")[:100]
            print(f"    Response: {preview}{'...' if len(event.get('text', '')) > 100 else ''}")
        elif event_type == "thought":
            duration = event.get("duration_ms", 0)
            print(f"    Thought: {event.get('word_count', 0)} words ({duration}ms)")
        elif event_type == "file_edit":
            file_path = event.get("file_path", "")
            print(f"    Edit: {file_path} (+{event.get('chars_added', 0)}/-{event.get('chars_removed', 0)} chars)")
        elif event_type == "shell_command":
            command = event.get("command", "")[:80]
            tool_use_id = event.get("tool_use_id", "")
            corr_tag = f" | id={tool_use_id}" if tool_use_id else ""
            print(f"    Command: {command}{corr_tag}")
        elif event_type == "tool_use":
            tool_name = event.get("tool_name", "")
            agent_msg = event.get("agent_message", "")[:50]
            print(f"    Tool: {tool_name} - {agent_msg}")
        elif event_type == "tool_result":
            tool_name = event.get("tool_name", "")
            duration = event.get("duration_ms", 0)
            output = event.get("tool_output", "")[:100]
            print(f"    Tool: {tool_name} ({duration}ms) -> {output}")
        elif event_type == "tool_failure":
            tool_name = event.get("tool_name", "")
            failure_type = event.get("failure_type", "")
            error = event.get("error_message", "")[:100]
            print(f"    FAILED: {tool_name} ({failure_type}) - {error}")
        elif event_type == "shell_result":
            command = event.get("command", "")[:80]
            exit_code = event.get("exit_code")
            is_success = event.get("is_success")
            model = event.get("model", "")
            exit_status = "exit=?" if exit_code is None else f"exit={exit_code}{' ✓' if is_success else ' ✗'}"
            model_tag = f", model={model}" if model else ""
            output = event.get("output", "")[:80]
            print(f"    Command: {command} ({exit_status}{model_tag})")
            if output:
                print(f"    Output: {output}")
        elif event_type == "user_prompt":
            prompt = event.get("prompt_text", "")[:120]
            print(f"    Prompt: {prompt}")
        elif event_type == "file_read":
            file_path = event.get("file_path", "")
            print(f"    Read: {file_path}")
        elif event_type == "mcp_call":
            tool_name = event.get("tool_name", "")
            print(f"    MCP Call: {tool_name}")
        elif event_type == "mcp_result":
            tool_name = event.get("tool_name", "")
            duration = event.get("duration_ms", 0)
            print(f"    MCP Result: {tool_name} ({duration}ms)")
        elif event_type == "subagent_start":
            subagent_type = event.get("subagent_type", "")
            task = event.get("task", "")[:80]
            print(f"    Subagent: {subagent_type} - {task}")
        elif event_type == "subagent_stop":
            status = event.get("status", "")
            summary = event.get("summary", "")[:80]
            print(f"    Subagent stopped: {status} - {summary}")
        elif event_type == "compaction":
            trigger = event.get("trigger", "")
            usage = event.get("context_usage_percent", 0)
            print(f"    Compaction: trigger={trigger}, {usage}% used")

        print()


def search_sessions(query):
    """Search across all recorded sessions."""
    results = []
    if not SESSIONS_DIR.exists():
        print("No recorded sessions found.")
        return

    for session_file in SESSIONS_DIR.glob("*/session.json"):
        try:
            session = json.loads(session_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: skipping corrupted file {session_file}: {e}")
            continue
        for i, event in enumerate(session.get("events", [])):
            event_str = json.dumps(event).lower()
            if query.lower() in event_str:
                results.append({
                    "session_id": session["session_id"],
                    "event_index": i,
                    "event_type": event.get("type", ""),
                    "timestamp": event.get("timestamp", ""),
                    "match_preview": get_match_preview(event, query),
                })

    print(f"\n{'=' * 80}")
    print(f"Search Results for: '{query}' ({len(results)} matches)")
    print(f"{'=' * 80}\n")

    for r in results:
        print(f"Session: {r['session_id']}")
        print(f"  Time: {r['timestamp']} | Type: {r['event_type']}")
        print(f"  Preview: {r['match_preview']}")
        print()


def get_match_preview(event, query):
    """Get a preview of the event with the query highlighted."""
    event_text = json.dumps(event)
    idx = event_text.lower().find(query.lower())
    if idx >= 0:
        start = max(0, idx - 50)
        end = min(len(event_text), idx + len(query) + 50)
        return f"...{event_text[start:end]}..."
    return event_text[:100]


def show_stats():
    """Show aggregate statistics across all sessions."""
    if not INDEX_FILE.exists():
        print("No recorded sessions found.")
        return

    index = json.loads(INDEX_FILE.read_text())

    total_sessions = len(index)
    total_events = sum(s.get("event_count", 0) for s in index.values())
    total_responses = sum(s.get("responses", 0) for s in index.values())
    total_thoughts = sum(s.get("thoughts", 0) for s in index.values())
    total_edits = sum(s.get("file_edits", 0) for s in index.values())

    print(f"\n{'=' * 80}")
    print("Aggregate Conversation Statistics")
    print(f"{'=' * 80}\n")
    print(f"Total Sessions: {total_sessions}")
    print(f"Total Events: {total_events}")
    print(f"Total Agent Responses: {total_responses}")
    print(f"Total Agent Thoughts: {total_thoughts}")
    print(f"Total File Edits: {total_edits}")

    if total_sessions > 0:
        print(f"\nAverages per Session:")
        print(f"  Events: {total_events / total_sessions:.1f}")
        print(f"  Responses: {total_responses / total_sessions:.1f}")
        print(f"  Thoughts: {total_thoughts / total_sessions:.1f}")
        print(f"  File Edits: {total_edits / total_sessions:.1f}")


# -- SQLite-backed functions (--db mode) -----------------------------------

def db_list_sessions(recent=None):
    """List sessions from SQLite DB."""
    from narratives_db import NarrativesDB

    with NarrativesDB() as db:
        sessions = db.list_sessions(limit=recent)

    if not sessions:
        print("No sessions in SQLite DB. Run backfill first.")
        return

    print(f"\n{'=' * 80}")
    print(f"Agent Conversations from SQLite DB ({len(sessions)} sessions)")
    print(f"{'=' * 80}\n")

    for s in sessions:
        print(f"Session: {s['session_id']}")
        print(f"  Created: {s['created_at']}")
        print(f"  Status: {s['status']} | Duration: {s['duration_ms']}ms")
        print()


def db_view_session(session_id):
    """View a session's narrative and stats from SQLite DB."""
    from narratives_db import NarrativesDB

    with NarrativesDB() as db:
        session = db.list_sessions()
        session_row = next((s for s in session if s['session_id'] == session_id), None)
        narrative = db.get_narrative(session_id)

    if session_row is None:
        print(f"Session not found in DB: {session_id}")
        return

    print(f"\n{'=' * 80}")
    print(f"Session: {session_id}")
    print(f"Created: {session_row['created_at']}")
    print(f"Status: {session_row['status']}")
    print(f"Duration: {session_row['duration_ms']}ms")
    print(f"{'=' * 80}\n")

    if narrative:
        print("## Narrative ##")
        print(f"Generated: {narrative['generated_at']}")
        print(f"Strategy: {narrative['strategy']}")
        print(f"Words: {narrative['word_count']}")
        print(f"\n{narrative['narrative']}\n")
    else:
        print("(No narrative available)")


def db_search_sessions(query):
    """Search narratives in SQLite DB."""
    from narratives_db import NarrativesDB

    with NarrativesDB() as db:
        results = db.search_narratives(query)

    if not results:
        print(f"No narratives matching '{query}'")
        return

    print(f"\n{'=' * 80}")
    print(f"Search Results for: '{query}' ({len(results)} matches)")
    print(f"{'=' * 80}\n")

    for r in results:
        print(f"Session: {r['session_id']}")
        print(f"  Generated: {r['generated_at']} | Words: {r['word_count']}")
        text = r["narrative"]
        preview = text[:200] + "..." if len(text) > 200 else text
        print(f"  Preview: {preview}")
        print()


def db_show_stats():
    """Show aggregate statistics from SQLite DB."""
    from narratives_db import NarrativesDB

    with NarrativesDB() as db:
        sessions = db.list_sessions()

    if not sessions:
        print("No sessions in SQLite DB.")
        return

    total = len(sessions)
    completed = sum(1 for s in sessions if s["status"] == "completed")
    total_duration_ms = sum(s.get("duration_ms", 0) or 0 for s in sessions)

    # Count narratives with a single query
    with NarrativesDB() as db:
        sessions = db.list_sessions()
        cur = db._conn.execute(
            "SELECT COUNT(*) as cnt FROM narratives"
        )
        narrative_count = cur.fetchone()["cnt"]

    print(f"\n{'=' * 80}")
    print("SQLite DB Statistics")
    print(f"{'=' * 80}\n")
    print(f"Total Sessions: {total}")
    print(f"Completed: {completed}")
    print(f"In-progress/Unknown: {total - completed}")
    print(f"Sessions with Narratives: {narrative_count}/{total}")
    print(f"Total Duration: {total_duration_ms / 1000:.1f}s")


# -- Conversation-level functions -------------------------------------------

def list_conversations_db(status=None, limit=None):
    """List conversations from SQLite with session counts."""
    from narratives_db import NarrativesDB

    with NarrativesDB() as db:
        conn = db._conn
        query = (
            "SELECT c.conversation_id, c.created_at, c.status, c.git_branch, "
            "c.model, COUNT(s.session_id) as session_count, "
            "COALESCE(SUM(s.duration_ms), 0) as total_duration_ms, "
            "MAX(s.created_at) as last_session_at "
            "FROM conversations c "
            "LEFT JOIN sessions s ON c.conversation_id = s.conversation_id "
        )
        params = []
        if status is not None:
            query += "WHERE c.status = ? "
            params.append(status)
        query += "GROUP BY c.conversation_id ORDER BY last_session_at DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        cur = conn.execute(query, params)
        conversations = [dict(row) for row in cur.fetchall()]

    if not conversations:
        print("No conversations in SQLite DB.")
        return

    print(f"\n{'=' * 80}")
    print(f"Conversations from SQLite DB ({len(conversations)} total)")
    print(f"{'=' * 80}\n")

    for c in conversations:
        print(f"Conversation: {c['conversation_id']}")
        print(f"  Created: {c['created_at']} | Status: {c['status']}")
        print(f"  Sessions: {c['session_count']} | Total Duration: {c['total_duration_ms'] / 1000:.1f}s")
        if c['git_branch']:
            print(f"  Branch: {c['git_branch']}")
        if c['model']:
            print(f"  Model: {c['model']}")
        print()


def get_conversation(conversation_id):
    """Show all sessions + aggregate stats + timeline for a conversation."""
    from narratives_db import NarrativesDB

    with NarrativesDB() as db:
        # Get conversation metadata
        cur = db._conn.execute(
            "SELECT * FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        )
        conv = cur.fetchone()
        if conv is None:
            print(f"Conversation not found: {conversation_id}")
            return
        conv = dict(conv)

        # Get all sessions for this conversation
        sessions = db.list_sessions()
        conv_sessions = [s for s in sessions if s.get("conversation_id") == conversation_id]

        # Get aggregate stats
        total_duration_ms = sum(s.get("duration_ms", 0) or 0 for s in conv_sessions)
        completed = sum(1 for s in conv_sessions if s["status"] == "completed")

        # Get events timeline across all sessions
        all_events = []
        for s in conv_sessions:
            events = db.get_events_by_session(s["session_id"])
            for ev in events:
                ev["session_id"] = s["session_id"]
                all_events.append(ev)
        all_events.sort(key=lambda e: e.get("timestamp", ""))

    print(f"\n{'=' * 80}")
    print(f"Conversation: {conversation_id}")
    print(f"{'=' * 80}\n")

    print("## Conversation Info ##")
    print(f"  Created: {conv['created_at']}")
    print(f"  Status: {conv['status']}")
    if conv.get("completed_at"):
        print(f"  Completed: {conv['completed_at']}")
    if conv.get("git_branch"):
        print(f"  Branch: {conv['git_branch']}")
    if conv.get("model"):
        print(f"  Model: {conv['model']}")
    if conv.get("composer_mode"):
        print(f"  Composer Mode: {conv['composer_mode']}")
    print()

    print("## Session Summary ##")
    print(f"  Total Sessions: {len(conv_sessions)}")
    print(f"  Completed: {completed}")
    print(f"  Total Duration: {total_duration_ms / 1000:.1f}s")
    print()

    for s in conv_sessions:
        print(f"  Session: {s['session_id']}")
        print(f"    Status: {s['status']} | Duration: {s['duration_ms']}ms | Created: {s['created_at']}")
    print()

    print(f"## Event Timeline ({len(all_events)} events) ##")
    for i, ev in enumerate(all_events):
        detail = json.loads(ev.get("detail_json", "{}"))
        model_tag = f" | model={ev['model']}" if ev.get("model") else ""
        hook_tag = f" | hook={ev['hook_event_name']}" if ev.get("hook_event_name") else ""
        session_tag = f" | session={ev['session_id'][:8]}..."
        print(f"  [{i + 1}] {ev['timestamp']} - {ev['event_type']}{model_tag}{hook_tag}{session_tag}")

        ev_type = ev["event_type"]
        if ev_type == "thought":
            text = detail.get("text", "")[:100]
            if text:
                print(f"    {text}")
        elif ev_type == "tool_use":
            tool = detail.get("tool_name", "")
            msg = detail.get("agent_message", "")[:60]
            if tool:
                print(f"    Tool: {tool} - {msg}")
        elif ev_type == "file_edit":
            fpath = detail.get("file_path", "")
            chars = detail.get("chars_added", 0)
            if fpath:
                print(f"    File: {fpath} (+{chars} chars)")
        elif ev_type == "subagent_start":
            subagent_type = detail.get("subagent_type", "")
            task = detail.get("task", "")[:80]
            print(f"    Subagent: {subagent_type} - {task}")

    print()

    show_conversation_aggregate_stats(conversation_id)


def show_conversation_aggregate_stats(conversation_id):
    """Show rolled-up stats for a conversation."""
    from narratives_db import NarrativesDB

    with NarrativesDB() as db:
        # Get sessions for this conversation
        sessions = db.list_sessions()
        conv_sessions = [s for s in sessions if s.get("conversation_id") == conversation_id]

        if not conv_sessions:
            print(f"No sessions found for conversation: {conversation_id}")
            return

        session_ids = [s["session_id"] for s in conv_sessions]
        placeholders = ",".join("?" for _ in session_ids)

        # Aggregate event counts by type
        cur = db._conn.execute(
            f"SELECT event_type, COUNT(*) as cnt FROM hook_events "
            f"WHERE session_id IN ({placeholders}) GROUP BY event_type ORDER BY cnt DESC",
            session_ids,
        )
        event_breakdown = {row["event_type"]: row["cnt"] for row in cur.fetchall()}

        # Aggregate duration stats
        total_events = sum(event_breakdown.values())
        total_duration_ms = sum(s.get("duration_ms", 0) or 0 for s in conv_sessions)

        # Count tool uses and unique files from session_stats
        total_tool_uses = 0
        total_file_edits = 0
        all_files = set()
        for s in conv_sessions:
            try:
                cur = db._conn.execute(
                    "SELECT total_tool_uses, total_file_edits, unique_files_edited "
                    "FROM session_stats WHERE session_id = ?",
                    (s["session_id"],),
                )
                row = cur.fetchone()
                if row:
                    total_tool_uses += row["total_tool_uses"] or 0
                    total_file_edits += row["total_file_edits"] or 0
                    files_json = row["unique_files_edited"]
                    if files_json:
                        all_files.update(json.loads(files_json))
            except Exception:
                pass

    print(f"## Aggregate Stats for Conversation {conversation_id} ##")
    print(f"  Total Events: {total_events}")
    print(f"  Total Sessions: {len(conv_sessions)}")
    print(f"  Total Duration: {total_duration_ms / 1000:.1f}s")
    print(f"  Total Tool Uses: {total_tool_uses}")
    print(f"  Total File Edits: {total_file_edits}")
    print(f"  Unique Files Modified: {len(all_files)}")
    print()

    if event_breakdown:
        print("  Event Breakdown:")
        for event_type, count in event_breakdown.items():
            print(f"    {event_type}: {count}")
        print()

    if all_files:
        print("  Files Modified:")
        for f in sorted(all_files):
            print(f"    {f}")
        print()


def main():
    parser = argparse.ArgumentParser(description="View recorded agent conversations")
    parser.add_argument("session_id", nargs="?", help="Session ID to view")
    parser.add_argument("--search", type=str, help="Search across all sessions")
    parser.add_argument("--stats", action="store_true", help="Show aggregate statistics")
    parser.add_argument("--recent", type=int, metavar="N", help="Show last N sessions")
    parser.add_argument("--db", action="store_true", help="Use SQLite DB instead of JSON files")
    parser.add_argument("--conversations", action="store_true", help="List conversations")
    parser.add_argument("--get-conversation", type=str, metavar="CONVERSATION_ID",
                        help="Show a conversation's sessions, stats, and timeline")
    parser.add_argument("--aggregate-stats", type=str, metavar="CONVERSATION_ID",
                        help="Show rolled-up stats for a conversation")

    args = parser.parse_args()

    # Conversation-level commands (always use SQLite)
    if args.conversations:
        list_conversations_db()
        return
    if args.get_conversation:
        get_conversation(args.get_conversation)
        return
    if args.aggregate_stats:
        show_conversation_aggregate_stats(args.aggregate_stats)
        return

    # SQLite DB mode
    if args.db:
        if args.search:
            db_search_sessions(args.search)
        elif args.stats:
            db_show_stats()
        elif args.session_id:
            db_view_session(args.session_id)
        else:
            db_list_sessions(recent=args.recent)
        return

    # JSON file mode (existing behavior)
    if args.search:
        search_sessions(args.search)
    elif args.stats:
        show_stats()
    elif args.session_id:
        view_session(args.session_id)
    else:
        list_sessions(recent=args.recent)


if __name__ == "__main__":
    main()