"""
Central configuration for the Sentiment Arc analysis module.

All configurable constants live here. No hardcoded paths in other modules.
Override via environment variables when needed.
"""

import os
from pathlib import Path

# Transcript root path — overridable via SENTIMENT_ARC_TRANSCRIPT_ROOT env var
# Points to .cursor/hooks/state/sessions where Cursor stores session.json files
TRANSCRIPT_ROOT = Path(
    os.environ.get(
        "SENTIMENT_ARC_TRANSCRIPT_ROOT",
        str(Path(__file__).resolve().parents[1] / "state" / "sessions")
    )
)

# Sentiment classification model — overridable via SENTIMENT_ARC_MODEL env var
# Default: cardiffnlp/twitter-roberta-base-sentiment-latest (trained on ~124M tweets,
# TweetEval benchmark — best available cardiffnlp RoBERTa sentiment model on HuggingFace)
# Note: "twitter-roberta-base-sentiment-long" does not exist on HuggingFace.
# Alternatives: "cardiffnlp/twitter-roberta-base-sentiment",
#               "distilbert-base-uncased-finetuned-sst-2-english"
SENTIMENT_MODEL = os.environ.get(
    "SENTIMENT_ARC_MODEL",
    "cardiffnlp/twitter-roberta-base-sentiment-latest"
)

# Embedding model for geometric features (user self-distance, model relevance trend)
# Overridable via SENTIMENT_ARC_EMBED_MODEL env var
# Default: all-mpnet-base-v2 (110M params, strong semantic similarity)
# Fallback: BAAI/bge-small-en-v1.5 (33M params, better than MiniLM on technical text)
EMBEDDING_MODEL = os.environ.get(
    "SENTIMENT_ARC_EMBED_MODEL",
    "sentence-transformers/all-mpnet-base-v2"
)

# Fallback embedding model if primary fails to load
EMBEDDING_MODEL_FALLBACK = "BAAI/bge-small-en-v1.5"

# Smoothing
SMOOTHING_ALPHA = 0.3  # First-order EMA smoothing factor

# Recovery event detection
MIN_DIP_DEPTH = 0.1  # Minimum dip depth (pre-dip to trough) to count as recovery

# Archetype classification thresholds
ARCHETYPE_THRESHOLDS = {
    "slope_positive": 0.005,
    "slope_negative": -0.005,
    "volatility_low": 0.02,
    "volatility_high": 0.05,
    "end_sentiment_high": 0.3,
    "end_sentiment_low": -0.3,
    "user_self_distance_low": 0.15,  # User repeating themselves
    "model_relevance_trend_negative": -0.003,
    "recovery_threshold": 0.15,  # Minimum sentiment rebound to count as recovery
}

# Minimum turns to produce a valid arc
MIN_TURNS_FOR_ANALYSIS = 4

# Batch processing
SENTIMENT_BATCH_SIZE = 32  # Texts per RoBERTa forward pass
EMBEDDING_BATCH_SIZE = 32  # Texts per sentence-transformers encode call
DB_BUSY_TIMEOUT_MS = 10000  # SQLite busy timeout

# Compute device — overridable via SENTIMENT_ARC_DEVICE env var
# Values: "auto" (default: CUDA if available, else CPU), "cuda", "cpu"
DEVICE = os.environ.get("SENTIMENT_ARC_DEVICE", "auto")

# Positive/negative anchor texts (kept for backwards compatibility with legacy configs)
# No longer used by the default RoBERTa sentiment classifier
POSITIVE_ANCHOR = "This is working well. The solution is correct and helpful."
NEGATIVE_ANCHOR = "This is wrong. The approach is confusing and unsatisfactory."

# Archetype names
ARCHETYPES = [
    "smooth_convergence",
    "rapid_resolution",
    "steady_friction",
    "escalating_frustration",
    "mismatched_effort",
    "looping",
    "abandoned",
    "inconclusive",
    "too_short",
    "error",
]

# Frustrating archetype names (for dashboard KPI grouping)
FRUSTRATING_ARCHETYPES = {
    "escalating_frustration",
    "mismatched_effort",
    "looping",
    "abandoned",
}

# Smooth archetype names (for dashboard KPI grouping)
SMOOTH_ARCHETYPES = {
    "smooth_convergence",
    "rapid_resolution",
}
