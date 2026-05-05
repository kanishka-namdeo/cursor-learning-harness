"""
Consecutive turn deduplication using character Jaccard similarity.

Merges same-role turns with near-identical text to avoid inflating
turn counts and creating artificial sentiment oscillations.
"""


def _jaccard_similarity(a: str, b: str) -> float:
    """Character-level Jaccard similarity between two strings."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    set_a = set(a)
    set_b = set(b)
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def deduplicate_turns(
    turns: list[dict],
    similarity_threshold: float = 0.95,
) -> list[dict]:
    """
    Merge consecutive same-role turns with near-identical text.

    Uses character Jaccard similarity. When two consecutive turns from the
    same role exceed the similarity threshold, they are merged into a single
    turn (keeping the last text). The merged turn records a repeat_count.

    Args:
        turns: list of turn dicts from parser
        similarity_threshold: Jaccard similarity above which turns are merged

    Returns:
        Deduplicated list of turns.
    """
    if len(turns) <= 1:
        return turns

    result: list[dict] = []
    i = 0
    while i < len(turns):
        current = turns[i]
        repeat_count = 1

        # Merge consecutive similar turns from the same role
        while i + 1 < len(turns):
            next_turn = turns[i + 1]
            if next_turn["role"] != current["role"]:
                break
            sim = _jaccard_similarity(current["text"], next_turn["text"])
            if sim < similarity_threshold:
                break
            # Merge: keep the last text, increment repeat count
            current = next_turn
            repeat_count += 1
            i += 1

        # Build the merged turn
        merged = dict(current)
        if repeat_count > 1:
            merged["repeat_count"] = repeat_count

        result.append(merged)
        i += 1

    return result
