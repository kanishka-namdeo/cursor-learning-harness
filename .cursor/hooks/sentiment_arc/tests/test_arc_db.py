"""Tests for arc_db.py — column existence checks and UPSERT with new columns."""

import json
import sqlite3
import tempfile
from pathlib import Path

from sentiment_arc.arc_db import (
    init_arc_tables,
    list_analyzed_session_ids,
    migrate_arc_tables,
    store_arc_features,
)


class TestArcDB:
    def test_init_creates_tables(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = init_arc_tables(db_path)
        try:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            table_names = [r[0] for r in tables]
            assert "session_arc_features" in table_names
            assert "arc_analysis_stats" in table_names
        finally:
            conn.close()

    def test_migrate_idempotent(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = init_arc_tables(db_path)
        try:
            # First migration
            migrate_arc_tables(conn)
            # Second migration should not raise
            migrate_arc_tables(conn)

            # Verify columns exist
            columns = conn.execute("PRAGMA table_info(session_arc_features)").fetchall()
            col_names = [c[1] for c in columns]
            assert "archetype_confidence" in col_names
            assert "sentiment_gap" in col_names
            assert "user_sentiment_trend" in col_names
            assert "assistant_sentiment_trend" in col_names
            assert "avg_user_sentiment" in col_names
            assert "avg_assistant_sentiment" in col_names
        finally:
            conn.close()

    def test_store_arc_features_with_new_columns(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = init_arc_tables(db_path)
        try:
            store_arc_features(
                conn,
                session_id="test-001",
                analysis={
                    "archetype": "smooth_convergence",
                    "turn_count": 10,
                    "arc_slope": 0.01,
                    "archetype_confidence": 1.0,
                    "user_sentiment_trend": -0.005,
                    "assistant_sentiment_trend": 0.02,
                    "sentiment_gap": 0.3,
                    "avg_user_sentiment": -0.1,
                    "avg_assistant_sentiment": 0.2,
                    "max_sentiment_gap": 0.5,
                },
                smoothed_arc=[0.0, 0.1, 0.2],
                raw_scores=[-0.1, 0.1, 0.3],
                model_name="test-model",
            )
            conn.commit()

            row = conn.execute(
                "SELECT * FROM session_arc_features WHERE session_id='test-001'"
            ).fetchone()
            assert row is not None
            assert row[2] == "smooth_convergence"  # archetype
            assert row[19] == 1.0  # archetype_confidence (column index 19)
        finally:
            conn.close()

    def test_store_error_record(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = init_arc_tables(db_path)
        try:
            store_arc_features(
                conn,
                session_id="err-001",
                analysis=None,
                smoothed_arc=None,
                raw_scores=None,
                model_name="test-model",
                error="Parse failed",
            )
            conn.commit()

            row = conn.execute(
                "SELECT * FROM session_arc_features WHERE session_id='err-001'"
            ).fetchone()
            assert row is not None
            assert row[2] == "error"  # archetype
            assert row[18] == "Parse failed"  # error_message
        finally:
            conn.close()

    def test_upsert_replaces_existing(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = init_arc_tables(db_path)
        try:
            store_arc_features(
                conn, "upsert-001",
                {"archetype": "inconclusive", "turn_count": 5},
                None, None, "model-a",
            )
            # Re-analyze with different data
            store_arc_features(
                conn, "upsert-001",
                {"archetype": "smooth_convergence", "turn_count": 10, "arc_slope": 0.01},
                [0.1, 0.2], [0.0, 0.2], "model-b",
            )
            conn.commit()

            rows = conn.execute(
                "SELECT COUNT(*) FROM session_arc_features WHERE session_id='upsert-001'"
            ).fetchone()
            assert rows[0] == 1

            row = conn.execute(
                "SELECT archetype, model_used FROM session_arc_features WHERE session_id='upsert-001'"
            ).fetchone()
            assert row[0] == "smooth_convergence"
            assert row[1] == "model-b"
        finally:
            conn.close()

    def test_list_analyzed_session_ids(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = init_arc_tables(db_path)
        try:
            store_arc_features(
                conn, "sess-a", {"archetype": "inconclusive", "turn_count": 4},
                None, None, "model",
            )
            store_arc_features(
                conn, "sess-b", {"archetype": "too_short", "turn_count": 2},
                None, None, "model",
            )
            conn.commit()

            ids = list_analyzed_session_ids(conn)
            assert ids == {"sess-a", "sess-b"}
        finally:
            conn.close()
