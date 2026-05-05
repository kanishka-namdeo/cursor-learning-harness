"""
Arc feature engineering and archetype classification.

Computes TRACE-inspired features from per-turn sentiment scores and
classifies each session into an interaction archetype.
"""

import logging
from typing import Any

import numpy as np

from . import config

logger = logging.getLogger(__name__)


def smooth_arc(scores: list[float], weights: list[float] | None = None, alpha: float = config.SMOOTHING_ALPHA) -> list[float]:
    """
    Exponential moving average smoothing of sentiment scores.

    smoothed[t] = alpha * scores[t] + (1 - alpha) * smoothed[t-1]

    When weights are provided, alpha is scaled per-turn:
        effective_alpha[t] = min(alpha * weights[t], 0.9)

    Edge cases:
    - Empty list -> returns []
    - Single score -> returns [score]
    """
    if not scores:
        return []
    if len(scores) == 1:
        return [scores[0]]

    smoothed = [scores[0]]
    for i in range(1, len(scores)):
        if weights and i < len(weights):
            effective_alpha = min(alpha * weights[i], 0.9)
        else:
            effective_alpha = alpha
        s = effective_alpha * scores[i] + (1 - effective_alpha) * smoothed[-1]
        smoothed.append(s)
    return smoothed


def _linear_regression_slope(values: list[float]) -> float | None:
    """Compute the slope of a simple linear regression (y = mx + b).

    Returns None if fewer than 2 data points.
    """
    n = len(values)
    if n < 2:
        return None

    xs = np.arange(n, dtype=np.float64)
    ys = np.array(values, dtype=np.float64)

    x_mean = xs.mean()
    y_mean = ys.mean()

    numerator = ((xs - x_mean) * (ys - y_mean)).sum()
    denominator = ((xs - x_mean) ** 2).sum()

    if denominator == 0:
        return 0.0

    return float(numerator / denominator)


def _cosine_dist(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine distance = 1 - cosine_similarity."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 1.0
    sim = float(np.dot(a, b) / (norm_a * norm_b))
    return 1.0 - max(-1.0, min(1.0, sim))


def compute_arc_features(
    turns: list[dict],
    user_scores: list[float],
    embeddings: list[np.ndarray | None] | None = None,
    confidences: list[float] | None = None,
) -> dict[str, Any]:
    """
    Compute all TRACE-inspired arc features from user-only sentiment scores.

    Sentiment is scored on user messages only (matching PostHog's production
    approach). Assistant text is not scored but is still used for embedding-based
    geometric features (model_relevance_trend).

    Args:
        turns: list of turn dicts from parser (with 'role' key)
        user_scores: list of per-turn sentiment scores for user turns only
        embeddings: optional list of per-turn embedding vectors (all turns)
        confidences: optional list of per-prediction confidence values for user turns

    Returns dict with all feature values. Features that cannot be computed
    are set to None.
    """
    thresholds = config.ARCHETYPE_THRESHOLDS
    turn_count = len(turns)

    # Compute turn length weights from user turns only, optionally scaled by confidence
    user_turns = [t for t in turns if t["role"] == "user"]
    if not user_turns:
        user_turns = turns  # fallback: use all turns for weights

    length_weights = [
        min(float(np.log2(max(len(t.get("text", "")), 1) + 1)), 3.0)
        for t in user_turns
    ]

    # Scale weights by confidence when available
    if confidences and len(confidences) == len(length_weights):
        weights = [
            lw * conf for lw, conf in zip(length_weights, confidences)
        ]
    else:
        weights = length_weights

    smoothed = smooth_arc(user_scores, weights=weights)

    # --- arc_slope ---
    arc_slope = _linear_regression_slope(smoothed)

    # --- arc_intercept ---
    arc_intercept = smoothed[0] if smoothed else None

    # --- late_volatility ---
    late_start = max(0, int(turn_count * 0.75))
    late_scores = smoothed[late_start:] if len(smoothed) > late_start else smoothed
    if len(late_scores) >= 2:
        late_volatility = float(np.var(late_scores))
    else:
        late_volatility = None

    # --- user_self_distance ---
    user_embeddings = []
    for i, turn in enumerate(turns):
        if turn["role"] == "user" and embeddings and embeddings[i] is not None:
            user_embeddings.append(embeddings[i])

    if len(user_embeddings) >= 2:
        distances = []
        for j in range(1, len(user_embeddings)):
            distances.append(_cosine_dist(user_embeddings[j - 1], user_embeddings[j]))
        user_self_distance = float(np.mean(distances))
    else:
        user_self_distance = None

    # --- model_relevance_trend ---
    # Pair consecutive user turns with the following assistant turns
    user_resp_similarities = []
    for i in range(len(turns) - 1):
        if turns[i]["role"] == "user" and turns[i + 1]["role"] == "assistant":
            if embeddings and embeddings[i] is not None and embeddings[i + 1] is not None:
                norm_u = np.linalg.norm(embeddings[i])
                norm_a = np.linalg.norm(embeddings[i + 1])
                if norm_u > 0 and norm_a > 0:
                    sim = float(np.dot(embeddings[i], embeddings[i + 1]) / (norm_u * norm_a))
                    user_resp_similarities.append(sim)

    if len(user_resp_similarities) >= 2:
        model_relevance_trend = _linear_regression_slope(user_resp_similarities)
    else:
        model_relevance_trend = None

    # --- recovery_events ---
    recovery_events = 0
    recovery_threshold = thresholds["recovery_threshold"]
    min_dip_depth = config.MIN_DIP_DEPTH
    last_recovery_end = -1
    if len(smoothed) >= 4:
        for i in range(1, len(smoothed) - 1):
            if i <= last_recovery_end:
                continue
            if smoothed[i] < smoothed[i - 1] - recovery_threshold:
                pre_dip = smoothed[i - 1]
                dip_depth = pre_dip - smoothed[i]
                if dip_depth >= min_dip_depth:
                    for j in range(i + 1, len(smoothed)):
                        if smoothed[j] > pre_dip:
                            recovery_events += 1
                            last_recovery_end = j
                            break

    # --- avg_sentiment (user-only) ---
    avg_sentiment = float(np.mean(user_scores)) if user_scores else None

    # --- sentiment_range (user-only) ---
    sentiment_range_val = float(max(user_scores) - min(user_scores)) if len(user_scores) >= 2 else 0.0

    # --- arc_etv ---
    arc_etv = float(np.var(smoothed)) if len(smoothed) >= 2 else 0.0

    # --- mismatched_effort_score (continuous 0.0-1.0) ---
    mismatched_effort_score = 0.0
    if user_self_distance is not None and model_relevance_trend is not None:
        # Distance component: closer to 0 = more repetition (higher signal)
        dist_component = max(0.0, 1.0 - user_self_distance / thresholds["user_self_distance_low"])
        # Trend component: more negative = model drifting away (higher signal)
        trend_component = max(0.0, 1.0 - model_relevance_trend / thresholds["model_relevance_trend_negative"])
        # Combined: geometric mean prevents one strong signal from dominating
        mismatched_effort_score = round(float(np.sqrt(dist_component * trend_component)), 6)

    # Keep boolean for backward compat
    mismatched_effort_signal = mismatched_effort_score > 0.5

    # --- last_score ---
    last_score = smoothed[-1] if smoothed else None

    # --- user_sentiment_trend (slope of user scores over time) ---
    user_sentiment_trend = _linear_regression_slope(user_scores) if len(user_scores) >= 2 else None

    # --- avg_model_confidence ---
    avg_model_confidence = float(np.mean(confidences)) if confidences else None

    # --- temporal features ---
    turn_timestamps = []
    for t in turns:
        ts = t.get("timestamp")
        if ts:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(ts)
                turn_timestamps.append(dt)
            except (ValueError, TypeError):
                turn_timestamps.append(None)
        else:
            turn_timestamps.append(None)

    inter_arrival_times = []
    for i in range(1, len(turn_timestamps)):
        if turn_timestamps[i] and turn_timestamps[i - 1]:
            delta = (turn_timestamps[i] - turn_timestamps[i - 1]).total_seconds()
            if delta >= 0:
                inter_arrival_times.append(delta)

    if len(inter_arrival_times) >= 2:
        mean_inter_arrival = float(np.mean(inter_arrival_times))
        inter_arrival_cv = float(np.std(inter_arrival_times)) / mean_inter_arrival if mean_inter_arrival > 0 else 0.0
        inter_arrival_trend = _linear_regression_slope(inter_arrival_times)
    else:
        mean_inter_arrival = None
        inter_arrival_cv = None
        inter_arrival_trend = None

    return {
        "arc_slope": arc_slope,
        "arc_intercept": arc_intercept,
        "late_volatility": late_volatility,
        "user_self_distance": user_self_distance,
        "model_relevance_trend": model_relevance_trend,
        "recovery_events": recovery_events,
        "turn_count": turn_count,
        "avg_sentiment": avg_sentiment,
        "sentiment_range": sentiment_range_val,
        "arc_etv": arc_etv,
        "mismatched_effort_signal": mismatched_effort_signal,
        "mismatched_effort_score": mismatched_effort_score,
        "last_score": last_score,
        "smoothed": smoothed,
        "raw_scores": user_scores,
        "user_sentiment_trend": user_sentiment_trend,
        "avg_model_confidence": avg_model_confidence,
        "mean_inter_arrival": mean_inter_arrival,
        "inter_arrival_cv": inter_arrival_cv,
        "inter_arrival_trend": inter_arrival_trend,
    }


def classify_archetype(features: dict[str, Any]) -> tuple[str, float]:
    """
    Rule-based archetype classification with confidence scoring.

    Priority order (first match wins):
    1. looping
    2. abandoned
    3. escalating_frustration
    4. mismatched_effort
    5. smooth_convergence
    6. rapid_resolution
    7. steady_friction
    8. inconclusive (default)

    Special: "too_short" if arc_slope is None (too few turns).

    Returns (archetype, confidence) where confidence is 0.0-1.0.
    """
    t = config.ARCHETYPE_THRESHOLDS

    arc_slope = features.get("arc_slope")
    if arc_slope is None:
        return "too_short", 0.0

    arc_etv = features.get("arc_etv", 0.0)
    recovery_events = features.get("recovery_events", 0)
    late_volatility = features.get("late_volatility")
    avg_sentiment = features.get("avg_sentiment")
    last_score = features.get("last_score")
    sentiment_range = features.get("sentiment_range", 0.0)
    mismatched_effort_score = features.get("mismatched_effort_score", 0.0)
    raw_scores = features.get("raw_scores", [])

    # Task completion signal (optional — may be None if LLM judge unavailable)
    task_label = features.get("task_completion_label")
    task_score = features.get("task_completion_score")
    task_completed = task_label == "completed"
    task_failed = task_label in ("failed", "abandoned")

    # Temporal signal
    inter_arrival_trend = features.get("inter_arrival_trend")

    # 1. looping — requires: recovery_events >= 3 AND arc_etv > volatility_high
    looping_conditions = [recovery_events >= 3, arc_etv > t["volatility_high"]]
    if all(looping_conditions):
        return "looping", 1.0
    looping_met = sum(looping_conditions) / len(looping_conditions)

    # 2. abandoned — only if task not completed
    if not task_completed and late_volatility is not None and last_score is not None:
        turn_count = features.get("turn_count", 0)
        late_start = max(0, int(turn_count * 0.75))
        if raw_scores and late_start > 0:
            max_before_late = max(raw_scores[:late_start])
            drop = last_score - max_before_late
            abandoned_conditions = [
                late_volatility > 0,
                last_score < t["end_sentiment_low"],
                arc_slope < t["slope_negative"],
                drop < -t["recovery_threshold"],
            ]
            if all(abandoned_conditions):
                # Growing gaps between turns strengthen the abandonment signal
                confidence = 1.0
                if inter_arrival_trend is not None and inter_arrival_trend > 0:
                    confidence = 1.0  # Already max, but confirms the pattern
                return "abandoned", confidence

    # 3. escalating_frustration — only if task failed/abandoned
    escalating_conditions = [
        arc_slope < t["slope_negative"],
        late_volatility is not None and late_volatility > t["volatility_low"],
    ]
    escalating_met = sum(escalating_conditions) / len(escalating_conditions)
    if all(escalating_conditions):
        if task_completed:
            return "mismatched_effort", 0.8
        if task_failed:
            return "escalating_frustration", 1.0
        return "escalating_frustration", 1.0

    # 4. mismatched_effort
    if mismatched_effort_score > 0.5:
        return "mismatched_effort", 1.0

    # 5. smooth_convergence — boost if task completed even with marginal sentiment
    if late_volatility is not None and last_score is not None:
        smooth_conditions = [
            arc_slope > t["slope_positive"],
            late_volatility < t["volatility_low"],
            last_score > t["end_sentiment_high"],
        ]
        if all(smooth_conditions):
            return "smooth_convergence", 1.0
        # If task completed and conditions are close, still call it smooth_convergence
        if task_completed and arc_slope > t["slope_positive"] and last_score > 0:
            return "smooth_convergence", 0.7

    # 6. rapid_resolution
    if sentiment_range is not None and last_score is not None and raw_scores:
        max_idx = raw_scores.index(max(raw_scores))
        if max_idx > 0:
            min_before_max = min(raw_scores[:max_idx])
            rebound = max(raw_scores) - min_before_max
            rapid_conditions = [
                sentiment_range > 0.4,
                rebound > t["recovery_threshold"],
                last_score > 0,
            ]
            if all(rapid_conditions):
                return "rapid_resolution", 1.0
            # Task completed with fast rebound even if not meeting all conditions
            if task_completed and rebound > t["recovery_threshold"] and last_score > 0:
                return "rapid_resolution", 0.6

    # 7. steady_friction — only if task not completed
    if avg_sentiment is not None:
        steady_conditions = [
            abs(arc_slope) < 0.003,
            avg_sentiment < -0.05,
            arc_etv < t["volatility_low"],
        ]
        if all(steady_conditions):
            if task_failed:
                return "steady_friction", 1.0
            if task_completed:
                return "mismatched_effort", 0.7
            return "steady_friction", 1.0

    # 8. default — inconclusive
    return "inconclusive", 0.0


def analyze_session(turns: list[dict], embeddings: list[np.ndarray | None] | None = None) -> dict:
    """
    Top-level analysis: compute features and classify archetype.

    Scores sentiment on user messages only (matching PostHog's production
    approach). For short sessions, returns a minimal dict with archetype=
    "too_short" so callers get uniform behavior.
    """
    if len(turns) < config.MIN_TURNS_FOR_ANALYSIS:
        return {
            "archetype": "too_short",
            "turn_count": len(turns),
            "arc_slope": None,
            "archetype_confidence": 0.0,
            "avg_sentiment": None,
            "sentiment_range": 0.0,
            "arc_etv": 0.0,
            "recovery_events": 0,
        }

    # Extract user-only texts
    user_texts = [t["text"] for t in turns if t["role"] == "user"]
    if not user_texts:
        return {
            "archetype": "too_short",
            "turn_count": len(turns),
            "arc_slope": None,
            "archetype_confidence": 0.0,
            "avg_sentiment": None,
            "sentiment_range": 0.0,
            "arc_etv": 0.0,
            "recovery_events": 0,
        }

    # Score sentiment (user only)
    from .embedder import compute_sentiment_scores
    user_scores = compute_sentiment_scores(user_texts)

    # Compute features
    features = compute_arc_features(turns, user_scores, embeddings)

    # Classify archetype (returns tuple: archetype, confidence)
    archetype, confidence = classify_archetype(features)
    features["archetype"] = archetype
    features["archetype_confidence"] = confidence

    return features
