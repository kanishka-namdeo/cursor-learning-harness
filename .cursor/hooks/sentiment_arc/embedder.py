"""
Sentiment scoring via dedicated sentiment classification model.

Uses cardiffnlp/twitter-roberta-base-sentiment-latest for direct sentiment
classification (positive/neutral/negative → [-1, +1] score).
Embeddings for geometric features use a separate sentence-transformers model.
"""

import logging
from typing import Any

import numpy as np

from . import config

logger = logging.getLogger(__name__)

# Module-level model caches
_sentiment_cache: dict[str, Any] = {}
_embedding_cache: dict[str, Any] = {}


def _resolve_device() -> str:
    """Resolve the compute device from config, auto-detecting if set to 'auto'."""
    configured = config.DEVICE

    if configured == "cuda":
        return "cuda"
    if configured == "cpu":
        return "cpu"

    # Auto-detect: prefer CUDA when available
    try:
        import torch
        if torch.cuda.is_available():
            logger.info("Auto-detected GPU, using CUDA")
            return "cuda"
        logger.info("No GPU detected, falling back to CPU")
    except ImportError:
        logger.info("torch not available, defaulting to CPU")

    return "cpu"


class ModelError(Exception):
    """Raised when a model cannot be loaded."""
    pass


def get_sentiment_model(model_name: str | None = None):
    """
    Lazily load the sentiment classification model (RoBERTa-based).

    Returns a dict with 'tokenizer' and 'model' keys.
    Caches the loaded model to avoid re-downloading on subsequent calls.

    Raises ModelError if the model cannot be loaded.
    """
    name = model_name or config.SENTIMENT_MODEL

    if name in _sentiment_cache:
        return _sentiment_cache[name]

    try:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ImportError:
        raise ModelError(
            "transformers is not installed. Run: pip install transformers torch"
        )

    try:
        import torch
    except ImportError:
        torch = None  # type: ignore[misc]

    device = _resolve_device()

    try:
        logger.info("Loading sentiment model: %s (device=%s)", name, device)
        tokenizer = AutoTokenizer.from_pretrained(name)
        model = AutoModelForSequenceClassification.from_pretrained(name)
        model = model.to(device)
        model.eval()

        _sentiment_cache[name] = {"tokenizer": tokenizer, "model": model, "device": device}
        logger.info("Sentiment model loaded: %s", name)
        return _sentiment_cache[name]
    except Exception as e:
        raise ModelError(f"Failed to load sentiment model '{name}': {e}")


def get_embedding_model(model_name: str | None = None):
    """
    Lazily load the embedding model via sentence-transformers.

    Caches the loaded model to avoid re-downloading on subsequent calls.

    Raises ModelError if the model cannot be loaded.
    """
    name = model_name or config.EMBEDDING_MODEL

    if name in _embedding_cache:
        return _embedding_cache[name]

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise ModelError(
            "sentence-transformers is not installed. Run: pip install sentence-transformers torch"
        )

    device = _resolve_device()

    try:
        logger.info("Loading embedding model: %s (device=%s)", name, device)
        model = SentenceTransformer(name, device=device)
        _embedding_cache[name] = model
        logger.info("Embedding model loaded: %s", name)
        return model
    except Exception as e:
        raise ModelError(f"Failed to load embedding model '{name}': {e}")


def _safe_embed(text: str, model, max_length: int) -> np.ndarray | None:
    """Embed a single text string safely.

    The sentence-transformers model handles tokenization and truncation internally
    at its max token limit, so no pre-truncation is needed here.
    """
    if not text or not text.strip():
        return None

    try:
        embedding = model.encode(text, convert_to_numpy=True)
        if embedding is None:
            return None

        embedding = np.asarray(embedding, dtype=np.float32)
        if not np.all(np.isfinite(embedding)):
            logger.warning("NaN or Inf detected in embedding for text: %s", text[:50])
            return None

        return embedding
    except Exception as e:
        logger.error("Embedding failed for text (%d chars): %s", len(text), e)
        return None


def compute_sentiment_scores(
    texts: list[str],
    model=None,
) -> list[float]:
    """
    Compute sentiment scores using the RoBERTa sentiment classifier.

    Wrapper around compute_sentiment_scores_with_confidence that discards
    confidence values.
    """
    scores, _ = compute_sentiment_scores_with_confidence(texts, model)
    return scores


def compute_sentiment_scores_with_confidence(
    texts: list[str],
    model=None,
) -> tuple[list[float], list[float]]:
    """
    Compute sentiment scores and per-prediction confidence using RoBERTa.

    Maps the 3-class output (negative=0, neutral=1, positive=2) to [-1, +1]:
      score = P(positive) - P(negative)

    Returns (scores, confidences) where:
    - scores: P(positive) - P(negative), range [-1, +1]
    - confidences: max(P(negative), P(neutral), P(positive)), range [0.33, 1.0]

    Falls back to neutral (0.0) score and 0.33 confidence on empty strings
    or scoring failures.
    """
    if model is None:
        try:
            model = get_sentiment_model()
        except ModelError as e:
            logger.error("Cannot load sentiment model: %s", e)
            return [0.0] * len(texts), [0.33] * len(texts)

    tokenizer = model["tokenizer"]
    classifier = model["model"]
    device = model.get("device")
    batch_size = config.SENTIMENT_BATCH_SIZE

    try:
        import torch
    except ImportError:
        logger.error("torch is required for sentiment scoring")
        return [0.0] * len(texts), [0.33] * len(texts)

    # Build index map: position in output list -> (index, text) for non-empty texts
    valid_items: list[tuple[int, str]] = []
    scores: list[float] = [0.0] * len(texts)
    confidences: list[float] = [0.33] * len(texts)

    for i, text in enumerate(texts):
        stripped = text.strip() if text else ""
        if not stripped:
            scores[i] = 0.0
            confidences[i] = 0.33
        elif len(stripped) < 2:
            scores[i] = 0.0
            confidences[i] = 0.33
        else:
            valid_items.append((i, stripped))

    if not valid_items:
        return scores, confidences

    # Process in batches
    for batch_start in range(0, len(valid_items), batch_size):
        batch = valid_items[batch_start:batch_start + batch_size]
        batch_texts = [t for _, t in batch]

        try:
            inputs = tokenizer(
                batch_texts,
                return_tensors="pt",
                truncation=True,
                max_length=512,
                padding=True,
            )
            if device:
                inputs = {k: v.to(device) for k, v in inputs.items()}

            with torch.no_grad():
                outputs = classifier(**inputs)
                probs = torch.softmax(outputs.logits, dim=1)

            # CardiffNLP label order: negative(0), neutral(1), positive(2)
            for offset, (orig_idx, _) in enumerate(batch):
                score = float(probs[offset, 2].item() - probs[offset, 0].item())
                confidence = float(probs[offset].max().item())
                scores[orig_idx] = max(-1.0, min(1.0, score))
                confidences[orig_idx] = max(0.33, min(1.0, confidence))

        except Exception as e:
            logger.error("Batch sentiment scoring failed: %s", e)
            # Fall back to 0.0 score and 0.33 confidence for all items in this batch
            for orig_idx, _ in batch:
                scores[orig_idx] = 0.0
                confidences[orig_idx] = 0.33

    return scores, confidences


def compute_turn_embeddings(
    texts: list[str],
    model=None,
) -> list[np.ndarray | None]:
    """
    Compute raw embedding vectors for a list of texts.

    Returns a list of numpy arrays (one per text), or None for failed embeds.
    Used by arc_analyzer for geometric features (user self-distance, etc.).

    Uses batched encoding (batch_size from config.EMBEDDING_BATCH_SIZE)
    for 5-20x speedup over per-text encode calls.
    """
    if model is None:
        try:
            model = get_embedding_model()
        except ModelError as e:
            logger.error("Cannot load embedding model: %s", e)
            return [None] * len(texts)

    embeddings: list[np.ndarray | None] = [None] * len(texts)
    batch_size = config.EMBEDDING_BATCH_SIZE

    # Identify non-empty texts
    valid_items: list[tuple[int, str]] = []
    for i, text in enumerate(texts):
        stripped = text.strip() if text else ""
        if stripped:
            valid_items.append((i, stripped))

    if not valid_items:
        return embeddings

    # Process in batches
    for batch_start in range(0, len(valid_items), batch_size):
        batch = valid_items[batch_start:batch_start + batch_size]
        batch_texts = [t for _, t in batch]

        try:
            batch_embeddings = model.encode(batch_texts, convert_to_numpy=True)
            if batch_embeddings is None:
                continue

            batch_embeddings = np.asarray(batch_embeddings, dtype=np.float32)

            for offset, (orig_idx, _) in enumerate(batch):
                emb = batch_embeddings[offset]
                if np.all(np.isfinite(emb)):
                    embeddings[orig_idx] = emb
                else:
                    logger.warning("NaN/Inf in embedding for text at index %d", orig_idx)

        except Exception as e:
            logger.error("Batch embedding failed: %s", e)
            # Leave as None for failed items

    return embeddings


# Backwards compatibility alias — returns the sentiment model
get_model = get_sentiment_model
