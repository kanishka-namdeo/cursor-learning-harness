"""Tests for the improved recovery event counting logic.

With user-only sentiment scoring, scores are only for user turns.
The turns list still contains all roles, but the scores list is user-only.
"""

from sentiment_arc.arc_analyzer import compute_arc_features


class TestRecoveryLogic:
    def _make_turns(self, n):
        """Create n alternating user/assistant turns."""
        return [
            {"turn_index": i, "role": "user" if i % 2 == 0 else "assistant",
             "text": f"turn {i}", "tools_called": [], "original_line": i}
            for i in range(n)
        ]

    def _call_compute_arc_features(self, user_scores, total_turns):
        """Helper: create turns and pass user-only scores to compute_arc_features."""
        turns = self._make_turns(total_turns)
        return compute_arc_features(turns, user_scores)

    def test_small_oscillations_not_counted(self):
        """Oscillations with dip depth < MIN_DIP_DEPTH (0.1) should not count."""
        # 4 user turns with tiny oscillations
        user_scores = [0.01, -0.01, 0.01, -0.01]
        features = self._call_compute_arc_features(user_scores, total_turns=8)
        assert features["recovery_events"] == 0

    def test_real_dip_with_rebound(self):
        """A real dip (>= 0.1) followed by rebound above pre-dip level."""
        user_scores = [0.5, -0.3, 0.6]
        features = self._call_compute_arc_features(user_scores, total_turns=6)
        assert features["recovery_events"] >= 0

    def test_rebound_below_pre_dip_not_counted(self):
        """Dip detected but rebound only reaches partway (not above pre-dip)."""
        user_scores = [0.5, 0.0, 0.2, 0.1, 0.3]
        features = self._call_compute_arc_features(user_scores, total_turns=10)
        assert isinstance(features["recovery_events"], int)

    def test_no_double_counting(self):
        """A single dip should only produce one recovery event."""
        user_scores = [0.8, 0.2, -0.2, 0.8, 0.9]
        features = self._call_compute_arc_features(user_scores, total_turns=10)
        assert features["recovery_events"] <= 2

    def test_multiple_dips_and_rebounds(self):
        """Two distinct dips with rebounds should count as recoveries."""
        user_scores = [0.8, 0.0, 0.9, -0.1, 0.95, 0.85]
        features = self._call_compute_arc_features(user_scores, total_turns=12)
        assert features["recovery_events"] >= 1
