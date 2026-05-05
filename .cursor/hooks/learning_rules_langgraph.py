"""
Learning Rules LangGraph Agent

LangGraph-based agent that extracts learning signals, evaluates effectiveness,
compares against existing rules, uses an LLM to decide whether to rewrite
learning-critical.mdc, and writes the result with audit logging.

Usage:
    import learning_rules_langgraph
    graph = learning_rules_langgraph.build_graph()
    result = graph.invoke({"session_id": "all"})
"""

import hashlib
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
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
LEARNING_CRITICAL_PATH = HOOKS_DIR.parent / "rules" / "learning-critical.mdc"

sys.path.insert(0, str(HOOKS_DIR))
from conversation_recorder import is_process_alive

load_dotenv(str(LLM_ENV_PATH), override=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

QUICK_DECIDE_NEW_RULES_THRESHOLD = 2
QUICK_DECIDE_INEFFECTIVE_THRESHOLD = 2
FULL_AGENT_TIMEOUT_SECONDS = 600  # 10 min hard ceiling
FULL_AGENT_PARENT_CHECK_INTERVAL = 30
CHANGELOG_MAX_SIZE_BYTES = 1_000_000  # 1MB
LOCK_STALE_SECONDS = 300  # 5 minutes
LLM_PROMPT_MAX_SIGNALS = 20
LLM_PROMPT_MAX_RULES = 10
LLM_PROMPT_MAX_LESSING_LENGTH = 200
LLM_PROMPT_MAX_DIFF_LENGTH = 500
MAX_EXTRACT_SESSIONS = 100
MAX_EXTRACT_RULES = 50
LEARNING_RULES_LOCK_TIMEOUT = 120  # seconds

# Changelog validation
_REQUIRED_FIELDS = {"ts", "mode", "decision", "reason"}
_VALID_MODES = {"quick", "full"}
_VALID_DECISIONS = {"write", "skip"}


# ---------------------------------------------------------------------------
# LLM setup (reuses same pattern as summarizer_agent.py)
# ---------------------------------------------------------------------------

def get_llm() -> ChatOpenAI:
    """Create a ChatOpenAI instance using llm.env configuration."""
    api_key = os.getenv("API_KEY", "")
    if not api_key:
        print("[learning-rules] ERROR: API_KEY not set in llm.env", file=sys.stderr)
        raise RuntimeError("API_KEY not set in llm.env")

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

LEARNING_RULES_LOCK_PATH = STATE_DIR / ".learning_rules_lock"


def _try_acquire_lock() -> bool:
    """Acquire the learning rules lock. Returns False if already held."""
    try:
        if LEARNING_RULES_LOCK_PATH.exists():
            try:
                content = LEARNING_RULES_LOCK_PATH.read_text(encoding="utf-8").strip()
                parts = content.split("|")
                pid = int(parts[0])
                timestamp = float(parts[1]) if len(parts) > 1 else 0
                elapsed = time.time() - timestamp

                if elapsed < LEARNING_RULES_LOCK_TIMEOUT and is_process_alive(pid):
                    return False  # Another instance is running
                # Stale lock, remove it
                LEARNING_RULES_LOCK_PATH.unlink(missing_ok=True)
            except (ValueError, OSError):
                LEARNING_RULES_LOCK_PATH.unlink(missing_ok=True)

        fd = os.open(
            str(LEARNING_RULES_LOCK_PATH),
            os.O_CREAT | os.O_WRONLY | os.O_EXCL,
        )
        os.write(fd, f"{os.getpid()}|{time.time()}".encode())
        os.close(fd)
        return True
    except (FileExistsError, OSError):
        return False


def _release_lock() -> None:
    """Release the learning rules lock."""
    LEARNING_RULES_LOCK_PATH.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# State definition
# ---------------------------------------------------------------------------

class LearningRulesState(TypedDict, total=False):
    session_id: str              # "all" for full re-evaluation
    new_signals: list[dict]      # extracted signals from LearningAnalyzer.extract_all()
    existing_signals: list[dict] # loaded from extracted_signals.json
    current_mdc_rules: list[dict]# parsed from current learning-critical.mdc
    change_diff: str             # human-readable diff/summary of changes
    should_write: bool           # final decision
    decision_reason: str         # why the LLM decided this way
    write_result: str            # success/failure message
    mode: str                    # "full" — identifies this as LangGraph-run


# ---------------------------------------------------------------------------
# Security: prompt sanitization (reuse _scrub_secrets pattern)
# ---------------------------------------------------------------------------

def _scrub_secrets(text: str) -> str:
    """Remove potential secrets from text. Returns scrubbed text."""
    result = text
    for pattern in (
        r"sk-[a-zA-Z0-9]{20,}",
        r"ghp_[a-zA-Z0-9]{36}",
        r"gho_[a-zA-Z0-9]{36}",
    ):
        if re.search(pattern, result):
            result = re.sub(pattern, "[REDACTED]", result)
    for pattern in (
        r"(?i)(api[_-]?key)\s*[:=]\s*(\S+)",
        r"(?i)(password)\s*[:=]\s*(\S+)",
        r"(?i)(token)\s*[:=]\s*([a-zA-Z0-9]{16,})",
        r"(?i)(aws_secret_access_key)\s*[:=]\s*(\S+)",
    ):
        if re.search(pattern, result):
            result = re.sub(pattern, r"\1: [REDACTED]", result)
    return result


# ---------------------------------------------------------------------------
# Changelog helpers
# ---------------------------------------------------------------------------

CHANGELOG_PATH = STATE_DIR / "learning_rules_changelog.jsonl"


def _validate_changelog_entry(entry: dict) -> bool:
    """Validate a changelog entry before writing."""
    if not _REQUIRED_FIELDS.issubset(entry.keys()):
        return False
    if entry.get("mode") not in _VALID_MODES:
        return False
    if entry.get("decision") not in _VALID_DECISIONS:
        return False
    return True


def _rotate_changelog_if_needed() -> None:
    """Rotate changelog if it exceeds CHANGELOG_MAX_SIZE_BYTES."""
    if not CHANGELOG_PATH.exists():
        return
    try:
        size = CHANGELOG_PATH.stat().st_size
        if size > CHANGELOG_MAX_SIZE_BYTES:
            backup_path = CHANGELOG_PATH.with_suffix(".jsonl.1")
            backup_path.unlink(missing_ok=True)
            CHANGELOG_PATH.rename(backup_path)
    except OSError:
        pass


def _append_changelog(entry: dict) -> bool:
    """Append a validated changelog entry with file-level lock."""
    if not _validate_changelog_entry(entry):
        print("[learning-rules] changelog entry validation failed", file=sys.stderr)
        return False

    _rotate_changelog_if_needed()

    try:
        CHANGELOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(str(CHANGELOG_PATH), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        return True
    except Exception as e:
        print(f"[learning-rules] failed to write changelog: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# MDC parser (parse markdown rules from learning-critical.mdc)
# ---------------------------------------------------------------------------

def _parse_mdc_rules(path: Path) -> list[dict]:
    """Parse rule sections from a learning-critical.mdc file."""
    if not path.exists():
        return []

    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return []

    rules = []
    # Split by ### headings to get individual rules
    sections = re.split(r"^### ", content, flags=re.MULTILINE)
    for section in sections:
        if not section.strip() or section.startswith("---") or section.startswith("# "):
            continue
        lines = section.strip().split("\n")
        header = lines[0].strip() if lines else ""
        rule_text = "\n".join(lines[1:]).strip()

        # Extract category and pattern from header: ### [TF-001] Pattern text
        cat_match = re.match(r"\[([A-Z]+-\d+)\]\s*(.*)", header)
        if cat_match:
            rule_id = cat_match.group(1)
            pattern = cat_match.group(2)
        else:
            rule_id = ""
            pattern = header

        rules.append({
            "rule_id": rule_id,
            "pattern": pattern,
            "full_text": rule_text,
        })

    return rules


# ---------------------------------------------------------------------------
# LLM response parser (4-level fallback)
# ---------------------------------------------------------------------------

def _parse_llm_decision(response_text: str) -> dict:
    """Parse LLM JSON response with 4-level fallback."""
    # Level 1: direct JSON
    try:
        data = json.loads(response_text.strip())
        if "decision" in data:
            return data
    except (json.JSONDecodeError, ValueError):
        pass

    # Level 2: extract from code blocks
    code_match = re.search(r"```(?:json)?\s*\n?({.*?})\s*\n?```", response_text, re.DOTALL)
    if code_match:
        try:
            data = json.loads(code_match.group(1))
            if "decision" in data:
                return data
        except (json.JSONDecodeError, ValueError):
            pass

    # Level 3: scan for decision field with regex
    decision_match = re.search(r'"decision"\s*:\s*"(yes|no)"', response_text, re.IGNORECASE)
    reason_match = re.search(r'"reason"\s*:\s*"([^"]*?)"', response_text, re.IGNORECASE)
    if decision_match:
        return {
            "decision": decision_match.group(1).lower(),
            "reason": reason_match.group(1) if reason_match else "no reason provided",
        }

    # Level 4: conservative default
    return {"decision": "no", "reason": "could not parse LLM response"}


# ---------------------------------------------------------------------------
# Orphan process guard
# ---------------------------------------------------------------------------

_parent_pid = os.getppid()
_start_time = time.time()


def _check_orphan_guard() -> bool:
    """Return True if we should continue, False if we should exit."""
    elapsed = time.time() - _start_time
    if elapsed > FULL_AGENT_TIMEOUT_SECONDS:
        print("[learning-rules] orphan guard: exceeded hard timeout, exiting", file=sys.stderr)
        return False

    if elapsed > 120:  # only check parent after 2 min to avoid early false negatives
        try:
            if not is_process_alive(_parent_pid):
                print("[learning-rules] orphan guard: parent process dead, exiting", file=sys.stderr)
                return False
        except Exception:
            pass

    return True


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

def extract_signals(state: LearningRulesState) -> LearningRulesState:
    """Extract fresh learning signals from the database and load existing signals."""
    if not _check_orphan_guard():
        raise RuntimeError("Orphan guard: parent dead or timeout exceeded")
    try:
        from learning_analyzer import LearningAnalyzer, compute_rule_hash

        analyzer = LearningAnalyzer()
        new_signals = analyzer.extract_all(session_id=None)

        # Apply memory limits
        new_signals = new_signals[:MAX_EXTRACT_RULES]

        # Compute hashes for comparison
        for rule in new_signals:
            if "hash" not in rule:
                rule["hash"] = compute_rule_hash(
                    rule.get("category", ""),
                    rule.get("pattern", ""),
                )

        # Load existing signals baseline
        signals_path = STATE_DIR / "extracted_signals.json"
        existing_signals = []
        if signals_path.exists():
            try:
                with open(signals_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                existing_signals = data.get("rules", [])
            except Exception:
                pass

        # Load current MDC rules
        current_mdc_rules = _parse_mdc_rules(LEARNING_CRITICAL_PATH)

        print(
            f"[learning-rules] extracted {len(new_signals)} new signals, "
            f"{len(existing_signals)} existing, {len(current_mdc_rules)} MDC rules",
            file=sys.stderr,
        )

        return {
            **state,
            "new_signals": new_signals,
            "existing_signals": existing_signals,
            "current_mdc_rules": current_mdc_rules,
        }

    except Exception as e:
        print(f"[learning-rules] extract_signals failed: {e}", file=sys.stderr)
        return {
            **state,
            "new_signals": [],
            "existing_signals": [],
            "current_mdc_rules": [],
        }


def evaluate_rules(state: LearningRulesState) -> LearningRulesState:
    """Run both effectiveness systems on the extracted signals."""
    if not _check_orphan_guard():
        raise RuntimeError("Orphan guard: parent dead or timeout exceeded")
    new_signals = state.get("new_signals", [])
    if not new_signals:
        return state

    try:
        from learning_analyzer import (
            compute_rule_effectiveness,
            compute_rule_hash,
            LearningAnalyzer,
            _get_session_sentiment_map,
        )

        # Sentiment-based effectiveness
        try:
            from learning_analyzer import get_db
            with get_db() as db:
                sentiment_map = _get_session_sentiment_map(db)
                compute_rule_effectiveness(new_signals, sentiment_map)
        except Exception as e:
            print(f"[learning-rules] sentiment effectiveness failed: {e}", file=sys.stderr)

        # Recurrence-based effectiveness
        analyzer = LearningAnalyzer()
        recurrence = analyzer.compute_recurrence_effectiveness()

        # Attach recurrence scores
        for rule in new_signals:
            rule_hash = rule.get("hash", compute_rule_hash(
                rule.get("category", ""),
                rule.get("pattern", ""),
            ))
            rule["recurrence_effectiveness"] = recurrence.get(rule_hash, "unknown")

        print("[learning-rules] effectiveness evaluation complete", file=sys.stderr)

        return {**state, "new_signals": new_signals}

    except Exception as e:
        print(f"[learning-rules] evaluate_rules failed: {e}", file=sys.stderr)
        return state


def compare_with_existing(state: LearningRulesState) -> LearningRulesState:
    """Compare new signals against existing rules and produce a change diff."""
    if not _check_orphan_guard():
        raise RuntimeError("Orphan guard: parent dead or timeout exceeded")
    new_signals = state.get("new_signals", [])
    existing_signals = state.get("existing_signals", [])
    current_mdc_rules = state.get("current_mdc_rules", [])

    try:
        from learning_analyzer import compute_rule_hash

        # Build hash sets
        existing_hashes = set()
        for rule in existing_signals:
            h = rule.get("hash", compute_rule_hash(
                rule.get("category", ""),
                rule.get("pattern", ""),
            ))
            existing_hashes.add(h)

        mdc_pattern_hashes = set()
        for rule in current_mdc_rules:
            # Reconstruct a hash from the MDC rule pattern text
            pattern = rule.get("pattern", "")
            # Try to match the pattern to a signal
            for sig in existing_signals:
                sig_pattern = sig.get("pattern", "")
                if pattern in sig_pattern or sig_pattern in pattern:
                    mdc_pattern_hashes.add(sig.get("hash", compute_rule_hash(
                        sig.get("category", ""),
                        sig.get("pattern", ""),
                    )))
                    break

        new_hashes = set()
        for rule in new_signals:
            h = rule.get("hash", compute_rule_hash(
                rule.get("category", ""),
                rule.get("pattern", ""),
            ))
            new_hashes.add(h)

        # Find genuinely new rules
        new_only = new_hashes - existing_hashes
        new_rules = [r for r in new_signals if r.get("hash") in new_only]

        # Find rules now proven ineffective
        ineffective_rules = [
            r for r in new_signals
            if r.get("recurrence_effectiveness") == "ineffective"
        ]

        # Find ranking changes (top rules by count changed)
        existing_top = sorted(existing_signals, key=lambda x: x.get("count", 0), reverse=True)[:5]
        new_top = sorted(new_signals, key=lambda x: x.get("count", 0), reverse=True)[:5]
        existing_top_hashes = {r.get("hash") for r in existing_top}
        new_top_hashes = {r.get("hash") for r in new_top}
        ranking_changes = len(new_top_hashes ^ existing_top_hashes)

        change_diff = (
            f"{len(new_rules)} new rule(s) not in existing signals. "
            f"{len(ineffective_rules)} rule(s) now ineffective (recurrence). "
            f"{ranking_changes} top-5 ranking change(s). "
            f"Total signals: {len(new_signals)} (was {len(existing_signals)})."
        )

        # Truncate diff for LLM prompt
        change_diff = change_diff[:LLM_PROMPT_MAX_DIFF_LENGTH]

        print(f"[learning-rules] compare: {change_diff}", file=sys.stderr)

        return {
            **state,
            "change_diff": change_diff,
        }

    except Exception as e:
        print(f"[learning-rules] compare_with_existing failed: {e}", file=sys.stderr)
        return {**state, "change_diff": "comparison failed"}


def llm_decide(state: LearningRulesState) -> LearningRulesState:
    """Use an LLM to decide whether learning-critical.mdc should be rewritten."""
    if not _check_orphan_guard():
        raise RuntimeError("Orphan guard: parent dead or timeout exceeded")
    new_signals = state.get("new_signals", [])
    current_mdc_rules = state.get("current_mdc_rules", [])
    change_diff = state.get("change_diff", "")

    try:
        llm = get_llm()
    except Exception:
        print("[learning-rules] LLM unavailable, defaulting to skip", file=sys.stderr)
        return {
            **state,
            "should_write": False,
            "decision_reason": "LLM unavailable, conservative skip",
        }

    try:
        # Build prompt sections with sanitization

        # Current rules section
        rules_section = "CURRENT RULES in learning-critical.mdc:\n"
        for i, rule in enumerate(current_mdc_rules[:LLM_PROMPT_MAX_RULES]):
            pattern = _scrub_secrets(rule.get("pattern", "")[:150])
            text = _scrub_secrets(rule.get("full_text", "")[:150])
            rules_section += f"{i+1}. [{rule.get('rule_id', '?')}] {pattern}\n   {text}\n\n"
        if not current_mdc_rules:
            rules_section += "(no current rules)\n"

        # Change diff section
        diff_section = f"PROPOSED CHANGES:\n{_scrub_secrets(change_diff[:LLM_PROMPT_MAX_DIFF_LENGTH])}\n"

        # Effectiveness data section
        eff_section = "EFFECTIVENESS DATA (top signals):\n"
        # Sort by effectiveness priority then count
        eff_priority = {"negative": 0, "positive": 1, "neutral": 2, "insufficient_data": 3}
        sorted_signals = sorted(
            new_signals,
            key=lambda r: (
                eff_priority.get(r.get("effectiveness_score", "insufficient_data"), 3),
                -r.get("count", 0),
            ),
        )
        for i, sig in enumerate(sorted_signals[:LLM_PROMPT_MAX_SIGNALS]):
            lesson = _scrub_secrets(sig.get("lesson", "")[:LLM_PROMPT_MAX_LESSING_LENGTH])
            eff = sig.get("effectiveness_score", "unknown")
            rec_eff = sig.get("recurrence_effectiveness", "unknown")
            eff_section += (
                f"{i+1}. [{sig.get('category', '?')}] {sig.get('pattern', '')[:120]}\n"
                f"   Sentiment: {eff}, Recurrence: {rec_eff}, Count: {sig.get('count', 0)}\n"
                f"   {lesson}\n\n"
            )

        system_prompt = (
            "You are evaluating whether to rewrite the learning rules file "
            "(.cursor/rules/learning-critical.mdc). This file controls what the "
            "AI coding agent learns from its sessions. Only rewrite it when "
            "there are genuinely new patterns or existing rules are proven ineffective."
        )

        user_prompt = (
            f"{rules_section}\n"
            f"{diff_section}\n"
            f"{eff_section}\n"
            "DECIDE: Should learning-critical.mdc be rewritten?\n"
            'Answer "yes" only if:\n'
            "- There are 2+ genuinely new patterns not in current rules, OR\n"
            "- 2+ current rules are proven ineffective (recurrence), OR\n"
            "- The top-10 ranking would meaningfully change\n"
            '\nOtherwise answer "no".\n\n'
            'Respond in JSON: {"decision": "yes"|"no", "reason": "..."}'
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        response = llm.invoke(messages)
        response_text = response.content if hasattr(response, "content") else str(response)

        parsed = _parse_llm_decision(response_text)
        decision = parsed.get("decision", "no").lower()
        reason = parsed.get("reason", "no reason provided")

        should_write = decision == "yes"

        print(
            f"[learning-rules] LLM decision: {decision}, reason: {reason[:100]}",
            file=sys.stderr,
        )

        return {
            **state,
            "should_write": should_write,
            "decision_reason": reason,
        }

    except Exception as e:
        print(f"[learning-rules] llm_decide failed: {e}", file=sys.stderr)
        return {
            **state,
            "should_write": False,
            "decision_reason": f"LLM call failed: {str(e)[:100]}",
        }


def write_or_skip(state: LearningRulesState) -> LearningRulesState:
    """Write learning-critical.mdc if should_write, otherwise log skip."""
    if not _check_orphan_guard():
        raise RuntimeError("Orphan guard: parent dead or timeout exceeded")
    should_write = state.get("should_write", False)
    decision_reason = state.get("decision_reason", "")

    try:
        if should_write:
            # Create backup of current file (frontmatter stripped to prevent loading as rule)
            if LEARNING_CRITICAL_PATH.exists():
                backup_path = LEARNING_CRITICAL_PATH.with_suffix(".mdc.bak")
                try:
                    from learning_analyzer import _strip_frontmatter_backup
                    _strip_frontmatter_backup(LEARNING_CRITICAL_PATH, backup_path)
                except Exception as e:
                    print(f"[learning-rules] backup failed: {e}", file=sys.stderr)

            # Acquire lock before writing
            if not _try_acquire_lock():
                print("[learning-rules] could not acquire lock, skipping write", file=sys.stderr)
                return {
                    **state,
                    "write_result": "lock not acquired, skipped",
                }

            try:
                from learning_analyzer import LearningAnalyzer
                analyzer = LearningAnalyzer()
                success = analyzer.sync_to_critical_mdc()

                # Count rules written
                rules_written = 0
                if LEARNING_CRITICAL_PATH.exists():
                    rules_written = len(_parse_mdc_rules(LEARNING_CRITICAL_PATH))

                if success:
                    # Count signals for changelog
                    signal_count = len(state.get("new_signals", []))
                    _append_changelog({
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "mode": "full",
                        "decision": "write",
                        "reason": decision_reason,
                        "llm_reasoning": decision_reason,
                        "signals_count": signal_count,
                        "rules_written": rules_written,
                        "session_id": state.get("session_id", "all"),
                    })
                    write_result = f"success, {rules_written} rules written"
                else:
                    write_result = "sync_to_critical_mdc returned False"

                print(f"[learning-rules] write_or_skip: {write_result}", file=sys.stderr)

                return {**state, "write_result": write_result}

            finally:
                _release_lock()

        else:
            # Skip — log it
            signal_count = len(state.get("new_signals", []))
            _append_changelog({
                "ts": datetime.now(timezone.utc).isoformat(),
                "mode": "full",
                "decision": "skip",
                "reason": decision_reason,
                "signals_count": signal_count,
                "session_id": state.get("session_id", "all"),
            })

            print("[learning-rules] write_or_skip: skipped", file=sys.stderr)

            return {**state, "write_result": "skipped"}

    except Exception as e:
        print(f"[learning-rules] write_or_skip failed: {e}", file=sys.stderr)
        return {**state, "write_result": f"failed: {e}"}


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph() -> StateGraph:
    """Build the learning rules StateGraph."""
    builder = StateGraph(LearningRulesState)

    builder.add_node("extract_signals", extract_signals)
    builder.add_node("evaluate_rules", evaluate_rules)
    builder.add_node("compare_with_existing", compare_with_existing)
    builder.add_node("llm_decide", llm_decide)
    builder.add_node("write_or_skip", write_or_skip)

    builder.add_edge(START, "extract_signals")
    builder.add_edge("extract_signals", "evaluate_rules")
    builder.add_edge("evaluate_rules", "compare_with_existing")
    builder.add_edge("compare_with_existing", "llm_decide")
    builder.add_edge("llm_decide", "write_or_skip")
    builder.add_edge("write_or_skip", END)

    return builder.compile()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2 or sys.argv[1] != "--full":
        print("Usage: learning_rules_langgraph.py --full", file=sys.stderr)
        sys.exit(1)

    # Orphan process guard check
    if not _check_orphan_guard():
        sys.exit(0)

    print("[learning-rules] starting full LangGraph agent...", file=sys.stderr)
    start_time = time.time()

    graph = build_graph()
    result = graph.invoke({
        "session_id": "all",
        "mode": "full",
    })

    elapsed = time.time() - start_time
    print(
        f"[learning-rules] completed in {elapsed:.1f}s: "
        f"should_write={result.get('should_write')}, "
        f"result={result.get('write_result')}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
