"""
Learning Rules Agent CLI

CLI wrapper for the learning rules system with two modes:
  --quick-decide <session_id>  Rule-based sync check (sync, within hook timeout)
  --full                       Full LangGraph agent (async, detached)

Usage:
    python learning_rules_agent.py --quick-decide <session_id>
    python learning_rules_agent.py --full
"""

import hashlib
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

# Resolve paths relative to this script
HOOKS_DIR = Path(__file__).parent.resolve()
STATE_DIR = HOOKS_DIR / "state"
LEARNING_CRITICAL_PATH = HOOKS_DIR.parent / "rules" / "learning-critical.mdc"
EXTRACTED_SIGNALS_PATH = STATE_DIR / "extracted_signals.json"
LAST_SIGNALS_PATH = STATE_DIR / ".last_extracted_signals.json"
CHANGELOG_PATH = STATE_DIR / "learning_rules_changelog.jsonl"

sys.path.insert(0, str(HOOKS_DIR))
from conversation_recorder import debug_log
from learning_rules_langgraph import (
    _try_acquire_lock,
    _release_lock,
    LEARNING_RULES_LOCK_PATH,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

QUICK_DECIDE_NEW_RULES_THRESHOLD = 2
QUICK_DECIDE_INEFFECTIVE_THRESHOLD = 2
QUICK_DECIDE_TIMEOUT_SECONDS = 10
CHANGELOG_MAX_SIZE_BYTES = 1_000_000  # 1MB

_REQUIRED_FIELDS = {"ts", "mode", "decision", "reason"}
_VALID_MODES = {"quick", "full"}
_VALID_DECISIONS = {"write", "skip"}


# ---------------------------------------------------------------------------
# Changelog helpers (same pattern as learning_rules_langgraph.py)
# ---------------------------------------------------------------------------

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
        debug_log("learning_rules: changelog entry validation failed")
        return False

    _rotate_changelog_if_needed()

    # Acquire lock to prevent concurrent writes with full agent
    acquired = _try_acquire_lock()
    if not acquired:
        # Retry once after short sleep
        time.sleep(0.5)
        acquired = _try_acquire_lock()
        if not acquired:
            debug_log("learning_rules: could not acquire lock for changelog append")
            return False

    try:
        CHANGELOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(str(CHANGELOG_PATH), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        return True
    except Exception as e:
        debug_log(f"learning_rules: failed to write changelog: {e}")
        return False
    finally:
        _release_lock()


# ---------------------------------------------------------------------------
# Baseline update (atomic write)
# ---------------------------------------------------------------------------

def _update_baseline(signals: list[dict]) -> bool:
    """Atomically update .last_extracted_signals.json with current signals."""
    try:
        payload = {"rules": signals}
        fd, tmp_path = tempfile.mkstemp(
            dir=str(LAST_SIGNALS_PATH.parent),
            suffix=".json.tmp",
        )
        try:
            with open(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, default=str)
            LAST_SIGNALS_PATH.unlink(missing_ok=True)
            Path(tmp_path).rename(LAST_SIGNALS_PATH)
            return True
        except Exception:
            Path(tmp_path).unlink(missing_ok=True)
            raise
    except Exception as e:
        debug_log(f"learning_rules: failed to update baseline: {e}")
        return False


# ---------------------------------------------------------------------------
# Quick-decide mode
# ---------------------------------------------------------------------------

def _quick_decide(session_id: str) -> bool:
    """Rule-based check: should learning-critical.mdc be rewritten?

    Compares extracted_signals.json against .last_extracted_signals.json.
    Writes to learning-critical.mdc if new_rules >= threshold OR
    ineffective_rules >= threshold.

    Transactional ordering:
    1. sync_to_critical_mdc() (critical side effect)
    2. Append changelog entry (audit trail)
    3. Update .last_extracted_signals.json (comparison baseline)
    """
    try:
        from learning_analyzer import compute_rule_hash, LearningAnalyzer

        # Load current signals
        current_rules = []
        if EXTRACTED_SIGNALS_PATH.exists():
            try:
                with open(EXTRACTED_SIGNALS_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                current_rules = data.get("rules", [])
            except Exception:
                pass

        if not current_rules:
            debug_log(f"learning_rules: no signals for session {session_id[:12]}..., skipping")
            return False

        # Compute hashes for current rules
        for rule in current_rules:
            if "hash" not in rule:
                rule["hash"] = compute_rule_hash(
                    rule.get("category", ""),
                    rule.get("pattern", ""),
                )

        # Load previous baseline
        previous_rules = []
        if LAST_SIGNALS_PATH.exists():
            try:
                with open(LAST_SIGNALS_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                previous_rules = data.get("rules", [])
            except Exception:
                pass

        previous_hashes = set()
        for rule in previous_rules:
            h = rule.get("hash", compute_rule_hash(
                rule.get("category", ""),
                rule.get("pattern", ""),
            ))
            previous_hashes.add(h)

        # Find new unique rules
        current_hashes = {r.get("hash") for r in current_rules}
        new_hashes = current_hashes - previous_hashes
        new_rules_count = len(new_hashes)

        # Find rules that are now ineffective (check recurrence)
        ineffective_count = 0
        try:
            analyzer = LearningAnalyzer()
            recurrence = analyzer.compute_recurrence_effectiveness()
            for rule in current_rules:
                h = rule.get("hash")
                if recurrence.get(h) == "ineffective":
                    ineffective_count += 1
        except Exception as e:
            debug_log(f"learning_rules: recurrence check failed: {e}")

        # Decision
        signals_before = len(previous_rules)
        signals_after = len(current_rules)
        should_write = (
            new_rules_count >= QUICK_DECIDE_NEW_RULES_THRESHOLD
            or ineffective_count >= QUICK_DECIDE_INEFFECTIVE_THRESHOLD
        )

        if should_write:
            debug_log(
                f"learning_rules: quick-decide WRITE — {new_rules_count} new, "
                f"{ineffective_count} ineffective for session {session_id[:12]}..."
            )

            # Step 1: Write learning-critical.mdc
            # Create backup first (frontmatter stripped to prevent loading as rule)
            if LEARNING_CRITICAL_PATH.exists():
                backup_path = LEARNING_CRITICAL_PATH.with_suffix(".mdc.bak")
                try:
                    from learning_analyzer import _strip_frontmatter_backup
                    _strip_frontmatter_backup(LEARNING_CRITICAL_PATH, backup_path)
                except Exception:
                    pass

            analyzer = LearningAnalyzer()
            sync_success = analyzer.sync_to_critical_mdc()

            if not sync_success:
                debug_log("learning_rules: quick-decide sync_to_critical_mdc failed, aborting")
                return False

            # Step 2: Append changelog
            _append_changelog({
                "ts": datetime.now(timezone.utc).isoformat(),
                "mode": "quick",
                "decision": "write",
                "reason": (
                    f"{new_rules_count} new unique patterns detected, "
                    f"{ineffective_count} rules now ineffective"
                ),
                "signals_before": signals_before,
                "signals_after": signals_after,
                "session_id": session_id,
            })

            # Step 3: Update baseline
            _update_baseline(current_rules)

        else:
            debug_log(
                f"learning_rules: quick-decide SKIP — {new_rules_count} new, "
                f"{ineffective_count} ineffective for session {session_id[:12]}..."
            )

            # Write skip changelog entry
            _append_changelog({
                "ts": datetime.now(timezone.utc).isoformat(),
                "mode": "quick",
                "decision": "skip",
                "reason": (
                    f"no meaningful change ({new_rules_count} new patterns, "
                    f"{ineffective_count} ineffective rules)"
                ),
                "signals_count": signals_after,
                "session_id": session_id,
            })

            # Still update baseline so we don't re-check the same signals next time
            _update_baseline(current_rules)

        return True

    except Exception as e:
        debug_log(f"learning_rules: quick-decide failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Full mode
# ---------------------------------------------------------------------------

def _full_mode() -> bool:
    """Run the full LangGraph agent."""
    try:
        from learning_rules_langgraph import build_graph

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
        return True

    except Exception as e:
        print(f"[learning-rules] full mode failed: {e}", file=sys.stderr)
        debug_log(f"learning_rules: full mode failed: {e}")
        return False


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]

    if not args:
        print("Usage: python learning_rules_agent.py [OPTIONS]")
        print("  --quick-decide <session_id>  Rule-based sync check (sync)")
        print("  --full                       Full LangGraph agent (async)")
        sys.exit(1)

    if args[0] == "--quick-decide" and len(args) > 1:
        session_id = args[1]
        _quick_decide(session_id)

    elif args[0] == "--full":
        _full_mode()

    else:
        print(f"Unknown command: {args[0]}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
