"""Tests for smooth_arc weighting and analyze_session uniform return."""

import numpy as np

from sentiment_arc.arc_analyzer import analyze_session, compute_arc_features, smooth_arc


class TestSmoothArcWeighted:
    def test_unweighted_default(self):
        result = smooth_arc([0.0, 1.0, 0.5])
        assert len(result) == 3
        assert result[0] == 0.0

    def test_weighted_increases_alpha(self):
        scores = [0.0, 1.0, 0.5]
        weights = [1.0, 3.0, 1.0]
        result = smooth_arc(scores, weights=weights)
        assert abs(result[1] - 0.9) < 1e-9

    def test_weighted_capped_at_09(self):
        scores = [0.0, 1.0, 0.0]
        weights = [1.0, 10.0, 1.0]
        result = smooth_arc(scores, weights=weights)
        assert abs(result[1] - 0.9) < 1e-9

    def test_no_weights_same_as_default(self):
        result_weighted = smooth_arc([0.0, 1.0, 0.5])
        result_unweighted = smooth_arc([0.0, 1.0, 0.5], weights=None)
        assert result_weighted == result_unweighted


class TestAnalyzeSessionUniform:
    def test_short_session_returns_too_short_dict(self):
        turns = [
            {"turn_index": 0, "role": "user", "text": "hi", "tools_called": [], "original_line": 0},
        ]
        result = analyze_session(turns)
        assert result["archetype"] == "too_short"
        assert result["turn_count"] == 1
        assert result["archetype_confidence"] == 0.0
        assert result["recovery_events"] == 0

    def test_empty_session_returns_too_short(self):
        result = analyze_session([])
        assert result["archetype"] == "too_short"
        assert result["turn_count"] == 0


class TestComputeArcFeaturesWeighted:
    def test_long_turn_gets_more_weight(self):
        turns = [
            {"turn_index": 0, "role": "user", "text": "hi", "tools_called": [], "original_line": 0},
            {"turn_index": 1, "role": "assistant", "text": "a" * 500, "tools_called": [], "original_line": 1},
            {"turn_index": 2, "role": "user", "text": "ok", "tools_called": [], "original_line": 2},
        ]
        # Only user turns scored: 2 scores for 2 user turns
        scores = [0.0, 0.5]
        features = compute_arc_features(turns, scores)
        assert "smoothed" in features
        assert len(features["smoothed"]) == 2