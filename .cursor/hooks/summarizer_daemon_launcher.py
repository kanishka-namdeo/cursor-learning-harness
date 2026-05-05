#!/usr/bin/env python3
"""
Summarizer Daemon Launcher - Ensures exactly one daemon instance.

Checks if the daemon is already running (via PID file + process check).
If running, does nothing. If not, starts it as a detached background process.

Used by summarizer_trigger.py to ensure the daemon is alive before writing triggers.
"""

import os
import sys
import shutil
import time
import subprocess
from pathlib import Path

# Resolve paths relative to this script
HOOKS_DIR = Path(__file__).parent.resolve()
LLM_ENV_PATH = HOOKS_DIR.parent / "llm.env"
STATE_DIR = HOOKS_DIR / "state"
PID_FILE = STATE_DIR / "summarizer_daemon.pid"

_PYTHON = shutil.which("python") or "python"
PYTHON_PATH = sys.executable if sys.executable else _PYTHON
DAEMON_SCRIPT = str(HOOKS_DIR / "summarizer_daemon.py")

# Import shared _is_process_alive from summarizer_agent (single source of truth)
sys.path.insert(0, str(HOOKS_DIR))
from conversation_recorder import is_process_alive


def is_daemon_running() -> bool:
    """
    Check if the daemon is already running (E2, E3).

    Returns True if the PID file exists and the process is alive.
    Removes stale PID files (process dead or file older than 60s).
    """
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

        # Process is dead
        if elapsed > 60:
            # Definitely stale, remove it
            PID_FILE.unlink(missing_ok=True)
        else:
            # Recent but process dead -- also stale
            PID_FILE.unlink(missing_ok=True)

        return False
    except (ValueError, OSError):
        PID_FILE.unlink(missing_ok=True)
        return False


LAUNCH_LOCK = STATE_DIR / ".daemon_launch_lock"


def _acquire_launch_lock() -> int:
    """Acquire an exclusive launch lock. Returns the file descriptor."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(LAUNCH_LOCK), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o644)
    if os.name == "nt":
        try:
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            os.close(fd)
            return -1
    return fd


def _release_launch_lock(fd: int):
    """Release the exclusive launch lock."""
    if fd >= 0:
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass


def ensure_daemon_running():
    """
    Ensure the summarizer daemon is running.

    If already running, do nothing.
    If not running, launch it as a detached background process.

    Uses an exclusive launch lock to prevent race conditions when multiple
    hooks fire simultaneously.
    """
    launch_lock_fd = _acquire_launch_lock()
    try:
        if is_daemon_running():
            return

        STATE_DIR.mkdir(parents=True, exist_ok=True)
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        subprocess.Popen(
            [PYTHON_PATH, DAEMON_SCRIPT],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            cwd=str(HOOKS_DIR),
        )
    except Exception as e:
        print(f"[daemon-launcher] Failed to start daemon: {e}", file=sys.stderr)
    finally:
        _release_launch_lock(launch_lock_fd)


if __name__ == "__main__":
    ensure_daemon_running()
    print("[daemon-launcher] Daemon ensured", file=sys.stderr)
