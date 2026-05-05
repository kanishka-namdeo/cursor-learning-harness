"""Tests for parser.py — user_prompt and response extraction, tool_use exclusion."""

import json
import tempfile
from pathlib import Path

import pytest

from sentiment_arc.parser import (
    discover_transcripts,
    load_session_transcript,
)


def _write_session_json(session_dir: Path, events: list[dict]) -> Path:
    """Helper: write a minimal session.json with the given events."""
    session_dir.mkdir(parents=True, exist_ok=True)
    session_file = session_dir / "session.json"
    session_file.write_text(
        json.dumps({"session_id": session_dir.name, "events": events}),
        encoding="utf-8",
    )
    return session_file


class TestLoadSessionTranscript:
    def test_user_prompt_event(self, tmp_path):
        session_dir = tmp_path / "abc123"
        _write_session_json(session_dir, [
            {"type": "user_prompt", "prompt_text": "hello", "sequence": 0},
        ])
        turns, error = load_session_transcript(session_dir / "session.json")
        assert error is None
        assert len(turns) == 1
        assert turns[0]["role"] == "user"
        assert turns[0]["text"] == "hello"
        assert turns[0]["event_type"] == "user_prompt"

    def test_response_event(self, tmp_path):
        session_dir = tmp_path / "def456"
        _write_session_json(session_dir, [
            {"type": "response", "text": "here is the answer", "sequence": 0},
        ])
        turns, error = load_session_transcript(session_dir / "session.json")
        assert error is None
        assert turns[0]["role"] == "assistant"
        assert turns[0]["event_type"] == "response"

    def test_tool_use_event_excluded(self, tmp_path):
        """tool_use events are excluded from the turn stream entirely."""
        session_dir = tmp_path / "ghi789"
        _write_session_json(session_dir, [
            {
                "type": "tool_use",
                "tool_name": "Shell",
                "tool_input": "pytest --failed",
                "sequence": 0,
            },
        ])
        turns, error = load_session_transcript(session_dir / "session.json")
        assert error is None
        assert len(turns) == 0  # tool_use excluded

    def test_mixed_events(self, tmp_path):
        """tool_use events are filtered out; only user_prompt and response kept."""
        session_dir = tmp_path / "jkl012"
        _write_session_json(session_dir, [
            {"type": "user_prompt", "prompt_text": "fix the bug", "sequence": 0},
            {"type": "response", "text": "ok", "sequence": 1},
            {"type": "tool_use", "tool_name": "Shell", "tool_input": "pytest", "sequence": 2},
            {"type": "response", "text": "done", "sequence": 3},
        ])
        turns, error = load_session_transcript(session_dir / "session.json")
        assert error is None
        assert len(turns) == 3  # user, response, response (tool_use excluded)
        assert [t["role"] for t in turns] == ["user", "assistant", "assistant"]

    def test_empty_prompt_text_skipped(self, tmp_path):
        session_dir = tmp_path / "mno345"
        _write_session_json(session_dir, [
            {"type": "user_prompt", "prompt_text": "", "sequence": 0},
            {"type": "user_prompt", "prompt_text": "   ", "sequence": 1},
            {"type": "user_prompt", "prompt_text": "real prompt", "sequence": 2},
        ])
        turns, _ = load_session_transcript(session_dir / "session.json")
        assert len(turns) == 1

    def test_timestamp_captured(self, tmp_path):
        """Timestamps are extracted from events."""
        session_dir = tmp_path / "ts001"
        _write_session_json(session_dir, [
            {
                "type": "user_prompt",
                "prompt_text": "hello",
                "sequence": 0,
                "timestamp": "2026-01-01T00:00:00Z",
            },
        ])
        turns, _ = load_session_transcript(session_dir / "session.json")
        assert turns[0]["timestamp"] == "2026-01-01T00:00:00Z"

    def test_file_not_found(self, tmp_path):
        turns, error = load_session_transcript(tmp_path / "nonexistent" / "session.json")
        assert error is not None
        assert "File not found" in error

    def test_invalid_json(self, tmp_path):
        session_dir = tmp_path / "pqr678"
        session_dir.mkdir()
        (session_dir / "session.json").write_text("not json", encoding="utf-8")
        turns, error = load_session_transcript(session_dir / "session.json")
        assert error is not None
        assert "Invalid JSON" in error


class TestDiscoverTranscripts:
    def test_discovers_session_json(self, tmp_path):
        session_dir = tmp_path / "session-a"
        session_dir.mkdir()
        (session_dir / "session.json").write_text(
            json.dumps({"session_id": "session-a", "events": []}), encoding="utf-8"
        )
        results = discover_transcripts(tmp_path)
        assert len(results) == 1
        assert results[0].name == "session.json"

    def test_ignores_non_directories(self, tmp_path):
        (tmp_path / "not_a_dir.json").write_text("ignored", encoding="utf-8")
        results = discover_transcripts(tmp_path)
        assert len(results) == 0

    def test_returns_empty_for_missing_root(self, tmp_path):
        results = discover_transcripts(tmp_path / "nonexistent")
        assert results == []
