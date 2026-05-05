"""Tests for score_text.py - text type classification."""

from sentiment_arc.score_text import classify_text_type, score_text_by_type


class TestClassifyTextType:
    def test_natural_language(self):
        assert classify_text_type("The solution looks good to me.") == "natural_language"

    def test_code_block(self):
        text = 'def hello():\n    print("world")\n    return True'
        assert classify_text_type(text) == "code"

    def test_error_traceback(self):
        text = "Traceback (most recent call last):\n  File \"test.py\", line 1\nTypeError: NoneType"
        assert classify_text_type(text) == "error_trace"

    def test_empty_text(self):
        assert classify_text_type("") == "natural_language"

    def test_whitespace_only(self):
        assert classify_text_type("   ") == "natural_language"

    def test_mixed_code_and_error(self):
        text = "def foo():\n    raise ValueError('bad')"
        result = classify_text_type(text)
        assert result in ("mixed", "code")


class TestScoreTextByType:
    def test_code_is_neutral(self):
        text = "def hello():\n    return 42"
        score = score_text_by_type(text, sentiment_model=None, compute_fn=None)
        assert score == 0.0

    def test_error_is_negative(self):
        text = "Traceback: TypeError on line 10"
        score = score_text_by_type(text, sentiment_model=None, compute_fn=None)
        assert score < 0

    def test_natural_language_calls_fn(self):
        """Natural language should call compute_fn. We pass a mock."""
        called = []
        def mock_fn(texts, model):
            called.extend(texts)
            return [0.5]
        score = score_text_by_type("great work", sentiment_model="mock", compute_fn=mock_fn)
        assert called == ["great work"]
        assert score == 0.5

    def test_natural_language_no_fn_returns_zero(self):
        score = score_text_by_type("some text", sentiment_model=None, compute_fn=None)
        assert score == 0.0
