"""End-to-end integration tests: parse → dedup → score → features → classify."""

import json
import tempfile
from pathlib import Path

from sentiment_arc.arc_analyzer import analyze_session, classify_archetype, compute_arc_features
from sentiment_arc.dedup import deduplicate_turns
from sentiment_arc.parser import load_session_transcript
from sentiment_arc.score_text import classify_text_type, score_text_by_type


class TestParserToDedup:
    """Test that parsed turns flow correctly into dedup."""

    def _write_session(self, tmp_path, events):
        session_dir = tmp_path / "test-session"
        session_dir.mkdir()
        (session_dir / "session.json").write_text(
            json.dumps({"session_id": "test-session", "events": events}),
            encoding="utf-8",
        )
        return session_dir / "session.json"

    def test_parse_and_dedup_pipeline(self, tmp_path):
        """Parse session with repeated prompts, then dedup."""
        session_file = self._write_session(tmp_path, [
            {"type": "user_prompt", "prompt_text": "fix the bug", "sequence": 0},
            {"type": "response", "text": "Sure, looking into it.", "sequence": 1},
            {"type": "user_prompt", "prompt_text": "fix the bug", "sequence": 2},
            {"type": "response", "text": "Found the issue.", "sequence": 3},
        ])
        turns, error = load_session_transcript(session_file)
        assert error is None
        assert len(turns) == 4

        deduped = deduplicate_turns(turns)
        # Two identical user prompts at indices 0 and 2 are NOT consecutive
        # (separated by response), so no dedup
        assert len(deduped) == 4

    def test_parse_dedup_analyze(self, tmp_path):
        """Full pipeline: parse → dedup → compute features."""
        session_file = self._write_session(tmp_path, [
            {"type": "user_prompt", "prompt_text": "hello", "sequence": 0},
            {"type": "response", "text": "hi there!", "sequence": 1},
            {"type": "user_prompt", "prompt_text": "help me", "sequence": 2},
            {"type": "response", "text": "of course", "sequence": 3},
            {"type": "user_prompt", "prompt_text": "thanks", "sequence": 4},
        ])
        turns, error = load_session_transcript(session_file)
        assert error is None

        deduped = deduplicate_turns(turns)
        assert len(deduped) == 5  # No consecutive duplicates

        scores = [0.1, 0.0, 0.8]  # user-only scores (turns 0, 2, 4 are user)
        features = compute_arc_features(deduped, scores)
        assert "archetype" not in features  # classify_archetype not called yet
        assert "arc_slope" in features


class TestTextClassification:
    """Test text type classification in isolation."""

    def test_code_classification(self):
        code = "def foo():\n    return 42"
        assert classify_text_type(code) == "code"

    def test_error_classification(self):
        error = "Traceback (most recent call last):\nTypeError: bad"
        assert classify_text_type(error) == "error_trace"

    def test_natural_language_classification(self):
        nl = "The solution looks great, thank you!"
        assert classify_text_type(nl) == "natural_language"

    def test_mixed_classification(self):
        mixed = "def foo():\n    raise ValueError('bad')"
        result = classify_text_type(mixed)
        assert result == "mixed"


class TestArchetypeClassification:
    """Test archetype classification with computed features."""

    def test_smooth_convergence_features(self):
        features = {
            "arc_slope": 0.01,
            "arc_etv": 0.005,
            "recovery_events": 0,
            "late_volatility": 0.01,
            "avg_sentiment": 0.3,
            "last_score": 0.5,
            "sentiment_range": 0.3,
            "mismatched_effort_signal": False,
            "raw_scores": [0.1, 0.3, 0.5],
            "turn_count": 10,
        }
        archetype, confidence = classify_archetype(features)
        assert archetype == "smooth_convergence"
        assert confidence == 1.0

    def test_escalating_frustration_features(self):
        features = {
            "arc_slope": -0.02,
            "arc_etv": 0.01,
            "recovery_events": 1,
            "late_volatility": 0.05,
            "avg_sentiment": -0.2,
            "last_score": 0.1,
            "sentiment_range": 0.4,
            "mismatched_effort_signal": False,
            "raw_scores": [-0.1, -0.2, -0.1, 0.1],
            "turn_count": 10,
        }
        archetype, confidence = classify_archetype(features)
        assert archetype == "escalating_frustration"
        assert confidence == 1.0


class TestAnalyzeSessionShort:
    """Test that short sessions are handled uniformly."""

    def test_too_short_returns_dict(self):
        turns = [
            {"turn_index": 0, "role": "user", "text": "hi", "tools_called": [], "original_line": 0},
            {"turn_index": 1, "role": "assistant", "text": "hey", "tools_called": [], "original_line": 1},
        ]
        result = analyze_session(turns)
        assert isinstance(result, dict)
        assert result["archetype"] == "too_short"
        assert result["archetype_confidence"] == 0.0
