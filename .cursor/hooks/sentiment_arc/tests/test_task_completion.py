"""Tests for task_completion.py — LLM-as-judge task completion detection."""

import json
from unittest.mock import MagicMock, patch

from sentiment_arc.task_completion import (
    _extract_final_turns,
    _has_final_user_message,
    evaluate_task_completion,
)


def _make_turn(
    role: str,
    text: str,
    index: int,
    event_type: str = None,
) -> dict:
    return {
        "turn_index": index,
        "role": role,
        "text": text,
        "tools_called": [],
        "original_line": index,
        "event_type": event_type or ("user_prompt" if role == "user" else "response"),
    }


# ---------------------------------------------------------------------------
# _extract_final_turns
# ---------------------------------------------------------------------------

class TestExtractFinalTurns:
    def test_basic_extraction(self):
        turns = [
            _make_turn("user", "How do I fix this bug?", 0),
            _make_turn("assistant", "Let me look into it.", 1),
            _make_turn("user", "Any progress?", 2),
            _make_turn("assistant", "Found the issue.", 3),
            _make_turn("user", "Great, thanks!", 4),
        ]
        first, final = _extract_final_turns(turns, n=2)
        assert "How do I fix" in first
        assert "Any progress?" in final
        assert "Great, thanks!" in final

    def test_first_prompt_truncated(self):
        long_text = "x" * 1000
        turns = [_make_turn("user", long_text, 0)]
        first, _ = _extract_final_turns(turns)
        assert len(first) <= 500

    def test_no_user_turns(self):
        turns = [_make_turn("assistant", "hello", 0)]
        first, final = _extract_final_turns(turns)
        assert "no user prompt" in first.lower()

    def test_final_turns_truncated(self):
        turns = [
            _make_turn("user", "x" * 1000, 0),
            _make_turn("assistant", "y" * 1000, 1),
        ]
        _, final = _extract_final_turns(turns)
        # Each turn text should be truncated to 400 chars
        assert "x" * 401 not in final


# ---------------------------------------------------------------------------
# _has_final_user_message
# ---------------------------------------------------------------------------

class TestHasFinalUserMessage:
    def test_ends_with_user(self):
        turns = [
            _make_turn("assistant", "Here is the fix.", 0),
            _make_turn("user", "Thanks!", 1),
        ]
        assert _has_final_user_message(turns) is True

    def test_ends_with_assistant(self):
        turns = [
            _make_turn("user", "Fix it", 0),
            _make_turn("assistant", "Done.", 1),
        ]
        assert _has_final_user_message(turns) is False

    def test_empty_turns(self):
        assert _has_final_user_message([]) is False

    def test_ignores_empty_text(self):
        turns = [
            _make_turn("user", "", 0),
            _make_turn("assistant", "response", 1),
            _make_turn("user", "   ", 2),
        ]
        # Last non-empty text turn is from assistant
        assert _has_final_user_message(turns) is False


# ---------------------------------------------------------------------------
# evaluate_task_completion — short / edge cases
# ---------------------------------------------------------------------------

class TestEvaluateTaskCompletionEdgeCases:
    def test_too_few_turns(self):
        turns = [_make_turn("user", "hello", 0)]
        result = evaluate_task_completion(turns)
        assert result["label"] == "abandoned"
        assert result["score"] == 0.0

    def test_single_turn(self):
        turns = [_make_turn("assistant", "hello", 0)]
        result = evaluate_task_completion(turns)
        assert result["label"] == "abandoned"


# ---------------------------------------------------------------------------
# evaluate_task_completion — LLM mocked tests
# ---------------------------------------------------------------------------

class TestEvaluateTaskCompletionMocked:
    def _mock_llm_response(self, score: float, label: str, explanation: str):
        """Create a mock LLM response with the given JSON content."""
        mock_resp = MagicMock()
        mock_resp.content = json.dumps({
            "score": score,
            "label": label,
            "explanation": explanation,
        })
        return mock_resp

    def test_completed_session(self):
        turns = [
            _make_turn("user", "Help me write a function", 0),
            _make_turn("assistant", "Here is the function.", 1),
            _make_turn("user", "That works perfectly, thanks!", 2),
        ]
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = self._mock_llm_response(
            0.95, "completed", "The user confirmed the solution works."
        )

        with patch("sentiment_arc.task_completion._get_llm", return_value=mock_llm):
            result = evaluate_task_completion(turns)

        assert result["label"] == "completed"
        assert result["score"] == 0.95
        assert "works" in result["explanation"].lower()

    def test_failed_session(self):
        turns = [
            _make_turn("user", "Fix the build error", 0),
            _make_turn("assistant", "Try this change.", 1),
            _make_turn("user", "This doesn't work at all.", 2),
        ]
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = self._mock_llm_response(
            0.1, "failed", "User expressed clear dissatisfaction."
        )

        with patch("sentiment_arc.task_completion._get_llm", return_value=mock_llm):
            result = evaluate_task_completion(turns)

        assert result["label"] == "failed"
        assert result["score"] == 0.1

    def test_partial_session(self):
        turns = [
            _make_turn("user", "Add authentication", 0),
            _make_turn("assistant", "Here is login code.", 1),
            _make_turn("user", "This helps but I still need logout.", 2),
        ]
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = self._mock_llm_response(
            0.5, "partial", "Progress made but unresolved needs remain."
        )

        with patch("sentiment_arc.task_completion._get_llm", return_value=mock_llm):
            result = evaluate_task_completion(turns)

        assert result["label"] == "partial"
        assert 0.4 <= result["score"] <= 0.6

    def test_abandoned_no_final_user(self):
        turns = [
            _make_turn("user", "Start this task", 0),
            _make_turn("assistant", "Working on it...", 1),
        ]
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = self._mock_llm_response(
            0.2, "abandoned", "No final user confirmation."
        )

        with patch("sentiment_arc.task_completion._get_llm", return_value=mock_llm):
            result = evaluate_task_completion(turns)

        assert result["label"] == "abandoned"

    def test_llm_unavailable(self):
        turns = [
            _make_turn("user", "Hello", 0),
            _make_turn("assistant", "Hi", 1),
            _make_turn("user", "Thanks", 2),
        ]

        with patch("sentiment_arc.task_completion._get_llm", side_effect=RuntimeError("API_KEY not set")):
            result = evaluate_task_completion(turns)

        assert result["label"] == "unknown"
        assert result["score"] is None

    def test_llm_unavailable_abandoned_fallback(self):
        """When LLM unavailable and no final user, fallback to abandoned heuristic."""
        turns = [
            _make_turn("user", "Hello", 0),
            _make_turn("assistant", "Hi", 1),
        ]

        with patch("sentiment_arc.task_completion._get_llm", side_effect=RuntimeError("no key")):
            # Patch _has_final_user_message to return False
            with patch("sentiment_arc.task_completion._has_final_user_message", return_value=False):
                result = evaluate_task_completion(turns)

        assert result["label"] == "abandoned"
        assert result["score"] == 0.1

    def test_invalid_json_retry(self):
        turns = [
            _make_turn("user", "Help me", 0),
            _make_turn("assistant", "Done", 1),
            _make_turn("user", "Thanks", 2),
        ]
        mock_llm = MagicMock()
        # First call returns invalid JSON, second returns valid
        mock_llm.invoke.side_effect = [
            MagicMock(content="not valid json {{{"),
            MagicMock(content=json.dumps({
                "score": 0.9,
                "label": "completed",
                "explanation": "User thanked the assistant.",
            })),
        ]

        with patch("sentiment_arc.task_completion._get_llm", return_value=mock_llm):
            result = evaluate_task_completion(turns)

        assert result["label"] == "completed"
        assert result["score"] == 0.9

    def test_score_clamped(self):
        """Scores outside [0, 1] should be clamped."""
        turns = [_make_turn("user", "hi", 0), _make_turn("assistant", "hey", 1)]
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = self._mock_llm_response(
            1.5, "completed", "Score was out of range."
        )

        with patch("sentiment_arc.task_completion._get_llm", return_value=mock_llm):
            result = evaluate_task_completion(turns)

        assert result["score"] == 1.0

    def test_invalid_label_inferred_from_score(self):
        """If LLM returns an unknown label, infer from score."""
        turns = [_make_turn("user", "hi", 0), _make_turn("assistant", "hey", 1)]
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = self._mock_llm_response(
            0.9, "super_happy", "Everything went well."
        )

        with patch("sentiment_arc.task_completion._get_llm", return_value=mock_llm):
            result = evaluate_task_completion(turns)

        assert result["label"] == "completed"

    def test_markdown_fence_stripped(self):
        """LLM responses wrapped in ```json ... ``` should be parsed."""
        turns = [_make_turn("user", "hi", 0), _make_turn("assistant", "hey", 1)]
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(
            content='```json\n{"score": 0.8, "label": "completed", "explanation": "Good."}\n```'
        )

        with patch("sentiment_arc.task_completion._get_llm", return_value=mock_llm):
            result = evaluate_task_completion(turns)

        assert result["label"] == "completed"
        assert result["score"] == 0.8
