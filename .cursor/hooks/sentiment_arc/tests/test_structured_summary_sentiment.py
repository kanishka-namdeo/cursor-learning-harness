"""Tests for Phase 2: Sentiment Structured Summary Integration.

Tests cover:
- inject_sentiment_into_structured enrichment
- _make_empty_structured_summary sentiment defaults
- merge_structured_summaries sentiment aggregation
- conversation sentiment aggregation (load_conversation_sentiment)
"""

import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add hooks dir to path
HOOKS_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(HOOKS_DIR))


class TestMakeEmptyStructuredSummary:
    """Test that _make_empty_structured_summary includes all sentiment fields."""

    def test_has_sentiment_fields(self):
        from summarizer_agent import _make_empty_structured_summary

        result = _make_empty_structured_summary("test outcome")

        assert result["sentiment_archetype"] == ""
        assert result["sentiment_confidence"] == 0.0
        assert result["arc_slope"] is None
        assert result["avg_sentiment"] is None
        assert result["recovery_events"] == 0
        assert result["mismatched_effort_score"] is None
        assert result["sentiment_gap"] is None
        assert result["user_sentiment_trend"] is None
        assert result["assistant_sentiment_trend"] is None

    def test_sentiment_fields_types(self):
        from summarizer_agent import _make_empty_structured_summary

        result = _make_empty_structured_summary()

        assert isinstance(result["sentiment_archetype"], str)
        assert isinstance(result["sentiment_confidence"], float)
        assert isinstance(result["recovery_events"], int)
        assert result["arc_slope"] is None
        assert result["avg_sentiment"] is None


class TestInjectSentimentIntoStructured:
    """Test that inject_sentiment_into_structured enriches structured summaries."""

    @patch("sentiment_arc.arc_db.init_arc_tables")
    @patch("sentiment_arc.arc_db.get_arc_features_for_session")
    def test_enriches_structured_summary(self, mock_get_arc, mock_init):
        from summarizer_agent import inject_sentiment_into_structured

        mock_arc = {
            "archetype": "looping",
            "archetype_confidence": 0.82,
            "arc_slope": -0.0012,
            "avg_sentiment": -0.15,
            "recovery_events": 3,
            "mismatched_effort_score": 0.65,
            "sentiment_gap": 0.25,
            "user_sentiment_trend": -0.003,
            "assistant_sentiment_trend": 0.001,
        }
        mock_get_arc.return_value = mock_arc
        mock_conn = MagicMock()
        mock_init.return_value = mock_conn

        structured = {"schema_version": 1, "outcome": "test"}
        result = inject_sentiment_into_structured("test-session-id", structured)

        assert result["sentiment_archetype"] == "looping"
        assert result["sentiment_confidence"] == 0.82
        assert result["arc_slope"] == -0.0012
        assert result["avg_sentiment"] == -0.15
        assert result["recovery_events"] == 3
        assert result["mismatched_effort_score"] == 0.65
        assert result["sentiment_gap"] == 0.25
        assert result["user_sentiment_trend"] == -0.003
        assert result["assistant_sentiment_trend"] == 0.001
        mock_conn.close.assert_called_once()

    @patch("sentiment_arc.arc_db.init_arc_tables")
    @patch("sentiment_arc.arc_db.get_arc_features_for_session")
    def test_returns_structured_unchanged_when_no_arc(self, mock_get_arc, mock_init):
        from summarizer_agent import inject_sentiment_into_structured

        mock_get_arc.return_value = None
        mock_conn = MagicMock()
        mock_init.return_value = mock_conn

        structured = {"schema_version": 1, "outcome": "test"}
        original = dict(structured)
        result = inject_sentiment_into_structured("test-session-id", structured)

        # All original keys preserved, no new keys added
        assert result == original

    @patch("sentiment_arc.arc_db.init_arc_tables")
    @patch("sentiment_arc.arc_db.get_arc_features_for_session")
    def test_returns_structured_unchanged_on_exception(self, mock_get_arc, mock_init):
        from summarizer_agent import inject_sentiment_into_structured

        mock_init.side_effect = Exception("DB unavailable")

        structured = {"schema_version": 1, "outcome": "test"}
        result = inject_sentiment_into_structured("test-session-id", structured)

        assert result == structured


class TestMergeStructuredSummariesSentimentAggregation:
    """Test that merge_structured_summaries aggregates sentiment across sessions."""

    def test_merge_aggregates_sentiment(self, tmp_path):
        from narratives_db import NarrativesDB

        db_path = tmp_path / "test.db"

        with patch("narratives_db.DEBUG_LOG", tmp_path / "hook-debug.log"):
            db = NarrativesDB(db_path=db_path)

            conn = db._conn
            # Migrations already created sessions and structured_summaries tables
            # Ensure session rows exist
            db._ensure_session_row("s1")
            db._ensure_session_row("s2")
            db._ensure_session_row("s3")

            # Disable FKs temporarily for test setup
            conn.execute("PRAGMA foreign_keys=OFF")

            # Ensure conversation row exists (migration 5 creates this)
            conn.execute("INSERT OR IGNORE INTO conversations (conversation_id) VALUES ('conv-1')")

            # Set conversation_id
            conn.execute("UPDATE sessions SET conversation_id = 'conv-1' WHERE session_id IN ('s1', 's2', 's3')")

            for sid, arch, slope, sent in [
                ("s1", "smooth_convergence", 0.005, 0.3),
                ("s2", "looping", -0.002, -0.1),
                ("s3", "smooth_convergence", 0.003, 0.2),
            ]:
                structured = {
                    "schema_version": 1,
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
                    "outcome": "done",
                    "session_type": "feature",
                    "sentiment_archetype": arch,
                    "arc_slope": slope,
                    "avg_sentiment": sent,
                    "recovery_events": 0,
                }
                conn.execute(
                    "INSERT OR REPLACE INTO structured_summaries (session_id, structured_json, generated_at) VALUES (?, ?, ?)",
                    (sid, json.dumps(structured), "2026-05-05T00:00:00"),
                )
            conn.execute("PRAGMA foreign_keys=ON")
            conn.commit()

            merged = db.merge_structured_summaries("conv-1")

            assert "_sentiment_aggregates" in merged
            agg = merged["_sentiment_aggregates"]
            assert agg["dominant_archetype"] == "smooth_convergence"
            assert agg["archetype_distribution"]["smooth_convergence"] == 2
            assert agg["archetype_distribution"]["looping"] == 1
            assert agg["frustration_count"] == 1  # looping is frustrating
            assert agg["avg_arc_slope"] is not None
            assert agg["avg_sentiment"] is not None
            assert len(agg["sentiment_trajectory"]) == 3

            db.close()


class TestConversationSentimentAggregation:
    """Test load_conversation_sentiment in conversation_summarizer_agent.py."""

    def test_load_conversation_sentiment_aggregates(self):
        # Need to patch at the source module since the import is lazy
        with patch("sentiment_arc.arc_db.init_arc_tables") as mock_init, \
             patch("sentiment_arc.arc_db.get_arc_features_for_session") as mock_get:

            mock_arc_data = {
                "session-1": {
                    "archetype": "smooth_convergence",
                    "archetype_confidence": 0.9,
                    "arc_slope": 0.005,
                    "avg_sentiment": 0.3,
                },
                "session-2": {
                    "archetype": "looping",
                    "archetype_confidence": 0.8,
                    "arc_slope": -0.002,
                    "avg_sentiment": -0.1,
                },
            }

            mock_conn = MagicMock()
            mock_init.return_value = mock_conn
            mock_get.side_effect = lambda conn, sid: mock_arc_data.get(sid)

            # Force-reimport to pick up patches
            import importlib
            import conversation_summarizer_agent
            importlib.reload(conversation_summarizer_agent)

            from conversation_summarizer_agent import load_conversation_sentiment

            state = {
                "conversation_id": "conv-1",
                "sessions": [
                    {"session_id": "session-1"},
                    {"session_id": "session-2"},
                ],
            }

            result = load_conversation_sentiment(state)

            sentiment = result.get("conversation_sentiment", {})
            assert sentiment["dominant_archetype"] in ("smooth_convergence", "looping")
            assert sentiment["session_count_with_arc"] == 2
            assert len(sentiment["sentiment_trajectory"]) == 2
            assert sentiment["frustration_count"] == 1
            assert sentiment["avg_arc_slope"] is not None
            assert sentiment["avg_sentiment"] is not None
            mock_conn.close.assert_called_once()

    def test_load_conversation_sentiment_handles_empty(self):
        import importlib
        import conversation_summarizer_agent
        importlib.reload(conversation_summarizer_agent)

        from conversation_summarizer_agent import load_conversation_sentiment

        state = {
            "conversation_id": "conv-empty",
            "sessions": [],
        }

        result = load_conversation_sentiment(state)
        assert result["conversation_sentiment"] == {}

    def test_load_conversation_sentiment_fail_open(self):
        with patch("sentiment_arc.arc_db.init_arc_tables", side_effect=Exception("DB error")):
            import importlib
            import conversation_summarizer_agent
            importlib.reload(conversation_summarizer_agent)

            from conversation_summarizer_agent import load_conversation_sentiment

            state = {
                "conversation_id": "conv-fail",
                "sessions": [{"session_id": "session-1"}],
            }

            result = load_conversation_sentiment(state)

            # Should not crash, should return with empty sentiment data
            assert "conversation_sentiment" in result
