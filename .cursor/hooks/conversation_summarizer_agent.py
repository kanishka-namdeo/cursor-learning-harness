#!/usr/bin/env python3
"""
LangGraph Conversation-Level Summarizer Agent

Generates narrative and structured summaries for conversations (groups of
related sessions) using a StateGraph-based agent. Uses existing session-level
summaries as building blocks rather than re-processing raw events.

Usage:
    python conversation_summarizer_agent.py <conversation_id>
    python conversation_summarizer_agent.py <conversation_id> --force
    python conversation_summarizer_agent.py <conversation_id> --regenerate
"""

import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import TypedDict

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

# Resolve paths relative to this script
HOOKS_DIR = Path(__file__).parent.resolve()
LLM_ENV_PATH = HOOKS_DIR.parent / "llm.env"
STATE_DIR = HOOKS_DIR / "state"
CONVERSATIONS_DIR = STATE_DIR / "conversations"

sys.path.insert(0, str(HOOKS_DIR))
from conversation_recorder import ConversationRecorder, debug_log, is_process_alive
from narratives_db import NarrativesDB

load_dotenv(str(LLM_ENV_PATH), override=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEBOUNCE_SECONDS = 60
LOCK_TIMEOUT_SECONDS = 120
MAX_NARRATIVE_CHARS = 100_000

# ---------------------------------------------------------------------------
# LLM setup
# ---------------------------------------------------------------------------

def get_llm():
    api_key = os.getenv("API_KEY", "")
    if not api_key:
        print("[conv-summarizer] ERROR: API_KEY not set in llm.env", file=sys.stderr)
        sys.exit(1)

    base_url = os.getenv("BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("REASONING_MODEL", "qwen3.6-plus")

    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=0.3,
        max_tokens=8192,
        timeout=90,
    )


# ---------------------------------------------------------------------------
# Lock file helpers (per-conversation, same pattern as session locks)
# ---------------------------------------------------------------------------

def acquire_lock(conversation_id: str) -> bool:
    """Acquire a per-conversation lock. Returns False if already locked."""
    conv_dir = CONVERSATIONS_DIR / conversation_id
    conv_dir.mkdir(parents=True, exist_ok=True)
    lock_file = conv_dir / ".summarizer_lock"

    if lock_file.exists():
        try:
            content = lock_file.read_text().strip()
            parts = content.split("|")
            pid = int(parts[0])
            timestamp = float(parts[1]) if len(parts) > 1 else 0
            elapsed = time.time() - timestamp

            if elapsed < LOCK_TIMEOUT_SECONDS and _is_process_alive(pid):
                return False
            lock_file.unlink(missing_ok=True)
        except (ValueError, OSError):
            lock_file.unlink(missing_ok=True)

    lock_path = str(lock_file)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_WRONLY | os.O_EXCL)
        os.write(fd, f"{os.getpid()}|{time.time()}".encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False
    except OSError:
        return False


def release_lock(conversation_id: str):
    lock_file = CONVERSATIONS_DIR / conversation_id / ".summarizer_lock"
    lock_file.unlink(missing_ok=True)


def _is_process_alive(pid: int) -> bool:
    """Cross-platform process check (delegates to shared utility)."""
    return is_process_alive(pid)


# ---------------------------------------------------------------------------
# Debounce helpers
# ---------------------------------------------------------------------------

def check_debounce(conversation_id: str) -> bool:
    """Returns True if we should skip (within debounce window)."""
    ts_file = CONVERSATIONS_DIR / conversation_id / ".last_summarized_timestamp"
    if not ts_file.exists():
        return False
    try:
        last_ts = float(ts_file.read_text().strip())
        return (time.time() - last_ts) < DEBOUNCE_SECONDS
    except (ValueError, OSError):
        return False


def mark_summarized(conversation_id: str):
    ts_file = CONVERSATIONS_DIR / conversation_id / ".last_summarized_timestamp"
    ts_file.write_text(str(time.time()))


# ---------------------------------------------------------------------------
# State definition
# ---------------------------------------------------------------------------

class ConversationSummarizerState(TypedDict, total=False):
    conversation_id: str
    sessions: list           # session metadata from DB
    session_narratives: dict # {session_id: narrative_text}
    session_structured: list # per-session structured summaries
    merged_structured: dict  # from merge_structured_summaries
    aggregated_stats: dict   # from aggregate_conversation_stats
    previous_narrative: str  # existing conversation narrative
    conversation_narrative: str
    conversation_structured: dict
    strategy: str            # "full" | "incremental" | "skip"
    error: str
    force: bool
    regenerate: bool
    formatted_context: str
    conversation_sentiment: dict  # aggregated sentiment data (Phase 2)


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

def load_conversation(state: ConversationSummarizerState) -> ConversationSummarizerState:
    """Load conversation data and decide summarization strategy."""
    conversation_id = state["conversation_id"]
    force = state.get("force", False)
    regenerate = state.get("regenerate", False)

    try:
        with NarrativesDB() as db:
            sessions = db.get_sessions_by_conversation(conversation_id)
    except Exception as e:
        print(f"[conv-summarizer] Failed to load conversation {conversation_id}: {e}", file=sys.stderr)
        return {**state, "strategy": "skip", "error": str(e)}

    if not sessions:
        return {**state, "strategy": "skip", "error": "No sessions found"}

    # Single session — no added value from conversation-level summary
    if len(sessions) == 1 and not force:
        return {**state, "strategy": "skip", "error": "Only 1 session (use --force to override)"}

    # Load session narratives (SQLite only — no longer stored in session.json)
    session_narratives = {}
    missing_narrative_sessions = []

    for s in sessions:
        sid = s["session_id"]
        narrative_text = ""
        try:
            with NarrativesDB() as db:
                row = db.get_narrative(sid)
                if row and row.get("narrative"):
                    narrative_text = row["narrative"]
        except Exception:
            pass

        if narrative_text and narrative_text.strip():
            session_narratives[sid] = narrative_text
        else:
            missing_narrative_sessions.append(sid[:12])

    # Check for existing conversation narrative
    previous_narrative = ""
    try:
        with NarrativesDB() as db:
            conv_narr = db.get_conversation_narrative(conversation_id)
            if conv_narr:
                previous_narrative = conv_narr.get("narrative", "")
    except Exception:
        pass

    # Determine strategy
    if force or regenerate:
        strategy = "full"
    else:
        if missing_narrative_sessions:
            print(
                f"[conv-summarizer] Sessions missing narrative: "
                f"{', '.join(missing_narrative_sessions)}. Skipping.",
                file=sys.stderr,
            )
            return {**state, "strategy": "skip", "error": f"Missing narratives: {', '.join(missing_narrative_sessions)}"}

        if check_debounce(conversation_id) and previous_narrative:
            return {**state, "strategy": "skip"}

        if previous_narrative:
            strategy = "incremental"
        else:
            strategy = "full"

    # Gather merged structured summaries and aggregated stats
    merged_structured = {}
    aggregated_stats = {}
    session_structured = []

    try:
        with NarrativesDB() as db:
            merged_structured = db.merge_structured_summaries(conversation_id)
            aggregated_stats = db.aggregate_conversation_stats(conversation_id)
            # Also load per-session structured data
            for s in sessions:
                ss = db.get_structured_summary(s["session_id"])
                if ss and ss.get("structured_data"):
                    session_structured.append(ss["structured_data"])
    except Exception as e:
        debug_log(f"conv-summarizer: failed to load structured/stats: {e}")

    return {
        **state,
        "sessions": sessions,
        "session_narratives": session_narratives,
        "session_structured": session_structured,
        "merged_structured": merged_structured,
        "aggregated_stats": aggregated_stats,
        "previous_narrative": previous_narrative,
        "strategy": strategy,
    }


def route_after_load(state: ConversationSummarizerState) -> str:
    if state.get("strategy") == "skip":
        return END
    return "build_context"


def load_conversation_sentiment(state: ConversationSummarizerState) -> ConversationSummarizerState:
    """Load sentiment arc data for all sessions in the conversation."""
    sessions = state.get("sessions", [])
    if not sessions:
        return {**state, "conversation_sentiment": {}}

    sentiment_data: dict = {
        "per_session_archetypes": {},
        "dominant_archetype": "",
        "archetype_distribution": {},
        "avg_arc_slope": None,
        "avg_sentiment": None,
        "frustration_count": 0,
        "sentiment_trajectory": [],
        "session_count_with_arc": 0,
    }

    try:
        from collections import Counter

        from sentiment_arc.arc_db import get_arc_features_for_session, init_arc_tables
        conn = init_arc_tables()

        slopes = []
        sentiments = []
        archetypes = []
        frustration_archetypes = {"escalating_frustration", "mismatched_effort", "looping", "abandoned"}

        for idx, s in enumerate(sessions):
            sid = s["session_id"]
            arc = get_arc_features_for_session(conn, sid)

            if arc:
                sentiment_data["per_session_archetypes"][sid] = {
                    "archetype": arc.get("archetype", ""),
                    "confidence": arc.get("archetype_confidence", 0.0),
                    "arc_slope": arc.get("arc_slope"),
                    "avg_sentiment": arc.get("avg_sentiment"),
                }
                sentiment_data["sentiment_trajectory"].append({
                    "session_index": idx,
                    "session_id": sid,
                    "archetype": arc.get("archetype", ""),
                    "avg_sentiment": arc.get("avg_sentiment"),
                })

                arch = arc.get("archetype", "")
                if arch and arch not in ("too_short", "inconclusive", "error"):
                    archetypes.append(arch)
                    if arch in frustration_archetypes:
                        sentiment_data["frustration_count"] += 1

                slope = arc.get("arc_slope")
                if slope is not None:
                    slopes.append(slope)

                avg_s = arc.get("avg_sentiment")
                if avg_s is not None:
                    sentiments.append(avg_s)

                sentiment_data["session_count_with_arc"] += 1

        conn.close()

        if archetypes:
            dist = Counter(archetypes)
            sentiment_data["archetype_distribution"] = dict(dist)
            sentiment_data["dominant_archetype"] = dist.most_common(1)[0][0]

        if slopes:
            sentiment_data["avg_arc_slope"] = round(sum(slopes) / len(slopes), 6)
        if sentiments:
            sentiment_data["avg_sentiment"] = round(sum(sentiments) / len(sentiments), 4)

    except Exception:
        pass

    return {**state, "conversation_sentiment": sentiment_data}


def build_context(state: ConversationSummarizerState) -> ConversationSummarizerState:
    """Build LLM context from session-level artifacts."""
    strategy = state.get("strategy", "skip")
    session_narratives = state.get("session_narratives", {})
    sessions = state.get("sessions", [])
    aggregated_stats = state.get("aggregated_stats", {})
    merged_structured = state.get("merged_structured", {})
    previous_narrative = state.get("previous_narrative", "")

    if not session_narratives:
        return {**state, "strategy": "skip"}

    lines = []

    # Conversation metadata
    conv_id = state["conversation_id"]
    session_count = len(sessions)

    # Determine date range
    dates = []
    for s in sessions:
        created = s.get("created_at", "")
        if created:
            dates.append(created[:10])
    date_range = ""
    if dates:
        date_range = f" spanning {min(dates)} to {max(dates)}" if len(dates) > 1 else f" on {dates[0]}"

    lines.append(f"# Conversation Summary: {conv_id[:12]}...")
    lines.append(f"Sessions: {session_count}{date_range}")
    lines.append("")

    # Aggregated stats
    if aggregated_stats:
        lines.append("## Conversation Statistics")
        lines.append(f"- Total events: {aggregated_stats.get('total_events', 0)}")
        lines.append(f"- Total file edits: {aggregated_stats.get('total_file_edits', 0)}")
        files = aggregated_stats.get("unique_files_edited", [])
        lines.append(f"- Unique files edited: {len(files)}")
        lines.append(f"- Total tool uses: {aggregated_stats.get('total_tool_uses', 0)}")
        thinking_ms = aggregated_stats.get("total_thinking_time_ms", 0)
        lines.append(f"- Total thinking time: {thinking_ms / 1000:.0f}s")
        main_count = aggregated_stats.get("main_session_count", "?")
        subagent_count = aggregated_stats.get("subagent_session_count", "?")
        lines.append(f"- Main sessions: {main_count}, Subagent sessions: {subagent_count}")
        lines.append("")

    # Session narratives timeline
    lines.append("## Session Summaries (Chronological)")
    lines.append("")

    session_ids = [s["session_id"] for s in sessions]

    for sid in session_ids:
        narrative = session_narratives.get(sid, "")
        if not narrative:
            continue

        session_meta = next((s for s in sessions if s["session_id"] == sid), {})
        created = session_meta.get("created_at", "")
        status = session_meta.get("status", "")

        lines.append(f"### Session {sid[:12]}... (created={created}, status={status})")
        lines.append(narrative)
        lines.append("")

    # Merged structured data
    if merged_structured:
        lines.append("## Merged Structured Data")
        if merged_structured.get("objectives"):
            lines.append(f"Objectives: {', '.join(merged_structured['objectives'])}")
        if merged_structured.get("files_modified"):
            lines.append(f"Files modified: {', '.join(merged_structured['files_modified'])}")
        if merged_structured.get("outcome"):
            lines.append(f"Outcome: {merged_structured['outcome']}")
        if merged_structured.get("decisions"):
            for d in merged_structured["decisions"]:
                if isinstance(d, dict):
                    lines.append(f"Decision: {d.get('decision', '')}")
        if merged_structured.get("errors_encountered"):
            for e in merged_structured["errors_encountered"]:
                if isinstance(e, dict):
                    lines.append(f"Error: {e.get('error', '')}")
        if merged_structured.get("open_questions"):
            lines.append(f"Open questions: {', '.join(merged_structured['open_questions'])}")
        lines.append("")

    # Sentiment arc context (Phase 2)
    conv_sentiment = state.get("conversation_sentiment", {})
    if conv_sentiment and conv_sentiment.get("per_session_archetypes"):
        lines.append("## Conversation Sentiment Arc Analysis")
        lines.append("")
        dominant = conv_sentiment.get("dominant_archetype", "")
        if dominant:
            lines.append(f"- Dominant interaction pattern: {dominant}")

        dist = conv_sentiment.get("archetype_distribution", {})
        if dist:
            lines.append(f"- Archetype distribution: {', '.join(f'{k}: {v}' for k, v in dist.items())}")

        avg_slope = conv_sentiment.get("avg_arc_slope")
        if avg_slope is not None:
            direction = "improving" if avg_slope > 0.005 else "declining" if avg_slope < -0.005 else "stable"
            lines.append(f"- Overall sentiment trend: {direction} (avg slope={avg_slope:.4f})")

        avg_sent = conv_sentiment.get("avg_sentiment")
        if avg_sent is not None:
            tone = "positive" if avg_sent > 0.1 else "negative" if avg_sent < -0.1 else "neutral"
            lines.append(f"- Overall tone: {tone}")

        frust = conv_sentiment.get("frustration_count", 0)
        total_with_arc = conv_sentiment.get("session_count_with_arc", 0)
        if frust > 0 and total_with_arc > 0:
            lines.append(f"- Frustrating sessions: {frust}/{total_with_arc}")

        trajectory = conv_sentiment.get("sentiment_trajectory", [])
        if trajectory:
            lines.append("- Session-by-session pattern:")
            for t in trajectory:
                arch = t.get("archetype", "no data")
                sent = t.get("avg_sentiment")
                sent_str = f" (sentiment={sent:.3f})" if sent is not None else ""
                lines.append(f"  Session {t['session_id'][:12]}...: {arch}{sent_str}")

        lines.append("")

    context = "\n".join(lines)

    # For incremental: include previous conversation narrative
    if strategy == "incremental" and previous_narrative:
        context = (
            f"## Previous Conversation Summary\n\n{previous_narrative}\n\n"
            f"## Session Summaries Since Last Summary\n\n" + context
        )

    return {**state, "formatted_context": context}


def generate_narrative(state: ConversationSummarizerState) -> ConversationSummarizerState:
    """Call the LLM to generate the conversation-level narrative summary."""
    context = state.get("formatted_context", "")
    strategy = state.get("strategy", "full")
    previous_narrative = state.get("previous_narrative", "")
    sessions = state.get("sessions", [])

    session_count = len(sessions)
    subagent_sessions = sum(1 for s in sessions if s.get("is_background_agent", 0))

    system_prompt = (
        f"You are summarizing a multi-session conversation from an AI coding assistant (Cursor).\n"
        f"This conversation consists of {session_count} sessions"
        f" ({subagent_sessions} subagent sessions)\n\n"
    )

    if strategy == "incremental" and previous_narrative:
        system_prompt += (
            f"Below is the existing conversation summary. New session summaries have been "
            f"added since the last update. Update the summary to incorporate the new work.\n\n"
            f"Existing summary:\n{previous_narrative}\n\n"
        )

    system_prompt += (
        f"Session summaries (each is a summary of one session):\n"
        f"{context}\n\n"
        f"Produce a concise conversation-level narrative covering:\n"
        f"1. What the user was trying to accomplish across all sessions\n"
        f"2. How the work evolved across sessions (progression, pivots, iterations)\n"
        f"3. Key technical decisions and their reasoning\n"
        f"4. Files and systems modified (high-level, not every change)\n"
        f"5. Tool usage patterns and any notable failures or challenges\n"
        f"6. Subagent work and outcomes (if any)\n"
        f"7. Final outcome and any remaining open questions\n"
        f"8. Cross-session patterns (e.g., recurring issues, iterative test-fix cycles)\n\n"
        f"Write in a clear, professional tone. Keep it under 1000 words.\n"
        f"Use markdown formatting."
    )

    # Add sentiment-specific instruction when arc data is available
    conv_sentiment = state.get("conversation_sentiment", {})
    if conv_sentiment and conv_sentiment.get("dominant_archetype"):
        sentiment_instruction = (
            "\nInteraction Pattern Analysis:\n"
            "The session sentiment arc analysis below shows how the user's experience evolved. "
            "Weave this into your narrative naturally — describe the interaction quality, "
            "not just the technical work. For example:\n"
            "- If 'looping' dominates: describe retry patterns and what finally broke the cycle\n"
            "- If 'escalating_frustration': highlight the failure cascade and unresolved issues\n"
            "- If 'smooth_convergence': note the productive, steady progress\n"
            "- If 'mismatched_effort': describe the gap between effort and outcome\n"
            "- If 'rapid_resolution': note the quick, efficient turnaround\n"
            "- If 'abandoned': note where the conversation ended without resolution\n"
            "If sentiment data is sparse or absent, skip this section.\n\n"
        )
        system_prompt += sentiment_instruction

    try:
        llm = get_llm()
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content="Generate the conversation-level summary."),
        ])
        content = response.content

        # Retry if empty
        if not content or not content.strip():
            print("[conv-summarizer] Empty LLM response, retrying", file=sys.stderr)
            response = llm.invoke([
                SystemMessage(content="You MUST produce a summary based on the session summaries above. Even a short summary is better than nothing."),
                HumanMessage(content=context),
            ])
            content = response.content

        if not content or not content.strip():
            return {**state, "error": "LLM returned empty response after retry", "conversation_narrative": ""}

        return {**state, "conversation_narrative": str(content)}

    except Exception as e:
        print(f"[conv-summarizer] LLM error: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return {**state, "error": str(e), "conversation_narrative": ""}


def generate_structured(state: ConversationSummarizerState) -> ConversationSummarizerState:
    """Generate conversation-level structured summary from merged session data."""
    merged = state.get("merged_structured", {})
    sessions = state.get("sessions", [])
    aggregated_stats = state.get("aggregated_stats", {})

    if not merged and not sessions:
        return {**state, "conversation_structured": {}}

    subagent_count = sum(1 for s in sessions if s.get("is_background_agent", 0))

    # Synthesize from merged data
    structured = {
        "schema_version": 1,
        "conversation_id": state["conversation_id"],
        "session_count": len(sessions),
        "main_session_count": len(sessions) - subagent_count,
        "subagent_session_count": subagent_count,
        "objectives": merged.get("objectives", []),
        "files_modified": merged.get("files_modified", []),
        "files_created": merged.get("files_created", []),
        "files_deleted": merged.get("files_deleted", []),
        "decisions": merged.get("decisions", []),
        "errors_encountered": merged.get("errors_encountered", []),
        "tool_usage_summary": merged.get("tool_usage_summary", {}),
        "subagent_work": merged.get("subagent_work", []),
        "code_patterns": merged.get("code_patterns", []),
        "open_questions": merged.get("open_questions", []),
        "outcome": merged.get("outcome", ""),
        "session_type": merged.get("session_type", "other"),
        "aggregate_stats": {
            "total_events": aggregated_stats.get("total_events", 0),
            "total_file_edits": aggregated_stats.get("total_file_edits", 0),
            "total_tool_uses": aggregated_stats.get("total_tool_uses", 0),
            "total_thinking_time_ms": aggregated_stats.get("total_thinking_time_ms", 0),
            "total_chars_added": aggregated_stats.get("total_chars_added", 0),
            "total_chars_removed": aggregated_stats.get("total_chars_removed", 0),
        },
    }

    # Add sentiment fields from conversation sentiment aggregation (Phase 2)
    conv_sentiment = state.get("conversation_sentiment", {})
    structured["sentiment_archetype"] = conv_sentiment.get("dominant_archetype", "")
    structured["sentiment_trajectory"] = conv_sentiment.get("sentiment_trajectory", [])
    structured["sentiment_archetype_distribution"] = conv_sentiment.get("archetype_distribution", {})
    structured["sentiment_avg_arc_slope"] = conv_sentiment.get("avg_arc_slope")
    structured["sentiment_avg_sentiment"] = conv_sentiment.get("avg_sentiment")
    structured["sentiment_frustration_count"] = conv_sentiment.get("frustration_count", 0)
    structured["sentiment_session_count_with_arc"] = conv_sentiment.get("session_count_with_arc", 0)

    return {**state, "conversation_structured": structured}


def save_summary(state: ConversationSummarizerState) -> ConversationSummarizerState:
    """Persist conversation summary to SQLite only (no JSON files on disk)."""
    conversation_id = state["conversation_id"]
    narrative = state.get("conversation_narrative", "")
    structured = state.get("conversation_structured", {})
    error = state.get("error", "")
    strategy = state.get("strategy", "full")
    sessions = state.get("sessions", [])

    if error and not narrative:
        narrative = f"[Conversation summarization failed: {error}]"

    generated_at = datetime.now().isoformat()
    session_count = len(sessions)

    # Write to SQLite (fail-open)
    try:
        with NarrativesDB() as db:
            # Write narrative
            if narrative:
                db.upsert_conversation_narrative(
                    conversation_id=conversation_id,
                    narrative=narrative,
                    generated_at=generated_at,
                    session_count=session_count,
                )

            # Write structured summary
            if structured:
                db.upsert_conversation_structured(
                    conversation_id=conversation_id,
                    structured_json=structured,
                    generated_at=generated_at,
                    session_count=session_count,
                )

            # Update conversation status
            db._conn.execute(
                """
                UPDATE conversations
                SET completed_at = ?, status = ?, last_updated = CURRENT_TIMESTAMP
                WHERE conversation_id = ?
                """,
                (generated_at, "summarized", conversation_id),
            )
            db._conn.commit()
    except Exception as e:
        debug_log(f"conv-summarizer: SQLite write failed: {e}")

    mark_summarized(conversation_id)

    print(
        f"[conv-summarizer] Summary saved for conversation {conversation_id[:12]}... "
        f"(strategy={strategy}, sessions={session_count})",
        file=sys.stderr,
    )

    return state


# ---------------------------------------------------------------------------
# Graph definition
# ---------------------------------------------------------------------------

def build_graph():
    builder = StateGraph(ConversationSummarizerState)
    builder.add_node("load_conversation", load_conversation)
    builder.add_node("build_context", build_context)
    builder.add_node("load_conversation_sentiment", load_conversation_sentiment)
    builder.add_node("generate_narrative", generate_narrative)
    builder.add_node("generate_structured", generate_structured)
    builder.add_node("save_summary", save_summary)

    builder.add_edge(START, "load_conversation")
    builder.add_conditional_edges("load_conversation", route_after_load, {
        "build_context": "build_context",
        END: END,
    })
    builder.add_edge("build_context", "load_conversation_sentiment")
    builder.add_edge("load_conversation_sentiment", "generate_narrative")
    builder.add_edge("generate_narrative", "generate_structured")
    builder.add_edge("generate_structured", "save_summary")
    builder.add_edge("save_summary", END)

    return builder.compile()


graph = build_graph()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: conversation_summarizer_agent.py <conversation_id> [--force] [--regenerate]", file=sys.stderr)
        sys.exit(1)

    conversation_id = sys.argv[1]
    force = "--force" in sys.argv
    regenerate = "--regenerate" in sys.argv

    # Acquire lock
    if not acquire_lock(conversation_id):
        print(f"[conv-summarizer] Another summarizer is running for conversation {conversation_id}, skipping", file=sys.stderr)
        sys.exit(0)

    try:
        result = graph.invoke({
            "conversation_id": conversation_id,
            "force": force,
            "regenerate": regenerate,
        })

        strategy = result.get("strategy", "unknown")
        if strategy == "skip":
            print(f"[conv-summarizer] Skipped summarization for conversation {conversation_id} (strategy=skip)", file=sys.stderr)
        elif result.get("error"):
            print(f"[conv-summarizer] Error for conversation {conversation_id}: {result['error']}", file=sys.stderr)
        else:
            print(f"[conv-summarizer] Done: conversation {conversation_id[:12]}... (strategy={strategy}, sessions={len(result.get('sessions', []))})", file=sys.stderr)

    finally:
        release_lock(conversation_id)


if __name__ == "__main__":
    main()
