"""Tests for dedup.py — Jaccard similarity and turn merging."""

from sentiment_arc.dedup import _jaccard_similarity, deduplicate_turns


def _turn(role, text, idx=0):
    return {
        "turn_index": idx,
        "role": role,
        "text": text,
        "tools_called": [],
        "original_line": idx,
    }


class TestJaccardSimilarity:
    def test_identical_strings(self):
        assert _jaccard_similarity("hello", "hello") == 1.0

    def test_completely_different(self):
        sim = _jaccard_similarity("abc", "xyz")
        assert sim < 0.1

    def test_empty_strings(self):
        assert _jaccard_similarity("", "") == 1.0

    def test_one_empty(self):
        assert _jaccard_similarity("hello", "") == 0.0

    def test_similar_but_not_identical(self):
        sim = _jaccard_similarity("hello world", "hello earth")
        assert 0.3 < sim < 1.0


class TestDeduplicateTurns:
    def test_no_dedup_needed(self):
        turns = [
            _turn("user", "hello", 0),
            _turn("assistant", "hi there", 1),
        ]
        result = deduplicate_turns(turns)
        assert len(result) == 2

    def test_identical_consecutive_turns_merged(self):
        turns = [
            _turn("user", "run pytest", 0),
            _turn("user", "run pytest", 1),
            _turn("user", "run pytest", 2),
            _turn("assistant", "done", 3),
        ]
        result = deduplicate_turns(turns)
        assert len(result) == 2
        assert result[0]["repeat_count"] == 3
        assert result[0]["text"] == "run pytest"

    def test_different_text_not_merged(self):
        turns = [
            _turn("user", "run pytest", 0),
            _turn("user", "fix the bug", 1),
        ]
        result = deduplicate_turns(turns)
        assert len(result) == 2
        assert "repeat_count" not in result[0]
        assert "repeat_count" not in result[1]

    def test_different_roles_not_merged(self):
        turns = [
            _turn("user", "hello", 0),
            _turn("assistant", "hello", 1),
        ]
        result = deduplicate_turns(turns)
        assert len(result) == 2

    def test_single_turn(self):
        turns = [_turn("user", "hi", 0)]
        result = deduplicate_turns(turns)
        assert len(result) == 1

    def test_empty_list(self):
        assert deduplicate_turns([]) == []
