"""
Database query functions for the Narratives Dashboard.

All functions read from the existing narratives.db (SQLite) and return
data structures ready for Streamlit/Plotly consumption.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

NARRATIVES_DB_PATH = Path(__file__).parent.parent / "state" / "narratives.db"


def _connect() -> sqlite3.Connection:
    """Open a read-only connection to the narratives database."""
    conn = sqlite3.connect(str(NARRATIVES_DB_PATH), uri=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=3000")
    return conn


def _rows_to_dicts(cursor) -> list[dict]:
    return [dict(row) for row in cursor.fetchall()]


# ---------------------------------------------------------------------------
# Overview queries
# ---------------------------------------------------------------------------

def get_kpi_stats() -> dict:
    """Return top-level KPI numbers for the dashboard."""
    conn = _connect()
    try:
        total_sessions = conn.execute(
            "SELECT COUNT(*) as cnt FROM sessions"
        ).fetchone()["cnt"]

        total_events = conn.execute(
            "SELECT COALESCE(SUM(total_events), 0) as s FROM session_stats"
        ).fetchone()["s"]

        avg_duration = conn.execute(
            "SELECT COALESCE(AVG(duration_ms), 0) as a FROM sessions WHERE duration_ms > 0"
        ).fetchone()["a"]

        total_tool_calls = conn.execute(
            "SELECT COALESCE(SUM(total_tool_calls), 0) as s FROM session_tool_stats"
        ).fetchone()["s"]

        total_narratives = conn.execute(
            "SELECT COUNT(*) as cnt FROM narratives"
        ).fetchone()["cnt"]

        total_file_edits = conn.execute(
            "SELECT COALESCE(SUM(total_file_edits), 0) as s FROM session_stats"
        ).fetchone()["s"]

        return {
            "total_sessions": total_sessions,
            "total_events": total_events,
            "avg_duration_ms": round(avg_duration, 0),
            "total_tool_calls": total_tool_calls,
            "total_narratives": total_narratives,
            "total_file_edits": total_file_edits,
        }
    finally:
        conn.close()


def get_sessions_time_series(days: int = 30, date_from: str = "", date_to: str = "") -> list[dict]:
    """Return session count per day, filtered by days or explicit date range."""
    conn = _connect()
    try:
        conditions = []
        params: list = []
        if date_from and date_to:
            conditions.append("s.created_at >= ?")
            params.append(date_from)
            conditions.append("s.created_at <= ?")
            params.append(date_to + " 23:59:59")
        else:
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            conditions.append("s.created_at >= ?")
            params.append(cutoff)
        where_clause = " AND ".join(conditions)
        rows = conn.execute(
            f"""
            SELECT DATE(s.created_at) as day, COUNT(*) as count
            FROM sessions s
            WHERE {where_clause}
            GROUP BY DATE(s.created_at)
            ORDER BY day ASC
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_tool_usage_top_n(n: int = 10, date_from: str = "", date_to: str = "") -> list[dict]:
    """Return the top N most-used tools across all sessions, optionally filtered by date."""
    conn = _connect()
    try:
        conditions = []
        params: list = []
        if date_from and date_to:
            conditions.append("s.created_at >= ?")
            params.append(date_from)
            conditions.append("s.created_at <= ?")
            params.append(date_to + " 23:59:59")
        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
            SELECT st.tool_usage_breakdown
            FROM session_stats st
            JOIN sessions s ON s.session_id = st.session_id
            WHERE st.tool_usage_breakdown IS NOT NULL AND {where_clause}
        """
        rows = conn.execute(query, params).fetchall()

        totals: dict[str, int] = {}
        for row in rows:
            breakdown = json.loads(row["tool_usage_breakdown"])
            for tool_name, count in breakdown.items():
                totals[tool_name] = totals.get(tool_name, 0) + (
                    count if isinstance(count, int) else count.get("calls", 0)
                    if isinstance(count, dict) else 0
                )

        sorted_tools = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:n]
        return [{"tool": name, "count": count} for name, count in sorted_tools]
    finally:
        conn.close()


def get_session_status_breakdown() -> list[dict]:
    """Return session counts grouped by status."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT status, COUNT(*) as count FROM sessions GROUP BY status ORDER BY count DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_recent_sessions(limit: int = 20, date_from: str = "", date_to: str = "") -> list[dict]:
    """Return the most recent sessions with basic info, optionally filtered by date."""
    conn = _connect()
    try:
        conditions = []
        params: list = []
        if date_from and date_to:
            conditions.append("s.created_at >= ?")
            params.append(date_from)
            conditions.append("s.created_at <= ?")
            params.append(date_to + " 23:59:59")
        where_clause = " AND ".join(conditions) if conditions else "1=1"

        rows = conn.execute(
            f"""
            SELECT s.session_id, s.created_at, s.status, s.duration_ms,
                   s.model, s.composer_mode,
                   n.word_count, n.strategy,
                   st.total_events, st.total_file_edits, st.total_tool_uses
            FROM sessions s
            LEFT JOIN narratives n ON s.session_id = n.session_id
            LEFT JOIN session_stats st ON s.session_id = st.session_id
            WHERE {where_clause}
            ORDER BY s.created_at DESC
            LIMIT ?
            """,
            [*params, limit],
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Session Explorer queries
# ---------------------------------------------------------------------------

def get_sessions_explorer(
    search: str = "",
    status: str = "",
    model: str = "",
    date_from: str = "",
    date_to: str = "",
    sort_col: str = "created_at",
    sort_dir: str = "DESC",
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[dict], int]:
    """Return a paginated, filtered session list with total count."""
    conn = _connect()
    try:
        conditions = []
        params: list = []

        if search:
            conditions.append(
                "(s.session_id LIKE ? OR n.narrative LIKE ? OR s.model LIKE ?)"
            )
            params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

        if status:
            conditions.append("s.status = ?")
            params.append(status)

        if model:
            conditions.append("s.model LIKE ?")
            params.append(f"%{model}%")

        if date_from:
            conditions.append("s.created_at >= ?")
            params.append(date_from)

        if date_to:
            conditions.append("s.created_at <= ?")
            params.append(date_to + " 23:59:59")

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # Total count
        count_row = conn.execute(
            f"""
            SELECT COUNT(*) as cnt
            FROM sessions s
            LEFT JOIN narratives n ON s.session_id = n.session_id
            WHERE {where_clause}
            """,
            params,
        ).fetchone()
        total = count_row["cnt"]

        # Paginated data
        valid_sort_cols = {
            "session_id", "created_at", "status", "duration_ms",
            "model", "word_count", "total_events", "total_file_edits",
        }
        if sort_col not in valid_sort_cols:
            sort_col = "created_at"
        if sort_dir not in ("ASC", "DESC"):
            sort_dir = "DESC"

        offset = (page - 1) * page_size

        rows = conn.execute(
            f"""
            SELECT s.session_id, s.created_at, s.status, s.duration_ms,
                   s.model, s.composer_mode,
                   n.word_count, n.strategy,
                   st.total_events, st.total_file_edits, st.total_tool_uses
            FROM sessions s
            LEFT JOIN narratives n ON s.session_id = n.session_id
            LEFT JOIN session_stats st ON s.session_id = st.session_id
            WHERE {where_clause}
            ORDER BY s.{sort_col} {sort_dir}
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()

        return [dict(r) for r in rows], total
    finally:
        conn.close()


def get_session_detail(session_id: str) -> dict | None:
    """Return full details for a single session."""
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT s.*, n.narrative, n.generated_at, n.strategy,
                   n.word_count, n.event_count_at_summary,
                   st.total_events, st.total_responses, st.total_thoughts,
                   st.total_thinking_time_ms, st.total_file_edits,
                   st.unique_files_edited, st.total_shell_commands,
                   st.total_tool_uses, st.tool_usage_breakdown,
                   st.net_code_change, st.total_chars_added,
                   st.total_chars_removed
            FROM sessions s
            LEFT JOIN narratives n ON s.session_id = n.session_id
            LEFT JOIN session_stats st ON s.session_id = st.session_id
            WHERE s.session_id = ?
            """,
            (session_id,),
        ).fetchone()

        if row is None:
            return None

        result = dict(row)

        # Parse JSON fields
        if result.get("unique_files_edited"):
            try:
                result["unique_files_list"] = json.loads(result["unique_files_edited"])
            except (json.JSONDecodeError, TypeError):
                result["unique_files_list"] = []

        if result.get("tool_usage_breakdown"):
            try:
                result["tool_breakdown"] = json.loads(result["tool_usage_breakdown"])
            except (json.JSONDecodeError, TypeError):
                result["tool_breakdown"] = {}

        # Get tool stats if available
        ts = conn.execute(
            "SELECT * FROM session_tool_stats WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if ts:
            ts_dict = dict(ts)
            result["tool_total_calls"] = ts_dict.get("total_tool_calls", 0)
            result["tool_successes"] = ts_dict.get("total_tool_successes", 0)
            result["tool_failures"] = ts_dict.get("total_tool_failures", 0)
            result["tool_errors"] = ts_dict.get("total_tool_errors", 0)
            result["tool_avg_duration_ms"] = ts_dict.get("avg_tool_duration_ms", 0)

        return result
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Narrative queries
# ---------------------------------------------------------------------------

def get_all_narratives_list() -> list[dict]:
    """Return session_id + metadata for all sessions with narratives."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT n.session_id, n.generated_at, n.word_count, n.strategy,
                   s.created_at, s.status, s.model, s.duration_ms
            FROM narratives n
            JOIN sessions s ON n.session_id = s.session_id
            ORDER BY n.generated_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tool Analytics queries
# ---------------------------------------------------------------------------

def get_tool_frequency_table() -> list[dict]:
    """Return all tools ranked by total usage count."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT tool_usage_breakdown, tool_failure_breakdown, avg_tool_duration_ms "
            "FROM session_tool_stats"
        ).fetchall()

        totals: dict[str, dict] = {}
        for row in rows:
            usage = json.loads(row["tool_usage_breakdown"]) if row["tool_usage_breakdown"] else {}
            failures = json.loads(row["tool_failure_breakdown"]) if row["tool_failure_breakdown"] else {}

            for tool_name, count in usage.items():
                if tool_name not in totals:
                    totals[tool_name] = {"tool": tool_name, "total_calls": 0, "total_failures": 0, "durations": []}

                c = count if isinstance(count, int) else (count.get("calls", 0) if isinstance(count, dict) else 0)
                totals[tool_name]["total_calls"] += c

            for tool_name, count in failures.items():
                if tool_name in totals:
                    c = count if isinstance(count, int) else 0
                    totals[tool_name]["total_failures"] += c

            if row["avg_tool_duration_ms"]:
                for tool_name in totals:
                    totals[tool_name]["durations"].append(row["avg_tool_duration_ms"])

        result = []
        for tool_name, data in totals.items():
            avg_dur = sum(data["durations"]) / len(data["durations"]) if data["durations"] else 0
            result.append({
                "tool": tool_name,
                "total_calls": data["total_calls"],
                "total_failures": data["total_failures"],
                "avg_duration_ms": round(avg_dur, 1),
                "success_rate": round(
                    (1 - data["total_failures"] / data["total_calls"]) * 100, 1
                ) if data["total_calls"] > 0 else 0,
            })

        result.sort(key=lambda x: x["total_calls"], reverse=True)
        return result
    finally:
        conn.close()


def get_tool_time_series(top_n: int = 5, date_from: str = "", date_to: str = "") -> list[dict]:
    """Return tool usage over time for the top N tools, optionally filtered by date."""
    conn = _connect()
    try:
        # First find top tools
        conditions = []
        params: list = []
        if date_from and date_to:
            conditions.append("s.created_at >= ?")
            params.append(date_from)
            conditions.append("s.created_at <= ?")
            params.append(date_to + " 23:59:59")
        where_clause = " AND ".join(conditions) if conditions else "1=1"

        usage_rows = conn.execute(
            f"""
            SELECT st.tool_usage_breakdown
            FROM session_stats st
            JOIN sessions s ON s.session_id = st.session_id
            WHERE st.tool_usage_breakdown IS NOT NULL AND {where_clause}
            """,
            params,
        ).fetchall()

        totals: dict[str, int] = {}
        for row in usage_rows:
            breakdown = json.loads(row["tool_usage_breakdown"])
            for tool_name, count in breakdown.items():
                totals[tool_name] = totals.get(tool_name, 0) + (
                    count if isinstance(count, int) else count.get("calls", 0)
                    if isinstance(count, dict) else 0
                )

        top_tools = sorted(totals.keys(), key=lambda t: totals[t], reverse=True)[:top_n]

        # Get sessions with dates and tool breakdowns
        session_params = list(params)
        session_rows = conn.execute(
            f"""
            SELECT DATE(s.created_at) as day, st.tool_usage_breakdown
            FROM sessions s
            JOIN session_stats st ON s.session_id = st.session_id
            WHERE st.tool_usage_breakdown IS NOT NULL AND {where_clause}
            ORDER BY day ASC
            """,
            session_params,
        ).fetchall()

        daily: dict[str, dict[str, int]] = {}
        for row in session_rows:
            day = row["day"]
            if day not in daily:
                daily[day] = {t: 0 for t in top_tools}
            breakdown = json.loads(row["tool_usage_breakdown"])
            for tool in top_tools:
                if tool in breakdown:
                    c = breakdown[tool]
                    daily[day][tool] += c if isinstance(c, int) else (c.get("calls", 0) if isinstance(c, dict) else 0)

        result = []
        for day in sorted(daily.keys()):
            entry = {"day": day}
            for tool in top_tools:
                entry[tool] = daily[day].get(tool, 0)
            result.append(entry)

        return result
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# File Activity queries
# ---------------------------------------------------------------------------

def get_top_edited_files(limit: int = 20, date_from: str = "", date_to: str = "") -> list[dict]:
    """Return the most frequently edited files across all sessions, optionally filtered by date."""
    conn = _connect()
    try:
        conditions = []
        params: list = []
        if date_from and date_to:
            conditions.append("s.created_at >= ?")
            params.append(date_from)
            conditions.append("s.created_at <= ?")
            params.append(date_to + " 23:59:59")
        where_clause = " AND ".join(conditions) if conditions else "1=1"

        rows = conn.execute(
            f"""
            SELECT s.session_id, st.unique_files_edited, st.total_file_edits,
                   st.net_code_change, st.total_chars_added, st.total_chars_removed
            FROM sessions s
            JOIN session_stats st ON s.session_id = st.session_id
            WHERE st.unique_files_edited IS NOT NULL AND {where_clause}
            """,
            params,
        ).fetchall()

        file_stats: dict[str, dict] = {}
        for row in rows:
            try:
                files = json.loads(row["unique_files_edited"])
            except (json.JSONDecodeError, TypeError):
                continue

            for f in files:
                if f not in file_stats:
                    file_stats[f] = {
                        "file": f,
                        "sessions_touched": 0,
                        "total_sessions_with_file": 0,
                    }
                file_stats[f]["sessions_touched"] += 1

        result = sorted(file_stats.values(), key=lambda x: x["sessions_touched"], reverse=True)[:limit]
        return result
    finally:
        conn.close()


def get_code_changes_per_session(date_from: str = "", date_to: str = "") -> list[dict]:
    """Return net code changes per session, optionally filtered by date range."""
    conn = _connect()
    try:
        conditions = []
        params: list = []
        if date_from:
            conditions.append("s.created_at >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("s.created_at <= ?")
            params.append(date_to + " 23:59:59")
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        rows = conn.execute(
            f"""
            SELECT s.session_id, s.created_at,
                   st.net_code_change, st.total_chars_added,
                   st.total_chars_removed, st.total_file_edits
            FROM sessions s
            JOIN session_stats st ON s.session_id = st.session_id
            WHERE {where_clause}
            ORDER BY s.created_at ASC
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Model Comparison queries
# ---------------------------------------------------------------------------

def get_model_comparison() -> list[dict]:
    """Return per-model aggregated stats for comparison."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT
                COALESCE(s.model, 'Unknown') as model,
                COUNT(DISTINCT s.session_id) as total_sessions,
                ROUND(AVG(s.duration_ms), 0) as avg_duration_ms,
                COALESCE(AVG(st.total_events), 0) as avg_events,
                COALESCE(AVG(st.total_file_edits), 0) as avg_file_edits,
                COALESCE(AVG(st.total_tool_uses), 0) as avg_tool_uses,
                COALESCE(AVG(st.total_thinking_time_ms), 0) as avg_thinking_time_ms,
                COALESCE(SUM(st.total_file_edits), 0) as total_file_edits,
                COALESCE(SUM(st.total_chars_added), 0) as total_chars_added,
                COALESCE(SUM(st.total_chars_removed), 0) as total_chars_removed
            FROM sessions s
            LEFT JOIN session_stats st ON s.session_id = st.session_id
            GROUP BY COALESCE(s.model, 'Unknown')
            ORDER BY total_sessions DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_model_usage_over_time(days: int = 90) -> list[dict]:
    """Return session counts per model per day over the last N days."""
    conn = _connect()
    try:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        rows = conn.execute(
            """
            SELECT DATE(s.created_at) as day,
                   COALESCE(s.model, 'Unknown') as model,
                   COUNT(*) as sessions
            FROM sessions s
            WHERE s.created_at >= ?
            GROUP BY DATE(s.created_at), COALESCE(s.model, 'Unknown')
            ORDER BY day ASC
            """,
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_tool_usage_by_model() -> list[dict]:
    """Return tool usage breakdown aggregated by model."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT COALESCE(s.model, 'Unknown') as model,
                   st.tool_usage_breakdown
            FROM sessions s
            JOIN session_stats st ON s.session_id = st.session_id
            WHERE st.tool_usage_breakdown IS NOT NULL
            """
        ).fetchall()

        model_tool_totals: dict[str, dict[str, int]] = {}
        for row in rows:
            model = row["model"]
            if model not in model_tool_totals:
                model_tool_totals[model] = {}
            breakdown = json.loads(row["tool_usage_breakdown"])
            for tool_name, count in breakdown.items():
                c = count if isinstance(count, int) else (count.get("calls", 0) if isinstance(count, dict) else 0)
                model_tool_totals[model][tool_name] = model_tool_totals[model].get(tool_name, 0) + c

        result = []
        for model, tools in model_tool_totals.items():
            for tool_name, count in tools.items():
                result.append({"model": model, "tool": tool_name, "total_calls": count})
        result.sort(key=lambda x: x["total_calls"], reverse=True)
        return result
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Conversation Summaries queries
# ---------------------------------------------------------------------------

def get_conversation_narratives_list() -> list[dict]:
    """Return conversation_id + metadata for all conversations with narratives."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT cn.conversation_id, cn.generated_at, cn.word_count, cn.session_count,
                   c.created_at, c.completed_at, c.status, c.git_branch, c.composer_mode,
                   c.model, c.user_email
            FROM conversation_narratives cn
            JOIN conversations c ON cn.conversation_id = c.conversation_id
            ORDER BY cn.generated_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_conversation_structured_summaries_list() -> list[dict]:
    """Return conversation_id + metadata for all conversations with structured summaries."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT css.conversation_id, css.generated_at, css.session_count,
                   css.decisions_count, css.errors_count,
                   css.objectives, css.files_modified, css.files_created, css.files_deleted,
                   c.created_at, c.status, c.git_branch, c.composer_mode
            FROM conversation_structured_summaries css
            JOIN conversations c ON css.conversation_id = c.conversation_id
            ORDER BY css.generated_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_conversation_detail(conversation_id: str) -> dict | None:
    """Return full details for a single conversation including narrative, structured summary, sessions, and stats."""
    conn = _connect()
    try:
        # Conversation metadata
        conv = conn.execute(
            "SELECT * FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        if conv is None:
            return None

        result = dict(conv)

        # Narrative
        narr = conn.execute(
            "SELECT * FROM conversation_narratives WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        if narr:
            result["narrative"] = narr["narrative"]
            result["narrative_generated_at"] = narr["generated_at"]
            result["narrative_word_count"] = narr["word_count"]
            result["narrative_session_count"] = narr["session_count"]

        # Structured summary
        css = conn.execute(
            "SELECT * FROM conversation_structured_summaries WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        if css:
            result["structured_data"] = json.loads(css["structured_json"]) if css["structured_json"] else {}
            result["structured_generated_at"] = css["generated_at"]
            result["decisions_count"] = css["decisions_count"]
            result["errors_count"] = css["errors_count"]
            result["structured_objectives"] = json.loads(css["objectives"]) if css["objectives"] else []
            result["structured_files_modified"] = json.loads(css["files_modified"]) if css["files_modified"] else []
            result["structured_files_created"] = json.loads(css["files_created"]) if css["files_created"] else []
            result["structured_files_deleted"] = json.loads(css["files_deleted"]) if css["files_deleted"] else []

        # Member sessions
        sessions = conn.execute(
            """
            SELECT s.session_id, s.created_at, s.completed_at, s.status, s.duration_ms,
                   s.model, s.composer_mode, s.is_background_agent,
                   n.word_count as narrative_word_count,
                   st.total_events, st.total_file_edits, st.total_tool_uses,
                   st.net_code_change, st.total_chars_added, st.total_chars_removed
            FROM sessions s
            LEFT JOIN narratives n ON s.session_id = n.session_id
            LEFT JOIN session_stats st ON s.session_id = st.session_id
            WHERE s.conversation_id = ?
            ORDER BY s.created_at ASC
            """,
            (conversation_id,),
        ).fetchall()
        result["sessions"] = [dict(r) for r in sessions]
        result["session_count"] = len(result["sessions"])

        # Aggregate stats across all member sessions
        session_ids = [r["session_id"] for r in sessions]
        if session_ids:
            placeholders = ",".join("?" for _ in session_ids)
            agg = conn.execute(
                f"""
                SELECT
                    COALESCE(SUM(total_events), 0) as total_events,
                    COALESCE(SUM(total_file_edits), 0) as total_file_edits,
                    COALESCE(SUM(total_tool_uses), 0) as total_tool_uses,
                    COALESCE(SUM(total_thinking_time_ms), 0) as total_thinking_time_ms,
                    COALESCE(SUM(total_chars_added), 0) as total_chars_added,
                    COALESCE(SUM(total_chars_removed), 0) as total_chars_removed,
                    COALESCE(SUM(net_code_change), 0) as net_code_change,
                    COALESCE(SUM(total_shell_commands), 0) as total_shell_commands
                FROM session_stats
                WHERE session_id IN ({placeholders})
                """,
                session_ids,
            ).fetchone()
            if agg:
                result["agg_stats"] = dict(agg)

        # Tool stats for member sessions
        if session_ids:
            placeholders = ",".join("?" for _ in session_ids)
            tool_stats = conn.execute(
                f"""
                SELECT
                    COALESCE(SUM(total_tool_calls), 0) as total_tool_calls,
                    COALESCE(SUM(total_tool_successes), 0) as total_tool_successes,
                    COALESCE(SUM(total_tool_failures), 0) as total_tool_failures,
                    COALESCE(SUM(total_tool_errors), 0) as total_tool_errors
                FROM session_tool_stats
                WHERE session_id IN ({placeholders})
                """,
                session_ids,
            ).fetchone()
            if tool_stats:
                ts_dict = dict(tool_stats)
                total_calls = ts_dict["total_tool_calls"]
                total_failures = ts_dict["total_tool_failures"]
                ts_dict["tool_success_rate"] = (
                    round((1 - total_failures / total_calls) * 100, 1) if total_calls > 0 else 100.0
                )
                result["tool_stats"] = ts_dict

        return result
    finally:
        conn.close()


def get_conversations_explorer(
    search: str = "",
    status: str = "",
    date_from: str = "",
    date_to: str = "",
    sort_col: str = "created_at",
    sort_dir: str = "DESC",
    page: int = 1,
    page_size: int = 25,
    archetype_filter: str = "",
) -> tuple[list[dict], int]:
    """Return a paginated, filtered conversation list with total count."""
    conn = _connect()
    try:
        conditions = []
        params: list = []

        if search:
            conditions.append(
                "(c.conversation_id LIKE ? OR cn.narrative LIKE ? OR c.model LIKE ?)"
            )
            params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

        if status:
            conditions.append("c.status = ?")
            params.append(status)

        if date_from:
            conditions.append("c.created_at >= ?")
            params.append(date_from)

        if date_to:
            conditions.append("c.created_at <= ?")
            params.append(date_to + " 23:59:59")

        if archetype_filter:
            conditions.append("css.dominant_archetype = ?")
            params.append(archetype_filter)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # Total count
        count_row = conn.execute(
            f"""
            SELECT COUNT(*) as cnt
            FROM conversations c
            LEFT JOIN conversation_narratives cn ON c.conversation_id = cn.conversation_id
            LEFT JOIN conversation_structured_summaries css ON c.conversation_id = css.conversation_id
            WHERE {where_clause}
            """,
            params,
        ).fetchone()
        total = count_row["cnt"]

        # Paginated data
        valid_sort_cols = {
            "conversation_id", "created_at", "status", "session_count",
            "word_count", "model", "git_branch", "dominant_archetype",
            "avg_sentiment", "avg_arc_slope", "frustration_count",
        }
        if sort_col not in valid_sort_cols:
            sort_col = "created_at"
        if sort_dir not in ("ASC", "DESC"):
            sort_dir = "DESC"

        offset = (page - 1) * page_size

        rows = conn.execute(
            f"""
            SELECT c.conversation_id, c.created_at, c.completed_at, c.status,
                   c.git_branch, c.composer_mode, c.model,
                   cn.word_count, cn.session_count, cn.generated_at as narrative_generated_at,
                   css.decisions_count, css.errors_count,
                   css.dominant_archetype, css.avg_arc_slope, css.avg_sentiment, css.frustration_count
            FROM conversations c
            LEFT JOIN conversation_narratives cn ON c.conversation_id = cn.conversation_id
            LEFT JOIN conversation_structured_summaries css ON c.conversation_id = css.conversation_id
            WHERE {where_clause}
            ORDER BY c.{sort_col} {sort_dir}
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()

        return [dict(r) for r in rows], total
    finally:
        conn.close()


def get_conversation_kpi_stats() -> dict:
    """Return top-level KPI numbers for conversations."""
    conn = _connect()
    try:
        total_conversations = conn.execute(
            "SELECT COUNT(*) as cnt FROM conversations"
        ).fetchone()["cnt"]

        total_sessions = conn.execute(
            "SELECT COUNT(*) as cnt FROM sessions WHERE conversation_id IS NOT NULL"
        ).fetchone()["cnt"]

        total_narratives = conn.execute(
            "SELECT COUNT(*) as cnt FROM conversation_narratives"
        ).fetchone()["cnt"]

        total_structured = conn.execute(
            "SELECT COUNT(*) as cnt FROM conversation_structured_summaries"
        ).fetchone()["cnt"]

        avg_sessions_per_conv = conn.execute(
            """
            SELECT COALESCE(AVG(session_count), 0) as a
            FROM conversation_narratives
            WHERE session_count > 0
            """
        ).fetchone()["a"]

        total_conversation_events = conn.execute(
            """
            SELECT COALESCE(SUM(total_events), 0) as s
            FROM session_stats ss
            JOIN sessions s ON s.session_id = ss.session_id
            WHERE s.conversation_id IS NOT NULL
            """
        ).fetchone()["s"]

        return {
            "total_conversations": total_conversations,
            "total_sessions_in_conversations": total_sessions,
            "total_narratives": total_narratives,
            "total_structured_summaries": total_structured,
            "avg_sessions_per_conversation": round(avg_sessions_per_conv, 1),
            "total_conversation_events": total_conversation_events,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Error Tracking queries
# ---------------------------------------------------------------------------

def get_error_summary() -> dict:
    """Return top-level error/failure KPIs."""
    conn = _connect()
    try:
        total_tool_stats = conn.execute(
            """
            SELECT COALESCE(SUM(total_tool_calls), 0) as total_calls,
                   COALESCE(SUM(total_tool_failures), 0) as total_failures,
                   COALESCE(SUM(total_tool_errors), 0) as total_errors
            FROM session_tool_stats
            """
        ).fetchone()

        failed_sessions = conn.execute(
            "SELECT COUNT(*) as cnt FROM sessions WHERE status = 'failed'"
        ).fetchone()

        return {
            "total_tool_calls": total_tool_stats["total_calls"],
            "total_tool_failures": total_tool_stats["total_failures"],
            "total_tool_errors": total_tool_stats["total_errors"],
            "failed_sessions": failed_sessions["cnt"],
        }
    finally:
        conn.close()


def get_top_failing_tools(n: int = 10) -> list[dict]:
    """Return the top N tools with the most failures."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT tool_failure_breakdown FROM session_tool_stats WHERE tool_failure_breakdown IS NOT NULL"
        ).fetchall()

        totals: dict[str, int] = {}
        for row in rows:
            breakdown = json.loads(row["tool_failure_breakdown"])
            for tool_name, count in breakdown.items():
                c = count if isinstance(count, int) else 0
                totals[tool_name] = totals.get(tool_name, 0) + c

        sorted_tools = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:n]
        return [{"tool": name, "failures": count} for name, count in sorted_tools]
    finally:
        conn.close()


def get_errors_time_series(days: int = 30) -> list[dict]:
    """Return failure/error counts per day over the last N days."""
    conn = _connect()
    try:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        rows = conn.execute(
            """
            SELECT DATE(s.created_at) as day,
                   COALESCE(SUM(sts.total_tool_failures), 0) as failures,
                   COALESCE(SUM(sts.total_tool_errors), 0) as errors
            FROM sessions s
            LEFT JOIN session_tool_stats sts ON s.session_id = sts.session_id
            WHERE s.created_at >= ?
            GROUP BY DATE(s.created_at)
            ORDER BY day ASC
            """,
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_recent_failed_sessions(limit: int = 20) -> list[dict]:
    """Return the most recent sessions with failures or errors."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT s.session_id, s.created_at, s.model, s.status, s.duration_ms,
                   st.total_tool_failures, st.total_tool_errors,
                   st.tool_failure_breakdown
            FROM sessions s
            LEFT JOIN session_stats st ON s.session_id = st.session_id
            WHERE (st.total_tool_failures > 0 OR st.total_tool_errors > 0 OR s.status = 'failed')
            ORDER BY s.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("tool_failure_breakdown"):
                try:
                    d["failure_breakdown"] = json.loads(d["tool_failure_breakdown"])
                except (json.JSONDecodeError, TypeError):
                    d["failure_breakdown"] = {}
            else:
                d["failure_breakdown"] = {}
            result.append(d)
        return result
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Sentiment Arc queries
# ---------------------------------------------------------------------------


def get_arc_kpi_stats() -> dict:
    """Return top-level KPI numbers for the Sentiment Arcs page.

    Edge case: returns all zeros/empty if table is empty.
    """
    conn = _connect()
    try:
        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM session_arc_features"
        ).fetchone()["cnt"]

        smooth = conn.execute(
            """SELECT COUNT(*) as cnt FROM session_arc_features
               WHERE archetype IN ('smooth_convergence', 'rapid_resolution')"""
        ).fetchone()["cnt"]

        frustrating = conn.execute(
            """SELECT COUNT(*) as cnt FROM session_arc_features
               WHERE archetype IN ('escalating_frustration', 'mismatched_effort', 'looping', 'abandoned')"""
        ).fetchone()["cnt"]

        avg_slope_row = conn.execute(
            "SELECT AVG(arc_slope) as a FROM session_arc_features WHERE arc_slope IS NOT NULL"
        ).fetchone()
        avg_slope = avg_slope_row["a"] if avg_slope_row["a"] is not None else 0.0

        top_archetype_row = conn.execute(
            """SELECT archetype, COUNT(*) as cnt FROM session_arc_features
               GROUP BY archetype ORDER BY cnt DESC LIMIT 1"""
        ).fetchone()
        top_archetype = top_archetype_row["archetype"] if top_archetype_row else ""

        mismatched = conn.execute(
            """SELECT COUNT(*) as cnt FROM session_arc_features
               WHERE mismatched_effort_signal = 1"""
        ).fetchone()["cnt"]

        return {
            "total_analyzed": total,
            "smooth_count": smooth,
            "smooth_pct": round(smooth / total * 100, 1) if total > 0 else 0,
            "frustrating_count": frustrating,
            "frustrating_pct": round(frustrating / total * 100, 1) if total > 0 else 0,
            "avg_arc_slope": round(avg_slope, 4),
            "top_archetype": top_archetype,
            "mismatched_effort_count": mismatched,
        }
    finally:
        conn.close()


def get_archetype_distribution() -> list[dict]:
    """Return archetype counts sorted by count descending."""
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT archetype, COUNT(*) as count FROM session_arc_features
               GROUP BY archetype ORDER BY count DESC"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_arc_time_series(date_from: str = "", date_to: str = "") -> list[dict]:
    """Daily archetype counts, joined with sessions.created_at for dates.

    Edge case: skips sessions not in sessions table.
    """
    conn = _connect()
    try:
        conditions = []
        params: list = []
        if date_from and date_to:
            conditions.append("s.created_at >= ?")
            params.append(date_from)
            conditions.append("s.created_at <= ?")
            params.append(date_to + " 23:59:59")
        where_clause = " AND ".join(conditions) if conditions else "1=1"

        rows = conn.execute(
            f"""
            SELECT DATE(s.created_at) as day, af.archetype, COUNT(*) as count
            FROM session_arc_features af
            JOIN sessions s ON s.session_id = af.session_id
            WHERE {where_clause}
            GROUP BY DATE(s.created_at), af.archetype
            ORDER BY day ASC
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_arc_session_list(
    search: str = "",
    archetype_filter: str = "",
    date_from: str = "",
    date_to: str = "",
    sort_col: str = "analyzed_at",
    sort_dir: str = "DESC",
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[dict], int]:
    """Paginated session list from session_arc_features + sessions join.

    sort_col validated against whitelist; defaults to analyzed_at if invalid.
    """
    conn = _connect()
    try:
        valid_sort_cols = {
            "analyzed_at", "archetype", "arc_slope", "avg_sentiment",
            "turn_count", "session_id",
        }
        if sort_col not in valid_sort_cols:
            sort_col = "analyzed_at"
        if sort_dir not in ("ASC", "DESC"):
            sort_dir = "DESC"

        conditions = []
        params: list = []

        if search:
            conditions.append("af.session_id LIKE ?")
            params.append(f"%{search}%")

        if archetype_filter:
            conditions.append("af.archetype = ?")
            params.append(archetype_filter)

        if date_from and date_to:
            conditions.append("s.created_at >= ?")
            params.append(date_from)
            conditions.append("s.created_at <= ?")
            params.append(date_to + " 23:59:59")

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # Total count
        count_row = conn.execute(
            f"""SELECT COUNT(*) as cnt
                FROM session_arc_features af
                LEFT JOIN sessions s ON s.session_id = af.session_id
                WHERE {where_clause}""",
            params,
        ).fetchone()
        total = count_row["cnt"]

        # Paginated data
        offset = (page - 1) * page_size
        rows = conn.execute(
            f"""
            SELECT af.session_id, af.archetype, af.arc_slope, af.avg_sentiment,
                   af.turn_count, af.mismatched_effort_signal, af.analyzed_at,
                   af.error_message,
                   af.task_completion_label, af.task_completion_score,
                   s.duration_ms, s.created_at as session_created
            FROM session_arc_features af
            LEFT JOIN sessions s ON s.session_id = af.session_id
            WHERE {where_clause}
            ORDER BY af.{sort_col} {sort_dir}
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()

        return [dict(r) for r in rows], total
    finally:
        conn.close()


def get_arc_session_detail(session_id: str) -> dict | None:
    """Full arc analysis for one session including smoothed_arc parsed to list.

    Returns None if session not found.
    """
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM session_arc_features WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None

        result = dict(row)

        # Parse JSON fields
        if result.get("smoothed_arc_json"):
            try:
                result["smoothed_arc"] = json.loads(result["smoothed_arc_json"])
            except (json.JSONDecodeError, TypeError):
                result["smoothed_arc"] = None

        if result.get("per_turn_sentiments_json"):
            try:
                result["per_turn_sentiments"] = json.loads(result["per_turn_sentiments_json"])
            except (json.JSONDecodeError, TypeError):
                result["per_turn_sentiments"] = None

        # Join with sessions for duration
        sess = conn.execute(
            "SELECT duration_ms, created_at, model FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if sess:
            result["duration_ms"] = sess["duration_ms"]
            result["session_created_at"] = sess["created_at"]
            result["session_model"] = sess["model"]

        return result
    finally:
        conn.close()


def get_top_frustrating_sessions(limit: int = 20) -> list[dict]:
    """Sessions with frustration archetypes, ordered by most negative arc_slope.

    Returns empty list if no frustrating sessions.
    """
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT af.session_id, af.archetype, af.arc_slope, af.avg_sentiment,
                   af.analyzed_at, s.duration_ms, s.created_at as session_created
            FROM session_arc_features af
            LEFT JOIN sessions s ON s.session_id = af.session_id
            WHERE af.archetype IN ('escalating_frustration', 'mismatched_effort', 'looping', 'abandoned')
            ORDER BY af.arc_slope ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_arc_archetype_examples(archetype: str, limit: int = 5) -> list[dict]:
    """Sample sessions of a given archetype for inspection."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT af.session_id, af.archetype, af.arc_slope, af.avg_sentiment,
                   af.turn_count, af.analyzed_at, s.created_at as session_created
            FROM session_arc_features af
            LEFT JOIN sessions s ON s.session_id = af.session_id
            WHERE af.archetype = ?
            ORDER BY af.analyzed_at DESC
            LIMIT ?
            """,
            (archetype, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_arc_error_sessions(limit: int = 20) -> list[dict]:
    """Sessions where error_message IS NOT NULL, ordered by analyzed_at DESC.

    Returns empty list if no errors.
    """
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT session_id, error_message, analyzed_at, archetype
            FROM session_arc_features
            WHERE error_message IS NOT NULL
            ORDER BY analyzed_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Task Completion queries
# ---------------------------------------------------------------------------


def get_task_completion_kpi_stats() -> dict:
    """Return task completion KPIs: counts/percentages of completed/partial/failed/abandoned."""
    conn = _connect()
    try:
        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM session_arc_features"
            " WHERE task_completion_label IS NOT NULL AND task_completion_label != 'unknown'"
        ).fetchone()["cnt"]

        if total == 0:
            return {
                "total_evaluated": 0,
                "completed": 0, "completed_pct": 0,
                "partial": 0, "partial_pct": 0,
                "failed": 0, "failed_pct": 0,
                "abandoned": 0, "abandoned_pct": 0,
                "avg_score": 0.0,
            }

        completed = conn.execute(
            "SELECT COUNT(*) as cnt FROM session_arc_features"
            " WHERE task_completion_label = 'completed'"
        ).fetchone()["cnt"]

        partial = conn.execute(
            "SELECT COUNT(*) as cnt FROM session_arc_features"
            " WHERE task_completion_label = 'partial'"
        ).fetchone()["cnt"]

        failed = conn.execute(
            "SELECT COUNT(*) as cnt FROM session_arc_features"
            " WHERE task_completion_label = 'failed'"
        ).fetchone()["cnt"]

        abandoned = conn.execute(
            "SELECT COUNT(*) as cnt FROM session_arc_features"
            " WHERE task_completion_label = 'abandoned'"
        ).fetchone()["cnt"]

        avg_row = conn.execute(
            "SELECT AVG(task_completion_score) as a FROM session_arc_features"
            " WHERE task_completion_score IS NOT NULL"
        ).fetchone()
        avg_score = avg_row["a"] if avg_row["a"] is not None else 0.0

        return {
            "total_evaluated": total,
            "completed": completed,
            "completed_pct": round(completed / total * 100, 1) if total > 0 else 0,
            "partial": partial,
            "partial_pct": round(partial / total * 100, 1) if total > 0 else 0,
            "failed": failed,
            "failed_pct": round(failed / total * 100, 1) if total > 0 else 0,
            "abandoned": abandoned,
            "abandoned_pct": round(abandoned / total * 100, 1) if total > 0 else 0,
            "avg_score": round(avg_score, 3),
        }
    finally:
        conn.close()


def get_task_completion_by_archetype() -> list[dict]:
    """Cross-tabulation: task completion label distribution by archetype.

    Returns rows like: {archetype, completed, partial, failed, abandoned, total, completion_rate}
    """
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT
                archetype,
                SUM(CASE WHEN task_completion_label = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN task_completion_label = 'partial' THEN 1 ELSE 0 END) as partial,
                SUM(CASE WHEN task_completion_label = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN task_completion_label = 'abandoned' THEN 1 ELSE 0 END) as abandoned,
                COUNT(*) as total,
                AVG(task_completion_score) as avg_score
            FROM session_arc_features
            WHERE task_completion_label IS NOT NULL AND task_completion_label != 'unknown'
            GROUP BY archetype
            ORDER BY total DESC
            """
        ).fetchall()

        result = []
        for r in rows:
            d = dict(r)
            t = d["total"]
            c = d["completed"]
            d["completion_rate"] = round(c / t * 100, 1) if t > 0 else 0
            result.append(d)

        return result
    finally:
        conn.close()


def get_failed_task_sessions(limit: int = 20) -> list[dict]:
    """Sessions with frustrating archetypes AND low task completion.

    Most actionable category: sessions where user was frustrated AND task was not completed.
    """
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT af.session_id, af.archetype, af.task_completion_label,
                   af.task_completion_score, af.task_completion_explanation,
                   af.arc_slope, af.avg_sentiment, af.analyzed_at,
                   s.duration_ms, s.created_at as session_created
            FROM session_arc_features af
            LEFT JOIN sessions s ON s.session_id = af.session_id
            WHERE af.archetype IN ('escalating_frustration', 'mismatched_effort', 'looping', 'abandoned')
              AND af.task_completion_label IN ('failed', 'abandoned')
            ORDER BY af.task_completion_score ASC, af.arc_slope ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_task_completion_session_list(
    label_filter: str = "",
    limit: int = 50,
) -> list[dict]:
    """Return sessions filtered by task completion label."""
    conn = _connect()
    try:
        conditions = ["task_completion_label IS NOT NULL", "task_completion_label != 'unknown'"]
        params: list = []
        if label_filter:
            conditions.append("task_completion_label = ?")
            params.append(label_filter)

        where_clause = " AND ".join(conditions)

        rows = conn.execute(
            f"""
            SELECT af.session_id, af.archetype, af.task_completion_label,
                   af.task_completion_score, af.task_completion_explanation,
                   af.avg_sentiment, af.arc_slope, af.analyzed_at,
                   s.created_at as session_created
            FROM session_arc_features af
            LEFT JOIN sessions s ON s.session_id = af.session_id
            WHERE {where_clause}
            ORDER BY af.task_completion_score ASC
            LIMIT ?
            """,
            [*params, limit],
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# New Sentiment Arc queries (continuous mismatched_effort + temporal features)
# ---------------------------------------------------------------------------


def get_mismatched_effort_top_sessions(limit: int = 20) -> list[dict]:
    """Sessions with highest mismatched_effort_score.

    Returns empty list if no data.
    """
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT af.session_id, af.archetype, af.mismatched_effort_score,
                   af.user_self_distance, af.model_relevance_trend,
                   af.arc_slope, af.avg_sentiment, af.analyzed_at,
                   s.duration_ms, s.created_at as session_created
            FROM session_arc_features af
            LEFT JOIN sessions s ON s.session_id = af.session_id
            WHERE af.mismatched_effort_score IS NOT NULL
              AND af.mismatched_effort_score > 0
            ORDER BY af.mismatched_effort_score DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_abandoned_candidate_sessions(limit: int = 20) -> list[dict]:
    """Sessions with negative arc_slope AND positive inter_arrival_trend.

    Returns empty list if no data.
    """
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT af.session_id, af.archetype, af.arc_slope,
                   af.inter_arrival_trend, af.mean_inter_arr,
                   af.avg_sentiment, af.analyzed_at,
                   s.duration_ms, s.created_at as session_created
            FROM session_arc_features af
            LEFT JOIN sessions s ON s.session_id = af.session_id
            WHERE af.arc_slope < 0
              AND af.inter_arrival_trend IS NOT NULL
              AND af.inter_arrival_trend > 0
            ORDER BY af.inter_arrival_trend DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Shell Failure queries
# ---------------------------------------------------------------------------


def get_shell_failure_kpi() -> dict:
    """Return total shell failures across all sessions."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(total_shell_failures), 0) as total_shell_failures "
            "FROM session_stats"
        ).fetchone()
        return {"total_shell_failures": row["total_shell_failures"]}
    finally:
        conn.close()


def get_shell_failures_by_model() -> list[dict]:
    """Return shell failure rate grouped by model."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT
                COALESCE(s.model, 'Unknown') as model,
                COUNT(DISTINCT s.session_id) as total_sessions,
                COALESCE(SUM(st.total_shell_failures), 0) as total_shell_failures,
                COALESCE(SUM(st.total_shell_commands), 0) as total_shell_commands,
                CASE
                    WHEN COALESCE(SUM(st.total_shell_commands), 0) > 0
                    THEN ROUND(
                        CAST(SUM(st.total_shell_failures) AS FLOAT) /
                        SUM(st.total_shell_commands) * 100, 1
                    )
                    ELSE 0
                END as shell_failure_rate_pct
            FROM sessions s
            LEFT JOIN session_stats st ON s.session_id = st.session_id
            GROUP BY COALESCE(s.model, 'Unknown')
            ORDER BY total_shell_failures DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_shell_failures_per_session(limit: int = 20) -> list[dict]:
    """Return sessions with the most shell failures."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT s.session_id, s.created_at, s.model,
                   st.total_shell_failures, st.total_shell_commands,
                   st.total_file_edits, st.total_tool_uses
            FROM sessions s
            JOIN session_stats st ON s.session_id = st.session_id
            WHERE st.total_shell_failures > 0
            ORDER BY st.total_shell_failures DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tool Duration Comparison queries
# ---------------------------------------------------------------------------


def get_tool_duration_comparison() -> list[dict]:
    """Return per-tool avg success vs failure duration from session_tool_stats."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT tool_usage_breakdown, avg_tool_duration_ms, "
            "avg_success_duration_ms, avg_failure_duration_ms "
            "FROM session_tool_stats"
        ).fetchall()

        tool_durations: dict[str, dict] = {}
        for row in rows:
            usage = json.loads(row["tool_usage_breakdown"]) if row["tool_usage_breakdown"] else {}
            for tool_name in usage:
                if tool_name not in tool_durations:
                    tool_durations[tool_name] = {
                        "tool": tool_name,
                        "success_durations": [],
                        "failure_durations": [],
                    }
                if row["avg_success_duration_ms"]:
                    tool_durations[tool_name]["success_durations"].append(row["avg_success_duration_ms"])
                if row["avg_failure_duration_ms"]:
                    tool_durations[tool_name]["failure_durations"].append(row["avg_failure_duration_ms"])

        result = []
        for tool_name, data in tool_durations.items():
            avg_success = (
                sum(data["success_durations"]) / len(data["success_durations"])
                if data["success_durations"] else 0
            )
            avg_failure = (
                sum(data["failure_durations"]) / len(data["failure_durations"])
                if data["failure_durations"] else 0
            )
            result.append({
                "tool": tool_name,
                "avg_success_duration_ms": round(avg_success, 1),
                "avg_failure_duration_ms": round(avg_failure, 1),
                "duration_diff_ms": round(avg_failure - avg_success, 1),
            })

        result.sort(key=lambda x: abs(x["duration_diff_ms"]), reverse=True)
        return result
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Event Timeline queries
# ---------------------------------------------------------------------------


def get_recent_events(limit: int = 100, event_type_filter: str = "") -> list[dict]:
    """Return the most recent hook_events across all sessions."""
    conn = _connect()
    try:
        conditions = []
        params: list = []
        if event_type_filter:
            conditions.append("event_type = ?")
            params.append(event_type_filter)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        rows = conn.execute(
            f"""
            SELECT session_id, sequence, timestamp, event_type, model,
                   hook_event_name, generation_id, detail_json
            FROM hook_events
            WHERE {where_clause}
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            [*params, limit],
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_event_type_distribution() -> list[dict]:
    """Return event type frequency counts."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT event_type, COUNT(*) as count
            FROM hook_events
            GROUP BY event_type
            ORDER BY count DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_hourly_event_volume(hours: int = 24) -> list[dict]:
    """Return event volume per hour for the last N hours."""
    conn = _connect()
    try:
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        rows = conn.execute(
            """
            SELECT
                strftime('%Y-%m-%d %H:00', timestamp) as hour,
                COUNT(*) as count,
                event_type
            FROM hook_events
            WHERE timestamp >= ?
            GROUP BY strftime('%Y-%m-%d %H:00', timestamp), event_type
            ORDER BY hour ASC
            """,
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_event_timeline_for_session(session_id: str) -> list[dict]:
    """Return all hook_events for a specific session, ordered by sequence."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT sequence, timestamp, event_type, model,
                   hook_event_name, generation_id, detail_json
            FROM hook_events
            WHERE session_id = ?
            ORDER BY sequence ASC
            """,
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Session Structured Summaries queries
# ---------------------------------------------------------------------------


def get_session_structured_summaries_list(session_type_filter: str = "") -> list[dict]:
    """Return session-level structured summaries, optionally filtered by session_type."""
    conn = _connect()
    try:
        conditions = []
        params: list = []
        if session_type_filter:
            conditions.append("ss.session_type = ?")
            params.append(session_type_filter)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        rows = conn.execute(
            f"""
            SELECT ss.session_id, ss.generated_at, ss.session_type,
                   ss.objectives, ss.files_modified, ss.files_created, ss.files_deleted,
                   ss.decisions_count, ss.errors_count,
                   s.created_at, s.status, s.model, s.conversation_id
            FROM structured_summaries ss
            LEFT JOIN sessions s ON ss.session_id = s.session_id
            WHERE {where_clause}
            ORDER BY ss.generated_at DESC
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_session_structured_detail(session_id: str) -> dict | None:
    """Return full structured summary for a single session."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM structured_summaries WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None

        result = dict(row)
        if result.get("structured_json"):
            try:
                result["structured_data"] = json.loads(result["structured_json"])
            except (json.JSONDecodeError, TypeError):
                result["structured_data"] = {}
        for field in ["objectives", "files_modified", "files_created", "files_deleted"]:
            if result.get(field):
                try:
                    result[f"{field}_list"] = json.loads(result[field])
                except (json.JSONDecodeError, TypeError):
                    result[f"{field}_list"] = []

        return result
    finally:
        conn.close()


def get_session_type_distribution() -> list[dict]:
    """Return counts of sessions grouped by session_type."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT COALESCE(session_type, 'unknown') as session_type,
                   COUNT(*) as count
            FROM structured_summaries
            GROUP BY COALESCE(session_type, 'unknown')
            ORDER BY count DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Conversation Sentiment queries (Phase 2)
# ---------------------------------------------------------------------------


def get_conversation_sentiment_summary(conversation_id: str) -> dict | None:
    """Get aggregated sentiment data for a conversation's structured summary."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM conversation_structured_summaries WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        try:
            result["sentiment_trajectory"] = json.loads(result.get("sentiment_trajectory", "[]"))
            result["archetype_distribution"] = json.loads(result.get("archetype_distribution", "{}"))
        except (json.JSONDecodeError, TypeError):
            result["sentiment_trajectory"] = []
            result["archetype_distribution"] = {}
        return result
    finally:
        conn.close()


def get_conversation_sentiment_list(sort_col: str = "created_at", limit: int = 50) -> list[dict]:
    """List conversations with sentiment data, sorted."""
    conn = _connect()
    try:
        valid_sort_cols = {"created_at", "dominant_archetype", "avg_arc_slope", "avg_sentiment", "frustration_count", "session_count"}
        if sort_col not in valid_sort_cols:
            sort_col = "created_at"
        order_expr = "c.created_at" if sort_col == "created_at" else f"css.{sort_col}"

        rows = conn.execute(
            f"""SELECT css.conversation_id, css.dominant_archetype, css.avg_arc_slope,
                       css.avg_sentiment, css.frustration_count, css.session_count,
                       css.generated_at, c.created_at as conv_created
                FROM conversation_structured_summaries css
                LEFT JOIN conversations c ON c.conversation_id = css.conversation_id
                WHERE css.dominant_archetype != ''
                ORDER BY {order_expr} DESC
                LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_conversation_sentiment_time_series(days: int = 30) -> list[dict]:
    """Daily average sentiment metrics across conversations."""
    conn = _connect()
    try:
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        rows = conn.execute(
            """SELECT DATE(c.created_at) as day,
                      AVG(css.avg_sentiment) as avg_sentiment,
                      AVG(css.avg_arc_slope) as avg_slope,
                      COUNT(*) as conversations
               FROM conversation_structured_summaries css
               JOIN conversations c ON c.conversation_id = css.conversation_id
               WHERE c.created_at >= ?
               GROUP BY DATE(c.created_at)
               ORDER BY day ASC""",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_conversation_sentiment_kpi_stats() -> dict:
    """Return conversation-level sentiment KPIs."""
    conn = _connect()
    try:
        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM conversation_structured_summaries "
            "WHERE dominant_archetype != ''"
        ).fetchone()["cnt"]
        if total == 0:
            return {"total_with_sentiment": 0}
        # Archetype distribution
        rows = conn.execute(
            "SELECT dominant_archetype, COUNT(*) as cnt "
            "FROM conversation_structured_summaries "
            "WHERE dominant_archetype != '' "
            "GROUP BY dominant_archetype ORDER BY cnt DESC"
        ).fetchall()
        dist = {r["dominant_archetype"]: r["cnt"] for r in rows}
        avg_s = conn.execute(
            "SELECT AVG(avg_sentiment) as a FROM conversation_structured_summaries "
            "WHERE avg_sentiment IS NOT NULL"
        ).fetchone()["a"]
        return {
            "total_with_sentiment": total,
            "archetype_distribution": dist,
            "avg_sentiment": round(avg_s, 4) if avg_s is not None else 0.0,
        }
    finally:
        conn.close()
