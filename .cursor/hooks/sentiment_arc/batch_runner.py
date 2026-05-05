"""
CLI entry point for batch sentiment arc analysis.

Usage:
    python .cursor/hooks/sentiment_arc/batch_runner.py [--root <path>] [--limit N]
        [--session-id <id>] [--force] [--include-subagents] [--model <name>]
        [--no-progress] [--dry-run]
"""

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

from . import config
from . import parser as transcript_parser
from . import embedder
from . import arc_analyzer
from . import arc_db

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Analyze agent transcript sentiment arcs."
    )
    ap.add_argument(
        "--root", type=Path, default=None,
        help="Transcript root directory (default: from config)",
    )
    ap.add_argument(
        "--limit", type=int, default=0,
        help="Only analyze first N sessions (for testing)",
    )
    ap.add_argument(
        "--session-id", type=str, default=None,
        help="Analyze a single session by UUID",
    )
    ap.add_argument(
        "--force", action="store_true",
        help="Re-analyze sessions that already have results",
    )
    ap.add_argument(
        "--include-subagents", action="store_true",
        help="Include subagent transcripts",
    )
    ap.add_argument(
        "--model", type=str, default=None,
        help="Override sentiment model (default: from config)",
    )
    ap.add_argument(
        "--no-progress", action="store_true",
        help="Disable tqdm progress bar",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Discover sessions and print count without analyzing",
    )
    ap.add_argument(
        "--no-dedup", action="store_true",
        help="Disable consecutive turn deduplication",
    )
    ap.add_argument(
        "--no-text-type-scoring", action="store_true",
        help="Disable text-type-aware scoring (score all text with model)",
    )
    ap.add_argument(
        "--no-task-completion", action="store_true",
        help="Skip LLM-as-judge task completion evaluation",
    )
    ap.add_argument(
        "--task-completion-only", action="store_true",
        help="Only re-evaluate task completion for sessions that already have arc features",
    )
    return ap.parse_args(argv)


def _run_task_completion_only(
    conn: sqlite3.Connection,
    transcript_paths: list,
    args,
) -> int:
    """Re-evaluate only task completion for sessions that already have arc features.

    Cheaper than full re-analysis: only LLM calls needed, no RoBERTa/embedding.
    """
    from .task_completion import evaluate_task_completion
    from .parser import load_session_transcript

    total = len(transcript_paths)
    if args.limit > 0:
        transcript_paths = transcript_paths[: args.limit]
        logger.info("--task-completion-only: limited to %d sessions", len(transcript_paths))

    updated = 0
    skipped = 0
    errors = 0

    use_progress = not args.no_progress
    if use_progress:
        try:
            from tqdm import tqdm
        except ImportError:
            tqdm = None
            use_progress = False

    iterator = enumerate(transcript_paths)
    if use_progress and tqdm:
        iterator = tqdm(list(enumerate(transcript_paths)), total=len(transcript_paths))

    for idx, transcript_path in iterator:
        session_id = transcript_path.parent.name
        label = f"{session_id[:16]}..."

        # Skip if no arc features exist yet (nothing to update)
        existing = arc_db.get_arc_features_for_session(conn, session_id)
        if existing is None:
            logger.debug("No arc features for %s, skipping task completion", label)
            skipped += 1
            continue

        # Parse turns
        turns, parse_error = load_session_transcript(transcript_path)
        if parse_error:
            logger.error("Parse error for %s: %s", label, parse_error)
            errors += 1
            continue

        # Evaluate task completion
        try:
            task_result = evaluate_task_completion(turns)
        except Exception as e:
            logger.error("Task completion failed for %s: %s", label, e)
            errors += 1
            continue

        # Build minimal update dict
        update = {
            "task_completion_score": task_result.get("score"),
            "task_completion_label": task_result.get("label"),
            "task_completion_explanation": task_result.get("explanation"),
        }
        # Preserve existing fields
        for key in existing:
            if key not in update:
                update[key] = existing[key]

        try:
            arc_db.store_arc_features(
                conn, session_id,
                update,
                None, None,
                existing.get("model_used", "unknown"),
            )
            updated += 1
        except Exception as e:
            logger.error("DB write failed for %s: %s", label, e)
            errors += 1

        if (idx + 1) % 50 == 0:
            conn.commit()

    conn.commit()
    logger.info("=== Task Completion Only Complete ===")
    logger.info("Total found:     %d", total)
    logger.info("Updated:         %d", updated)
    logger.info("Skipped:         %d", skipped)
    logger.info("Errors:          %d", errors)

    conn.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Resolve transcript root
    transcript_root = args.root or config.TRANSCRIPT_ROOT
    if not transcript_root.exists():
        logger.error("Transcript root does not exist: %s", transcript_root)
        return 1
    if not transcript_root.is_dir():
        logger.error("Transcript root is not a directory: %s", transcript_root)
        return 1

    # Initialize arc tables
    try:
        conn = arc_db.init_arc_tables()
    except Exception as e:
        logger.error("Failed to initialize arc tables: %s", e)
        return 1

    # Discover transcripts
    transcript_paths = transcript_parser.discover_transcripts(
        transcript_root, include_subagents=args.include_subagents
    )

    # Filter by session-id if specified
    if args.session_id:
        transcript_paths = [
            p for p in transcript_paths
            if args.session_id in p.name or args.session_id in p.parent.name
        ]
        if not transcript_paths:
            logger.error("No transcript found for session-id: %s", args.session_id)
            conn.close()
            return 1

    if not transcript_paths:
        logger.info("No transcripts found in %s", transcript_root)
        conn.close()
        return 0

    # Dry run mode
    if args.dry_run:
        logger.info("Dry run: found %d transcripts", len(transcript_paths))
        for p in transcript_paths[:10]:
            logger.info("  %s", p)
        if len(transcript_paths) > 10:
            logger.info("  ... and %d more", len(transcript_paths) - 10)
        conn.close()
        return 0

    # Filter already-analyzed sessions
    if not args.force:
        analyzed_ids = arc_db.list_analyzed_session_ids(conn)
        filtered = []
        for p in transcript_paths:
            session_id = p.parent.name
            if session_id not in analyzed_ids:
                filtered.append(p)
            else:
                logger.debug("Skipping already-analyzed: %s", session_id)
        transcript_paths = filtered
        logger.info("Skipping %d already-analyzed sessions", len(transcript_paths) - len(filtered) if filtered else len(transcript_paths))

    # Apply limit
    if args.limit > 0:
        transcript_paths = transcript_paths[: args.limit]

    if not transcript_paths:
        logger.info("No new sessions to analyze")
        conn.close()
        return 0

    # Task-completion-only mode: re-evaluate task completion for existing arc rows
    if args.task_completion_only:
        return _run_task_completion_only(conn, transcript_paths, args)

    # Load sentiment model and embedding model
    sentiment_model_name = args.model or config.SENTIMENT_MODEL
    embedding_model_name = config.EMBEDDING_MODEL
    try:
        sentiment_model = embedder.get_sentiment_model(sentiment_model_name)
    except embedder.ModelError as e:
        logger.error("Sentiment model error: %s", e)
        conn.close()
        return 1
    try:
        embedding_model = embedder.get_embedding_model(embedding_model_name)
    except embedder.ModelError as e:
        logger.error("Embedding model error: %s", e)
        conn.close()
        return 1

    # Progress bar setup
    use_progress = not args.no_progress
    if use_progress:
        try:
            from tqdm import tqdm
        except ImportError:
            tqdm = None
            use_progress = False

    total = len(transcript_paths)
    logger.info("Analyzing %d sessions", total)

    # Processing loop
    success_count = 0
    error_count = 0
    too_short_count = 0
    skip_count = 0
    all_archetypes: dict[str, int] = {}
    slopes = []

    iterator = enumerate(transcript_paths)
    if use_progress and tqdm:
        iterator = tqdm(list(enumerate(transcript_paths)), total=total)

    DB_COMMIT_INTERVAL = 50  # Commit every N sessions to reduce disk I/O

    for idx, transcript_path in iterator:
        session_id = transcript_path.parent.name
        label = f"{session_id[:16]}..."

        # Parse
        turns, parse_error = transcript_parser.load_session_transcript(transcript_path)

        if parse_error:
            logger.error("Parse error for %s: %s", label, parse_error)
            arc_db.store_arc_features(conn, session_id, None, None, None, sentiment_model_name, error=parse_error)
            error_count += 1
        elif len(turns) < config.MIN_TURNS_FOR_ANALYSIS:
            logger.info("Too short: %s (%d turns)", label, len(turns))
            arc_db.store_arc_features(
                conn, session_id,
                {"archetype": "too_short", "turn_count": len(turns), "archetype_confidence": 0.0},
                None, None, sentiment_model_name,
            )
            too_short_count += 1
            all_archetypes["too_short"] = all_archetypes.get("too_short", 0) + 1
        else:
            # Deduplicate consecutive turns (enabled by default)
            if not args.no_dedup:
                from .dedup import deduplicate_turns
                original_count = len(turns)
                turns = deduplicate_turns(turns)
                if len(turns) < original_count:
                    logger.debug("Deduped %s: %d -> %d turns", label, original_count, len(turns))
                # Check if dedup made it too short
                if len(turns) < config.MIN_TURNS_FOR_ANALYSIS:
                    logger.info("Too short after dedup: %s (%d turns)", label, len(turns))
                    arc_db.store_arc_features(
                        conn, session_id,
                        {"archetype": "too_short", "turn_count": len(turns), "archetype_confidence": 0.0},
                        None, None, sentiment_model_name,
                    )
                    too_short_count += 1
                    all_archetypes["too_short"] = all_archetypes.get("too_short", 0) + 1
                    continue

            # Score user turns only with text-type awareness (enabled by default)
            user_texts = [t["text"] for t in turns if t["role"] == "user"]
            if not user_texts:
                logger.info("No user turns in %s, skipping", label)
                arc_db.store_arc_features(
                    conn, session_id,
                    {"archetype": "too_short", "turn_count": len(turns), "archetype_confidence": 0.0},
                    None, None, sentiment_model_name,
                )
                too_short_count += 1
                all_archetypes["too_short"] = all_archetypes.get("too_short", 0) + 1
                continue

            # Compute embeddings on ALL turns (for model_relevance_trend)
            all_texts = [t["text"] for t in turns]
            try:
                embeddings = embedder.compute_turn_embeddings(all_texts, embedding_model)
            except Exception as e:
                logger.error("Scoring/embedding failed for %s: %s", label, e)
                arc_db.store_arc_features(conn, session_id, None, None, None, sentiment_model_name, error=str(e))
                error_count += 1
            else:
                # Score user turns only with text-type awareness, extracting confidences
                if not args.no_text_type_scoring:
                    from .score_text import score_text_by_type_with_confidence
                    from .embedder import compute_sentiment_scores_with_confidence
                    user_scores = []
                    user_confidences = []
                    for text in user_texts:
                        score, conf = score_text_by_type_with_confidence(
                            text,
                            sentiment_model,
                            compute_fn=compute_sentiment_scores_with_confidence,
                        )
                        user_scores.append(score)
                        user_confidences.append(conf)
                else:
                    user_scores = embedder.compute_sentiment_scores(user_texts, sentiment_model)
                    user_confidences = None

                try:
                    features = arc_analyzer.compute_arc_features(
                        turns, user_scores, embeddings, confidences=user_confidences,
                    )
                    archetype, confidence = arc_analyzer.classify_archetype(features)
                    features["archetype"] = archetype
                    features["archetype_confidence"] = confidence

                    # Task completion detection (LLM-as-judge)
                    if not args.no_task_completion:
                        try:
                            from .task_completion import evaluate_task_completion
                            task_result = evaluate_task_completion(turns)
                            features["task_completion_score"] = task_result.get("score")
                            features["task_completion_label"] = task_result.get("label")
                            features["task_completion_explanation"] = task_result.get("explanation")
                        except Exception as e:
                            logger.debug("Task completion eval failed for %s: %s", label, e)
                            features.setdefault("task_completion_score", None)
                            features.setdefault("task_completion_label", "unknown")
                            features.setdefault("task_completion_explanation", str(e))
                except Exception as e:
                    logger.error("Analysis failed for %s: %s", label, e)
                    arc_db.store_arc_features(conn, session_id, None, None, None, sentiment_model_name, error=str(e))
                    error_count += 1
                else:
                    try:
                        arc_db.store_arc_features(
                            conn, session_id,
                            features,
                            features.get("smoothed", []),
                            features.get("raw_scores", []),
                            sentiment_model_name,
                        )
                    except Exception as e:
                        logger.error("DB write failed for %s: %s", label, e)
                        # Retry once with minimal backoff (no sleep)
                        try:
                            arc_db.store_arc_features(
                                conn, session_id,
                                features,
                                features.get("smoothed", []),
                                features.get("raw_scores", []),
                                sentiment_model_name,
                            )
                        except Exception as e2:
                            logger.error("DB write retry failed for %s: %s", label, e2)
                            skip_count += 1
                            continue

                    success_count += 1
                    slopes.append(features.get("arc_slope"))
                    all_archetypes[archetype] = all_archetypes.get(archetype, 0) + 1

        # Batch commit: flush to disk every N inserts
        if (idx + 1) % DB_COMMIT_INTERVAL == 0:
            conn.commit()

        if use_progress and tqdm is None:
            logger.info("[%d/%d] %s done", idx + 1, total, label)

    # Update stats
    valid_slopes = [s for s in slopes if s is not None]
    avg_slope = None
    if valid_slopes:
        avg_slope = sum(valid_slopes) / len(valid_slopes)

    arc_db.update_analysis_stats(conn, success_count, sentiment_model_name, avg_slope, all_archetypes)

    # Summary
    logger.info("=== Analysis Complete ===")
    logger.info("Total found:    %d", total)
    logger.info("Analyzed:       %d", success_count)
    logger.info("Too short:      %d", too_short_count)
    logger.info("Errors:         %d", error_count)
    logger.info("Skipped:        %d", skip_count)
    logger.info("Archetypes:     %s", dict(sorted(all_archetypes.items(), key=lambda x: -x[1])))

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
