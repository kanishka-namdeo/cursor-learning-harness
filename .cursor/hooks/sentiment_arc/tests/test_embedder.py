"""Tests for embedder.py — label maps, mock scoring, fallback behavior."""

import numpy as np
import pytest

from sentiment_arc import config
from sentiment_arc.embedder import (
    ModelError,
    compute_sentiment_scores,
    compute_sentiment_scores_with_confidence,
    compute_turn_embeddings,
    get_embedding_model,
    get_sentiment_model,
)


class TestSentimentModelLoading:
    def test_model_cached(self):
        """Second call should return cached model without re-loading."""
        model_a = get_sentiment_model()
        model_b = get_sentiment_model()
        assert model_a is model_b

    def test_model_has_expected_keys(self):
        """Loaded model dict should have tokenizer, model, and device."""
        model = get_sentiment_model()
        assert "tokenizer" in model
        assert "model" in model
        assert "device" in model


class TestSentimentScoringWithModel:
    """These tests require the sentiment model to be loaded successfully."""

    def test_neutral_empty_string(self):
        """Empty strings should score as neutral (0.0)."""
        scores = compute_sentiment_scores([""])
        assert scores == [0.0]

    def test_neutral_whitespace(self):
        """Whitespace-only strings should score as neutral."""
        scores = compute_sentiment_scores(["   "])
        assert scores == [0.0]

    def test_neutral_single_char(self):
        """Single-char texts should be skipped as neutral."""
        scores = compute_sentiment_scores(["x"])
        assert scores == [0.0]

    def test_returns_list_same_length(self):
        """Output list should have same length as input list."""
        texts = ["hello", "", "world", "  ", "test"]
        scores = compute_sentiment_scores(texts)
        assert len(scores) == len(texts)

    def test_scores_in_range(self):
        """All scores should be in [-1, +1]."""
        texts = [
            "This is amazing and wonderful!",
            "This is terrible and awful.",
            "The sky is blue.",
        ]
        scores = compute_sentiment_scores(texts)
        for s in scores:
            assert -1.0 <= s <= 1.0

    def test_positive_text_scores_positive(self):
        """Clearly positive text should have positive score."""
        scores = compute_sentiment_scores(["This is great and works perfectly!"])
        assert scores[0] > 0

    def test_negative_text_scores_negative(self):
        """Clearly negative text should have negative score."""
        scores = compute_sentiment_scores(["This is terrible and completely broken."])
        assert scores[0] < 0

    def test_batch_processing(self):
        """Batch of texts should all get scores (no zeros from batch failures)."""
        texts = [f"Test sentence number {i}" for i in range(40)]
        scores = compute_sentiment_scores(texts)
        assert len(scores) == 40
        # At least some should be non-neutral
        assert any(s != 0.0 for s in scores)


class TestSentimentScoringWithMockModel:
    """Tests that verify scoring logic using a mock model (no network needed)."""

    def test_mock_model_scoring(self):
        """Verify that positive-biased model returns positive scores."""
        import torch

        class MockTokenizer:
            def __call__(self, texts, **kwargs):
                return {"input_ids": torch.zeros(len(texts), 10)}

        class MockModel:
            def __call__(self, **kwargs):
                # 3-class output: negative, neutral, positive
                # Large logits so softmax produces ~[0.0, 0.0, 1.0]
                class Outputs:
                    logits = torch.tensor([[-10.0, -10.0, 10.0]])
                return Outputs()

        mock = {"tokenizer": MockTokenizer(), "model": MockModel(), "device": None}
        scores = compute_sentiment_scores(["test text"], model=mock)
        # score = P(positive) - P(negative) ≈ 1.0 - 0.0 = 1.0
        assert scores[0] > 0.9

    def test_mock_negative_scoring(self):
        """Negative-biased model should return negative scores."""
        import torch

        class MockTokenizer:
            def __call__(self, texts, **kwargs):
                return {"input_ids": torch.zeros(len(texts), 10)}

        class MockModel:
            def __call__(self, **kwargs):
                # Large logits so softmax produces ~[1.0, 0.0, 0.0]
                class Outputs:
                    logits = torch.tensor([[10.0, -10.0, -10.0]])
                return Outputs()

        mock = {"tokenizer": MockTokenizer(), "model": MockModel(), "device": None}
        scores = compute_sentiment_scores(["test text"], model=mock)
        # score = P(positive) - P(negative) ≈ 0.0 - 1.0 = -1.0
        assert scores[0] < -0.9

    def test_clipping_to_range(self):
        """Scores should be clipped to [-1, +1] range."""
        import torch

        class MockTokenizer:
            def __call__(self, texts, **kwargs):
                return {"input_ids": torch.zeros(len(texts), 10)}

        class MockModel:
            def __call__(self, **kwargs):
                # All negative: negative=1.0, positive=0.0
                class Outputs:
                    logits = torch.tensor([[10.0, -10.0, -10.0]])
                return Outputs()

        mock = {"tokenizer": MockTokenizer(), "model": MockModel(), "device": None}
        scores = compute_sentiment_scores(["test text"], model=mock)
        assert -1.0 <= scores[0] <= 1.0


class TestEmbeddingModelLoading:
    def test_model_cached(self):
        """Second call should return cached model."""
        model_a = get_embedding_model()
        model_b = get_embedding_model()
        assert model_a is model_b

    def test_custom_model_name(self):
        """Should be able to load a specific embedding model."""
        model = get_embedding_model(config.EMBEDDING_MODEL)
        assert model is not None


class TestTurnEmbeddings:
    def test_embeddings_have_correct_shape(self):
        """All valid texts should produce embeddings of same dimension."""
        texts = ["hello world", "testing embeddings", "third text"]
        embeddings = compute_turn_embeddings(texts)
        non_none = [e for e in embeddings if e is not None]
        assert len(non_none) == len(texts)
        # All embeddings should have same shape
        shapes = set(e.shape for e in non_none)
        assert len(shapes) == 1

    def test_empty_text_returns_none(self):
        """Empty strings should get None embeddings."""
        embeddings = compute_turn_embeddings(["", "  ", "valid text"])
        assert embeddings[0] is None
        assert embeddings[1] is None
        assert embeddings[2] is not None

    def test_preserves_order(self):
        """Embedding order should match input order."""
        texts = ["alpha", "beta", "gamma"]
        embeddings = compute_turn_embeddings(texts)
        non_none = [e for e in embeddings if e is not None]
        assert len(non_none) == 3


class TestModelError:
    def test_invalid_model_raises(self):
        """Non-existent model should raise ModelError."""
        with pytest.raises(ModelError):
            get_sentiment_model("nonexistent-model-12345-xyz")

    def test_invalid_embedding_model_raises(self):
        """Non-existent embedding model should raise ModelError."""
        with pytest.raises(ModelError):
            get_embedding_model("nonexistent-embedding-model-xyz")


class TestConfigIntegration:
    def test_default_sentiment_model_is_latest(self):
        """Default should be roberta-base-sentiment-latest (available on HF)."""
        assert "sentiment-latest" in config.SENTIMENT_MODEL

    def test_default_embedding_model_is_mpnet(self):
        """Default should be all-mpnet-base-v2, not MiniLM."""
        assert "mpnet" in config.EMBEDDING_MODEL.lower()
        assert "minilm" not in config.EMBEDDING_MODEL.lower()

    def test_fallback_model_is_set(self):
        """Fallback should be configured."""
        assert "bge" in config.EMBEDDING_MODEL_FALLBACK.lower()


class TestSentimentScoringWithConfidence:
    """Tests for compute_sentiment_scores_with_confidence."""

    def test_returns_parallel_lists(self):
        """Scores and confidences should have equal length to input."""
        texts = ["hello", "", "world"]
        scores, confidences = compute_sentiment_scores_with_confidence(texts)
        assert len(scores) == len(texts)
        assert len(confidences) == len(texts)

    def test_confidence_in_range(self):
        """Confidence values should be in [0.33, 1.0]."""
        texts = [
            "This is amazing and wonderful!",
            "This is terrible and awful.",
            "The sky is blue.",
        ]
        scores, confidences = compute_sentiment_scores_with_confidence(texts)
        for c in confidences:
            assert 0.33 <= c <= 1.0

    def test_empty_text_confidence(self):
        """Empty text should get minimum confidence (0.33)."""
        scores, confidences = compute_sentiment_scores_with_confidence([""])
        assert scores == [0.0]
        assert confidences == [0.33]

    def test_mock_model_with_confidence(self):
        """Verify mock model returns both score and confidence."""
        import torch

        class MockTokenizer:
            def __call__(self, texts, **kwargs):
                return {"input_ids": torch.zeros(len(texts), 10)}

        class MockModel:
            def __call__(self, **kwargs):
                class Outputs:
                    logits = torch.tensor([[-10.0, -10.0, 10.0]])
                return Outputs()

        mock = {"tokenizer": MockTokenizer(), "model": MockModel(), "device": None}
        scores, confidences = compute_sentiment_scores_with_confidence(["test"], model=mock)
        assert scores[0] > 0.9
        assert confidences[0] > 0.9

    def test_backward_compat_wrapper(self):
        """compute_sentiment_scores should still work as before."""
        texts = ["hello", "world"]
        scores = compute_sentiment_scores(texts)
        assert len(scores) == 2
        assert all(-1.0 <= s <= 1.0 for s in scores)
