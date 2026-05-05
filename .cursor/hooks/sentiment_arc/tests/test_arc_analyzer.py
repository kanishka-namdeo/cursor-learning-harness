"""Tests for arc_analyzer.py — user-only sentiment scoring and archetype classification."""

from sentiment_arc.arc_analyzer import (
    analyze_session,
    classify_archetype,
    compute_arc_features,
    smooth_arc,
)


class TestSmoothArc:
    def test_empty(self):
        assert smooth_arc([]) == []

    def test_single(self):
        assert smooth_arc([0.5]) == [0.5]

    def test_two_values(self):
        # alpha=0.3: smoothed[1] = 0.3*1.0 + 0.7*0.0 = 0.3
        result = smooth_arc([0.0, 1.0])
        assert result[0] == 0.0
        assert abs(result[1] - 0.3) < 1e-9


class TestComputeArcFeatures:
    def _make_turns(self, roles, with_timestamps=False):
        turns = []
        for i, r in enumerate(roles):
            turn = {
                "turn_index": i,
                "role": r,
                "text": f"turn {i}",
                "original_line": i,
            }
            if with_timestamps:
                minutes = (i * 30) // 60
                seconds = (i * 30) % 60
                turn["timestamp"] = f"2026-01-01T00:{minutes:02d}:{seconds:02d}"
            turns.append(turn)
        return turns

    def test_user_only_scores(self):
        """Scores are for user turns only; turns list still contains all roles."""
        turns = self._make_turns(["user", "assistant", "user", "assistant"])
        # Only user turns are scored
        user_scores = [0.2, -0.1]
        features = compute_arc_features(turns, user_scores)

        assert "user_sentiment_trend" in features
        assert "avg_sentiment" in features

        # avg_sentiment is mean of user_scores: (0.2 + -0.1) / 2 = 0.05
        assert abs(features["avg_sentiment"] - 0.05) < 1e-9

        # Removed features should not be present
        assert "assistant_sentiment_trend" not in features
        assert "sentiment_gap" not in features
        assert "avg_user_sentiment" not in features
        assert "avg_assistant_sentiment" not in features
        assert "max_sentiment_gap" not in features
        assert "arc_ecp" not in features

    def test_single_user_score(self):
        turns = self._make_turns(["user", "assistant", "user"])
        user_scores = [0.3]
        features = compute_arc_features(turns, user_scores)

        assert features["avg_sentiment"] == 0.3
        assert features["sentiment_range"] == 0.0
        assert features["user_sentiment_trend"] is None

    def test_no_user_turns(self):
        turns = self._make_turns(["assistant", "assistant"])
        user_scores = []
        features = compute_arc_features(turns, user_scores)

        assert features["avg_sentiment"] is None
        assert features["arc_slope"] is None

    def test_confidence_weighting(self):
        """Confidence values are used to weight the smoothing."""
        turns = self._make_turns(["user", "user", "user"])
        user_scores = [0.0, 0.5, 1.0]
        confidences = [0.9, 0.5, 0.3]  # High, medium, low confidence
        features = compute_arc_features(turns, user_scores, confidences=confidences)

        assert "avg_model_confidence" in features
        assert abs(features["avg_model_confidence"] - 0.5667) < 0.001

    def test_confidence_none(self):
        """No confidences passed — avg_model_confidence should be None."""
        turns = self._make_turns(["user", "user"])
        user_scores = [0.2, 0.3]
        features = compute_arc_features(turns, user_scores, confidences=None)

        assert features["avg_model_confidence"] is None

    def test_mismatched_effort_continuous(self):
        """mismatched_effort_score is continuous in [0.0, 1.0]."""
        turns = self._make_turns(["user", "assistant", "user", "assistant", "user"])
        user_scores = [-0.1, -0.3, -0.5]
        # Embeddings: user self-distance ~0.05 (low = repeating), model_relevance_trend ~-0.01 (negative = drifting)
        import numpy as np
        embeddings = [
            np.array([1.0, 0.0, 0.0]),
            np.array([1.0, 0.0, 0.0]),  # assistant close to user
            np.array([1.0, 0.05, 0.0]),  # user slightly different
            np.array([0.9, 0.0, 0.0]),   # assistant drifting
            np.array([1.0, 0.1, 0.0]),   # user drifting more
        ]
        features = compute_arc_features(turns, user_scores, embeddings=embeddings)

        assert "mismatched_effort_score" in features
        assert 0.0 <= features["mismatched_effort_score"] <= 1.0
        # Both signals present: low user_self_distance + negative model_relevance_trend
        assert features["mismatched_effort_score"] > 0.0

    def test_mismatched_effort_one_signal_weak(self):
        """Geometric mean keeps score low when one signal is strong and other is weak."""
        turns = self._make_turns(["user", "assistant", "user", "assistant", "user"])
        user_scores = [-0.1, -0.3, -0.5]
        import numpy as np
        # User self-distance HIGH (very different embeddings each time)
        # Model relevance trend POSITIVE (model getting more relevant)
        embeddings = [
            np.array([1.0, 0.0, 0.0]),
            np.array([0.5, 0.5, 0.0]),
            np.array([0.0, 1.0, 0.0]),  # user very different
            np.array([0.2, 0.8, 0.0]),
            np.array([-0.5, 0.5, 0.0]),  # user even more different
        ]
        features = compute_arc_features(turns, user_scores, embeddings=embeddings)

        # High self-distance (user not repeating) -> low signal
        # Positive trend (model improving) -> low signal
        assert features["mismatched_effort_score"] < 0.1

    def test_temporal_features(self):
        """Temporal features computed correctly from timestamps."""
        turns = self._make_turns(
            ["user", "assistant", "user", "assistant", "user"],
            with_timestamps=True,
        )
        user_scores = [0.1, 0.2, 0.3]
        features = compute_arc_features(turns, user_scores)

        assert "mean_inter_arrival" in features
        assert features["mean_inter_arrival"] is not None
        assert features["mean_inter_arrival"] > 0  # 30s gaps
        assert "inter_arrival_cv" in features
        assert "inter_arrival_trend" in features

    def test_no_timestamps(self):
        """Graceful None return when no timestamps available."""
        turns = self._make_turns(["user", "assistant", "user"])
        user_scores = [0.1, 0.2]
        features = compute_arc_features(turns, user_scores)

        assert features["mean_inter_arrival"] is None
        assert features["inter_arrival_cv"] is None
        assert features["inter_arrival_trend"] is None

    def test_inter_arrival_trend_detection(self):
        """Growing gaps produce positive trend."""
        # Timestamps with growing gaps: 0s, 30s, 60s, 120s, 240s
        timestamps = [
            "2026-01-01T00:00:00",
            "2026-01-01T00:00:30",
            "2026-01-01T00:01:30",
            "2026-01-01T00:03:30",
            "2026-01-01T00:07:30",
        ]
        turns = []
        for i, (role, ts) in enumerate(zip(
            ["user", "assistant", "user", "assistant", "user"], timestamps
        )):
            turns.append({
                "turn_index": i,
                "role": role,
                "text": f"turn {i}",
                "original_line": i,
                "timestamp": ts,
            })

        user_scores = [0.1, 0.0, -0.1]
        features = compute_arc_features(turns, user_scores)

        assert features["inter_arrival_trend"] is not None
        assert features["inter_arrival_trend"] > 0  # gaps are growing


class TestClassifyArchetype:
    def test_too_short(self):
        archetype, confidence = classify_archetype({"arc_slope": None})
        assert archetype == "too_short"
        assert confidence == 0.0

    def test_inconclusive(self):
        features = {
            "arc_slope": 0.001,
            "arc_etv": 0.01,
            "recovery_events": 0,
            "late_volatility": 0.01,
            "avg_sentiment": 0.0,
            "last_score": 0.0,
            "sentiment_range": 0.0,
            "mismatched_effort_score": 0.0,
            "raw_scores": [0.0],
        }
        archetype, confidence = classify_archetype(features)
        assert archetype == "inconclusive"
        assert confidence == 0.0

    def test_smooth_convergence(self):
        features = {
            "arc_slope": 0.01,
            "arc_etv": 0.005,
            "recovery_events": 0,
            "late_volatility": 0.01,
            "avg_sentiment": 0.3,
            "last_score": 0.5,
            "sentiment_range": 0.3,
            "mismatched_effort_score": 0.0,
            "raw_scores": [0.1, 0.3, 0.5],
            "turn_count": 3,
        }
        archetype, confidence = classify_archetype(features)
        assert archetype == "smooth_convergence"
        assert confidence == 1.0

    def test_escalating_frustration(self):
        features = {
            "arc_slope": -0.02,
            "arc_etv": 0.01,
            "recovery_events": 1,
            "late_volatility": 0.05,
            "avg_sentiment": -0.2,
            "last_score": 0.1,
            "sentiment_range": 0.4,
            "mismatched_effort_score": 0.0,
            "raw_scores": [-0.1, -0.2, -0.1, 0.1],
            "turn_count": 4,
        }
        archetype, confidence = classify_archetype(features)
        assert archetype == "escalating_frustration"
        assert confidence == 1.0

    def test_mismatched_effort(self):
        features = {
            "arc_slope": 0.0,
            "arc_etv": 0.01,
            "recovery_events": 0,
            "late_volatility": 0.01,
            "avg_sentiment": 0.0,
            "last_score": 0.0,
            "sentiment_range": 0.0,
            "mismatched_effort_score": 0.8,
            "raw_scores": [0.0],
        }
        archetype, confidence = classify_archetype(features)
        assert archetype == "mismatched_effort"
        assert confidence == 1.0

    def test_looping(self):
        features = {
            "arc_slope": 0.0,
            "arc_etv": 0.06,
            "recovery_events": 4,
            "late_volatility": 0.03,
            "avg_sentiment": 0.0,
            "last_score": 0.0,
            "sentiment_range": 0.1,
            "mismatched_effort_score": 0.0,
            "raw_scores": [0.1, -0.2, 0.3, -0.1, 0.2, -0.3],
        }
        archetype, confidence = classify_archetype(features)
        assert archetype == "looping"
        assert confidence == 1.0


class TestAnalyzeSession:
    def test_short_session_returns_too_short(self):
        turns = [
            {"turn_index": 0, "role": "user", "text": "hi", "original_line": 0},
        ]
        result = analyze_session(turns)
        assert result["archetype"] == "too_short"
        assert result["archetype_confidence"] == 0.0
        assert result["turn_count"] == 1

    def test_empty_session_returns_too_short(self):
        result = analyze_session([])
        assert result["archetype"] == "too_short"
        assert result["turn_count"] == 0

    def test_no_user_turns_returns_too_short(self):
        turns = [
            {"turn_index": 0, "role": "assistant", "text": "Hello, how can I help?", "original_line": 0},
            {"turn_index": 1, "role": "assistant", "text": "Here is the solution.", "original_line": 1},
            {"turn_index": 2, "role": "assistant", "text": "Done.", "original_line": 2},
            {"turn_index": 3, "role": "assistant", "text": "Anything else?", "original_line": 3},
        ]
        result = analyze_session(turns)
        assert result["archetype"] == "too_short"
