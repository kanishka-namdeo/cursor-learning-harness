#!/usr/bin/env python3
"""
Cursor Agent Conversation Recorder - Utility Module

Provides shared utilities for recording agent conversations across all hook events.
Stores conversations in .cursor/hooks/state/ with session-based organization.
"""

import json
import sys
import os
import subprocess
import time
import uuid
import traceback
from datetime import datetime, timedelta
from pathlib import Path

try:
    import msvcrt
    HAS_FILE_LOCKING = True
except ImportError:
    HAS_FILE_LOCKING = False


HOOKS_DIR = Path(__file__).parent.resolve()
STATE_DIR = HOOKS_DIR / "state"
DEBUG_LOG = STATE_DIR / "hook-debug.log"
SESSIONS_DIR = STATE_DIR / "sessions"

_SESSION_LOCK_TIMEOUT = 10  # Max seconds to wait for a lock before giving up


# ---------------------------------------------------------------------------
# Shared utility: text truncation
# ---------------------------------------------------------------------------

TRUNCATION_MARKER = "[...truncated]"


def truncate(text: str, max_chars: int, marker: str = TRUNCATION_MARKER) -> str:
    """Truncate text to max_chars, appending marker if truncated."""
    if not text or len(text) <= max_chars:
        return text or ""
    return text[:max_chars - len(marker)] + marker


# ---------------------------------------------------------------------------
# Shared utility: cross-platform process check
# ---------------------------------------------------------------------------

def is_process_alive(pid: int) -> bool:
    """Check if a process with the given PID is alive (cross-platform)."""
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        pass

    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            return f" {pid} " in result.stdout or f"\t{pid}\t" in result.stdout
        except (subprocess.SubprocessError, OSError):
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


# ---------------------------------------------------------------------------
# Shared utility: resolve canonical session_id from hook payload
# ---------------------------------------------------------------------------

def get_raw_session_id(payload: dict) -> str:
    """Extract the raw session/conversation identifier from a hook payload.

    This is the value Cursor passes -- it may be a session_id that later gets
    resolved to a different conversation_id by ConversationLinker.
    """
    return payload.get("session_id") or payload.get("conversation_id") or "unknown"


def resolve_session_id(payload: dict) -> str:
    """Resolve the canonical session_id for the current hook invocation.

    Resolution order:
    1. Read conversation_id from the existing session.json (set by session_start.py)
    2. Fall back to get_raw_session_id(payload)
    """
    raw_id = get_raw_session_id(payload)
    if raw_id == "unknown":
        return raw_id

    session_file = SESSIONS_DIR / raw_id / "session.json"
    if session_file.exists():
        try:
            session = json.loads(session_file.read_text())
            resolved = session.get("conversation_id", "")
            if resolved:
                return resolved
        except (json.JSONDecodeError, OSError):
            pass

    return raw_id


def _lock_file(file_path: Path, timeout: int = _SESSION_LOCK_TIMEOUT) -> bool:
    """Acquire an exclusive file lock. Returns True on success, False on timeout."""
    if not HAS_FILE_LOCKING:
        return True  # No locking available, proceed anyway

    lock_path = file_path.with_suffix(file_path.suffix + ".lock")
    start = time.monotonic()

    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY | os.O_EXCL)
            # Store PID in lock file for debugging
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            if time.monotonic() - start >= timeout:
                return False
            time.sleep(0.05)


def _unlock_file(file_path: Path):
    """Release an exclusive file lock."""
    lock_path = file_path.with_suffix(file_path.suffix + ".lock")
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


def debug_log(message):
    """Write debug message to log file with automatic rotation."""
    try:
        DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        # Rotate log if it exceeds 1MB
        if DEBUG_LOG.exists() and DEBUG_LOG.stat().st_size > 1_000_000:
            for i in range(2, 0, -1):
                old = DEBUG_LOG.with_suffix(f".log.{i}")
                new = DEBUG_LOG.with_suffix(f".log.{i+1}")
                if old.exists():
                    if i == 2:
                        old.unlink(missing_ok=True)  # Drop oldest rotated log
                    else:
                        old.rename(new)
            DEBUG_LOG.rename(DEBUG_LOG.with_suffix(".log.1"))

        timestamp = datetime.now().isoformat()
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


CURRENT_JSON_SCHEMA_VERSION = 4


class ConversationLinker:
    """Manages stable conversation IDs across multiple sessions.

    Handles conversation ID generation, resolution heuristics, file locking,
    compaction detection, workspace fingerprinting, and subagent linking.
    """

    STATE_DIR = HOOKS_DIR / "state"
    LINKS_FILE = STATE_DIR / "conversation_links.json"
    FINGERPRINT_FILE = STATE_DIR / "conversation_fingerprint.json"
    SESSIONS_DIR = STATE_DIR / "sessions"

    def __init__(self):
        self.STATE_DIR.mkdir(parents=True, exist_ok=True)

    def _read_links(self) -> dict:
        """Read conversation links JSON file."""
        if self.LINKS_FILE.exists():
            return json.loads(self.LINKS_FILE.read_text())
        return {}

    def _write_links(self, links: dict):
        """Write conversation links JSON file with file locking."""
        if _lock_file(self.LINKS_FILE):
            try:
                self.LINKS_FILE.write_text(json.dumps(links, indent=2))
            finally:
                _unlock_file(self.LINKS_FILE)
        else:
            debug_log(f"Lock timeout writing {self.LINKS_FILE}, writing without lock")
            self.LINKS_FILE.write_text(json.dumps(links, indent=2))

    def get_or_create_conversation(self, session_id: str, payload: dict) -> str:
        """Resolve or create a stable conversation_id for a session.

        Resolution order:
        1. Check if session_id already has a conversation_id in links file
        2. Check for subagent session (use parent_conversation_id from payload)
        3. Check for recent compaction on previous session (reuse conversation_id)
        4. Check workspace fingerprint match (reuse existing conversation_id)
        5. Generate new UUID v4
        """
        links = self._read_links()

        # Check existing mapping
        if session_id in links:
            return links[session_id]

        # Subagent session
        parent_conv_id = payload.get("parent_conversation_id", "")
        if parent_conv_id:
            self.link_session_to_conversation(session_id, parent_conv_id)
            return parent_conv_id

        # Recent compaction check
        conv_id = self._resolve_from_recent_compaction(session_id, payload)
        if conv_id:
            self.link_session_to_conversation(session_id, conv_id)
            return conv_id

        # Workspace fingerprint check
        conv_id = self._resolve_from_fingerprint(payload)
        if conv_id:
            self.link_session_to_conversation(session_id, conv_id)
            return conv_id

        # Generate new
        conversation_id = str(uuid.uuid4())
        self.link_session_to_conversation(session_id, conversation_id)
        self._update_fingerprint(conversation_id, payload)
        return conversation_id

    def link_session_to_conversation(self, session_id: str, conversation_id: str):
        """Persist a session->conversation mapping."""
        links = self._read_links()
        links[session_id] = conversation_id
        self._write_links(links)

    def get_conversation_id_for_session(self, session_id: str) -> str | None:
        """Get the conversation_id for a session_id."""
        links = self._read_links()
        return links.get(session_id)

    def _resolve_from_recent_compaction(self, session_id: str, payload: dict) -> str | None:
        """Check if previous session had recent compaction (within 60s).

        If so, reuse that session's conversation_id.

        Optimization: only scans the last N sessions from the links file
        (sorted by most recently updated) instead of iterating ALL entries.
        """
        workspace_roots = payload.get("workspace_roots", [])
        if not workspace_roots:
            return None

        links = self._read_links()
        now = datetime.now()

        # Limit scan to the 10 most recently updated sessions to avoid O(n) I/O
        MAX_SCAN = 10
        candidates = []
        for sid, cid in links.items():
            session_file = self.SESSIONS_DIR / sid / "session.json"
            if not session_file.exists():
                continue
            try:
                session = json.loads(session_file.read_text())
                last_updated = session.get("last_updated", "")
                if not last_updated:
                    continue
                updated_at = datetime.fromisoformat(last_updated)
                if (now - updated_at) > timedelta(seconds=60):
                    continue
                events = session.get("events", [])
                has_recent_compaction = any(
                    e.get("type") == "compaction"
                    for e in events[-5:]
                )
                if has_recent_compaction:
                    candidates.append((updated_at, cid))
            except (json.JSONDecodeError, ValueError, OSError):
                continue

            # Stop scanning once we have enough candidates
            if len(candidates) >= MAX_SCAN:
                break

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]
        return None

    def _resolve_from_fingerprint(self, payload: dict) -> str | None:
        """Check workspace fingerprint for matching conversation.

        If workspace_roots, git_branch, and composer_mode match an existing
        fingerprint, reuse its conversation_id.
        """
        if not self.FINGERPRINT_FILE.exists():
            return None

        try:
            fingerprints = json.loads(self.FINGERPRINT_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return None

        workspace_key = json.dumps(payload.get("workspace_roots", []), sort_keys=True)
        git_branch = payload.get("git_branch", "")
        composer_mode = payload.get("composer_mode", "")

        for fp in fingerprints:
            if (fp.get("workspace_key") == workspace_key and
                fp.get("git_branch") == git_branch and
                fp.get("composer_mode") == composer_mode):
                # Check if conversation is not completed
                conv_id = fp.get("conversation_id")
                if conv_id:
                    # Verify conversation exists and is active
                    try:
                        from narratives_db import NarrativesDB
                        with NarrativesDB() as db:
                            sessions = db.get_sessions_by_conversation(conv_id)
                            if sessions:
                                last_session = sessions[-1]
                                if last_session.get("status") != "completed":
                                    return conv_id
                    except Exception:
                        pass
        return None

    def _update_fingerprint(self, conversation_id: str, payload: dict):
        """Update workspace fingerprint with new conversation."""
        fingerprints = []
        if self.FINGERPRINT_FILE.exists():
            try:
                fingerprints = json.loads(self.FINGERPRINT_FILE.read_text())
            except (json.JSONDecodeError, OSError):
                fingerprints = []

        new_fp = {
            "conversation_id": conversation_id,
            "workspace_key": json.dumps(payload.get("workspace_roots", []), sort_keys=True),
            "git_branch": payload.get("git_branch", ""),
            "composer_mode": payload.get("composer_mode", ""),
            "last_active_at": datetime.now().isoformat(),
        }

        # Remove old fingerprint with same workspace_key
        fingerprints = [fp for fp in fingerprints
                       if fp.get("workspace_key") != new_fp["workspace_key"]]
        fingerprints.append(new_fp)

        self.FINGERPRINT_FILE.write_text(json.dumps(fingerprints, indent=2))

    def link_subagent_session(self, session_id: str, parent_conversation_id: str):
        """Link a subagent session to its parent conversation."""
        self.link_session_to_conversation(session_id, parent_conversation_id)

    def compact_links(self, max_age_days: int = 30) -> int:
        """Remove entries for sessions older than max_age_days to prevent unbounded growth.

        Only removes entries where the session's conversation has been completed.
        Returns the number of entries removed.
        """
        links = self._read_links()
        cutoff = datetime.now() - timedelta(days=max_age_days)
        removed = 0
        to_remove = []

        for sid, cid in links.items():
            session_file = self.SESSIONS_DIR / sid / "session.json"
            if not session_file.exists():
                to_remove.append(sid)  # Session file missing, safe to remove
                continue
            try:
                session = json.loads(session_file.read_text())
                last_updated = session.get("last_updated", "")
                if not last_updated:
                    continue
                updated_at = datetime.fromisoformat(last_updated)
                if updated_at < cutoff:
                    summary = session.get("summary", {})
                    if summary.get("finalized_at"):
                        to_remove.append(sid)
            except (json.JSONDecodeError, ValueError, OSError):
                to_remove.append(sid)  # Corrupt file, clean it up

        for sid in to_remove:
            del links[sid]
            removed += 1

        if removed > 0:
            self._write_links(links)

        return removed


class ConversationRecorder:
    """Manages conversation recording with session-based storage."""

    HOOKS_DIR = Path(__file__).parent.resolve()
    STATE_DIR = HOOKS_DIR / "state"
    SESSIONS_DIR = STATE_DIR / "sessions"
    INDEX_FILE = STATE_DIR / "sessions_index.json"

    # Indexed event arrays for fast access by type
    INDEXED_EVENT_TYPES = {
        "response": "responses",
        "thought": "thoughts",
        "file_edit": "file_edits",
        "shell_command": "shell_commands",
        "tool_use": "tool_uses",
        "tool_result": "tool_results",
        "tool_failure": "tool_failures",
        "shell_result": "shell_results",
        "file_read": "file_reads",
        "mcp_call": "mcp_calls",
        "mcp_result": "mcp_results",
        "subagent_start": "subagent_starts",
        "subagent_stop": "subagent_stops",
        "user_prompt": "user_prompts",
        "compaction": "compactions",
        "tab_file_read": "tab_file_reads",
        "tab_file_edit": "tab_file_edits",
    }

    def __init__(self):
        self.STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    def get_session_dir(self, session_id):
        session_dir = self.SESSIONS_DIR / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    def load_session(self, session_id):
        session_dir = self.get_session_dir(session_id)
        session_file = session_dir / "session.json"

        if session_file.exists():
            return json.loads(session_file.read_text())
        else:
            session = {
                "session_id": session_id,
                "conversation_id": "",
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
                "schema_version": CURRENT_JSON_SCHEMA_VERSION,
                "events": [],
                "file_edits": [],
                "thoughts": [],
                "responses": [],
                "shell_commands": [],
                "tool_uses": [],
                "tool_results": [],
                "tool_failures": [],
                "shell_results": [],
                "file_reads": [],
                "mcp_calls": [],
                "mcp_results": [],
                "subagent_starts": [],
                "subagent_stops": [],
                "user_prompts": [],
                "compactions": [],
                "summary": {
                    "last_summary_event_count": 0,
                },
            }
            session_file.write_text(json.dumps(session, indent=2))
            return session

    def save_session(self, session_id, session_data):
        session_data["last_updated"] = datetime.now().isoformat()
        session_dir = self.get_session_dir(session_id)
        session_file = session_dir / "session.json"
        session_file.write_text(json.dumps(session_data, indent=2))
        self._update_index(session_data)

    def add_event(self, session_id, event_type, data):
        session_dir = self.get_session_dir(session_id)
        session_file = session_dir / "session.json"

        if _lock_file(session_file):
            try:
                session = self.load_session(session_id)

                event = {
                    "sequence": len(session["events"]),
                    "timestamp": datetime.now().isoformat(),
                    "type": event_type,
                    **data,
                }
                session["events"].append(event)

                if event_type in self.INDEXED_EVENT_TYPES:
                    session[self.INDEXED_EVENT_TYPES[event_type]].append(event)

                self.save_session(session_id, session)
            finally:
                _unlock_file(session_file)
        else:
            debug_log(f"Lock timeout for session {session_id}, appending event without lock")
            session = self.load_session(session_id)
            event = {
                "sequence": len(session["events"]),
                "timestamp": datetime.now().isoformat(),
                "type": event_type,
                **data,
            }
            session["events"].append(event)

            if event_type in self.INDEXED_EVENT_TYPES:
                session[self.INDEXED_EVENT_TYPES[event_type]].append(event)

            self.save_session(session_id, session)

        # Dual-write to SQLite (fail-open — JSON system unaffected if this fails)
        # Resolve conversation_id from session.json to ensure SQLite uses the
        # canonical ID, not the raw session_id passed by individual hooks.
        try:
            conv_id = session.get("conversation_id", "") or session_id
            from narratives_db import NarrativesDB
            with NarrativesDB() as db:
                db.insert_event(
                    session_id=conv_id,
                    sequence=event["sequence"],
                    timestamp=event["timestamp"],
                    event_type=event_type,
                    model=data.get("model", ""),
                    hook_event_name=data.get("hook_event_name", ""),
                    generation_id=data.get("generation_id", ""),
                    detail=event,
                )
        except Exception as e:
            debug_log(f"dual-write SQLite insert failed: {e}")

    def _update_index(self, session_data):
        # Use file locking to prevent concurrent index corruption
        if _lock_file(self.INDEX_FILE):
            try:
                index = {}
                if self.INDEX_FILE.exists():
                    try:
                        index = json.loads(self.INDEX_FILE.read_text())
                    except json.JSONDecodeError:
                        index = {}

                entry = {
                    "created_at": session_data["created_at"],
                    "last_updated": session_data["last_updated"],
                    "conversation_id": session_data.get("conversation_id", ""),
                    "event_count": len(session_data["events"]),
                }
                # Track all indexed event types
                for array_name in (
                    "file_edits", "thoughts", "responses", "shell_commands",
                    "tool_uses", "tool_results", "tool_failures", "shell_results",
                    "file_reads", "mcp_calls", "mcp_results", "subagent_starts",
                    "subagent_stops", "user_prompts", "compactions",
                ):
                    entry[array_name] = len(session_data.get(array_name, []))

                index[session_data["session_id"]] = entry

                self.INDEX_FILE.write_text(json.dumps(index, indent=2))
            finally:
                _unlock_file(self.INDEX_FILE)
        else:
            debug_log(f"Index lock timeout for session {session_data['session_id']}")

    def get_last_summary_event_count(self, session_id):
        """Get the event count at the last summary generation."""
        session = self.load_session(session_id)
        return session.get("summary", {}).get("last_summary_event_count", 0)

    def search_sessions(self, query):
        results = []
        for session_file in self.SESSIONS_DIR.glob("*/session.json"):
            session = json.loads(session_file.read_text())
            for event in session["events"]:
                event_str = json.dumps(event).lower()
                if query.lower() in event_str:
                    results.append({"session": session["session_id"], "event": event})
        return results


def get_conversation_id(payload):
    """Extract conversation ID from hook payload.

    Deprecated: prefer resolve_session_id() for canonical ID resolution.
    This function is kept for backward compatibility.
    """
    return get_raw_session_id(payload)


def capture_common_fields(payload: dict) -> dict:
    """Extract common fields available on every hook invocation."""
    return {
        "model": payload.get("model", ""),
        "hook_event_name": payload.get("hook_event_name", ""),
        "generation_id": payload.get("generation_id", ""),
    }


def read_hook_input():
    """Read and parse JSON from stdin, stripping double-encoded UTF-8 BOM."""
    try:
        raw_bytes = sys.stdin.buffer.read()

        # Strip double-encoded BOM: c3 af c2 bb c2 bf
        if raw_bytes.startswith(b"\xc3\xaf\xc2\xbb\xc2\xbf"):
            raw_bytes = raw_bytes[5:]

        # Also handle single-encoded BOM: ef bb bf
        if raw_bytes.startswith(b"\xef\xbb\xbf"):
            raw_bytes = raw_bytes[3:]

        raw = raw_bytes.decode("utf-8")
        return json.loads(raw)
    except json.JSONDecodeError as e:
        debug_log(f"JSON decode error: {e}")
        print(json.dumps({"permission": "allow"}))
        sys.exit(0)


def safe_output(data):
    """Output JSON to stdout, fail-open on error."""
    try:
        print(json.dumps(data))
    except Exception:
        print(json.dumps({"permission": "allow"}))


def safe_handle_error(e):
    """Handle errors gracefully with stderr logging."""
    debug_log(f"Error: {e}\n{traceback.format_exc()}")
    print(f"[conversation-recorder] Error: {e}", file=sys.stderr)
    print(json.dumps({"permission": "allow"}))
