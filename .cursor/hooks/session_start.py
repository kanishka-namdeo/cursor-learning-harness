#!/usr/bin/env python3
"""
Session Start Hook - Initialize conversation recording session.
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conversation_recorder import ConversationRecorder, ConversationLinker, read_hook_input, safe_output, get_conversation_id, CURRENT_JSON_SCHEMA_VERSION, debug_log


def _run_git(*args: str) -> str:
    """Run a git command and return stripped stdout, or empty string on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return ""


def _get_git_context() -> dict:
    """Capture git branch, commit, and dirty status."""
    branch = _run_git("rev-parse", "--abbrev-ref", "HEAD")
    commit = _run_git("rev-parse", "HEAD")
    status_output = _run_git("status", "--porcelain")
    return {
        "git_branch": branch if branch else None,
        "git_commit": commit if commit else None,
        "git_is_dirty": bool(status_output),
    }


def main():
    payload = read_hook_input()
    conversation_id = get_conversation_id(payload)
    is_background = payload.get("is_background_agent", False)
    composer_mode = payload.get("composer_mode", "unknown")

    # Capture common payload fields that were previously discarded
    cursor_version = payload.get("cursor_version", "")
    workspace_roots = payload.get("workspace_roots", [])
    user_email = payload.get("user_email")
    transcript_path = payload.get("transcript_path")
    generation_id = payload.get("generation_id", "")

    # Capture git context
    git_ctx = _get_git_context()

    recorder = ConversationRecorder()
    session = recorder.load_session(conversation_id)

    # Resolve stable conversation_id (may differ from initial session_id)
    linker = ConversationLinker()
    conversation_id = linker.get_or_create_conversation(conversation_id, payload)
    session["conversation_id"] = conversation_id

    session["metadata"] = {
        "is_background_agent": is_background,
        "composer_mode": composer_mode,
        "hook_version": "1.0",
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
        "schema_version": CURRENT_JSON_SCHEMA_VERSION,
        "cursor_version": cursor_version,
        "workspace_roots": workspace_roots,
        "user_email": user_email,
        "transcript_path": transcript_path,
        "generation_id": generation_id,
        "git_branch": git_ctx["git_branch"],
        "git_commit": git_ctx["git_commit"],
        "git_is_dirty": git_ctx["git_is_dirty"],
        "conversation_id": conversation_id,
    }

    recorder.save_session(conversation_id, session)

    print(
        f"[conversation-recorder] Session started: {conversation_id} "
        f"(background={is_background}, mode={composer_mode}, "
        f"cursor={cursor_version}, git_branch={git_ctx['git_branch']})",
        file=sys.stderr,
    )

    # Persist to SQLite (fail-open — JSON system unaffected if this fails)
    try:
        from narratives_db import NarrativesDB
        with NarrativesDB() as db:
            db.upsert_conversation(
                conversation_id=conversation_id,
                created_at=session["created_at"],
                composer_mode=composer_mode,
                model=payload.get("model", ""),
                cursor_version=cursor_version,
                user_email=user_email,
                workspace_roots=json.dumps(workspace_roots) if workspace_roots else None,
                git_branch=git_ctx["git_branch"],
                git_commit=git_ctx["git_commit"],
                is_background_agent=is_background,
            )
            db.upsert_session(
                session_id=conversation_id,
                conversation_id=conversation_id,
                created_at=session["created_at"],
                composer_mode=composer_mode,
                model=payload.get("model", ""),
                cursor_version=cursor_version,
                user_email=user_email,
                workspace_roots=json.dumps(workspace_roots) if workspace_roots else None,
                git_branch=git_ctx["git_branch"],
                git_commit=git_ctx["git_commit"],
                is_background_agent=is_background,
            )
    except Exception as e:
        debug_log(f"session_start SQLite write failed: {e}")

    safe_output({"permission": "allow"})


if __name__ == "__main__":
    main()
