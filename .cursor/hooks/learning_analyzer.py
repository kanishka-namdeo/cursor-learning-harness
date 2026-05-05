#!/usr/bin/env python3
"""
Learning Analyzer — Auto-generates .cursor/rules/learning.mdc from session telemetry.

Extracts holistic learning signals from the existing SQLite database and session
JSON files, then produces actionable markdown rule entries that Cursor IDE
automatically includes in every conversation.

Usage:
    python learning_analyzer.py --bootstrap     # Generate learning.mdc from all sessions
    python learning_analyzer.py --update <sid>  # Update from a single session
    python learning_analyzer.py --status        # Show current rules and confidence
"""

import hashlib
import json
import re
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# Resolve paths relative to this script
HOOKS_DIR = Path(__file__).parent.resolve()
STATE_DIR = HOOKS_DIR / "state"
LEARNING_MDC_PATH = HOOKS_DIR.parent / "rules" / "learning.mdc"
RULE_USAGE_PATH = STATE_DIR / "rule_usage.json"

sys.path.insert(0, str(HOOKS_DIR))

# --- Category prefixes for rule IDs ---
CATEGORY_PREFIX = {
    "Tool Failures": "TF",
    "Shell Commands": "SC",
    "Sentiment Patterns": "SP",
    "File Hotspots": "FH",
    "Compaction Patterns": "CP",
    "Decision Quality": "DQ",
    "Subagent Patterns": "SA",
    "Successful Patterns": "OK",
    "Procedural Patterns": "PP",
    "Correction Rules": "CR",
}

# Thresholds
STALE_SESSIONS_THRESHOLD = 20
MIN_ACTIVE_COUNT = 2
MAX_ACTIVE_RULES = 25
MAX_CRITICAL_RULES = 10  # Hermes-style progressive disclosure: alwaysApply file cap
MAX_EXTRACT_SESSIONS = 100  # memory limit for extract_all queries
MIN_HOTSPOT_PCT = 15.0
FILE_NOT_FOUND_NOISE_THRESHOLD = 1  # single-occurrence file-not-found rules are noise
PROCEDURAL_THRESHOLD = 3  # Hermes-style: require 3+ successful completions before promoting a procedure

# Negative sentiment archetypes (indicate poor outcomes)
NEGATIVE_ARCHETYPES = {"escalating_frustration", "looping", "abandoned", "steady_friction", "mismatched_effort"}
POSITIVE_ARCHETYPES = {"smooth_convergence", "rapid_resolution"}


def _strip_frontmatter_backup(source: Path, dest: Path) -> None:
    """Copy source to dest, stripping YAML frontmatter so Cursor doesn't load it as a rule."""
    content = source.read_text(encoding="utf-8")
    # Remove YAML frontmatter block (--- ... ---)
    if content.startswith("---"):
        end_idx = content.find("---\n", 4)
        if end_idx != -1:
            content = content[end_idx + 4:].lstrip()
    dest.write_text(content, encoding="utf-8")


# Task category buckets for subagent pattern grouping
TASK_CATEGORY_KEYWORDS = [
    ("Explore", ["explore", "find", "search", "discover", "scan"]),
    ("Execute plan", ["execute", "implement", "build", "create", "continue", "phase"]),
    ("Test", ["test", "verify", "check", "validate", "confirm"]),
    ("Debug", ["debug", "fix", "troubleshoot", "investigate", "find.*bug"]),
    ("Resume", ["resume", "continue", "pick up", "follow up"]),
]

# User correction patterns (Hermes-style: detects explicit user feedback as strong signal)
CORRECTION_PATTERNS = [
    r"(?:no,\s*(?:that'?s\s+)?(?:wrong|incorrect|not\s+right|not\s+correct))",
    r"you\s+should\s+(?:have\s+)?(?:look|check|read|use|try)",
    r"why\s+did\s+(?:i\s+have\s+to|you\s+not)",
    r"that'?s\s+not\s+(?:what|correct|right)",
    r"(?:i\s+already\s+(?:told|said|asked))",
    r"(?:please\s+(?:investigate|do)\s+(?:this\s+)?(?:yourself|by\s+yourself))",
    r"(?:stop\s+(?:doing|trying))",
    r"(?:don'?t\s+(?:do|use|try|call))",
    r"(?:you\s+need\s+to\s+(?:look|check|read))",
    r"(?:look\s+at\s+(?:the\s+)?(?.+?)\s+first)",
    r"(?:you\s+missed)",
    r"(?:that\s+is\s+not\s+what\s+i\s+asked)",
]

# Tool call sequences that indicate a procedural pattern (Hermes-style procedural memory)
# Sequences are stored as comma-separated tool names in session transcripts
PROCEDURAL_SEQUENCE_PATTERNS = [
    ("Grep or SemanticSearch", "Read", "StrReplace or Write", "Shell"),
    ("Read", "SemanticSearch", "StrReplace"),
    ("SemanticSearch", "Read", "StrReplace", "Shell"),
]

# --- Helper: import NarrativesDB lazily ---

def get_db():
    from narratives_db import NarrativesDB
    return NarrativesDB()


# =============================================================================
# Rule Usage Tracking
# =============================================================================

def load_rule_usage() -> dict:
    """Load rule usage data from JSON file."""
    if not RULE_USAGE_PATH.exists():
        return {}
    try:
        with open(RULE_USAGE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_rule_usage(usage: dict) -> None:
    """Save rule usage data to JSON file."""
    RULE_USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RULE_USAGE_PATH, "w", encoding="utf-8") as f:
        json.dump(usage, f, indent=2)


def track_rule_usage(session_id: str, transcript_text: str, rule_ids: list[str]) -> None:
    """Check if a session transcript references any learning.mdc rule IDs."""
    usage = load_rule_usage()
    for rule_id in rule_ids:
        if rule_id in transcript_text:
            if rule_id not in usage:
                usage[rule_id] = {"referenced_sessions": [], "total_refs": 0}
            if session_id not in usage[rule_id]["referenced_sessions"]:
                usage[rule_id]["referenced_sessions"].append(session_id)
            usage[rule_id]["total_refs"] = usage[rule_id].get("total_refs", 0) + 1
    save_rule_usage(usage)


# =============================================================================
# Signal Extractors
# =============================================================================

def _get_session_sentiment_map(db) -> dict[str, str]:
    """Build a map of session_id -> sentiment_archetype for outcome scoring."""
    result = {}
    try:
        with db._conn:
            cur = db._conn.execute(
                "SELECT session_id, sentiment_archetype FROM structured_summaries "
                "WHERE sentiment_archetype IS NOT NULL AND sentiment_archetype != ''"
            )
            for row in cur.fetchall():
                row_dict = dict(row)
                result[row_dict["session_id"]] = row_dict["sentiment_archetype"]
    except Exception:
        pass
    return result


def compute_rule_effectiveness(rules: list[dict], sentiment_map: dict[str, str]) -> None:
    """Add effectiveness_score to each rule by correlating with session outcomes.

    Modifies rules in-place.
    """
    for rule in rules:
        sessions = rule.get("evidence_sessions", [])
        if not sessions:
            rule["effectiveness_score"] = "insufficient_data"
            continue

        negative_count = 0
        positive_count = 0
        neutral_count = 0

        for sid in sessions:
            arch = sentiment_map.get(sid, "")
            if arch in NEGATIVE_ARCHETYPES:
                negative_count += 1
            elif arch in POSITIVE_ARCHETYPES:
                positive_count += 1
            else:
                neutral_count += 1

        total = negative_count + positive_count
        if total < 2:
            rule["effectiveness_score"] = "insufficient_data"
        elif negative_count > positive_count and negative_count / total >= 0.6:
            rule["effectiveness_score"] = "negative"
            rule["negative_outcome_count"] = negative_count
            rule["total_outcome_count"] = total
        elif positive_count > negative_count and positive_count / total >= 0.6:
            rule["effectiveness_score"] = "positive"
            rule["positive_outcome_count"] = positive_count
            rule["total_outcome_count"] = total
        else:
            rule["effectiveness_score"] = "neutral"


def cluster_file_errors(error_files: list[str], min_cluster: int = 2) -> dict[str, list[str]]:
    """Group file-not-found errors by parent directory to find root causes."""
    clusters = defaultdict(list)
    for filepath in error_files:
        p = Path(filepath)
        # Use the first two directory levels as cluster key
        parts = p.parts
        if len(parts) >= 3:
            cluster_key = str(Path(*parts[:3]))
        else:
            cluster_key = str(p.parent)
        clusters[cluster_key].append(filepath)
    return {k: v for k, v in clusters.items() if len(v) >= min_cluster}


def extract_tool_failures(db, session_id: str | None = None) -> list[dict]:
    """Extract tool failure patterns with root-cause clustering for file-not-found errors."""
    results = []

    if session_id:
        events = db.get_events_by_session(session_id, event_type="tool_failure")
    else:
        with db._conn:
            cur = db._conn.execute(
                "SELECT * FROM hook_events WHERE event_type = 'tool_failure' ORDER BY timestamp ASC"
            )
            events = [dict(row) for row in cur.fetchall()]

    # Separate file-not-found errors from other failures
    file_not_found_errors = defaultdict(list)  # directory -> [(session_id, filepath)]
    other_failures = defaultdict(list)  # (tool, ftype, err) -> [session_id]

    for ev in events:
        detail = json.loads(ev.get("detail_json", "{}"))
        tool_name = detail.get("tool_name", ev.get("model", "unknown"))
        error_msg = detail.get("error_message", "")
        failure_type = detail.get("failure_type", "unknown")

        if "File not found" in error_msg:
            # Extract the filepath from the error message
            m = re.search(r"File not found:\s*(.+)", error_msg)
            filepath = m.group(1).strip() if m else error_msg
            # Use directory as cluster key
            p = Path(filepath)
            cluster_key = str(Path(*p.parts[:3])) if len(p.parts) >= 3 else str(p.parent)
            file_not_found_errors[cluster_key].append((ev["session_id"], filepath))
        else:
            error_preview = error_msg[:200] if error_msg else ""
            other_failures[(tool_name, failure_type, error_preview)].append(ev["session_id"])

    # Create clustered rules for file-not-found errors
    for dir_key, session_file_pairs in file_not_found_errors.items():
        sessions = list(set(s for s, _ in session_file_pairs))
        if len(sessions) < FILE_NOT_FOUND_NOISE_THRESHOLD:
            continue

        # Collect example files
        example_files = list(set(f for _, f in session_file_pairs))[:5]
        example_str = ", ".join(Path(f).name for f in example_files)

        results.append({
            "category": "Tool Failures",
            "pattern": f"Read tool fails with 'File not found' in `{dir_key}/` — stale or transient data (sessions: {len(sessions)})",
            "lesson": (
                f"Files in `{dir_key}/` may be deleted during compaction or between sessions. "
                f"Examples: {example_str}. "
                f"Check file existence before reading and handle gracefully with a default or skip."
            ),
            "evidence_sessions": sessions,
            "count": len(sessions),
            "evidence_files": example_files,
            "clustered": True,
        })

    # Create rules for other failures
    for (tool, ftype, err), sessions in other_failures.items():
        if len(sessions) < 1:
            continue
        results.append({
            "category": "Tool Failures",
            "pattern": f"The `{tool}` tool fails with {ftype} error: `{err}`" if err else f"The `{tool}` tool fails with {ftype} error",
            "lesson": f"Investigate why `{tool}` fails with {ftype} and handle this case explicitly. Check input parameters and file state before calling.",
            "evidence_sessions": list(set(sessions)),
            "count": len(sessions),
            "evidence_files": [],
        })

    return results


def extract_shell_failures(db, session_id: str | None = None) -> list[dict]:
    """Extract shell commands that commonly fail (non-zero exit codes)."""
    results = []

    if session_id:
        events = db.get_events_by_session(session_id, event_type="shell_result")
    else:
        with db._conn:
            cur = db._conn.execute(
                "SELECT * FROM hook_events WHERE event_type = 'shell_result' ORDER BY timestamp ASC"
            )
            events = [dict(row) for row in cur.fetchall()]

    failure_counts = defaultdict(list)
    for ev in events:
        detail = json.loads(ev.get("detail_json", "{}"))
        exit_code = detail.get("exit_code")
        is_success = detail.get("is_success", True)
        if exit_code is not None and exit_code != 0 and not is_success:
            cmd = detail.get("command", "")[:150]
            output_preview = detail.get("output", "")[:100].strip()
            failure_counts[(cmd, output_preview)].append(ev["session_id"])

    for (cmd, output), sessions in failure_counts.items():
        if len(sessions) < 1 or not cmd:
            continue
        results.append({
            "category": "Shell Commands",
            "pattern": f"Shell command `{cmd}` fails with exit code (sessions: {len(sessions)})",
            "lesson": f"Verify prerequisites and environment before running `{cmd}`. Check if the command needs elevated permissions or specific working directory.",
            "evidence_sessions": list(set(sessions)),
            "count": len(sessions),
            "evidence_files": [],
        })

    return results


def extract_file_hotspots(db) -> list[dict]:
    """Find files edited frequently enough to be meaningful hotspots."""
    results = []

    with db._conn:
        cur = db._conn.execute(
            "SELECT files_modified, session_id FROM structured_summaries WHERE files_modified IS NOT NULL"
        )
        rows = [dict(row) for row in cur.fetchall()]

    file_session_map = defaultdict(set)
    for row in rows:
        try:
            files = json.loads(row["files_modified"])
            sid = row["session_id"]
            for f in files:
                if f:
                    file_session_map[f].add(sid)
        except (json.JSONDecodeError, TypeError):
            pass

    total_sessions = len(rows)
    for filepath, sessions in file_session_map.items():
        freq = len(sessions)
        pct = round(freq / max(total_sessions, 1) * 100, 1)
        if pct < MIN_HOTSPOT_PCT:
            continue
        results.append({
            "category": "File Hotspots",
            "pattern": f"`{filepath}` is edited in {freq}/{total_sessions} sessions ({pct}%)",
            "lesson": f"Before modifying `{filepath}`, review existing patterns and conventions in the file. It's a frequently modified hotspot — changes may have downstream effects.",
            "evidence_sessions": list(sessions),
            "count": freq,
            "evidence_files": [filepath],
        })

    results.sort(key=lambda x: x["count"], reverse=True)
    return results[:15]


def extract_sentiment_patterns(db, session_id: str | None = None) -> list[dict]:
    """Extract lessons from sentiment archetypes."""
    results = []

    if session_id:
        with db._conn:
            cur = db._conn.execute(
                "SELECT session_id, sentiment_archetype, arc_slope, avg_sentiment, recovery_events, mismatched_effort_score "
                "FROM structured_summaries WHERE session_id = ? AND sentiment_archetype != ''",
                (session_id,),
            )
            rows = [dict(row) for row in cur.fetchall()]
    else:
        with db._conn:
            cur = db._conn.execute(
                "SELECT session_id, sentiment_archetype, arc_slope, avg_sentiment, recovery_events, mismatched_effort_score "
                "FROM structured_summaries WHERE sentiment_archetype != '' AND sentiment_archetype NOT IN ('too_short', 'inconclusive') "
                "ORDER BY session_id"
            )
            rows = [dict(row) for row in cur.fetchall()]

    archetype_groups = defaultdict(list)
    for row in rows:
        arch = row.get("sentiment_archetype", "")
        if arch:
            archetype_groups[arch].append(row)

    lesson_templates = {
        "escalating_frustration": (
            "Sessions with escalating frustration often involve repeated failures without clear recovery. "
            "When encountering persistent errors, step back and reconsider the approach rather than repeating the same strategy. "
            "Consider asking the user for clarification or trying a fundamentally different approach after 3+ failed attempts."
        ),
        "looping": (
            "Looping sessions indicate the agent is going in circles — retrying the same approach without progress. "
            "If a tool or approach fails 3+ times on the same task, stop and analyze the root cause. "
            "Try a different tool, read the file fresh, or ask the user for direction."
        ),
        "abandoned": (
            "Abandoned sessions suggest the user gave up due to declining quality. "
            "Always ensure each iteration shows visible improvement. If progress stalls, summarize what's been tried and propose alternatives."
        ),
        "mismatched_effort": (
            "Mismatched effort sessions show high effort for low outcome. "
            "Before investing many tool calls in a single file, check if a simpler approach exists. "
            "Consider creating a helper function or refactoring rather than patching."
        ),
        "smooth_convergence": (
            "Smooth convergence sessions succeed by maintaining clear objectives and steady progress. "
            "Key pattern: clear initial objective, minimal backtracking, verify after each step."
        ),
        "rapid_resolution": (
            "Rapid resolution sessions recover quickly from setbacks. "
            "When an error occurs, diagnose it immediately rather than continuing on the same path. "
            "A fresh read of the relevant file often reveals the issue."
        ),
        "steady_friction": (
            "Steady friction sessions maintain negative sentiment throughout. "
            "This often means the approach itself has issues, not just implementation details. "
            "Consider whether the task needs re-scoping or a different architectural approach."
        ),
    }

    for arch, sessions in archetype_groups.items():
        lesson = lesson_templates.get(arch, f"Sessions with {arch} archetype suggest reviewing the approach.")
        results.append({
            "category": "Sentiment Patterns",
            "pattern": f"{len(sessions)} session(s) classified as '{arch}' archetype",
            "lesson": lesson,
            "evidence_sessions": [r["session_id"] for r in sessions],
            "count": len(sessions),
            "evidence_files": [],
        })

    return results


def extract_compaction_patterns(db, session_id: str | None = None) -> list[dict]:
    """Extract patterns from context compaction events."""
    results = []

    if session_id:
        events = db.get_events_by_session(session_id, event_type="compaction")
    else:
        with db._conn:
            cur = db._conn.execute(
                "SELECT * FROM hook_events WHERE event_type = 'compaction' ORDER BY timestamp ASC"
            )
            events = [dict(row) for row in cur.fetchall()]

    if events:
        usage_values = []
        for ev in events:
            detail = json.loads(ev.get("detail_json", "{}"))
            usage = detail.get("context_usage_percent", 0)
            usage_values.append(usage)

        avg_usage = sum(usage_values) / len(usage_values) if usage_values else 0
        max_usage = max(usage_values) if usage_values else 0

        results.append({
            "category": "Compaction Patterns",
            "pattern": f"Context compaction triggered {len(events)} times (avg {avg_usage:.0f}% usage, max {max_usage:.0f}%)",
            "lesson": (
                "Keep responses concise to avoid context compaction. "
                "When context usage is high, summarize previous work rather than repeating full details. "
                "Prioritize essential information in tool calls and explanations."
            ),
            "evidence_sessions": list(set(ev["session_id"] for ev in events)),
            "count": len(events),
            "evidence_files": [],
        })

    return results


def extract_decision_quality(db, session_id: str | None = None) -> list[dict]:
    """Extract decisions that led to errors vs. smooth outcomes.

    Fix: properly associate each decision with its own reason text.
    """
    results = []

    if session_id:
        with db._conn:
            cur = db._conn.execute(
                "SELECT structured_json, sentiment_archetype, session_id FROM structured_summaries WHERE session_id = ?",
                (session_id,),
            )
            rows = [dict(row) for row in cur.fetchall()]
    else:
        with db._conn:
            cur = db._conn.execute(
                "SELECT structured_json, sentiment_archetype, session_id FROM structured_summaries WHERE structured_json IS NOT NULL"
            )
            rows = [dict(row) for row in cur.fetchall()]

    # Store (row, reason) pairs so each decision gets its own reason
    decision_patterns = defaultdict(list)
    for row in rows:
        try:
            data = json.loads(row["structured_json"])
            arch = row.get("sentiment_archetype", "")
            for decision in data.get("decisions", []):
                if isinstance(decision, dict):
                    desc = decision.get("decision", "")[:150]
                    reason = decision.get("reason", "")[:100]
                    if desc:
                        decision_patterns[(desc, arch)].append((row, reason))
        except (json.JSONDecodeError, TypeError):
            pass

    for (desc, arch), matching in decision_patterns.items():
        if len(matching) < 1:
            continue
        # Collect unique reasons for this decision
        reasons = list(set(r for _, r in matching if r))
        reason_str = reasons[0] if reasons else "N/A"

        results.append({
            "category": "Decision Quality",
            "pattern": f"Decision: `{desc}` (appeared in {len(matching)} sessions, archetype: {arch or 'unknown'})",
            "lesson": f"Review this decision pattern. Reason given: {reason_str}. Consider if this pattern should be standardized or avoided.",
            "evidence_sessions": [r.get("session_id", "") for r, _ in matching],
            "count": len(matching),
            "evidence_files": [],
        })

    return results[:15]


def _categorize_task(task_text: str) -> str:
    """Bucket a task string into a high-level category."""
    task_lower = task_text.lower()
    for category, keywords in TASK_CATEGORY_KEYWORDS:
        for kw in keywords:
            if re.search(kw, task_lower):
                return category
    return "Other"


def extract_subagent_patterns(db, session_id: str | None = None) -> list[dict]:
    """Extract subagent patterns with outcome-based recommendations.

    Groups tasks by category (Explore, Test, Debug, etc.) instead of exact strings,
    and provides DO NOT / USE / CONSIDER recommendations based on success rate.
    """
    results = []
    sentiment_map = _get_session_sentiment_map(db)

    if session_id:
        with db._conn:
            cur = db._conn.execute(
                "SELECT structured_json FROM structured_summaries WHERE session_id = ?",
                (session_id,),
            )
            rows = [dict(row) for row in cur.fetchall()]
    else:
        with db._conn:
            cur = db._conn.execute(
                "SELECT structured_json FROM structured_summaries WHERE structured_json IS NOT NULL"
            )
            rows = [dict(row) for row in cur.fetchall()]

    # Group by (sa_type, task_category, outcome_quality)
    subagent_groups = defaultdict(list)
    for row in rows:
        try:
            data = json.loads(row["structured_json"])
            sid = row.get("session_id", "")
            for work in data.get("subagent_work", []):
                if isinstance(work, dict):
                    sa_type = work.get("subagent_type", "unknown")
                    task = work.get("task", "")[:150]
                    outcome = work.get("outcome", "")[:100]
                    task_cat = _categorize_task(task) if task else "Other"
                    # Determine if this was a success based on outcome text and sentiment
                    is_success = _assess_subagent_success(outcome, sentiment_map.get(sid, ""))
                    subagent_groups[(sa_type, task_cat)].append({
                        "session_id": sid,
                        "outcome": outcome,
                        "success": is_success,
                        "task": task,
                    })
        except (json.JSONDecodeError, TypeError):
            pass

    for (sa_type, task_cat), items in subagent_groups.items():
        total = len(items)
        successes = sum(1 for i in items if i["success"])
        success_rate = successes / total if total > 0 else 0
        sessions = [i["session_id"] for i in items]

        if success_rate < 0.3:
            lesson = (
                f"DO NOT use `{sa_type}` subagent for {task_cat} tasks — "
                f"failed or underperformed in {total - successes}/{total} sessions ({(1 - success_rate):.0%} failure rate). "
                f"Try a different agent type or direct execution."
            )
        elif success_rate > 0.7:
            lesson = (
                f"Use `{sa_type}` subagent for {task_cat} tasks — "
                f"succeeded in {successes}/{total} sessions ({success_rate:.0%} success rate)."
            )
        else:
            lesson = (
                f"`{sa_type}` subagent for {task_cat} has mixed results "
                f"({successes}/{total}, {success_rate:.0%} success). "
                f"Consider alternatives or add guardrails."
            )

        # Show a representative task example
        example_task = items[0]["task"] if items else "unknown task"

        results.append({
            "category": "Subagent Patterns",
            "pattern": f"`{sa_type}` subagent for {task_cat} ({successes}/{total} success, {total} sessions)",
            "lesson": lesson,
            "evidence_sessions": list(set(sessions)),
            "count": total,
            "evidence_files": [],
        })

    return results[:15]


def _assess_subagent_success(outcome: str, sentiment: str) -> bool:
    """Determine if a subagent run was successful based on outcome text and sentiment."""
    outcome_lower = outcome.lower()
    # Explicit failure indicators
    failure_indicators = ["failed", "error", "no tool calls", "no visible output", "unknown"]
    success_indicators = ["completed", "confirmed", "succeeded", "pass"]

    for indicator in failure_indicators:
        if indicator in outcome_lower:
            return False
    for indicator in success_indicators:
        if indicator in outcome_lower:
            return True

    # Fall back to sentiment
    if sentiment in POSITIVE_ARCHETYPES:
        return True
    if sentiment in NEGATIVE_ARCHETYPES:
        return False

    return True  # Default to success if no clear signal


def extract_success_patterns(db, session_id: str | None = None) -> list[dict]:
    """Extract patterns from sessions that went well — what to keep doing."""
    results = []

    if session_id:
        return results  # Skip for single-session updates

    with db._conn:
        cur = db._conn.execute(
            "SELECT session_id, sentiment_archetype, structured_json, files_modified "
            "FROM structured_summaries WHERE sentiment_archetype IN ('smooth_convergence', 'rapid_resolution')"
        )
        rows = [dict(row) for row in cur.fetchall()]

    if not rows:
        return results

    # Count tool usage patterns from structured data
    successful_tool_usage = Counter()
    successful_decisions = Counter()
    successful_file_types = Counter()

    for row in rows:
        sid = row["session_id"]
        try:
            data = json.loads(row["structured_json"]) if row.get("structured_json") else {}
            for work in data.get("subagent_work", []):
                if isinstance(work):
                    sa_type = work.get("subagent_type", "")
                    task_cat = _categorize_task(work.get("task", ""))
                    if sa_type:
                        successful_tool_usage[f"{sa_type} for {task_cat}"] += 1
            for decision in data.get("decisions", []):
                if isinstance(decision, dict):
                    desc = decision.get("decision", "")[:100]
                    if desc:
                        successful_decisions[desc] += 1
        except (json.JSONDecodeError, TypeError):
            pass

        # Track file types in successful sessions
        try:
            files = json.loads(row["files_modified"]) if row.get("files_modified") else []
            for f in files:
                ext = Path(f).suffix or "no extension"
                successful_file_types[ext] += 1
        except (json.JSONDecodeError, TypeError):
            pass

    total_success = len(rows)

    # Generate rules for top tool usage patterns
    for pattern, count in successful_tool_usage.most_common(3):
        if count >= 2:
            pct = round(count / total_success * 100)
            results.append({
                "category": "Successful Patterns",
                "pattern": f"Using {pattern} in {pct}% of successful sessions ({count}/{total_success})",
                "lesson": f"Continue using {pattern} — it correlates with smooth session outcomes.",
                "evidence_sessions": [row["session_id"] for row in rows[:count]],
                "count": count,
                "evidence_files": [],
            })

    # Generate rules for common successful decisions
    for decision, count in successful_decisions.most_common(3):
        if count >= 2:
            results.append({
                "category": "Successful Patterns",
                "pattern": f"Decision '{decision}' appeared in {count} successful sessions",
                "lesson": f"This decision pattern correlates with positive outcomes — consider it as a default approach.",
                "evidence_sessions": [row["session_id"] for row in rows[:count]],
                "count": count,
                "evidence_files": [],
            })

    return results


def extract_procedural_patterns(db, session_id: str | None = None) -> list[dict]:
    """Extract multi-step procedural patterns from session transcripts.

    Hermes-style: looks for recurring tool call sequences that succeeded 3+ times,
    and generates actionable procedure rules like:
    'When modifying files, the sequence Grep → Read → StrReplace → test works reliably.'
    """
    results = []

    if session_id:
        return results  # Skip for single-session updates

    with db._conn:
        cur = db._conn.execute(
            "SELECT session_id, structured_json, sentiment_archetype FROM structured_summaries "
            "WHERE structured_json IS NOT NULL AND sentiment_archetype NOT IN ('escalating_frustration', 'looping', 'abandoned')"
        )
        rows = [dict(row) for row in cur.fetchall()]

    # Build a map of tool call sequences from hook_events
    # tool_name is stored inside detail_json, not as a direct column
    with db._conn:
        cur = db._conn.execute(
            "SELECT session_id, detail_json FROM hook_events "
            "WHERE event_type = 'tool_call' ORDER BY session_id, timestamp ASC"
        )
        tool_events = [dict(row) for row in cur.fetchall()]

    # Group tool calls by session, preserving order
    session_sequences = defaultdict(list)
    for ev in tool_events:
        detail = json.loads(ev.get("detail_json", "{}"))
        tool_name = detail.get("tool_name", detail.get("name", "unknown"))
        session_sequences[ev["session_id"]].append(tool_name)

    # Find recurring subsequences of length 3+ that appear in successful sessions
    good_sessions = set()
    for row in rows:
        arch = row.get("sentiment_archetype", "")
        if arch in POSITIVE_ARCHETYPES or arch == "":
            good_sessions.add(row["session_id"])

    # Extract subsequences of length 3-5 from successful sessions
    sequence_counts = Counter()
    sequence_examples = defaultdict(list)

    for sid, tools in session_sequences.items():
        if sid not in good_sessions:
            continue
        # Extract all subsequences of length 3 to 5
        for length in range(3, 6):
            for i in range(len(tools) - length + 1):
                subseq = tuple(tools[i:i + length])
                sequence_counts[subseq] += 1
                if len(sequence_examples[subseq]) < 2:
                    sequence_examples[subseq].append(sid)

    # Generate procedural rules for sequences seen 3+ times (Hermes threshold)
    for seq, count in sequence_counts.most_common(10):
        if count < PROCEDURAL_THRESHOLD:
            continue

        # Skip sequences with only one tool type repeated
        if len(set(seq)) == 1:
            continue

        seq_str = " → ".join(seq)
        # Determine the task category from the tools used
        task_desc = _describe_tool_sequence(seq)

        results.append({
            "category": "Procedural Patterns",
            "pattern": f"When {task_desc}, the sequence {seq_str} works reliably (seen {count}x)",
            "lesson": (
                f"For {task_desc.lower()} tasks, follow this procedure: {seq_str}. "
                f"This sequence succeeded in {count} sessions without negative sentiment outcomes."
            ),
            "evidence_sessions": sequence_examples.get(seq, [])[:5],
            "count": count,
            "evidence_files": [],
            "is_procedural": True,
        })

    return results


def _describe_tool_sequence(tools: tuple[str, ...]) -> str:
    """Generate a human-readable description of what a tool sequence is used for."""
    tool_set = set(t.lower() for t in tools)

    if "grep" in tool_set or "semanticsearch" in tool_set:
        if "strreplace" in tool_set or "write" in tool_set:
            return "finding and modifying code"
        if "read" in tool_set:
            return "exploring code structure"

    if "shell" in tool_set:
        if "write" in tool_set or "strreplace" in tool_set:
            return "implementing and testing changes"
        if "read" in tool_set:
            return "running commands after reading context"

    if "strreplace" in tool_set:
        return "editing existing code"

    if "read" in tool_set:
        return "investigating files"

    return f"using {' + '.join(set(tools))}"


def extract_correction_rules(transcript_path: Path | None = None) -> list[dict]:
    """Scan a session transcript for user correction patterns and generate high-priority rules.

    Hermes-style: detects explicit user feedback like 'No, that's wrong', 'You should have...',
    and creates immediate learning rules with negative effectiveness.
    """
    results = []

    if transcript_path is None or not transcript_path.exists():
        return results

    try:
        content = transcript_path.read_text(encoding="utf-8")
    except Exception:
        return results

    # Also load the session JSON for structured correction data
    session_id = transcript_path.stem
    session_json_path = transcript_path.parent / session_id / "session.json"
    if session_json_path.exists():
        try:
            with open(session_json_path, "r", encoding="utf-8") as f:
                session_data = json.load(f)
            messages = session_data.get("messages", [])
            text_content = json.dumps(messages, ensure_ascii=False)
        except Exception:
            text_content = content
    else:
        text_content = content

    for pattern in CORRECTION_PATTERNS:
        matches = list(re.finditer(pattern, text_content, re.IGNORECASE))
        if not matches:
            continue

        # Extract context around the correction
        for match in matches[:3]:  # Limit to 3 corrections per session
            start = max(0, match.start() - 100)
            end = min(len(text_content), match.end() + 200)
            context = text_content[start:end].replace("\n", " ")

            # Generate a rule from this correction
            rule_pattern = f"User correction detected: '{match.group()[:80]}'"
            results.append({
                "category": "Correction Rules",
                "pattern": rule_pattern,
                "lesson": (
                    f"A user corrected the agent with '{match.group()[:60]}...'. "
                    f"Context: {context[:150]}. "
                    f"Avoid repeating this mistake — check assumptions before acting."
                ),
                "evidence_sessions": [session_id],
                "count": 1,
                "evidence_files": [],
                "effectiveness_score": "negative",  # Corrections are strong negative signals
                "is_correction": True,
            })

    return results


# =============================================================================
# Rule Deduplication & Merging
# =============================================================================

def compute_rule_hash(category: str, pattern: str) -> str:
    """Compute a deterministic hash for a rule identity."""
    key = f"{category}|{pattern}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def assign_rule_id(category: str, counter: Counter) -> str:
    """Assign a category-prefixed ID like TF-001."""
    prefix = CATEGORY_PREFIX.get(category, "XX")
    counter[category] += 1
    return f"{prefix}-{counter[category]:03d}"


def confidence_label(count: int, effectiveness: str | None = None) -> str:
    """Return a human-readable confidence label based on count and effectiveness."""
    if effectiveness == "negative" and count >= 3:
        return "High"
    elif effectiveness == "positive" and count >= 3:
        return "High"
    elif count >= 10:
        return "High"
    elif count >= 5:
        return "Medium"
    elif count >= 2:
        return "Low"
    return "Very Low"


def effectiveness_recommendation(effectiveness: str) -> str:
    """Return an action recommendation based on effectiveness score."""
    return {
        "negative": "DO NOT",
        "positive": "CONTINUE",
        "neutral": "MONITOR",
        "insufficient_data": "INSUFFICIENT DATA",
    }.get(effectiveness or "insufficient_data", "MONITOR")


def load_existing_rules(learning_path: Path) -> dict[str, dict]:
    """Parse existing learning.mdc and return rules keyed by hash."""
    if not learning_path.exists():
        return {}

    try:
        content = learning_path.read_text(encoding="utf-8")
    except Exception:
        return {}

    rules_list = []
    current_category = None
    current_rule = {}

    def save_rule(rule):
        if rule.get("pattern") and rule.get("category"):
            rule_hash = compute_rule_hash(rule["category"], rule["pattern"])
            rule["hash"] = rule_hash
            rules_list.append(rule)

    for line in content.split("\n"):
        stripped = line.strip()

        if stripped.startswith("## ") and not stripped.startswith("### "):
            cat_name = stripped[3:].strip()
            if not cat_name.startswith("Historical"):
                current_category = cat_name

        elif stripped.startswith("### ["):
            if current_rule.get("pattern"):
                save_rule(current_rule)
            current_rule = {"category": current_category}
            m = re.match(r"### \[[\w-]+\]\s+(.*)", stripped)
            if m:
                current_rule["pattern"] = m.group(1).strip()

        elif stripped.startswith("- **Lesson**:"):
            current_rule["lesson"] = stripped.replace("- **Lesson**:", "").strip()

        elif stripped.startswith("- **Evidence**:"):
            current_rule["evidence_raw"] = stripped.replace("- **Evidence**:", "").strip()

        elif stripped.startswith("- **Confidence**:"):
            conf_text = stripped.replace("- **Confidence**:", "").strip()
            current_rule["confidence_text"] = conf_text
            m = re.search(r"\((\d+)\s+(occurrence|sessions|events)", conf_text)
            current_rule["count"] = int(m.group(1)) if m else 1

    if current_rule.get("pattern"):
        save_rule(current_rule)

    return {r["hash"]: r for r in rules_list if "hash" in r}


def merge_rules(existing: dict[str, dict], new_rules: list[dict]) -> list[dict]:
    """Merge new rules into existing, accumulating evidence and updating confidence."""
    merged = dict(existing)

    for nr in new_rules:
        rule_hash = compute_rule_hash(nr["category"], nr["pattern"])

        if rule_hash in merged:
            old = merged[rule_hash]
            old_sessions = set(old.get("evidence_sessions", []))
            old_sessions.update(nr.get("evidence_sessions", []))
            old["evidence_sessions"] = list(old_sessions)
            old["count"] = old.get("count", 0) + nr.get("count", 0)
            old["last_seen_session"] = nr.get("evidence_sessions", [""])[-1] if nr.get("evidence_sessions") else ""
            # Prefer new rule's lesson — it may contain updated extraction logic fixes
            if nr.get("lesson"):
                old["lesson"] = nr["lesson"]
            if "effectiveness_score" in nr:
                old["effectiveness_score"] = nr["effectiveness_score"]
        else:
            nr["hash"] = rule_hash
            nr["last_seen_session"] = nr.get("evidence_sessions", [""])[-1] if nr.get("evidence_sessions") else ""
            merged[rule_hash] = nr

    return merged


# =============================================================================
# Rule Pruning
# =============================================================================

def prune_rules(merged: dict[str, dict], rule_usage: dict, total_sessions: int) -> dict[str, dict]:
    """Remove low-signal rules and cap active rules.

    Returns a filtered dict of rules.
    """
    to_delete = set()

    for rule_hash, rule in merged.items():
        count = rule.get("count", 1)
        effectiveness = rule.get("effectiveness_score", "insufficient_data")
        category = rule.get("category", "")
        pattern = rule.get("pattern", "")

        # Delete single-occurrence file-not-found noise
        if count == 1 and effectiveness == "insufficient_data" and "File not found" in pattern:
            to_delete.add(rule_hash)
            continue

        # Demote rules never referenced after many sessions
        referenced = rule_usage.get(rule_hash, {}).get("referenced_sessions", [])
        if not referenced and total_sessions > 10 and count < 2:
            to_delete.add(rule_hash)
            continue

        # Keep rules with clear signal (positive or negative effectiveness)
        if effectiveness in ("positive", "negative") and count >= MIN_ACTIVE_COUNT:
            continue  # Definitely keep

        # Keep rules with sufficient count
        if count >= MIN_ACTIVE_COUNT:
            continue

    # Apply deletions
    for h in to_delete:
        del merged[h]

    # Cap total rules: sort by (effectiveness_priority, count) and keep top MAX_ACTIVE_RULES
    if len(merged) > MAX_ACTIVE_RULES:
        effectiveness_priority = {
            "negative": 0,
            "positive": 1,
            "neutral": 2,
            "insufficient_data": 3,
        }
        sorted_rules = sorted(
            merged.items(),
            key=lambda kv: (effectiveness_priority.get(kv[1].get("effectiveness_score", "insufficient_data"), 3), -kv[1].get("count", 0)),
        )
        # Keep top MAX_ACTIVE_RULES, move rest to a "pruned" state (we just delete them)
        for rule_hash, _ in sorted_rules[MAX_ACTIVE_RULES:]:
            del merged[rule_hash]

    return merged


# =============================================================================
# Learning Analyzer
# =============================================================================

class LearningAnalyzer:
    """Extracts learning signals and writes .cursor/rules/learning.mdc."""

    def __init__(self, learning_path: Path | None = None):
        self.learning_path = learning_path or LEARNING_MDC_PATH
        self.all_rules: dict[str, dict] = {}
        self.total_sessions_analyzed = 0

    def extract_all(self, session_id: str | None = None) -> list[dict]:
        """Run all signal extractors and return combined rules."""
        rules = []
        try:
            with get_db() as db:
                # Memory limit: when extracting all sessions, cap to the most
                # recent MAX_EXTRACT_SESSIONS to avoid unbounded memory growth.
                allowed_sessions: set[str] | None = None
                if session_id is None:
                    cur = db._conn.execute(
                        "SELECT session_id FROM sessions ORDER BY completed_at DESC LIMIT ?",
                        (MAX_EXTRACT_SESSIONS,),
                    )
                    allowed_sessions = {row[0] for row in cur.fetchall()}

                rules.extend(extract_tool_failures(db, session_id))
                rules.extend(extract_shell_failures(db, session_id))
                if session_id is None:
                    rules.extend(extract_file_hotspots(db))
                    rules.extend(extract_success_patterns(db, session_id))
                    rules.extend(extract_procedural_patterns(db, session_id))
                rules.extend(extract_sentiment_patterns(db, session_id))
                rules.extend(extract_compaction_patterns(db, session_id))
                rules.extend(extract_decision_quality(db, session_id))
                rules.extend(extract_subagent_patterns(db, session_id))

                # Apply session limit post-filter when extracting all
                if allowed_sessions is not None:
                    for rule in rules:
                        orig = rule.get("evidence_sessions", [])
                        if orig:
                            filtered = [s for s in orig if s in allowed_sessions]
                            rule["evidence_sessions"] = filtered
                            rule["count"] = len(filtered)

                # Count total sessions for context
                cur = db._conn.execute("SELECT COUNT(*) FROM sessions")
                self.total_sessions_analyzed = cur.fetchone()[0]

                # Compute effectiveness scores
                sentiment_map = _get_session_sentiment_map(db)
                compute_rule_effectiveness(rules, sentiment_map)
        except Exception as e:
            print(f"[learning-analyzer] DB error: {e}", file=sys.stderr)

        return rules

    def build_mdc_content(self, rules: list[dict]) -> str:
        """Build the full .mdc file content from rules."""
        # Load existing rules for merging
        existing = load_existing_rules(self.learning_path)
        merged = merge_rules(existing, rules)

        # Load rule usage data
        rule_usage = load_rule_usage()

        # Prune low-signal rules
        merged = prune_rules(merged, rule_usage, self.total_sessions_analyzed)

        # Assign IDs per category
        counters = Counter()
        for rule in merged.values():
            if "assigned_id" not in rule:
                rule["assigned_id"] = assign_rule_id(rule.get("category", "XX"), counters)

        # Attach effectiveness-aware metadata
        for rule in merged.values():
            effectiveness = rule.get("effectiveness_score", "insufficient_data")
            rule["confidence"] = confidence_label(rule.get("count", 1), effectiveness)
            rule["recommendation"] = effectiveness_recommendation(effectiveness)

        # Group by category, separate stale/pruned
        categorized = defaultdict(list)
        historical = []

        for rule in merged.values():
            count = rule.get("count", 1)
            if count >= STALE_SESSIONS_THRESHOLD:
                historical.append(rule)
            else:
                cat = rule.get("category", "Other")
                categorized[cat].append(rule)

        # Sort rules within each category by effectiveness priority, then count
        effectiveness_priority = {
            "negative": 0,
            "positive": 1,
            "neutral": 2,
            "insufficient_data": 3,
        }
        for cat in categorized:
            categorized[cat].sort(
                key=lambda r: (
                    effectiveness_priority.get(r.get("effectiveness_score", "insufficient_data"), 3),
                    -r.get("count", 0),
                )
            )
        historical.sort(key=lambda r: r.get("count", 0), reverse=True)

        # Build output with new section order
        lines = []
        lines.append("---")
        lines.append("description: Auto-generated learning rules from session telemetry. Updated after each summarization.")
        lines.append("alwaysApply: true")
        lines.append("---")
        lines.append("")
        lines.append("# Agent Learning — Workspace Lessons")
        lines.append("")
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        total_rules = len(merged)
        lines.append(f"> Auto-generated from session telemetry. Last updated: {now}")
        lines.append(f"> Sessions analyzed: {self.total_sessions_analyzed} | Rules: {total_rules} | Last regenerated: {now}")
        lines.append("")

        # Section order: Successful Patterns first (most actionable), then failures
        category_order = [
            "Successful Patterns",
            "Tool Failures",
            "Subagent Patterns",
            "Shell Commands",
            "Sentiment Patterns",
            "File Hotspots",
            "Compaction Patterns",
            "Decision Quality",
        ]

        for cat in category_order:
            if cat not in categorized or not categorized[cat]:
                continue
            lines.append(f"## {cat}")
            lines.append("")
            for rule in categorized[cat]:
                rule_id = rule.get("assigned_id", "??-000")
                count = rule.get("count", 1)
                conf = rule.get("confidence", "Low")
                effectiveness = rule.get("effectiveness_score", "insufficient_data")
                recommendation = rule.get("recommendation", "MONITOR")

                lines.append(f"### [{rule_id}] {rule.get('pattern', 'Unknown')}")
                lines.append(f"- **Lesson**: {rule.get('lesson', 'Review this pattern.')}")
                lines.append(f"- **Effectiveness**: {effectiveness} | **Recommendation**: {recommendation}")

                evidence_sessions = rule.get("evidence_sessions", [])[:5]
                evidence_str = ", ".join(str(s)[:12] for s in evidence_sessions) if evidence_sessions else "N/A"
                lines.append(f"- **Evidence**: Sessions: {evidence_str} ({count} occurrence{'s' if count != 1 else ''})")
                lines.append(f"- **Confidence**: {conf} ({count} occurrence{'s' if count != 1 else ''})")

                # Show reference count if tracked
                rule_hash = rule.get("hash", "")
                if rule_hash in rule_usage:
                    ref_count = len(rule_usage[rule_hash].get("referenced_sessions", []))
                    lines.append(f"- **Referenced**: {ref_count} session(s)")

                lines.append("")

        # Historical
        if historical:
            lines.append("## Historical (stale, last seen >20 sessions ago)")
            lines.append("")
            for rule in historical:
                rule_id = rule.get("assigned_id", "??-000")
                lines.append(f"### [{rule_id}] {rule.get('pattern', 'Unknown')}")
                lines.append(f"- **Lesson**: {rule.get('lesson', 'Historical pattern.')}")
                lines.append(f"- **Confidence**: Low (stale)")
                lines.append("")

        return "\n".join(lines)

    def build_critical_mdc_content(self, rules: list[dict]) -> str:
        """Build progressive disclosure critical rules file (Hermes-style).

        Contains only the top MAX_CRITICAL_RULES rules that should alwaysApply.
        Mirrors Hermes's approach of loading only relevant skill descriptions
        to keep token overhead near zero.
        """
        # Load existing rules for merging
        existing = load_existing_rules(self.learning_path)
        merged = merge_rules(existing, rules)

        # Load rule usage data
        rule_usage = load_rule_usage()

        # Prune low-signal rules
        merged = prune_rules(merged, rule_usage, self.total_sessions_analyzed)

        # Sort all rules by effectiveness priority, then count
        effectiveness_priority = {
            "negative": 0,
            "positive": 1,
            "neutral": 2,
            "insufficient_data": 3,
        }
        sorted_rules = sorted(
            merged.values(),
            key=lambda r: (
                effectiveness_priority.get(r.get("effectiveness_score", "insufficient_data"), 3),
                -r.get("count", 0),
            ),
        )

        # Take top MAX_CRITICAL_RULES
        critical_rules = sorted_rules[:MAX_CRITICAL_RULES]

        # Assign IDs
        counters = Counter()
        for rule in critical_rules:
            rule["assigned_id"] = assign_rule_id(rule.get("category", "XX"), counters)

        lines = []
        lines.append("---")
        lines.append("description: Critical learning rules that always apply. Subset of learning.mdc for progressive disclosure.")
        lines.append("alwaysApply: true")
        lines.append("---")
        lines.append("")
        lines.append("# Agent Learning — Critical Rules")
        lines.append("")
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        lines.append(f"> Auto-generated critical subset. Last updated: {now}")
        lines.append(f"> Top {MAX_CRITICAL_RULES} rules from {self.total_sessions_analyzed} sessions. See learning.mdc for full rules.")
        lines.append("")

        for rule in critical_rules:
            rule_id = rule.get("assigned_id", "??-000")
            count = rule.get("count", 1)
            conf = confidence_label(count, rule.get("effectiveness_score"))
            recommendation = effectiveness_recommendation(rule.get("effectiveness_score", "insufficient_data"))

            lines.append(f"### [{rule_id}] {rule.get('pattern', 'Unknown')}")
            lines.append(f"- **Lesson**: {rule.get('lesson', 'Review this pattern.')}")
            lines.append(f"- **Recommendation**: {recommendation} | **Confidence**: {conf}")
            lines.append("")

        return "\n".join(lines)

    def write_critical_mdc(self, rules: list[dict] | None = None) -> bool:
        """Write the progressive disclosure critical rules file."""
        if rules is None:
            rules = self.extract_all()

        if not rules:
            return False

        critical_path = self.learning_path.parent / "learning-critical.mdc"
        content = self.build_critical_mdc_content(rules)
        critical_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(critical_path.parent),
                suffix=".mdc.tmp",
            )
            try:
                with open(fd, "w", encoding="utf-8") as f:
                    f.write(content)
                try:
                    critical_path.unlink(missing_ok=True)
                except OSError:
                    pass
                Path(tmp_path).rename(critical_path)
                print(
                    f"[learning-analyzer] Wrote {critical_path} "
                    f"({min(len(rules), MAX_CRITICAL_RULES)} critical rules)",
                    file=sys.stderr,
                )
                return True
            except Exception:
                Path(tmp_path).unlink(missing_ok=True)
                raise
        except Exception as e:
            print(f"[learning-analyzer] Failed to write learning-critical.mdc: {e}", file=sys.stderr)
            return False

    def write_signals_json(self, rules: list[dict] | None = None) -> bool:
        """Write extracted signals to JSON instead of .mdc files."""
        if rules is None:
            rules = self.extract_all()

        if not rules:
            print("[learning-analyzer] No signals to write", file=sys.stderr)
            return False

        output_path = STATE_DIR / "extracted_signals.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "generated_at": datetime.utcnow().isoformat(),
            "total_sessions": self.total_sessions_analyzed,
            "signal_count": len(rules),
            "rules": rules,
        }

        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(output_path.parent),
                suffix=".json.tmp",
            )
            try:
                with open(fd, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2, default=str)
                output_path.unlink(missing_ok=True)
                Path(tmp_path).rename(output_path)
                print(
                    f"[learning-analyzer] Wrote {output_path} "
                    f"({len(rules)} signals, {self.total_sessions_analyzed} sessions)",
                    file=sys.stderr,
                )
                return True
            except Exception:
                Path(tmp_path).unlink(missing_ok=True)
                raise
        except Exception as e:
            print(f"[learning-analyzer] Failed to write extracted_signals.json: {e}", file=sys.stderr)
            return False

    def update_from_session(self, session_id: str) -> bool:
        """Extract signals from a single session and write to JSON."""
        rules = self.extract_all(session_id)
        return self.write_signals_json(rules)

    def show_status(self):
        """Print current rules and their effectiveness status from JSON and rule_usage.json."""
        signals_path = STATE_DIR / "extracted_signals.json"
        if not signals_path.exists():
            print("No extracted_signals.json found. Run --bootstrap first.", file=sys.stderr)
            return

        with open(signals_path, "r") as f:
            data = json.load(f)

        rule_usage = load_rule_usage()
        rules = data.get("rules", [])

        if not rules:
            print("No signals extracted yet.", file=sys.stderr)
            return

        counters = Counter()
        for rule in rules:
            if "assigned_id" not in rule:
                rule["assigned_id"] = assign_rule_id(rule.get("category", "XX"), counters)

        print(f"\nLearning Signals ({len(rules)} total, {data.get('total_sessions', 0)} sessions):\n")
        for rule in sorted(rules, key=lambda x: x.get("count", 0), reverse=True):
            rule_id = rule.get("assigned_id", "??-000")
            cat = rule.get("category", "?")
            pattern = rule.get("pattern", "")[:80]
            count = rule.get("count", 0)
            rule_hash = rule.get("hash", compute_rule_hash(cat, pattern))
            effectiveness = rule_usage.get(rule_hash, {}).get("status", "unknown")
            print(f"  [{rule_id}] {cat}: {pattern}")
            print(f"    Count: {count}, Effectiveness: {effectiveness}")
            print()

    def compute_recurrence_effectiveness(self) -> dict[str, str]:
        """Check if extracted signals recur in sessions chronologically after rule creation.

        Returns a dict of rule_hash -> 'effective' | 'ineffective' | 'unknown'.
        """
        signals_path = STATE_DIR / "extracted_signals.json"
        if not signals_path.exists():
            return {}

        with open(signals_path, "r") as f:
            data = json.load(f)

        rules = data.get("rules", [])
        if not rules:
            return {}

        # Get all tool failures from hook_events chronologically
        try:
            with get_db() as db:
                cur = db._conn.execute(
                    "SELECT session_id, tool_name, error_message, created_at "
                    "FROM hook_events WHERE event_type='tool_failure' ORDER BY created_at"
                )
                failures = [dict(r) for r in cur.fetchall()]
        except Exception:
            return {}

        # Group failures by session
        session_failures = defaultdict(list)
        for f in failures:
            session_failures[f["session_id"]].append(f)

        # Get session timestamps
        try:
            with get_db() as db:
                cur = db._conn.execute(
                    "SELECT id, created_at FROM sessions ORDER BY created_at"
                )
                session_times = {dict(r)["id"]: dict(r)["created_at"] for r in cur.fetchall()}
        except Exception:
            return {}

        result = {}
        for rule in rules:
            rule_hash = rule.get("hash", compute_rule_hash(
                rule.get("category", ""), rule.get("pattern", "")
            ))
            evidence_sessions = set(rule.get("evidence_sessions", []))
            if not evidence_sessions:
                result[rule_hash] = "unknown"
                continue

            # Find the latest session in which this rule was observed
            rule_created_time = max(
                (session_times.get(s, "") for s in evidence_sessions if s in session_times),
                default=""
            )
            if not rule_created_time:
                result[rule_hash] = "unknown"
                continue

            # Count recurrences in sessions AFTER the rule was created
            recurrence_count = 0
            for sid, fails in session_failures.items():
                session_time = session_times.get(sid, "")
                if session_time > rule_created_time:
                    # Check if same tool+error pattern recurs
                    for f in fails:
                        tool_name = (f.get("tool_name") or "").lower()
                        error_msg = (f.get("error_message") or "").lower()
                        pattern_lower = (rule.get("pattern") or "").lower()
                        if tool_name in pattern_lower or pattern_lower in tool_name:
                            recurrence_count += 1
                            break

            if recurrence_count == 0:
                result[rule_hash] = "effective"
            elif recurrence_count >= 2:
                result[rule_hash] = "ineffective"
            else:
                result[rule_hash] = "unknown"

        return result

    def sync_to_critical_mdc(self) -> bool:
        """Rewrite learning-critical.mdc based on effectiveness data and extracted signals."""
        critical_path = self.learning_path.parent / "learning-critical.mdc"
        effectiveness = self.compute_recurrence_effectiveness()

        # Backup current file before writing (rollback safety, frontmatter stripped)
        if critical_path.exists():
            backup_path = critical_path.with_suffix(".mdc.bak")
            try:
                _strip_frontmatter_backup(critical_path, backup_path)
            except Exception as e:
                print(f"[learning-analyzer] Failed to create backup: {e}", file=sys.stderr)

        signals_path = STATE_DIR / "extracted_signals.json"
        if not signals_path.exists():
            print("[learning-analyzer] No extracted_signals.json to sync from.", file=sys.stderr)
            return False

        with open(signals_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        rules = data.get("rules", [])

        # Filter to active/effective rules, sort by count
        active_rules = [
            r for r in rules
            if effectiveness.get(
                r.get("hash", compute_rule_hash(r.get("category", ""), r.get("pattern", ""))),
                "unknown"
            ) in ("effective", "unknown")
        ]
        active_rules.sort(key=lambda x: x.get("count", 0), reverse=True)

        if not active_rules:
            print("[learning-analyzer] No active rules to sync.", file=sys.stderr)
            return False

        # Build content with actionable lessons
        lines = [
            "---",
            "description: Auto-synced critical learning rules from session data. Updated by --sync command.",
            "alwaysApply: true",
            "---",
            "",
            "# Critical Learning Rules",
            "",
            "> Auto-synced from extracted signals. Rules with proven effectiveness are prioritized.",
            "> Last synced: " + datetime.utcnow().isoformat(),
            "",
        ]

        for rule in active_rules[:MAX_CRITICAL_RULES]:
            pattern = rule.get("pattern", "Unknown")
            lesson = rule.get("lesson", "Review this pattern.")
            count = rule.get("count", 0)
            cat = rule.get("category", "?")
            rule_hash = rule.get("hash", compute_rule_hash(cat, pattern))
            eff = effectiveness.get(rule_hash, "unknown")

            # Rewrite lesson to be actionable if it's still generic
            if "investigate" in lesson.lower() or "consider" in lesson.lower():
                lesson = _make_actionable(lesson, cat, pattern)

            lines.append(f"### [{cat}] {pattern}")
            lines.append(f"- **Rule**: {lesson}")
            lines.append(f"- **Evidence**: {count} sessions")
            lines.append(f"- **Effectiveness**: {eff}")
            lines.append("")

        content = "\n".join(lines)

        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(critical_path.parent),
                suffix=".mdc.tmp",
            )
            try:
                with open(fd, "w", encoding="utf-8") as f:
                    f.write(content)
                critical_path.unlink(missing_ok=True)
                Path(tmp_path).rename(critical_path)
                print(
                    f"[learning-analyzer] Synced {critical_path} "
                    f"({min(len(active_rules), MAX_CRITICAL_RULES)} rules)",
                    file=sys.stderr,
                )
                return True
            except Exception:
                Path(tmp_path).unlink(missing_ok=True)
                raise
        except Exception as e:
            print(f"[learning-analyzer] Failed to sync learning-critical.mdc: {e}", file=sys.stderr)
            return False


def _make_actionable(lesson: str, category: str, pattern: str) -> str:
    """Convert a generic lesson into an actionable DO/NOT-DO rule."""
    tool_match = re.search(r"`(\w+)`", pattern)
    tool_name = tool_match.group(1) if tool_match else None

    if "not found" in pattern.lower() or "does not exist" in pattern.lower():
        return f"DO NOT call {tool_name} -- this tool does not exist. Check available tools before calling."
    elif "timeout" in pattern.lower() or "timed out" in pattern.lower():
        return f"Always scope {tool_name} calls with specific filters. Unscoped searches time out."
    elif "file not found" in pattern.lower():
        return f"Verify file existence before calling {tool_name}. Files may be deleted between sessions."
    elif "mixed results" in pattern.lower() or "success" in pattern.lower():
        return f"Use {tool_name} only for complex multi-step tasks. Use direct tools for simple queries."
    else:
        return lesson


def _manage_rule_status(rule_id: str, status: str) -> None:
    """Manually set a rule's status in rule_usage.json."""
    usage = load_rule_usage()

    # Find the rule by ID in extracted signals
    signals_path = STATE_DIR / "extracted_signals.json"
    if signals_path.exists():
        with open(signals_path, "r") as f:
            data = json.load(f)
        for rule in data.get("rules", []):
            assigned_id = rule.get("assigned_id", "")
            rule_hash = rule.get("hash", compute_rule_hash(
                rule.get("category", ""), rule.get("pattern", "")
            ))
            if assigned_id == rule_id or rule_hash == rule_id:
                if rule_hash not in usage:
                    usage[rule_hash] = {}
                usage[rule_hash]["status"] = status
                usage[rule_hash]["last_updated"] = datetime.utcnow().isoformat()
                usage[rule_hash]["manually_set"] = True
                save_rule_usage(usage)
                print(f"[learning-analyzer] Set rule {rule_id} status to '{status}'", file=sys.stderr)
                return

    print(f"[learning-analyzer] Rule {rule_id} not found", file=sys.stderr)


# =============================================================================
# CLI
# =============================================================================

def main():
    args = sys.argv[1:]

    if not args:
        print("Usage: python learning_analyzer.py [OPTIONS]")
        print("  --bootstrap              Generate signals JSON from all existing sessions")
        print("  --update <session_id>    Update signals from a single session")
        print("  --status                 Show current rules and effectiveness status")
        print("  --quick-scan <sid>       Scan session transcript for corrections and learning signals")
        print("  --sync                   Sync extracted signals to learning-critical.mdc")
        print("  --deprecate <rule_id>    Mark a rule as deprecated")
        print("  --verify <rule_id>       Mark a rule as manually verified")
        sys.exit(1)

    analyzer = LearningAnalyzer()

    if args[0] == "--bootstrap":
        print("[learning-analyzer] Bootstrapping from all sessions...", file=sys.stderr)
        rules = analyzer.extract_all()
        analyzer.write_signals_json(rules)

    elif args[0] == "--update" and len(args) > 1:
        session_id = args[1]
        print(f"[learning-analyzer] Updating from session {session_id}...", file=sys.stderr)
        analyzer.update_from_session(session_id)

    elif args[0] == "--status":
        analyzer.show_status()

    elif args[0] == "--quick-scan" and len(args) > 1:
        # Scan of a just-completed session transcript
        session_id = args[1]
        transcript_path = STATE_DIR / "sessions" / session_id / "session.json"
        print(f"[learning-analyzer] Quick-scanning session {session_id}...", file=sys.stderr)
        rules = analyzer.extract_all(session_id)
        rules.extend(extract_correction_rules(transcript_path))
        if rules:
            analyzer.total_sessions_analyzed = _count_sessions()
            analyzer.write_signals_json(rules)
            print(f"[learning-analyzer] Quick-scan found {len(rules)} rules for {session_id}", file=sys.stderr)
        else:
            print("[learning-analyzer] Quick-scan found no new rules", file=sys.stderr)

    elif args[0] == "--deprecate" and len(args) > 1:
        rule_id = args[1]
        _manage_rule_status(rule_id, "deprecated")

    elif args[0] == "--verify" and len(args) > 1:
        rule_id = args[1]
        _manage_rule_status(rule_id, "verified")

    elif args[0] == "--sync":
        print("[learning-analyzer] Syncing signals to learning-critical.mdc...", file=sys.stderr)
        analyzer.sync_to_critical_mdc()

    else:
        print(f"Unknown command: {args[0]}", file=sys.stderr)
        sys.exit(1)


def _count_sessions() -> int:
    """Quick session count without full DB initialization."""
    try:
        with get_db() as db:
            cur = db._conn.execute("SELECT COUNT(*) FROM sessions")
            return cur.fetchone()[0]
    except Exception:
        return 0


if __name__ == "__main__":
    main()
