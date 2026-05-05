#!/usr/bin/env python3
"""
Summarizer Daemon - Long-running background process for batch trigger processing.

Polls a trigger directory, collects and deduplicates triggers by session_id,
then invokes the summarizer LangGraph agent once per session per poll cycle.

Usage:
    python summarizer_daemon.py              # Run as foreground daemon
    python summarizer_daemon.py --start      # Launch as detached background process

Configuration:
    SUMMARIZER_POLL_INTERVAL in llm.env (default: 5, minimum: 1)
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path

# Resolve paths relative to this script
HOOKS_DIR = Path(__file__).parent.resolve()
LLM_ENV_PATH = HOOKS_DIR.parent / "llm.env"
STATE_DIR = HOOKS_DIR / "state"
TRIGGER_DIR = STATE_DIR / "summarizer_triggers"
SENTIMENT_ARC_TRIGGER_DIR = STATE_DIR / "sentiment_arc_triggers"
PID_FILE = STATE_DIR / "summarizer_daemon.pid"
DAEMON_LOG = STATE_DIR / "summarizer_daemon.log"

# Load LLM env
from dotenv import load_dotenv
load_dotenv(str(LLM_ENV_PATH), override=True)

# Configurable poll interval (E5: clamp to minimum 1s)
_raw_interval = os.getenv("SUMMARIZER_POLL_INTERVAL", "5")
try:
    POLL_INTERVAL = int(_raw_interval)
except (ValueError, TypeError):
    POLL_INTERVAL = 5
POLL_INTERVAL = max(1, POLL_INTERVAL)
if POLL_INTERVAL != int(_raw_interval):
    print(
        f"[daemon] POLL_INTERVAL clamped to {POLL_INTERVAL}s (minimum)",
        file=sys.stderr,
    )

# Import summarizer components after env is loaded
sys.path.insert(0, str(HOOKS_DIR))
from summarizer_agent import build_graph, acquire_lock, release_lock, is_process_alive

# Graceful shutdown flag (E10)
_shutdown_flag = False

LOCK_TIMEOUT_SECONDS = 120
STALE_TRIGGER_AGE_SECONDS = 24 * 3600  # 24 hours (E9)
CLEANUP_CYCLE_INTERVAL = 10  # Run cleanup every N poll cycles (E9)
MAX_RETRY_COUNT = 5  # Max retries per trigger before giving up


def debug_log(message: str):
    """Write debug message to daemon log file."""
    try:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(DAEMON_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


def write_pid_file():
    """Write PID file for daemon detection (E2).

    Before writing, checks if an existing PID file references a still-alive
    process with a different PID. If so, logs a warning and refuses to start
    to prevent duplicate daemon instances.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    if PID_FILE.exists():
        try:
            content = PID_FILE.read_text().strip()
            parts = content.split("|")
            existing_pid = int(parts[0])
            if existing_pid != os.getpid() and is_process_alive(existing_pid):
                debug_log(
                    f"[daemon] PID file references live PID {existing_pid}, "
                    f"refusing to start to avoid duplicate daemon"
                )
                raise RuntimeError(
                    f"Daemon already running (PID={existing_pid}). "
                    f"Cannot start duplicate instance."
                )
        except (ValueError, OSError):
            PID_FILE.unlink(missing_ok=True)

    PID_FILE.write_text(f"{os.getpid()}|{time.time()}")


def remove_pid_file():
    PID_FILE.unlink(missing_ok=True)


def is_daemon_running() -> bool:
    """Check if a daemon instance is already running (E2, E3)."""
    if not PID_FILE.exists():
        return False
    try:
        content = PID_FILE.read_text().strip()
        parts = content.split("|")
        pid = int(parts[0])
        timestamp = float(parts[1]) if len(parts) > 1 else 0
        elapsed = time.time() - timestamp

        if is_process_alive(pid):
            return True

        # Process is dead, check if PID file is stale (>60s)
        if elapsed > 60:
            PID_FILE.unlink(missing_ok=True)
            return False

        # Process dead but PID file is recent -- treat as stale
        PID_FILE.unlink(missing_ok=True)
        return False
    except (ValueError, OSError):
        PID_FILE.unlink(missing_ok=True)
        return False


def write_trigger(session_id: str, force: bool = False):
    """Producer: write a trigger file (idempotent -- overwrites existing)."""
    TRIGGER_DIR.mkdir(parents=True, exist_ok=True)
    trigger_file = TRIGGER_DIR / f"{session_id}.json"
    trigger_file.write_text(json.dumps({
        "session_id": session_id,
        "force": force,
        "created_at": time.time(),
    }))


def collect_triggers() -> dict:
    """
    Consumer: gather all pending triggers, deduplicate by session_id.

    E4: Skips corrupted JSON files gracefully.
    E8: Handles Windows file locking conflicts via OSError catch.
    E12: Force flag always wins during deduplication.
    """
    triggers: dict[str, bool] = {}
    try:
        trigger_files = list(TRIGGER_DIR.glob("*.json"))
    except OSError:
        return triggers

    for f in trigger_files:
        try:
            raw = f.read_text()
            # Strip BOM if present (PowerShell or Windows editors may add it)
            if raw.startswith('\ufeff'):
                raw = raw[1:]
            data = json.loads(raw)
            sid = data["session_id"]
            # Force flag always wins (E12)
            if sid not in triggers or data.get("force"):
                triggers[sid] = data.get("force", False)
        except (json.JSONDecodeError, KeyError, OSError):
            # E4: Corrupted file, E8: File lock conflict -- skip
            pass

    return triggers


def collect_sentiment_triggers() -> dict:
    """
    Consumer: gather all pending sentiment arc triggers, deduplicate by session_id.

    Same pattern as collect_triggers() but reads from SENTIMENT_ARC_TRIGGER_DIR.
    """
    triggers: dict[str, bool] = {}
    try:
        trigger_files = list(SENTIMENT_ARC_TRIGGER_DIR.glob("*.json"))
    except OSError:
        return triggers

    for f in trigger_files:
        try:
            raw = f.read_text()
            if raw.startswith('\ufeff'):
                raw = raw[1:]
            data = json.loads(raw)
            sid = data["session_id"]
            triggers[sid] = True
        except (json.JSONDecodeError, KeyError, OSError):
            pass

    return triggers


def _should_retry_trigger(trigger_file: Path) -> bool:
    """Check if a trigger should be retried based on retry count and age."""
    try:
        raw = trigger_file.read_text()
        data = json.loads(raw)
        retry_count = data.get("retry_count", 0)
        created_at = data.get("created_at", 0)
        age = time.time() - created_at

        if retry_count >= MAX_RETRY_COUNT:
            return False
        if age > STALE_TRIGGER_AGE_SECONDS:
            return False
        return True
    except (OSError, json.JSONDecodeError, KeyError):
        return True


def _bump_retry_counter(trigger_file: Path):
    """Increment the retry counter on a trigger file."""
    try:
        raw = trigger_file.read_text()
        data = json.loads(raw)
        data["retry_count"] = data.get("retry_count", 0) + 1
        data["last_retry_at"] = time.time()
        trigger_file.write_text(json.dumps(data))
    except (OSError, json.JSONDecodeError):
        pass


def process_batch(triggers: dict, graph):
    """
    Invoke summarizer once per session in batch.

    E6: Per-session error isolation -- one failure doesn't stop the batch.
    E7: Sessions not yet initialized are handled by summarizer_agent's skip logic.
    """
    for session_id, force in triggers.items():
        trigger_file = TRIGGER_DIR / f"{session_id}.json"

        success = False
        try:
            if not acquire_lock(session_id):
                debug_log(f"[daemon] Failed to acquire lock for {session_id}, skipping")
                continue

            # Run sentiment arc analysis first so data is available for the summarizer
            try:
                from sentiment_arc.batch_runner import main as sentiment_main
                sentiment_main([
                    "--session-id", session_id,
                    "--no-progress",
                ])
            except Exception as e:
                debug_log(f"[daemon] Sentiment pre-analysis skipped for {session_id}: {e}")

            result = graph.invoke({
                "session_id": session_id,
                "force": force,
                "regenerate": False,
            })

            strategy = result.get("strategy", "unknown")
            if strategy == "skip":
                debug_log(f"[daemon] Skipped {session_id} (strategy=skip)")
            elif result.get("error"):
                debug_log(f"[daemon] Error for {session_id}: {result['error']}")
            else:
                debug_log(f"[daemon] Summarized {session_id} (strategy={strategy})")
                success = True

        except Exception as e:
            # E6: Log failure but continue batch
            debug_log(f"[daemon] Failed to summarize {session_id}: {e}")
            traceback.print_exc()
            success = False
        finally:
            release_lock(session_id)

        if success:
            trigger_file.unlink(missing_ok=True)
        else:
            if _should_retry_trigger(trigger_file):
                _bump_retry_counter(trigger_file)
                debug_log(f"[daemon] Keeping trigger for {session_id} (retry scheduled)")
            else:
                trigger_file.unlink(missing_ok=True)
                debug_log(f"[daemon] Deleting exhausted/stale trigger for {session_id}")


def process_sentiment_batch(triggers: dict):
    """
    Run sentiment arc analysis once per session in batch.

    E6: Per-session error isolation -- one failure doesn't stop the batch.
    Calls sentiment_arc.batch_runner.main() for each session.
    """
    for session_id in triggers:
        trigger_file = SENTIMENT_ARC_TRIGGER_DIR / f"{session_id}.json"

        success = False
        try:
            sys.path.insert(0, str(HOOKS_DIR))
            from sentiment_arc.batch_runner import main as sentiment_main

            ret = sentiment_main([
                "--session-id", session_id,
                "--no-progress",
            ])
            if ret == 0:
                debug_log(f"[daemon] Sentiment arc analyzed {session_id}")
                success = True
            else:
                debug_log(f"[daemon] Sentiment arc analysis failed for {session_id} (exit={ret})")

        except Exception as e:
            debug_log(f"[daemon] Sentiment arc exception for {session_id}: {e}")
            traceback.print_exc()
            success = False

        if success:
            trigger_file.unlink(missing_ok=True)
        else:
            if _should_retry_trigger(trigger_file):
                _bump_retry_counter(trigger_file)
                debug_log(f"[daemon] Keeping sentiment trigger for {session_id} (retry scheduled)")
            else:
                trigger_file.unlink(missing_ok=True)
                debug_log(f"[daemon] Deleting exhausted/stale sentiment trigger for {session_id}")


def cleanup_stale_triggers():
    """E9: Periodic cleanup of orphaned trigger files older than 24 hours."""
    try:
        now = time.time()
        count = 0
        for f in TRIGGER_DIR.glob("*.json"):
            try:
                age = now - f.stat().st_mtime
                if age > STALE_TRIGGER_AGE_SECONDS:
                    f.unlink(missing_ok=True)
                    count += 1
            except OSError:
                pass
        for f in SENTIMENT_ARC_TRIGGER_DIR.glob("*.json"):
            try:
                age = now - f.stat().st_mtime
                if age > STALE_TRIGGER_AGE_SECONDS:
                    f.unlink(missing_ok=True)
                    count += 1
            except OSError:
                pass
        if count > 0:
            debug_log(f"[daemon] Cleaned up {count} stale trigger files")
    except Exception:
        pass


def shutdown_handler(signum, frame):
    """E10: Set shutdown flag on signal, finish current batch then exit."""
    global _shutdown_flag
    debug_log(f"[daemon] Received signal {signum}, finishing current batch...")
    _shutdown_flag = True


def daemon_loop():
    """Main daemon loop with graceful shutdown support."""
    global _shutdown_flag

    TRIGGER_DIR.mkdir(parents=True, exist_ok=True)
    SENTIMENT_ARC_TRIGGER_DIR.mkdir(parents=True, exist_ok=True)
    write_pid_file()

    # Register signal handlers (E10)
    try:
        signal.signal(signal.SIGINT, shutdown_handler)
        signal.signal(signal.SIGTERM, shutdown_handler)
    except (ValueError, OSError):
        # Signal handlers may not work in all contexts (e.g. non-main thread)
        pass

    debug_log(f"[daemon] Started (PID={os.getpid()}, poll_interval={POLL_INTERVAL}s)")

    # Build the LangGraph once at startup -- it is static and does not change
    graph = build_graph()

    poll_cycle = 0

    try:
        while not _shutdown_flag:
            triggers = collect_triggers()

            if triggers:
                debug_log(f"[daemon] Processing batch: {len(triggers)} session(s)")
                process_batch(triggers, graph)

            sentiment_triggers = collect_sentiment_triggers()
            if sentiment_triggers:
                debug_log(f"[daemon] Processing sentiment batch: {len(sentiment_triggers)} session(s)")
                process_sentiment_batch(sentiment_triggers)

            # E9: Periodic cleanup every CLEANUP_CYCLE_INTERVAL cycles
            poll_cycle += 1
            if poll_cycle >= CLEANUP_CYCLE_INTERVAL:
                cleanup_stale_triggers()
                poll_cycle = 0

            # Sleep in small increments to allow signal handling (E10)
            elapsed = 0
            while elapsed < POLL_INTERVAL and not _shutdown_flag:
                time.sleep(min(1, POLL_INTERVAL - elapsed))
                elapsed += 1

    except KeyboardInterrupt:
        pass
    finally:
        debug_log("[daemon] Shutting down")
        remove_pid_file()


def stop_daemon() -> bool:
    """Stop the running daemon by reading PID file and terminating the process.

    Returns True if daemon was stopped or wasn't running, False if stop failed.
    """
    if not PID_FILE.exists():
        debug_log("[daemon] Stop requested but no PID file found (not running)")
        return True

    try:
        content = PID_FILE.read_text().strip()
        parts = content.split("|")
        pid = int(parts[0])
    except (ValueError, OSError) as e:
        debug_log(f"[daemon] Failed to read PID file for stop: {e}")
        PID_FILE.unlink(missing_ok=True)
        return True

    if not _is_process_alive(pid):
        debug_log(f"[daemon] PID {pid} not alive, cleaning up stale PID file")
        PID_FILE.unlink(missing_ok=True)
        return True

    debug_log(f"[daemon] Stopping daemon (PID={pid})")

    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True, text=True, timeout=10,
            )
            debug_log(f"[daemon] taskkill sent to PID {pid}")
        except (subprocess.SubprocessError, OSError) as e:
            debug_log(f"[daemon] taskkill failed: {e}, trying os.kill fallback")
            try:
                os.kill(pid, signal.SIGINT)
            except OSError:
                pass
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass

    PID_FILE.unlink(missing_ok=True)
    debug_log(f"[daemon] Daemon stop complete for PID {pid}")
    return True


def daemonize():
    """Launch this script as a detached background process."""
    python_exe = sys.executable or shutil.which("python") or "python"
    script_path = str(Path(__file__).absolute())

    try:
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        subprocess.Popen(
            [python_exe, script_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            cwd=str(HOOKS_DIR),
        )
        print("[daemon] Daemon launched in background", file=sys.stderr)
    except Exception as e:
        print(f"[daemon] Failed to launch daemon: {e}", file=sys.stderr)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--start":
        daemonize()
    elif len(sys.argv) > 1 and sys.argv[1] == "--stop":
        stop_daemon()
    else:
        daemon_loop()


if __name__ == "__main__":
    main()
