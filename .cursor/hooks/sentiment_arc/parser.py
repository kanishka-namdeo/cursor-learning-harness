"""
JSON session parser for agent session data.

Reads session.json files from .cursor/hooks/state/sessions/<uuid>/session.json
and extracts user prompts and assistant responses for sentiment analysis.
tool_use events are excluded — they contain structural data (file contents,
error traces) rather than conversational sentiment.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Event types that contain user-facing text
_USER_TEXT_EVENTS = {"user_prompt"}
_ASSISTANT_TEXT_EVENTS = {"response"}


def load_session_transcript(path: Path) -> tuple[list[dict], str | None]:
    """
    Parse a single session.json file into a list of turns.

    Each turn dict contains:
        - turn_index: sequential index (0-based, user prompts and responses only)
        - role: "user" or "assistant"
        - text: the text content of the turn
        - original_line: event sequence number from the source
        - event_type: source event type (user_prompt, response)
        - timestamp: ISO 8601 timestamp from the source event

    Returns (turns, error). If the file is unreadable, error is a string.
    """
    turns = []

    try:
        with open(path, "r", encoding="utf-8") as f:
            session = json.load(f)
    except json.JSONDecodeError as e:
        return [], f"Invalid JSON in {path}: {e}"
    except FileNotFoundError:
        return [], f"File not found: {path}"
    except PermissionError:
        return [], f"Permission denied: {path}"
    except OSError as e:
        return [], f"OS error reading {path}: {e}"

    events = session.get("events")
    if not isinstance(events, list):
        return [], f"No 'events' array in {path}"

    turn_index = 0
    for event in events:
        event_type = event.get("type", "")

        if event_type in _USER_TEXT_EVENTS:
            text = event.get("prompt_text", "")
            if text and text.strip():
                turns.append({
                    "turn_index": turn_index,
                    "role": "user",
                    "text": text.strip(),
                    "original_line": event.get("sequence", turn_index),
                    "event_type": "user_prompt",
                    "timestamp": event.get("timestamp"),
                })
                turn_index += 1

        elif event_type in _ASSISTANT_TEXT_EVENTS:
            text = event.get("text", "")
            if text and text.strip():
                turns.append({
                    "turn_index": turn_index,
                    "role": "assistant",
                    "text": text.strip(),
                    "original_line": event.get("sequence", turn_index),
                    "event_type": "response",
                    "timestamp": event.get("timestamp"),
                })
                turn_index += 1

    logger.info("Parsed %d turns from %s", len(turns), path)
    return turns, None


def discover_transcripts(root: Path, include_subagents: bool = False) -> list[Path]:
    """
    Discover session.json files under root.

    Expects directory structure: root/<session-id>/session.json

    If include_subagents is False (default), only returns parent-level
    session.json files (depth 1 from root).

    Returns sorted list by session.json mtime (newest first).
    """
    if not root.exists():
        logger.warning("Transcript root does not exist: %s", root)
        return []

    if not root.is_dir():
        logger.warning("Transcript root is not a directory: %s", root)
        return []

    results = []
    try:
        for session_dir in sorted(root.iterdir()):
            if not session_dir.is_dir():
                continue

            session_json = session_dir / "session.json"
            if session_json.exists() and session_json.is_file():
                results.append(session_json)

                # Also look for subagent sessions if requested
                if include_subagents:
                    subagents_dir = session_dir / "subagents"
                    if subagents_dir.is_dir():
                        for sub_dir in sorted(subagents_dir.iterdir()):
                            sub_json = sub_dir / "session.json"
                            if sub_json.exists() and sub_json.is_file():
                                results.append(sub_json)
    except OSError as e:
        logger.error("Error walking transcript root %s: %s", root, e)

    # Sort by modification time, newest first
    results.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return results
