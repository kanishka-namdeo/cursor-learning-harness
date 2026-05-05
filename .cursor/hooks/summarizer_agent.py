#!/usr/bin/env python3
"""
LangGraph Session Summarizer Agent

Generates narrative summaries for Cursor conversation sessions using a
StateGraph-based agent with debounce protection and incremental updates.

Usage:
    python summarizer_agent.py <session_id>
    python summarizer_agent.py <session_id> --force
    python summarizer_agent.py <session_id> --regenerate
"""

import json
import os
import re
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
SESSIONS_DIR = STATE_DIR / "sessions"

sys.path.insert(0, str(HOOKS_DIR))
from conversation_recorder import ConversationRecorder, is_process_alive

load_dotenv(str(LLM_ENV_PATH), override=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEBOUNCE_SECONDS = 60
LOCK_TIMEOUT_SECONDS = 120
REGENERATE_THRESHOLD = 3

# Structured summary constants
STRUCTURED_SUMMARY_SCHEMA_VERSION = 1

SESSION_TYPE_CATEGORIES = (
    "feature", "bugfix", "refactor", "exploration",
    "documentation", "config", "testing", "deployment", "other",
)

# ---------------------------------------------------------------------------
# LLM setup
# ---------------------------------------------------------------------------

def get_llm():
    api_key = os.getenv("API_KEY", "")
    if not api_key:
        print("[summarizer] ERROR: API_KEY not set in llm.env", file=sys.stderr)
        sys.exit(1)

    base_url = os.getenv("BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("REASONING_MODEL", "qwen3.6-plus")

    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=0.3,
        max_tokens=4096,
        timeout=60,
    )


# ---------------------------------------------------------------------------
# Lock file helpers
# ---------------------------------------------------------------------------

def acquire_lock(session_id: str) -> bool:
    """Acquire a per-session lock using atomic file creation. Returns False if already locked."""
    session_dir = SESSIONS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    lock_file = session_dir / ".summarizer_lock"

    if lock_file.exists():
        try:
            content = lock_file.read_text().strip()
            parts = content.split("|")
            pid = int(parts[0])
            timestamp = float(parts[1]) if len(parts) > 1 else 0
            elapsed = time.time() - timestamp

            if elapsed < LOCK_TIMEOUT_SECONDS and _is_process_alive(pid):
                return False  # Another instance is running
            # Stale lock, remove it
            lock_file.unlink(missing_ok=True)
        except (ValueError, OSError):
            lock_file.unlink(missing_ok=True)

    # Use atomic file creation to prevent TOCTOU race
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


def release_lock(session_id: str):
    lock_file = SESSIONS_DIR / session_id / ".summarizer_lock"
    lock_file.unlink(missing_ok=True)


def _is_process_alive(pid: int) -> bool:
    """Cross-platform process check (delegates to shared utility)."""
    return is_process_alive(pid)


# ---------------------------------------------------------------------------
# Debounce helpers
# ---------------------------------------------------------------------------

def check_debounce(session_id: str) -> bool:
    """Returns True if we should skip (within debounce window)."""
    ts_file = SESSIONS_DIR / session_id / ".last_summarized_timestamp"
    if not ts_file.exists():
        return False
    try:
        last_ts = float(ts_file.read_text().strip())
        return (time.time() - last_ts) < DEBOUNCE_SECONDS
    except (ValueError, OSError):
        return False


def mark_summarized(session_id: str):
    ts_file = SESSIONS_DIR / session_id / ".last_summarized_timestamp"
    ts_file.write_text(str(time.time()))


# ---------------------------------------------------------------------------
# State definition
# ---------------------------------------------------------------------------

class SummarizerState(TypedDict, total=False):
    session_id: str
    events: list
    new_event_count: int
    previous_summary: str
    narrative_summary: str
    structured_summary: dict
    strategy: str          # "full_regenerate" | "delta_update" | "skip"
    error: str
    force: bool
    regenerate: bool
    structured_only: bool  # if True, skip narrative and only produce structured
    formatted_context: str # formatted event timeline for LLM


# ---------------------------------------------------------------------------
# Structured Summary Helpers
# ---------------------------------------------------------------------------

def _make_empty_structured_summary(outcome: str = "") -> dict:
    """Return an empty/default structured summary for trivial sessions."""
    return {
        "schema_version": STRUCTURED_SUMMARY_SCHEMA_VERSION,
        "objectives": [],
        "files_modified": [],
        "files_created": [],
        "files_deleted": [],
        "decisions": [],
        "errors_encountered": [],
        "tool_usage_summary": {},
        "subagent_work": [],
        "code_patterns": [],
        "open_questions": [],
        "outcome": outcome or "Session had insufficient events for analysis",
        "session_type": "other",
        "_verification_warnings": [],
        # Sentiment arc fields (Phase 2)
        "sentiment_archetype": "",
        "sentiment_confidence": 0.0,
        "arc_slope": None,
        "avg_sentiment": None,
        "recovery_events": 0,
        "mismatched_effort_score": None,
        "sentiment_gap": None,
        "user_sentiment_trend": None,
        "assistant_sentiment_trend": None,
    }


def _scrub_secrets(text: str) -> tuple[str, bool]:
    """Remove potential secrets from text. Returns (scrubbed_text, was_scrubbed)."""
    scrubbed = False
    result = text
    for pattern in (
        r"sk-[a-zA-Z0-9]{20,}",
        r"ghp_[a-zA-Z0-9]{36}",
        r"gho_[a-zA-Z0-9]{36}",
    ):
        if re.search(pattern, result):
            result = re.sub(pattern, "[REDACTED]", result)
            scrubbed = True
    for pattern in (
        r"(?i)(api[_-]?key)\s*[:=]\s*(\S+)",
        r"(?i)(password)\s*[:=]\s*(\S+)",
        r"(?i)(token)\s*[:=]\s*([a-zA-Z0-9]{16,})",
        r"(?i)(aws_secret_access_key)\s*[:=]\s*(\S+)",
    ):
        if re.search(pattern, result):
            result = re.sub(pattern, r"\1: [REDACTED]", result)
            scrubbed = True
    return result, scrubbed


def _verify_structured_summary(structured: dict, events: list) -> list[str]:
    """Cross-reference structured output against actual events. Returns list of warnings."""
    warnings = []

    # Verify files_modified against actual file_edits
    actual_files = set()
    for ev in events:
        if ev.get("type") == "file_edit":
            fp = ev.get("file_path", "")
            if fp:
                actual_files.add(fp)

    for f in structured.get("files_modified", []):
        if f and f not in actual_files:
            warnings.append(f"listed file '{f}' was not found in actual file_edit events")

    # Verify tool counts if present
    for tool_name, stats in structured.get("tool_usage_summary", {}).items():
        if isinstance(stats, dict) and "calls" in stats:
            actual_count = sum(
                1 for ev in events
                if ev.get("type") in ("tool_use", "mcp_call") and ev.get("tool_name") == tool_name
            )
            if stats["calls"] > actual_count + 5:  # allow some tolerance for capped events
                warnings.append(f"tool '{tool_name}' reported {stats['calls']} calls but only {actual_count} found in events")

    return warnings


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

def load_and_check(state: SummarizerState) -> SummarizerState:
    """Load session data and decide whether to summarize."""
    session_id = state["session_id"]
    force = state.get("force", False)
    do_regenerate = state.get("regenerate", False)

    try:
        recorder = ConversationRecorder()
        session = recorder.load_session(session_id)
    except Exception as e:
        print(f"[summarizer] Failed to load session {session_id}: {e}", file=sys.stderr)
        return {**state, "strategy": "skip", "error": str(e)}

    events = session.get("events", [])
    last_count = session.get("summary", {}).get("last_summary_event_count", 0)
    new_event_count = len(events) - last_count

    # Read previous narrative from SQLite (canonical source)
    previous_summary = ""
    try:
        from narratives_db import NarrativesDB
        with NarrativesDB() as db:
            row = db.get_narrative(session_id)
            if row and row.get("narrative"):
                previous_summary = row["narrative"]
    except Exception:
        pass

    # Force bypasses debounce and threshold
    if force or do_regenerate:
        strategy = "full_regenerate"
    else:
        # Debounce check
        if check_debounce(session_id):
            print(f"[summarizer] Debounce active for {session_id}, skipping", file=sys.stderr)
            return {**state, "strategy": "skip"}

        if new_event_count == 0:
            return {**state, "strategy": "skip"}

        if new_event_count >= REGENERATE_THRESHOLD or not previous_summary:
            strategy = "full_regenerate"
        else:
            strategy = "delta_update"

    return {
        **state,
        "events": events,
        "new_event_count": new_event_count,
        "previous_summary": previous_summary,
        "strategy": strategy,
    }


def _dedup_events(events: list) -> list:
    """Remove consecutive byte-identical events (dual-CWD double-fire)."""
    if not events:
        return []
    result = [events[0]]
    for ev in events[1:]:
        if json.dumps(ev, sort_keys=True) != json.dumps(result[-1], sort_keys=True):
            result.append(ev)
    return result


def _format_events(events: list, strategy: str, last_summary_event_count: int) -> str:
    """Format events into a readable timeline for the LLM."""
    events = _dedup_events(events)

    # For delta updates, slice from last_summary_event_count
    if strategy == "delta_update" and last_summary_event_count > 0:
        events = events[last_summary_event_count:]

    if not events:
        return ""

    lines = []
    for i, ev in enumerate(events, 1):
        ev_type = ev.get("type", "unknown")
        ts = ev.get("timestamp", "")

        if ev_type == "thought":
            text = ev.get("text", "")
            duration = ev.get("duration_seconds", 0)
            lines.append(f"### Step {i} [{ts}] - Agent Thought ({duration:.1f}s)")
            lines.append(text)

        elif ev_type == "response":
            text = ev.get("text", "")
            lines.append(f"### Step {i} [{ts}] - Agent Response")
            lines.append(text)

        elif ev_type == "tool_use":
            tool_name = ev.get("tool_name", "") or "(unknown tool)"
            agent_msg = ev.get("agent_message", "")
            tool_input = ev.get("tool_input", "")
            model = ev.get("model", "")
            model_tag = f" (model={model})" if model else ""
            lines.append(f"### Step {i} [{ts}] - Tool: {tool_name}{model_tag}")
            if agent_msg:
                lines.append(f"Context: {agent_msg}")
            if tool_input:
                lines.append(f"Input: {tool_input}")

        elif ev_type == "file_edit":
            file_path = ev.get("file_path", "")
            chars_added = ev.get("chars_added", 0)
            chars_removed = ev.get("chars_removed", 0)
            lines.append(f"### Step {i} [{ts}] - File Edit: {file_path}")
            lines.append(f"  +{chars_added} / -{chars_removed} chars")
            full_old = ev.get("full_old_string")
            full_new = ev.get("full_new_string")
            if full_old is not None or full_new is not None:
                lines.append(f"  Old: {full_old or '(new content)'}")
                lines.append(f"  New: {full_new or '(deleted content)'}")

        elif ev_type == "shell_command":
            cmd = ev.get("command", "")
            model = ev.get("model", "")
            model_tag = f" (model={model})" if model else ""
            lines.append(f"### Step {i} [{ts}] - Shell Command{model_tag}")
            lines.append(f"  `{cmd}`")

        elif ev_type == "stop":
            status = ev.get("status", "")
            loops = ev.get("loop_count", 0)
            error = ev.get("error_message", "")
            model = ev.get("model", "")
            model_tag = f", model={model}" if model else ""
            error_tag = f", error={error}" if error else ""
            lines.append(f"### Step {i} [{ts}] - Agent Loop End (status={status}, loops={loops}{model_tag}{error_tag})")

        elif ev_type == "user_prompt":
            text = ev.get("prompt_text", "")
            lines.append(f"### Step {i} [{ts}] - User Prompt")
            lines.append(text)

        elif ev_type == "tool_result":
            tool_name = ev.get("tool_name", "")
            duration = ev.get("duration_ms", 0)
            model = ev.get("model", "")
            model_tag = f", model={model}" if model else ""
            tool_input = ev.get("tool_input", "")
            output = ev.get("tool_output", "")
            lines.append(f"### Step {i} [{ts}] - Tool Result: {tool_name} ({duration}ms{model_tag})")
            if tool_input:
                lines.append(f"Input: {tool_input}")
            if output:
                lines.append(f"Output: {output}")

        elif ev_type == "tool_failure":
            tool_name = ev.get("tool_name", "")
            failure_type = ev.get("failure_type", "")
            error = ev.get("error_message", "")
            tool_input = ev.get("tool_input", "")
            lines.append(f"### Step {i} [{ts}] - Tool FAILED: {tool_name} ({failure_type})")
            if tool_input:
                lines.append(f"Input: {tool_input}")
            if error:
                lines.append(f"Error: {error}")

        elif ev_type == "shell_result":
            cmd = ev.get("command", "")
            exit_code = ev.get("exit_code")
            is_success = ev.get("is_success")
            exit_status = "exit=?" if exit_code is None else f"exit={exit_code}{' ✓' if is_success else ' ✗'}"
            model = ev.get("model", "")
            model_tag = f", model={model}" if model else ""
            output = ev.get("output", "")
            lines.append(f"### Step {i} [{ts}] - Shell Result ({exit_status}{model_tag})")
            lines.append(f"  `{cmd}`")
            if output:
                lines.append(f"Output: {output}")

        elif ev_type == "file_read":
            file_path = ev.get("file_path", "")
            content = ev.get("content", "")
            lines.append(f"### Step {i} [{ts}] - File Read: {file_path}")
            if content:
                lines.append(f"Content: {content}")

        elif ev_type == "mcp_call":
            tool_name = ev.get("tool_name", "")
            model = ev.get("model", "")
            model_tag = f" (model={model})" if model else ""
            tool_input = ev.get("tool_input", "")
            lines.append(f"### Step {i} [{ts}] - MCP Call: {tool_name}{model_tag}")
            if tool_input:
                lines.append(f"Input: {tool_input}")

        elif ev_type == "mcp_result":
            tool_name = ev.get("tool_name", "")
            duration = ev.get("duration_ms", 0)
            model = ev.get("model", "")
            model_tag = f", model={model}" if model else ""
            tool_input = ev.get("tool_input", "")
            result = ev.get("result", "")
            lines.append(f"### Step {i} [{ts}] - MCP Result: {tool_name} ({duration}ms{model_tag})")
            if tool_input:
                lines.append(f"Input: {tool_input}")
            if result:
                lines.append(f"Result: {result}")

        elif ev_type == "subagent_start":
            subagent_type = ev.get("subagent_type", "")
            task = ev.get("task", "")
            lines.append(f"### Step {i} [{ts}] - Subagent Started: {subagent_type} - {task}")

        elif ev_type == "subagent_stop":
            status = ev.get("status", "")
            summary_text = ev.get("summary", "")
            tool_calls = ev.get("tool_call_count", 0)
            messages = ev.get("message_count", 0)
            duration = ev.get("duration_ms", 0)
            lines.append(f"### Step {i} [{ts}] - Subagent Stopped: {status}")
            lines.append(f"  Summary: {summary_text}")
            lines.append(f"  Duration: {duration}ms, Messages: {messages}, Tool calls: {tool_calls}")

        elif ev_type == "compaction":
            usage_pct = ev.get("context_usage_percent", 0)
            msg_count = ev.get("messages_to_compact", 0)
            trigger = ev.get("trigger", "")
            lines.append(f"### Step {i} [{ts}] - Context Compaction ({usage_pct}% used, {msg_count} messages compacted, trigger={trigger})")

        lines.append("")  # blank separator

    return "\n".join(lines)


def build_context(state: SummarizerState) -> SummarizerState:
    """Format events into LLM context."""
    events = state.get("events", [])
    strategy = state.get("strategy", "skip")

    try:
        recorder = ConversationRecorder()
        session = recorder.load_session(state["session_id"])
    except Exception:
        session = {}

    last_count = session.get("summary", {}).get("last_summary_event_count", 0)
    formatted = _format_events(events, strategy, last_count)

    if not formatted:
        print("[summarizer] No events to format after filtering, skipping", file=sys.stderr)
        return {**state, "strategy": "skip"}

    return {**state, "formatted_context": formatted}


def generate_summary(state: SummarizerState) -> SummarizerState:
    """Call the LLM to generate the narrative and/or structured summary."""
    strategy = state.get("strategy", "full_regenerate")
    previous_summary = state.get("previous_summary", "")
    formatted = state.get("formatted_context", "")
    structured_only = state.get("structured_only", False)

    if strategy == "delta_update" and previous_summary:
        context_line = (
            "Here is the existing summary to update:\n\n"
            f"{previous_summary}\n\n"
            "Incorporate the new events below into it. "
            "Rewrite the full updated summary."
        )
    else:
        context_line = ""

    # Build narrative prompt (only if not structured_only)
    narrative_prompt = ""
    if not structured_only:
        narrative_prompt = (
            "Produce a concise narrative summary covering:\n"
            "1. What the user was trying to accomplish\n"
            "2. Key actions the agent took and why\n"
            "3. Important decisions, trade-offs, or reasoning patterns\n"
            "4. Files modified and what changed\n"
            "5. Tool usage patterns, failures, and MCP calls\n"
            "6. Subagent work (if any) and its outcomes\n"
            "7. Outcome and any remaining open questions\n\n"
            "Write in a clear, professional tone. Keep it under 500 words.\n"
            "Use markdown formatting.\n"
        )

        # If sentiment data exists, add instruction to weave it into the narrative
        sentiment_block = get_sentiment_context(state["session_id"])
        if sentiment_block:
            narrative_prompt += (
                "Interaction Pattern:\n"
                "The sentiment analysis below describes how the user's experience evolved. "
                "Reference it naturally in your narrative — e.g., mention frustration spikes, "
                "recovery moments, or smooth progress. Don't just repeat the data; integrate it.\n\n"
            )

    # Always produce structured JSON output
    structured_prompt = (
        "ALSO produce a JSON structured summary enclosed in ```json ... ``` code block.\n"
        "The JSON must match this schema exactly:\n"
        "{\n"
        '  "objectives": ["list of what the user was trying to accomplish"],\n'
        '  "files_modified": ["list of files that were changed"],\n'
        '  "files_created": ["list of new files created"],\n'
        '  "files_deleted": ["list of files removed"],\n'
        '  "decisions": [{"decision": "...", "reason": "...", "alternatives_considered": "..."}],\n'
        '  "errors_encountered": [{"error": "...", "context": "...", "resolution": "..."}],\n'
        '  "tool_usage_summary": {"tool_name": {"calls": N, "failures": N, "success_rate": 0.0}},\n'
        '  "subagent_work": [{"subagent_type": "...", "task": "...", "outcome": "...", "tool_calls": N}],\n'
        '  "code_patterns": ["notable patterns like added retry logic, extracted helper function"],\n'
        '  "open_questions": ["unresolved items or future work"],\n'
        '  "outcome": "one-line result",\n'
        '  "session_type": "feature|bugfix|refactor|exploration|documentation|config|testing|deployment|other"\n'
        "}\n"
        "Only use the session_type values listed above. "
        "Use empty lists [] for fields with no data, not null. "
        "Do NOT include fabricated files or tools."
    )

    # Combine prompts
    instruction_parts = []
    if narrative_prompt:
        instruction_parts.append(narrative_prompt)
    instruction_parts.append(structured_prompt)

    system_prompt = (
        f"You are summarizing a recorded AI coding assistant (Cursor) session.\n\n"
        f"{context_line}\n"
        f"Session events (chronological timeline):\n"
        f"{formatted}\n\n"
    )

    # Inject sentiment context if available
    sentiment_block = get_sentiment_context(state["session_id"])
    if sentiment_block:
        system_prompt += sentiment_block + "\n"

    system_prompt += (
        "Event types you may see:\n"
        "- User Prompt, Agent Thought, Agent Response, Agent Loop End\n"
        "- Tool, Tool Result, Tool FAILED\n"
        "- File Edit, File Read\n"
        "- Shell Command, Shell Result\n"
        "- MCP Call, MCP Result\n"
        "- Subagent Started, Subagent Stopped\n"
        "- Context Compaction\n\n"
        + "\n".join(instruction_parts)
    )

    human_prompt = "Generate the session summary."
    if structured_only:
        human_prompt = "Generate the structured JSON summary only (no narrative needed)."

    try:
        llm = get_llm()
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_prompt),
        ])
        content = response.content

        # Retry if empty
        if not content or not content.strip():
            print("[summarizer] Empty LLM response, retrying with explicit prompt", file=sys.stderr)
            retry_prompt = "You MUST produce a summary based on the events above. Even a short session should get a brief summary."
            if structured_only:
                retry_prompt = "You MUST produce a JSON structured summary based on the events above."
            response = llm.invoke([
                SystemMessage(content=retry_prompt),
                HumanMessage(content=formatted),
            ])
            content = response.content

        if not content or not content.strip():
            return {**state, "error": "LLM returned empty response after retry", "narrative_summary": "", "structured_summary": _make_empty_structured_summary()}

        result = {"narrative_summary": "", "structured_summary": {}}

        if structured_only:
            # Only extract structured
            structured = _extract_structured_summary(content)
            result["structured_summary"] = structured
        else:
            # Extract narrative (everything before the ```json block)
            narrative_text = _extract_narrative_from_combined(str(content))
            result["narrative_summary"] = narrative_text

            # Extract structured JSON from the response
            structured = _extract_structured_summary(content)
            result["structured_summary"] = structured

        return {**state, **result}

    except Exception as e:
        print(f"[summarizer] LLM error: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return {
            **state,
            "error": str(e),
            "narrative_summary": "",
            "structured_summary": _make_empty_structured_summary(f"LLM error: {e}"),
        }


def _extract_narrative_from_combined(content: str) -> str:
    """Extract narrative text, stripping out the ```json block."""
    # Remove ```json ... ``` blocks
    content_str = str(content)
    # Remove JSON code blocks
    pattern = r"```json\s*[\s\S]*?```\s*"
    narrative = re.sub(pattern, "", content_str).strip()
    # Remove any other code blocks
    pattern2 = r"```\s*[\s\S]*?```\s*"
    narrative = re.sub(pattern2, "", narrative).strip()
    if not narrative:
        narrative = content_str.strip()
    return narrative


def _extract_structured_summary(content) -> dict:
    """Extract and validate structured JSON from LLM output.

    Strategy:
    1. Try to find ```json ... ``` block
    2. If not found, try to find any {...} block
    3. If parsing fails, attempt auto-repair
    4. If all else fails, return empty structured summary with parse_error flag
    """
    content_str = str(content)

    # Strategy 1: Extract from ```json block
    json_match = re.search(r"```json\s*([\s\S]*?)```", content_str)
    if json_match:
        json_text = json_match.group(1).strip()
        structured = _parse_structured_json(json_text)
        if structured and "parse_error" not in structured:
            return structured

    # Strategy 2: Find any top-level JSON object containing expected keys
    # Look for patterns like { ... "objectives" ... }
    brace_match = re.search(r"\{[\s\S]*?(?:objectives|session_type|outcome)[\s\S]*?\}", content_str)
    if brace_match:
        json_text = brace_match.group(0).strip()
        structured = _parse_structured_json(json_text)
        if structured and "parse_error" not in structured:
            return structured

    # Strategy 3: Try the entire content as JSON (unlikely but worth trying)
    stripped = content_str.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        structured = _parse_structured_json(stripped)
        if structured and "parse_error" not in structured:
            return structured

    # All strategies failed
    debug_log = lambda msg: print(f"[summarizer] {msg}", file=sys.stderr)
    debug_log(f"Structured JSON extraction failed — returning empty structure")
    empty = _make_empty_structured_summary("Could not extract structured summary from LLM output")
    empty["_parse_error"] = True
    empty["_raw_response_first_500"] = content_str[:500]
    return empty


def _parse_structured_json(json_text: str) -> dict:
    """Parse and validate structured JSON with auto-repair attempts."""
    # First, try strict JSON parsing
    try:
        data = json.loads(json_text)
        return _validate_and_finalize_structured(data)
    except json.JSONDecodeError:
        pass

    # Attempt auto-repair
    repaired = _attempt_json_repair(json_text)
    if repaired is not None:
        try:
            data = json.loads(repaired)
            return _validate_and_finalize_structured(data)
        except json.JSONDecodeError:
            pass

    # Repair failed
    return {}


def _attempt_json_repair(text: str) -> str | None:
    """Attempt to fix common JSON issues in LLM output."""
    original = text

    # Strip control characters except newlines and tabs
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)

    # Remove trailing commas before } or ]
    text = re.sub(r",\s*([}\]])", r"\1", text)

    # Fix unquoted keys (e.g., {key: "value"} -> {"key": "value"})
    text = re.sub(r"(?<=\{|,)\s*([a-zA-Z_]\w*)\s*:", r' "\1":', text)

    # Fix single quotes to double quotes (careful: only outside string values)
    # Simple approach: replace all single quotes if no double quotes in the text
    if '"' not in text and "'" in text:
        text = text.replace("'", '"')

    # Add missing commas between key-value pairs
    text = re.sub(r'"\s*"\n\s*"', '",\n"', text)

    if text != original:
        return text
    return None


def _validate_and_finalize_structured(data: dict) -> dict:
    """Validate structured summary against schema, apply caps, scrub secrets."""
    if not isinstance(data, dict):
        return _make_empty_structured_summary()

    structured = dict(data)

    # Ensure schema version
    structured["schema_version"] = STRUCTURED_SUMMARY_SCHEMA_VERSION

    # Ensure all required keys exist with defaults
    defaults = _make_empty_structured_summary()
    for key, default_val in defaults.items():
        if key not in structured:
            structured[key] = default_val

    # Ensure list fields are actually lists
    for list_key in ("objectives", "files_modified", "files_created", "files_deleted",
                      "decisions", "errors_encountered", "subagent_work",
                      "code_patterns", "open_questions"):
        if not isinstance(structured.get(list_key), list):
            structured[list_key] = []

    # Scrub secrets from string fields in structured output
    scrubbed_any = False
    for decision in structured.get("decisions", []):
        if isinstance(decision, dict):
            for k in ("decision", "reason", "alternatives_considered"):
                if k in decision and isinstance(decision[k], str):
                    scrubbed, was = _scrub_secrets(decision[k])
                    decision[k] = scrubbed
                    scrubbed_any = scrubbed_any or was
    for error in structured.get("errors_encountered", []):
        if isinstance(error, dict):
            for k in ("error", "context", "resolution"):
                if k in error and isinstance(error[k], str):
                    scrubbed, was = _scrub_secrets(error[k])
                    error[k] = scrubbed
                    scrubbed_any = scrubbed_any or was

    if scrubbed_any:
        structured["_secrets_scrubbed"] = True

    return structured


def save_summary(state: SummarizerState) -> SummarizerState:
    """Persist the summary to SQLite only (no JSON summary files)."""
    session_id = state["session_id"]
    narrative = state.get("narrative_summary", "")
    structured = state.get("structured_summary", {})
    error = state.get("error", "")
    strategy = state.get("strategy", "full_regenerate")

    try:
        recorder = ConversationRecorder()

        # Load fresh session.json (race condition guard)
        session = recorder.load_session(session_id)
        events = session.get("events", [])
        current_event_count = len(events)

        # Run verification on structured output
        if structured and isinstance(structured, dict) and not structured.get("_parse_error"):
            warnings = _verify_structured_summary(structured, events)
            if warnings:
                existing_warnings = structured.get("_verification_warnings", [])
                existing_warnings.extend(warnings)
                structured["_verification_warnings"] = existing_warnings

        if error and not narrative:
            narrative = f"[Summarization failed: {error}]"

        # Inject sentiment arc data into structured summary (Phase 2)
        structured = inject_sentiment_into_structured(session_id, structured)

        # Use a single timestamp for all writes to ensure consistency
        generated_at = datetime.now().isoformat()

        # Store only summary metadata (no narrative or structured content)
        existing_summary = session.get("summary", {})
        summary_data = {
            "generated_at": generated_at,
            "strategy": strategy,
            "event_count_at_summary": current_event_count,
            "last_summary_event_count": current_event_count,
        }

        # Merge with existing summary fields (preserve stats from session_end.py)
        for key in ("total_events", "total_responses", "total_thoughts",
                     "total_thinking_time_ms", "total_thinking_time_seconds",
                     "total_file_edits", "unique_files_edited",
                     "total_shell_commands", "total_tool_uses",
                     "tool_usage_breakdown", "net_code_change",
                     "total_chars_added", "total_chars_removed",
                     "finalized_at", "end_reason", "session_duration_ms",
                     "session_duration_seconds", "final_status", "error_message"):
            if key in existing_summary:
                summary_data[key] = existing_summary[key]

        session["summary"] = summary_data
        recorder.save_session(session_id, session)

        # Mark for debounce
        mark_summarized(session_id)

        # Persist to SQLite only (fail-open)
        try:
            from narratives_db import NarrativesDB
            with NarrativesDB() as db:
                if narrative:
                    db.upsert_narrative(
                        session_id=session_id,
                        narrative=narrative,
                        generated_at=generated_at,
                        strategy=strategy,
                        event_count_at_summary=current_event_count,
                    )
                if structured:
                    db.upsert_structured_summary(
                        session_id=session_id,
                        structured_json=structured,
                        generated_at=generated_at,
                    )
        except Exception as e:
            print(f"[summarizer] SQLite write failed: {e}", file=sys.stderr)

        print(
            f"[summarizer] Summary saved for {session_id} "
            f"(strategy={strategy}, events={current_event_count}, "
            f"structured={'yes' if structured else 'no'})",
            file=sys.stderr,
        )

    except Exception as e:
        print(f"[summarizer] Failed to save summary for {session_id}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)

    return state


# ---------------------------------------------------------------------------
# Graph definition
# ---------------------------------------------------------------------------

def _format_context_or_skip(state: SummarizerState) -> str:
    """Route after build_context: skip if no events to format."""
    strategy = state.get("strategy", "skip")
    if strategy == "skip":
        return END
    return "generate_summary"


def _route_after_load(state: SummarizerState) -> str:
    """Route after load_and_check: if skip, go to save_structured_minimal instead of END."""
    if state.get("strategy") == "skip":
        return "save_structured_minimal"
    return "build_context"


def save_structured_minimal(state: SummarizerState) -> SummarizerState:
    """Save a minimal structured summary for sessions that were skipped (no new events or empty)."""
    session_id = state["session_id"]
    if state.get("structured_summary"):
        # Already has structured from a previous run, nothing to do
        return state

    try:
        recorder = ConversationRecorder()
        session = recorder.load_session(session_id)
        events = session.get("events", [])
        current_event_count = len(events)

        # Check if already has structured summary in SQLite
        try:
            from narratives_db import NarrativesDB
            with NarrativesDB() as db:
                if db.get_structured_summary(session_id):
                    return state
        except Exception:
            pass

        minimal = _make_empty_structured_summary(
            f"Session skipped summarization (strategy={state.get('strategy')}, events={current_event_count})"
        )

        summary_data = {
            "generated_at": datetime.now().isoformat(),
            "strategy": state.get("strategy", "skip"),
            "event_count_at_summary": current_event_count,
            "last_summary_event_count": current_event_count,
        }

        # Preserve existing stats
        existing_summary = session.get("summary", {})
        for key in ("total_events", "total_responses", "total_thoughts",
                     "total_thinking_time_ms", "total_thinking_time_seconds",
                     "total_file_edits", "unique_files_edited",
                     "total_shell_commands", "total_tool_uses",
                     "tool_usage_breakdown", "net_code_change",
                     "total_chars_added", "total_chars_removed",
                     "finalized_at", "end_reason", "session_duration_ms",
                     "session_duration_seconds", "final_status", "error_message"):
            if key in existing_summary:
                summary_data[key] = existing_summary[key]

        session["summary"] = summary_data
        recorder.save_session(session_id, session)

        # Persist to SQLite only
        try:
            from narratives_db import NarrativesDB
            with NarrativesDB() as db:
                db.upsert_structured_summary(
                    session_id=session_id,
                    structured_json=minimal,
                    generated_at=summary_data["generated_at"],
                )
        except Exception as e:
            print(f"[summarizer] SQLite minimal structured write failed: {e}", file=sys.stderr)

        print(
            f"[summarizer] Minimal structured summary saved for {session_id} "
            f"(strategy=skip, events={current_event_count})",
            file=sys.stderr,
        )

    except Exception as e:
        print(f"[summarizer] Failed to save minimal structured summary for {session_id}: {e}", file=sys.stderr)

    return state


# ---------------------------------------------------------------------------
# Sentiment context injection
# ---------------------------------------------------------------------------

def get_sentiment_context(session_id: str) -> str:
    """Read sentiment arc data and format as LLM context block.

    Fail-open: returns empty string if arc data unavailable.
    """
    try:
        from sentiment_arc.arc_db import get_arc_features_for_session, init_arc_tables

        conn = init_arc_tables()
        arc = get_arc_features_for_session(conn, session_id)
        conn.close()

        if arc is None:
            return ""

        archetype = arc.get("archetype", "")
        if not archetype or archetype in ("too_short", "inconclusive", "error"):
            return ""

        parts = ["## Session Interaction Pattern"]
        parts.append(f"- Archetype: {archetype}")

        confidence = arc.get("archetype_confidence")
        if confidence is not None:
            parts.append(f"- Confidence: {confidence:.2f}")

        slope = arc.get("arc_slope")
        if slope is not None:
            direction = "improving" if slope > 0.005 else "declining" if slope < -0.005 else "stable"
            parts.append(f"- Sentiment trend: {direction} (slope={slope:.4f})")

        avg_sent = arc.get("avg_sentiment")
        if avg_sent is not None:
            tone = "positive" if avg_sent > 0.1 else "negative" if avg_sent < -0.1 else "neutral"
            parts.append(f"- Overall tone: {tone}")

        recovery = arc.get("recovery_events")
        if recovery and recovery > 0:
            parts.append(f"- Recovery events: {recovery} (user bounced back after setbacks)")

        mismatched = arc.get("mismatched_effort_score")
        if mismatched is not None and mismatched > 0.5:
            parts.append("- Note: high effort-to-outcome mismatch detected")

        user_trend = arc.get("user_sentiment_trend")
        assist_trend = arc.get("assistant_sentiment_trend")
        gap = arc.get("sentiment_gap")
        if user_trend is not None and assist_trend is not None and gap is not None:
            if gap > 0.2:
                parts.append("- Note: assistant was noticeably more optimistic than the user")
            elif gap < -0.2:
                parts.append("- Note: user was more optimistic than the assistant")

        parts.append("")
        return "\n".join(parts)

    except Exception:
        return ""


def inject_sentiment_into_structured(session_id: str, structured: dict) -> dict:
    """Read sentiment arc data and enrich the structured summary dict.

    Fail-open: returns struct unchanged if arc data unavailable.
    """
    try:
        from sentiment_arc.arc_db import get_arc_features_for_session, init_arc_tables

        conn = init_arc_tables()
        arc = get_arc_features_for_session(conn, session_id)
        conn.close()

        if arc is None:
            return structured

        structured["sentiment_archetype"] = arc.get("archetype", "")
        structured["sentiment_confidence"] = arc.get("archetype_confidence", 0.0)
        structured["arc_slope"] = arc.get("arc_slope")
        structured["avg_sentiment"] = arc.get("avg_sentiment")
        structured["recovery_events"] = arc.get("recovery_events", 0)
        structured["mismatched_effort_score"] = arc.get("mismatched_effort_score")
        structured["sentiment_gap"] = arc.get("sentiment_gap")
        structured["user_sentiment_trend"] = arc.get("user_sentiment_trend")
        structured["assistant_sentiment_trend"] = arc.get("assistant_sentiment_trend")

        return structured
    except Exception:
        return structured


def generate_learning(state: SummarizerState) -> SummarizerState:
    """Analyze the completed session and update .cursor/rules/learning.mdc with new patterns."""
    session_id = state.get("session_id", "")
    if not session_id:
        return state
    try:
        from learning_analyzer import LearningAnalyzer, extract_correction_rules, STATE_DIR, _count_sessions

        analyzer = LearningAnalyzer()
        analyzer.update_from_session(session_id)

        # Hermes-style correction detection: scan transcript for user corrections
        transcript_path = STATE_DIR / "sessions" / session_id / "session.json"
        correction_rules = extract_correction_rules(transcript_path)
        if correction_rules:
            analyzer.total_sessions_analyzed = _count_sessions()
            analyzer.write_learning_mdc(correction_rules)
    except Exception as e:
        print(f"[summarizer] Learning update failed for {session_id}: {e}", file=sys.stderr)
    return state


def build_graph():
    builder = StateGraph(SummarizerState)
    builder.add_node("load_and_check", load_and_check)
    builder.add_node("build_context", build_context)
    builder.add_node("generate_summary", generate_summary)
    builder.add_node("save_summary", save_summary)
    builder.add_node("save_structured_minimal", save_structured_minimal)
    builder.add_node("generate_learning", generate_learning)

    builder.add_edge(START, "load_and_check")
    builder.add_conditional_edges("load_and_check", _route_after_load, {
        "build_context": "build_context",
        "save_structured_minimal": "save_structured_minimal",
    })
    builder.add_conditional_edges("build_context", _format_context_or_skip, {
        "generate_summary": "generate_summary",
        END: "generate_learning",
    })
    builder.add_edge("generate_summary", "save_summary")
    builder.add_edge("save_summary", "generate_learning")
    builder.add_edge("save_structured_minimal", "generate_learning")
    builder.add_edge("generate_learning", END)

    return builder.compile()


graph = build_graph()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: summarizer_agent.py <session_id> [--force] [--regenerate] [--structured]", file=sys.stderr)
        sys.exit(1)

    session_id = sys.argv[1]
    force = "--force" in sys.argv
    regenerate = "--regenerate" in sys.argv
    structured_only = "--structured" in sys.argv

    # Acquire lock
    if not acquire_lock(session_id):
        print(f"[summarizer] Another summarizer is running for {session_id}, skipping", file=sys.stderr)
        sys.exit(0)

    try:
        result = graph.invoke({
            "session_id": session_id,
            "force": force,
            "regenerate": regenerate,
            "structured_only": structured_only,
        })

        strategy = result.get("strategy", "unknown")
        if strategy == "skip":
            print(f"[summarizer] Session {session_id} skipped/minimal save (strategy=skip)", file=sys.stderr)
        elif result.get("error"):
            print(f"[summarizer] Error for {session_id}: {result['error']}", file=sys.stderr)
        else:
            has_structured = bool(result.get("structured_summary"))
            has_narrative = bool(result.get("narrative_summary"))
            print(f"[summarizer] Done: {session_id} (strategy={strategy}, "
                  f"structured={'yes' if has_structured else 'no'}, "
                  f"narrative={'yes' if has_narrative else 'no'})", file=sys.stderr)

    finally:
        release_lock(session_id)


if __name__ == "__main__":
    main()
