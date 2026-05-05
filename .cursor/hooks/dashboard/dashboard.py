"""
Narratives Dashboard v2.0 — Streamlit dashboard for viewing SQLite narratives.db data.

Run:
    streamlit run dashboard.py
"""

import sys
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Add parent directory to path so db_queries is importable
sys.path.insert(0, str(Path(__file__).parent))

import db_queries  # noqa: E402

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Narratives Dashboard",
    page_icon=":bar_chart:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Helper: format milliseconds to human-readable duration
# ---------------------------------------------------------------------------

def format_duration_ms(ms: float | int | None) -> str:
    if ms is None or ms == 0:
        return "—"
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}m"
    hours = minutes / 60
    return f"{hours:.1f}h"


def format_number(n: int | float | None) -> str:
    if n is None:
        return "—"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{n:,}"


def empty_state(icon: str, message: str, action: str | None = None) -> None:
    """Render a friendly empty state with optional call-to-action."""
    st.info(f"{icon} {message}")
    if action:
        st.code(action, language="bash")


def apply_date_filter() -> tuple[str, str]:
    """Return (date_from, date_to) strings based on sidebar preset selection."""
    preset = st.session_state.get("date_preset", "Last 30 days")
    today = datetime.now().date()
    if preset == "Last 7 days":
        start = today - timedelta(days=7)
    elif preset == "Last 14 days":
        start = today - timedelta(days=14)
    elif preset == "Last 30 days":
        start = today - timedelta(days=30)
    elif preset == "Last 90 days":
        start = today - timedelta(days=90)
    elif preset == "All time":
        return "", ""
    else:  # Custom
        start = st.session_state.get("custom_date_from", today - timedelta(days=30))
        end = st.session_state.get("custom_date_to", today)
        return str(start), str(end)
    end = today
    return str(start), str(end)


# ---------------------------------------------------------------------------
# Cached query wrappers
# ---------------------------------------------------------------------------

@st.cache_data(ttl=30)
def _cached_get_kpi_stats():
    return db_queries.get_kpi_stats()


@st.cache_data(ttl=30)
def _cached_sessions_time_series(days: int, date_from: str, date_to: str):
    return db_queries.get_sessions_time_series(days=days, date_from=date_from, date_to=date_to)


@st.cache_data(ttl=30)
def _cached_tool_usage_top_n(n: int, date_from: str, date_to: str):
    return db_queries.get_tool_usage_top_n(n=n, date_from=date_from, date_to=date_to)


@st.cache_data(ttl=30)
def _cached_session_status_breakdown():
    return db_queries.get_session_status_breakdown()


@st.cache_data(ttl=30)
def _cached_recent_sessions(limit: int, date_from: str, date_to: str):
    return db_queries.get_recent_sessions(limit=limit, date_from=date_from, date_to=date_to)


@st.cache_data(ttl=30)
def _cached_sessions_explorer(search, status, model, date_from, date_to, sort_col, sort_dir, page, page_size):
    return db_queries.get_sessions_explorer(
        search=search, status=status, model=model,
        date_from=date_from, date_to=date_to,
        sort_col=sort_col, sort_dir=sort_dir, page=page, page_size=page_size,
    )


@st.cache_data(ttl=30)
def _cached_session_detail(session_id: str):
    return db_queries.get_session_detail(session_id)


@st.cache_data(ttl=30)
def _cached_all_narratives_list():
    return db_queries.get_all_narratives_list()


@st.cache_data(ttl=30)
def _cached_tool_frequency_table():
    return db_queries.get_tool_frequency_table()


@st.cache_data(ttl=30)
def _cached_tool_time_series(top_n: int, date_from: str, date_to: str):
    return db_queries.get_tool_time_series(top_n=top_n, date_from=date_from, date_to=date_to)


@st.cache_data(ttl=30)
def _cached_top_edited_files(limit: int, date_from: str, date_to: str):
    return db_queries.get_top_edited_files(limit=limit, date_from=date_from, date_to=date_to)


@st.cache_data(ttl=30)
def _cached_code_changes_per_session(date_from: str, date_to: str):
    return db_queries.get_code_changes_per_session(date_from=date_from, date_to=date_to)


@st.cache_data(ttl=30)
def _cached_model_comparison():
    return db_queries.get_model_comparison()


@st.cache_data(ttl=30)
def _cached_model_usage_over_time(days: int):
    return db_queries.get_model_usage_over_time(days=days)


@st.cache_data(ttl=30)
def _cached_tool_usage_by_model():
    return db_queries.get_tool_usage_by_model()


@st.cache_data(ttl=30)
def _cached_error_summary():
    return db_queries.get_error_summary()


@st.cache_data(ttl=30)
def _cached_top_failing_tools(n: int):
    return db_queries.get_top_failing_tools(n=n)


@st.cache_data(ttl=30)
def _cached_errors_time_series(days: int):
    return db_queries.get_errors_time_series(days=days)


@st.cache_data(ttl=30)
def _cached_recent_failed_sessions(limit: int):
    return db_queries.get_recent_failed_sessions(limit=limit)


@st.cache_data(ttl=30)
def _cached_conversation_kpi_stats():
    return db_queries.get_conversation_kpi_stats()


@st.cache_data(ttl=30)
def _cached_conversations_explorer(search, status, date_from, date_to, sort_col, sort_dir, page, page_size, archetype_filter):
    return db_queries.get_conversations_explorer(
        search=search, status=status,
        date_from=date_from, date_to=date_to,
        sort_col=sort_col, sort_dir=sort_dir, page=page, page_size=page_size,
        archetype_filter=archetype_filter,
    )


@st.cache_data(ttl=30)
def _cached_conversation_detail(conversation_id: str):
    return db_queries.get_conversation_detail(conversation_id)


@st.cache_data(ttl=30)
def _cached_conversation_narratives_list():
    return db_queries.get_conversation_narratives_list()


@st.cache_data(ttl=30)
def _cached_conversation_structured_summaries_list():
    return db_queries.get_conversation_structured_summaries_list()


@st.cache_data(ttl=30)
def _cached_shell_failure_kpi():
    return db_queries.get_shell_failure_kpi()


@st.cache_data(ttl=30)
def _cached_shell_failures_by_model():
    return db_queries.get_shell_failures_by_model()


@st.cache_data(ttl=30)
def _cached_shell_failures_per_session(limit):
    return db_queries.get_shell_failures_per_session(limit=limit)


@st.cache_data(ttl=30)
def _cached_tool_duration_comparison():
    return db_queries.get_tool_duration_comparison()


@st.cache_data(ttl=30)
def _cached_recent_events(limit, event_type_filter):
    return db_queries.get_recent_events(limit=limit, event_type_filter=event_type_filter)


@st.cache_data(ttl=30)
def _cached_event_type_distribution():
    return db_queries.get_event_type_distribution()


@st.cache_data(ttl=30)
def _cached_hourly_event_volume(hours):
    return db_queries.get_hourly_event_volume(hours=hours)


@st.cache_data(ttl=30)
def _cached_session_structured_summaries(session_type_filter):
    return db_queries.get_session_structured_summaries_list(session_type_filter=session_type_filter)


@st.cache_data(ttl=30)
def _cached_session_structured_detail(session_id):
    return db_queries.get_session_structured_detail(session_id)


@st.cache_data(ttl=30)
def _cached_session_type_distribution():
    return db_queries.get_session_type_distribution()


@st.cache_data(ttl=60)
def _cached_arc_archetype_examples(archetype, limit):
    return db_queries.get_arc_archetype_examples(archetype=archetype, limit=limit)


@st.cache_data(ttl=60)
def _cached_mismatched_effort_top_sessions(limit):
    return db_queries.get_mismatched_effort_top_sessions(limit=limit)


@st.cache_data(ttl=60)
def _cached_abandoned_candidate_sessions(limit):
    return db_queries.get_abandoned_candidate_sessions(limit=limit)


@st.cache_data(ttl=60)
def _cached_task_completion_session_list(label_filter, limit):
    return db_queries.get_task_completion_session_list(label_filter=label_filter, limit=limit)


# ---------------------------------------------------------------------------
# Sentiment Arcs cached query wrappers
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60)
def _cached_arc_kpi_stats():
    return db_queries.get_arc_kpi_stats()


@st.cache_data(ttl=60)
def _cached_archetype_distribution():
    return db_queries.get_archetype_distribution()


@st.cache_data(ttl=60)
def _cached_arc_time_series(date_from, date_to):
    return db_queries.get_arc_time_series(date_from=date_from, date_to=date_to)


@st.cache_data(ttl=30)
def _cached_arc_session_list(search, archetype_filter, date_from, date_to, sort_col, sort_dir, page, page_size):
    return db_queries.get_arc_session_list(
        search=search, archetype_filter=archetype_filter,
        date_from=date_from, date_to=date_to,
        sort_col=sort_col, sort_dir=sort_dir, page=page, page_size=page_size,
    )


@st.cache_data(ttl=30)
def _cached_arc_session_detail(session_id):
    return db_queries.get_arc_session_detail(session_id)


@st.cache_data(ttl=60)
def _cached_top_frustrating_sessions(limit):
    return db_queries.get_top_frustrating_sessions(limit=limit)


@st.cache_data(ttl=60)
def _cached_arc_error_sessions(limit):
    return db_queries.get_arc_error_sessions(limit=limit)


@st.cache_data(ttl=60)
def _cached_task_completion_kpi():
    return db_queries.get_task_completion_kpi_stats()


@st.cache_data(ttl=60)
def _cached_task_completion_by_archetype():
    return db_queries.get_task_completion_by_archetype()


@st.cache_data(ttl=60)
def _cached_failed_task_sessions(limit):
    return db_queries.get_failed_task_sessions(limit=limit)


# ---------------------------------------------------------------------------
# CSV export helper
# ---------------------------------------------------------------------------

def download_csv(data: list[dict], filename: str, label: str = "Download CSV"):
    """Render a download button for a list-of-dicts as CSV."""
    if not data:
        return
    df = pd.DataFrame(data)
    csv = df.to_csv(index=False)
    st.download_button(label=label, data=csv, file_name=filename, mime="text/csv")


# ---------------------------------------------------------------------------
# Try connecting to DB — show error state if unavailable
# ---------------------------------------------------------------------------

def check_db_accessible() -> bool:
    try:
        _cached_get_kpi_stats()
        return True
    except Exception as e:
        st.error(f"Cannot connect to narratives.db: {e}")
        st.info("Make sure the database exists. Run `python narratives_db.py --backfill` to populate it.")
        return False


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

# Initialize page selection state
if "selected_page" not in st.session_state:
    st.session_state.selected_page = "Overview"

st.sidebar.title("Navigation")
page = st.sidebar.radio(
    "Select page",
    ["Overview", "Session Explorer", "Narrative Viewer", "Conversation Summaries", "Tool Analytics", "File Activity", "Model Comparison", "Error Tracking", "Event Timeline", "Sentiment Arcs"],
    label_visibility="collapsed",
    key="selected_page",
)

st.sidebar.markdown("---")

# Date range filter
st.sidebar.subheader("Date Range")
date_presets = ["Last 7 days", "Last 14 days", "Last 30 days", "Last 90 days", "All time", "Custom"]
date_preset = st.sidebar.radio(
    "Preset", date_presets,
    index=2,  # Default: Last 30 days
    horizontal=True,
    key="date_preset",
)
custom_col1, custom_col2 = st.sidebar.columns(2)
with custom_col1:
    st.date_input("From", value=datetime.now().date() - timedelta(days=30), key="custom_date_from", disabled=date_preset != "Custom")
with custom_col2:
    st.date_input("To", value=datetime.now().date(), key="custom_date_to", disabled=date_preset != "Custom")

date_from, date_to = apply_date_filter()

st.sidebar.markdown("---")

# Data controls
st.sidebar.subheader("Data Controls")
if st.sidebar.button("Refresh Cache", width="stretch"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.markdown("---")

# Info footer
kpis_quick = _cached_get_kpi_stats()
st.sidebar.caption(f"**Sessions:** {format_number(kpis_quick['total_sessions'])}")
st.sidebar.caption(f"**Schema:** v7")
st.sidebar.caption(f"**Dashboard v2.0**")
st.sidebar.caption("Data source: `state/narratives.db`")

# ---------------------------------------------------------------------------
# Page 1: Overview
# ---------------------------------------------------------------------------

if page == "Overview":
    st.title("Overview")

    if not check_db_accessible():
        st.stop()

    with st.spinner("Loading dashboard data..."):
        kpis = _cached_get_kpi_stats()
        shell_kpis = _cached_shell_failure_kpi()
        ts_data = _cached_sessions_time_series(days=30, date_from=date_from, date_to=date_to)
        tools = _cached_tool_usage_top_n(n=10, date_from=date_from, date_to=date_to)
        status_data = _cached_session_status_breakdown()
        recent = _cached_recent_sessions(limit=20, date_from=date_from, date_to=date_to)

    col1, col2, col3, col4, col5, col6, col7 = st.columns(7)
    col1.metric("Sessions", format_number(kpis["total_sessions"]))
    col2.metric("Narratives", format_number(kpis["total_narratives"]))
    col3.metric("Total Events", format_number(kpis["total_events"]))
    col4.metric("Avg Duration", format_duration_ms(kpis["avg_duration_ms"]))
    col5.metric("Tool Calls", format_number(kpis["total_tool_calls"]))
    col6.metric("File Edits", format_number(kpis["total_file_edits"]))
    col7.metric("Shell Failures", format_number(shell_kpis["total_shell_failures"]))

    st.markdown("---")

    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Sessions per Day (Last 30 Days)")
        if ts_data:
            fig = px.line(
                ts_data, x="day", y="count",
                markers=True, labels={"day": "Date", "count": "Sessions"},
            )
            fig.update_layout(height=300, margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig, width="stretch")
        else:
            empty_state(":chart_with_downwards_trend:", "No session data in the selected date range.")

    with col_right:
        st.subheader("Top 10 Tools")
        if tools:
            fig = px.bar(
                tools, x="count", y="tool", orientation="h",
                labels={"count": "Uses", "tool": "Tool"},
            )
            fig.update_layout(height=300, margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig, width="stretch")
        else:
            empty_state(":wrench:", "No tool usage data available.")

    st.markdown("---")

    col_pie, col_table = st.columns([1, 2])

    with col_pie:
        st.subheader("Session Status")
        if status_data:
            fig = px.pie(
                status_data, values="count", names="status",
                labels={"count": "Sessions", "status": "Status"},
            )
            fig.update_layout(height=300, margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig, width="stretch")
        else:
            empty_state(":pie_chart:", "No status data available.")

    with col_table:
        st.subheader("Recent Sessions")
        if recent:
            display = []
            for r in recent:
                display.append({
                    "Session ID": r["session_id"][:16] + "...",
                    "Created": r["created_at"][:19] if r["created_at"] else "—",
                    "Status": r["status"],
                    "Model": r.get("model") or "—",
                    "Duration": format_duration_ms(r.get("duration_ms")),
                    "Events": r.get("total_events") or 0,
                })
            df_recent = pd.DataFrame(display)
            event = st.dataframe(
                df_recent, width="stretch", hide_index=True,
                on_select="rerun", selection_mode="single-row",
                key="overview_recent_table",
            )
            download_csv(display, "recent_sessions.csv", "Download Sessions CSV")

            # Click-to-drill: show detail for selected row
            if event.selection and event.selection.rows:
                idx = event.selection.rows[0]
                selected_session = recent[idx]
                with st.expander(f"Session Detail: {selected_session['session_id'][:20]}...", expanded=True):
                    detail = _cached_session_detail(selected_session["session_id"])
                    if detail:
                        col_a, col_b = st.columns(2)
                        with col_a:
                            st.json({
                                "session_id": detail["session_id"],
                                "created_at": detail.get("created_at"),
                                "completed_at": detail.get("completed_at"),
                                "status": detail.get("status"),
                                "duration_ms": format_duration_ms(detail.get("duration_ms")),
                                "model": detail.get("model"),
                                "composer_mode": detail.get("composer_mode"),
                                "git_branch": detail.get("git_branch"),
                            })
                        with col_b:
                            st.metric("Events", detail.get("total_events", 0))
                            st.metric("File Edits", detail.get("total_file_edits", 0))
                            st.metric("Tool Uses", detail.get("total_tool_uses", 0))
                            st.metric("Thinking Time", format_duration_ms(detail.get("total_thinking_time_ms")))
        else:
            empty_state(":inbox:", "No sessions found.", action="python narratives_db.py --backfill")

# ---------------------------------------------------------------------------
# Page 2: Session Explorer
# ---------------------------------------------------------------------------

elif page == "Session Explorer":
    st.title("Session Explorer")

    if not check_db_accessible():
        st.stop()

    # Initialize pagination state
    if "explorer_page" not in st.session_state:
        st.session_state.explorer_page = 1
    if "explorer_page_size" not in st.session_state:
        st.session_state.explorer_page_size = 50
    if "explorer_sort_col" not in st.session_state:
        st.session_state.explorer_sort_col = "created_at"
    if "explorer_sort_dir" not in st.session_state:
        st.session_state.explorer_sort_dir = "DESC"
    if "explorer_selected_session" not in st.session_state:
        st.session_state.explorer_selected_session = None

    # Filters
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        search_query = st.text_input("Search", placeholder="Session ID, model, or narrative text...", key="explorer_search")
    with col_f2:
        status_filter = st.selectbox("Status", ["", "completed", "unknown", "failed"], key="explorer_status")
    with col_f3:
        model_filter = st.text_input("Model", placeholder="e.g. qwen3", key="explorer_model")

    # Pagination controls
    page_size = st.select_slider(
        "Rows per page", options=[25, 50, 100], value=st.session_state.explorer_page_size, key="explorer_page_size_slider"
    )
    if page_size != st.session_state.explorer_page_size:
        st.session_state.explorer_page_size = page_size
        st.session_state.explorer_page = 1

    # Results
    sessions, total_count = _cached_sessions_explorer(
        search=search_query,
        status=status_filter,
        model=model_filter,
        date_from=date_from,
        date_to=date_to,
        sort_col=st.session_state.explorer_sort_col,
        sort_dir=st.session_state.explorer_sort_dir,
        page=st.session_state.explorer_page,
        page_size=st.session_state.explorer_page_size,
    )

    # Page info
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    start_row = (st.session_state.explorer_page - 1) * page_size + 1
    end_row = min(st.session_state.explorer_page * page_size, total_count)
    if total_count > 0:
        st.markdown(f"**Showing {start_row}–{end_row} of {total_count} sessions**")
    else:
        st.markdown("**0 sessions** found")

    # Pagination buttons
    if total_pages > 1:
        pg_col1, pg_col2, pg_col3, pg_col4 = st.columns([1, 1, 1, 4])
        with pg_col1:
            if st.button("← Prev", disabled=st.session_state.explorer_page <= 1, width="stretch", key="explorer_prev"):
                st.session_state.explorer_page -= 1
                st.rerun()
        with pg_col2:
            new_page = st.number_input(
                "Page", min_value=1, max_value=total_pages,
                value=st.session_state.explorer_page, key="explorer_page_input"
            )
            if new_page != st.session_state.explorer_page:
                st.session_state.explorer_page = new_page
                st.rerun()
        with pg_col3:
            if st.button("Next →", disabled=st.session_state.explorer_page >= total_pages, width="stretch", key="explorer_next"):
                st.session_state.explorer_page += 1
                st.rerun()

    if sessions:
        table_data = []
        for s in sessions:
            table_data.append({
                "Session ID": s["session_id"],
                "Created": s["created_at"][:19] if s["created_at"] else "—",
                "Status": s["status"],
                "Model": s.get("model") or "—",
                "Duration": format_duration_ms(s.get("duration_ms")),
                "Words": s.get("word_count") or 0,
                "Events": s.get("total_events") or 0,
                "File Edits": s.get("total_file_edits") or 0,
                "Branch": s.get("git_branch") or "—",
                "BG": "Yes" if s.get("is_background_agent") else "",
            })
        df_sessions = pd.DataFrame(table_data)
        event = st.dataframe(
            df_sessions, width="stretch", hide_index=True,
            on_select="rerun", selection_mode="single-row",
            key="explorer_table",
        )
        download_csv(table_data, "sessions_export.csv", "Download CSV")

        # Session detail on row click
        if event.selection and event.selection.rows:
            idx = event.selection.rows[0]
            selected_id = sessions[idx]["session_id"]
            st.session_state.explorer_selected_session = selected_id

        if st.session_state.explorer_selected_session:
            detail = _cached_session_detail(st.session_state.explorer_selected_session)
            if detail:
                st.divider()
                st.subheader(f"Session: {st.session_state.explorer_selected_session[:30]}...")
                col_a, col_b = st.columns(2)
                with col_a:
                    st.json({
                        "session_id": detail["session_id"],
                        "created_at": detail.get("created_at"),
                        "completed_at": detail.get("completed_at"),
                        "status": detail.get("status"),
                        "end_reason": detail.get("end_reason") or "—",
                        "duration_ms": format_duration_ms(detail.get("duration_ms")),
                        "model": detail.get("model"),
                        "composer_mode": detail.get("composer_mode"),
                        "git_branch": detail.get("git_branch"),
                        "is_background_agent": detail.get("is_background_agent", False),
                    })
                with col_b:
                    st.metric("Events", detail.get("total_events", 0))
                    st.metric("File Edits", detail.get("total_file_edits", 0))
                    st.metric("Tool Uses", detail.get("total_tool_uses", 0))
                    st.metric("Thinking Time", format_duration_ms(detail.get("total_thinking_time_ms")))
    else:
        empty_state(":mag:", "No sessions match the current filters.")

# ---------------------------------------------------------------------------
# Page 3: Narrative Viewer
# ---------------------------------------------------------------------------

elif page == "Narrative Viewer":
    st.title("Narrative Viewer")

    if not check_db_accessible():
        st.stop()

    narratives = _cached_all_narratives_list()
    if not narratives:
        empty_state(":book:", "No narratives found. Run the backfill first.", action="python narratives_db.py --backfill")
        st.stop()

    # Initialize session state for navigation
    if "selected_narrative_session" not in st.session_state:
        st.session_state.selected_narrative_session = narratives[0]["session_id"]

    # Session selector
    options = {n["session_id"]: n for n in narratives}
    session_keys = list(options.keys())

    # Ensure selected session is valid
    if st.session_state.selected_narrative_session not in options:
        st.session_state.selected_narrative_session = session_keys[0]

    current_idx = session_keys.index(st.session_state.selected_narrative_session)

    session_id = st.selectbox(
        "Select Session",
        options=session_keys,
        format_func=lambda sid: f"{sid[:30]}...  |  {options[sid]['word_count']} words  |  {options[sid]['created_at'][:19]}",
        index=current_idx,
        key="narrative_selectbox",
    )
    st.session_state.selected_narrative_session = session_id

    if session_id:
        selected = options[session_id]
        detail = _cached_session_detail(session_id)

        # Sidebar metadata
        st.sidebar.subheader("Session Metadata")
        st.sidebar.markdown(f"**Status:** `{selected['status']}`")
        st.sidebar.markdown(f"**Model:** {selected['model'] or '—'}")
        st.sidebar.markdown(f"**Created:** {selected['created_at'][:19]}")
        st.sidebar.markdown(f"**Duration:** {format_duration_ms(selected['duration_ms'])}")
        if selected.get("strategy"):
            st.sidebar.markdown(f"**Strategy:** {selected['strategy']}")

        # Stats badges
        st.markdown("### Summary")
        col_b1, col_b2, col_b3, col_b4 = st.columns(4)
        col_b1.metric("Words", selected["word_count"])
        col_b2.metric("Events", detail.get("event_count_at_summary") if detail else "—")
        col_b3.metric("File Edits", detail.get("total_file_edits") if detail else "—")
        col_b4.metric("Tool Uses", detail.get("total_tool_uses") if detail else "—")

        # JSON export
        if detail:
            export_data = {
                "session_id": session_id,
                "model": selected.get("model"),
                "status": selected["status"],
                "created_at": selected["created_at"],
                "duration_ms": selected["duration_ms"],
                "word_count": selected["word_count"],
                "events": detail.get("total_events", 0),
                "file_edits": detail.get("total_file_edits", 0),
                "tool_uses": detail.get("total_tool_uses", 0),
                "narrative": detail.get("narrative", ""),
            }
            import json as _json
            json_str = _json.dumps(export_data, indent=2, default=str)
            st.download_button(
                label="Export as JSON",
                data=json_str,
                file_name=f"session_{session_id[:12]}.json",
                mime="application/json",
            )

        st.divider()

        # Narrative text
        st.markdown("### Narrative")
        if detail and detail.get("narrative"):
            narrative_text = detail["narrative"]
            NARRATIVE_TRUNCATE = 50_000
            if len(narrative_text) > NARRATIVE_TRUNCATE:
                show_full = st.checkbox("Show full narrative (large)")
                if show_full:
                    st.markdown(narrative_text)
                else:
                    st.markdown(narrative_text[:NARRATIVE_TRUNCATE] + "\n\n... *(truncated)*")
                    st.info(f"Narrative is {len(narrative_text):,} characters. Check the box above to show the full text.")
            else:
                st.markdown(narrative_text)
        else:
            empty_state(":memo:", "No narrative text available.")

        # Navigation — fixed: buttons now properly update selectbox
        st.divider()
        nav_cols = st.columns(2)
        with nav_cols[0]:
            if current_idx > 0:
                if st.button(":arrow_left: Previous Session", key="prev_nav", width="stretch"):
                    st.session_state.selected_narrative_session = session_keys[current_idx - 1]
                    st.rerun()
        with nav_cols[1]:
            if current_idx < len(session_keys) - 1:
                if st.button("Next Session :arrow_right:", key="next_nav", width="stretch"):
                    st.session_state.selected_narrative_session = session_keys[current_idx + 1]
                    st.rerun()

# ---------------------------------------------------------------------------
# Page 4: Conversation Summaries
# ---------------------------------------------------------------------------

elif page == "Conversation Summaries":
    st.title("Conversation Summaries")

    if not check_db_accessible():
        st.stop()

    with st.spinner("Loading conversation summaries..."):
        conv_kpis = _cached_conversation_kpi_stats()

    # KPI cards
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Conversations", format_number(conv_kpis["total_conversations"]))
    col2.metric("Sessions in Conversations", format_number(conv_kpis["total_sessions_in_conversations"]))
    col3.metric("Conversation Narratives", format_number(conv_kpis["total_narratives"]))
    col4.metric("Structured Summaries", format_number(conv_kpis["total_structured_summaries"]))
    col5.metric("Avg Sessions / Conversation", conv_kpis["avg_sessions_per_conversation"])
    col6.metric("Total Events", format_number(conv_kpis["total_conversation_events"]))

    # Sentiment KPI row
    conv_sent_kpis = db_queries.get_conversation_sentiment_kpi_stats()
    if conv_sent_kpis.get("total_with_sentiment", 0) > 0:
        st.markdown("### Sentiment Overview")
        col_s1, col_s2, col_s3 = st.columns(3)
        col_s1.metric("Conversations Analyzed", conv_sent_kpis["total_with_sentiment"])
        avg_s = conv_sent_kpis.get("avg_sentiment", 0)
        col_s2.metric("Avg Sentiment", f"{avg_s:.3f}")
        dist = conv_sent_kpis.get("archetype_distribution", {})
        top_arch = max(dist, key=dist.get) if dist else "—"
        col_s3.metric("Top Pattern", top_arch)

        # Archetype distribution bar chart
        if dist:
            arch_df = pd.DataFrame([{"Archetype": k, "Count": v} for k, v in dist.items()])
            fig_arch = px.bar(arch_df, x="Archetype", y="Count", color="Archetype")
            st.plotly_chart(fig_arch, use_container_width=True)

        st.markdown("---")

    st.markdown("---")

    # Tab switcher: Browse | Explorer
    conv_sub_tab = st.radio(
        "View mode", ["Conversation Narratives", "Structured Summaries", "Session Structured Summaries", "Conversation Explorer"],
        horizontal=True, label_visibility="collapsed", key="conv_sub_tab"
    )

    # ---- Narrative Viewer ----
    if conv_sub_tab == "Conversation Narratives":
        narratives = _cached_conversation_narratives_list()
        if not narratives:
            empty_state(":book:", "No conversation narratives found. Run conversation summarization first.")
            st.stop()

        if "selected_conv_narrative" not in st.session_state:
            st.session_state.selected_conv_narrative = narratives[0]["conversation_id"]

        options = {n["conversation_id"]: n for n in narratives}
        session_keys = list(options.keys())

        if st.session_state.selected_conv_narrative not in options:
            st.session_state.selected_conv_narrative = session_keys[0]

        current_idx = session_keys.index(st.session_state.selected_conv_narrative)

        conv_id = st.selectbox(
            "Select Conversation",
            options=session_keys,
            format_func=lambda cid: f"{cid[:30]}...  |  {options[cid]['session_count']} sessions  |  {options[cid]['word_count']} words",
            index=current_idx,
            key="conv_narrative_selectbox",
        )
        st.session_state.selected_conv_narrative = conv_id

        selected = options[conv_id]

        # Sidebar metadata
        st.sidebar.subheader("Conversation Metadata")
        st.sidebar.markdown(f"**Status:** `{selected.get('status', '—')}`")
        st.sidebar.markdown(f"**Model:** {selected.get('model') or '—'}")
        st.sidebar.markdown(f"**Created:** {selected['created_at'][:19] if selected['created_at'] else '—'}")
        if selected.get("completed_at"):
            st.sidebar.markdown(f"**Completed:** {selected['completed_at'][:19]}")
        if selected.get("git_branch"):
            st.sidebar.markdown(f"**Branch:** `{selected['git_branch']}`")
        if selected.get("user_email"):
            st.sidebar.markdown(f"**User:** {selected['user_email']}")

        # Stats badges
        st.markdown("### Summary")
        col_b1, col_b2, col_b3 = st.columns(3)
        col_b1.metric("Sessions", selected["session_count"])
        col_b2.metric("Words", selected["word_count"])
        col_b3.metric("Status", selected["status"])

        # Sentiment badges
        conv_sent = db_queries.get_conversation_sentiment_summary(conv_id)
        if conv_sent and conv_sent.get("dominant_archetype"):
            st.divider()
            st.markdown("### Sentiment Arc")
            col_s1, col_s2, col_s3 = st.columns(3)
            col_s1.metric("Dominant Pattern", conv_sent["dominant_archetype"])
            if conv_sent.get("avg_sentiment") is not None:
                col_s2.metric("Avg Sentiment", f"{conv_sent['avg_sentiment']:.3f}")
            if conv_sent.get("avg_arc_slope") is not None:
                col_s3.metric("Avg Slope", f"{conv_sent['avg_arc_slope']:.4f}")
            frust = conv_sent.get("frustration_count", 0)
            if frust > 0:
                st.warning(f"{frust} frustrating session(s) detected")

            # Sentiment trajectory sparkline
            traj = conv_sent.get("sentiment_trajectory", [])
            if len(traj) >= 2:
                traj_df = pd.DataFrame([
                    {"Session": f"#{t['session_index']+1}", "Sentiment": t.get("avg_sentiment", 0) or 0}
                    for t in traj if t.get("avg_sentiment") is not None
                ])
                fig_traj = px.line(
                    traj_df, x="Session", y="Sentiment", markers=True,
                    title="Session-by-Session Sentiment"
                )
                fig_traj.update_yaxes(range=[-1, 1])
                st.plotly_chart(fig_traj, use_container_width=True)

        st.divider()

        # Narrative text
        st.markdown("### Narrative")
        detail = _cached_conversation_detail(conv_id)
        if detail and detail.get("narrative"):
            narrative_text = detail["narrative"]
            NARRATIVE_TRUNCATE = 50_000
            if len(narrative_text) > NARRATIVE_TRUNCATE:
                show_full = st.checkbox("Show full narrative (large)", key="conv_show_full")
                if show_full:
                    st.markdown(narrative_text)
                else:
                    st.markdown(narrative_text[:NARRATIVE_TRUNCATE] + "\n\n... *(truncated)*")
                    st.info(f"Narrative is {len(narrative_text):,} characters. Check the box above to show the full text.")
            else:
                st.markdown(narrative_text)
        else:
            empty_state(":memo:", "No narrative text available.")

        # Member sessions table
        if detail and detail.get("sessions"):
            st.divider()
            st.subheader(f"Member Sessions ({len(detail['sessions'])})")
            sess_display = []
            for s in detail["sessions"]:
                sess_display.append({
                    "Session ID": s["session_id"][:20] + "..." if len(s["session_id"]) > 20 else s["session_id"],
                    "Created": s["created_at"][:19] if s["created_at"] else "—",
                    "Status": s.get("status") or "—",
                    "Model": s.get("model") or "—",
                    "Duration": format_duration_ms(s.get("duration_ms")),
                    "Events": s.get("total_events") or 0,
                    "File Edits": s.get("total_file_edits") or 0,
                })
            st.dataframe(pd.DataFrame(sess_display), width="stretch", hide_index=True)

        # Navigation
        st.divider()
        nav_cols = st.columns(2)
        with nav_cols[0]:
            if current_idx > 0:
                if st.button(":arrow_left: Previous Conversation", key="conv_prev", width="stretch"):
                    st.session_state.selected_conv_narrative = session_keys[current_idx - 1]
                    st.rerun()
        with nav_cols[1]:
            if current_idx < len(session_keys) - 1:
                if st.button("Next Conversation :arrow_right:", key="conv_next", width="stretch"):
                    st.session_state.selected_conv_narrative = session_keys[current_idx + 1]
                    st.rerun()

    # ---- Structured Summaries ----
    elif conv_sub_tab == "Structured Summaries":
        structured = _cached_conversation_structured_summaries_list()
        if not structured:
            empty_state(":clipboard:", "No conversation structured summaries found.")
            st.stop()

        if "selected_conv_structured" not in st.session_state:
            st.session_state.selected_conv_structured = structured[0]["conversation_id"]

        options_struct = {s["conversation_id"]: s for s in structured}
        struct_keys = list(options_struct.keys())

        if st.session_state.selected_conv_structured not in options_struct:
            st.session_state.selected_conv_structured = struct_keys[0]

        struct_current_idx = struct_keys.index(st.session_state.selected_conv_structured)

        struct_conv_id = st.selectbox(
            "Select Conversation (Structured)",
            options=struct_keys,
            format_func=lambda cid: f"{cid[:30]}...  |  {options_struct[cid]['session_count']} sessions  |  {options_struct[cid]['decisions_count']} decisions  |  {options_struct[cid]['errors_count']} errors",
            index=struct_current_idx,
            key="conv_structured_selectbox",
        )
        st.session_state.selected_conv_structured = struct_conv_id

        selected_struct = options_struct[struct_conv_id]

        # Stats badges
        col_b1, col_b2, col_b3, col_b4 = st.columns(4)
        col_b1.metric("Sessions", selected_struct["session_count"])
        col_b2.metric("Decisions", selected_struct["decisions_count"] or 0)
        col_b3.metric("Errors", selected_struct["errors_count"] or 0)
        col_b4.metric("Status", selected_struct.get("status") or "—")

        st.divider()

        # Objectives
        if selected_struct.get("objectives"):
            st.subheader("Objectives")
            objectives = json.loads(selected_struct["objectives"]) if isinstance(selected_struct["objectives"], str) else selected_struct["objectives"]
            for obj in objectives:
                st.markdown(f"- {obj}")

        # Files modified
        if selected_struct.get("files_modified"):
            st.subheader("Files Modified")
            files_mod = json.loads(selected_struct["files_modified"]) if isinstance(selected_struct["files_modified"], str) else selected_struct["files_modified"]
            st.code("\n".join(files_mod[:30]) + (f"\n... and {len(files_mod) - 30} more" if len(files_mod) > 30 else ""), language="text")

        # Files created
        if selected_struct.get("files_created"):
            st.subheader("Files Created")
            files_cre = json.loads(selected_struct["files_created"]) if isinstance(selected_struct["files_created"], str) else selected_struct["files_created"]
            st.code("\n".join(files_cre[:30]) + (f"\n... and {len(files_cre) - 30} more" if len(files_cre) > 30 else ""), language="text")

        # Files deleted
        if selected_struct.get("files_deleted"):
            st.subheader("Files Deleted")
            files_del = json.loads(selected_struct["files_deleted"]) if isinstance(selected_struct["files_deleted"], str) else selected_struct["files_deleted"]
            st.code("\n".join(files_del[:30]) + (f"\n... and {len(files_del) - 30} more" if len(files_del) > 30 else ""), language="text")

        # Full structured summary
        detail_struct = _cached_conversation_detail(struct_conv_id)
        if detail_struct and detail_struct.get("structured_data"):
            st.divider()
            st.subheader("Full Structured Summary")
            st.json(detail_struct["structured_data"])

    # ---- Session Structured Summaries ----
    elif conv_sub_tab == "Session Structured Summaries":
        structured_summaries = _cached_session_structured_summaries(session_type_filter="")
        if not structured_summaries:
            empty_state(":clipboard:", "No session structured summaries found.")
            st.stop()

        st.markdown("---")
        session_types = ["All"] + sorted(set(s.get("session_type") or "unknown" for s in structured_summaries))
        selected_type = st.selectbox("Filter by session type", session_types, key="session_structured_type_filter")
        type_filter = "" if selected_type == "All" else selected_type
        if type_filter:
            structured_summaries = _cached_session_structured_summaries(session_type_filter=type_filter)

        ss_table_data = []
        for ss in structured_summaries:
            ss_table_data.append({
                "Session ID": ss["session_id"][:20] + "..." if ss["session_id"] and len(ss["session_id"]) > 20 else (ss["session_id"] or "—"),
                "Type": ss.get("session_type") or "—",
                "Objectives": len(json.loads(ss["objectives"])) if ss.get("objectives") else 0,
                "Files Modified": len(json.loads(ss["files_modified"])) if ss.get("files_modified") else 0,
                "Files Created": len(json.loads(ss["files_created"])) if ss.get("files_created") else 0,
                "Files Deleted": len(json.loads(ss["files_deleted"])) if ss.get("files_deleted") else 0,
                "Decisions": ss.get("decisions_count") or 0,
                "Errors": ss.get("errors_count") or 0,
                "Status": ss.get("status") or "—",
                "Created": ss["created_at"][:19] if ss.get("created_at") else "—",
            })
        st.dataframe(pd.DataFrame(ss_table_data), width="stretch", hide_index=True)
        download_csv(ss_table_data, "session_structured_summaries.csv", "Download Session Structured CSV")

        st.divider()
        ss_detail = st.selectbox(
            "View Session Detail",
            options=[s["session_id"] for s in structured_summaries],
            format_func=lambda sid: sid[:40] + "...",
            key="session_structured_detail_select",
            label_visibility="collapsed"
        )
        if ss_detail:
            detail_ss = _cached_session_structured_detail(ss_detail)
            if detail_ss:
                st.subheader(f"Session: {ss_detail[:30]}...")
                col_det1, col_det2 = st.columns(2)
                with col_det1:
                    st.metric("Type", detail_ss.get("session_type") or "—")
                    st.metric("Decisions", detail_ss.get("decisions_count") or 0)
                    st.metric("Errors", detail_ss.get("errors_count") or 0)
                with col_det2:
                    st.metric("Files Modified", len(detail_ss.get("files_modified_list", [])))
                    st.metric("Files Created", len(detail_ss.get("files_created_list", [])))
                    st.metric("Files Deleted", len(detail_ss.get("files_deleted_list", [])))

                if detail_ss.get("objectives"):
                    st.markdown("**Objectives**")
                    objectives_list = detail_ss.get("objectives_list", [])
                    for obj in objectives_list:
                        st.markdown(f"- {obj}")

                if detail_ss.get("files_modified_list"):
                    st.markdown("**Files Modified**")
                    st.code("\n".join(detail_ss["files_modified_list"][:20]), language="text")

                if detail_ss.get("files_created_list"):
                    st.markdown("**Files Created**")
                    st.code("\n".join(detail_ss["files_created_list"][:20]), language="text")

                if detail_ss.get("structured_data"):
                    with st.expander("Full Structured JSON"):
                        st.json(detail_ss["structured_data"])

    # ---- Conversation Explorer ----
    elif conv_sub_tab == "Conversation Explorer":
        if "conv_explorer_page" not in st.session_state:
            st.session_state.conv_explorer_page = 1
        if "conv_explorer_page_size" not in st.session_state:
            st.session_state.conv_explorer_page_size = 25
        if "conv_explorer_sort_col" not in st.session_state:
            st.session_state.conv_explorer_sort_col = "created_at"
        if "conv_explorer_sort_dir" not in st.session_state:
            st.session_state.conv_explorer_sort_dir = "DESC"
        if "conv_explorer_selected" not in st.session_state:
            st.session_state.conv_explorer_selected = None

        # Filters
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            conv_search = st.text_input("Search", placeholder="Conversation ID, model, or narrative text...", key="conv_explorer_search")
        with col_f2:
            conv_status = st.selectbox("Status", ["", "active", "completed", "unknown"], key="conv_explorer_status")
        with col_f3:
            conv_archetype_f = st.selectbox("Sentiment", ["", "smooth_convergence", "rapid_resolution", "looping", "escalating_frustration", "mismatched_effort", "abandoned", "steady_friction", "inconclusive"], key="conv_explorer_archetype")

        page_size = st.select_slider(
            "Rows per page", options=[10, 25, 50], value=st.session_state.conv_explorer_page_size, key="conv_explorer_page_size_slider"
        )
        if page_size != st.session_state.conv_explorer_page_size:
            st.session_state.conv_explorer_page_size = page_size
            st.session_state.conv_explorer_page = 1

        sessions_conv, total_count_conv = _cached_conversations_explorer(
            search=conv_search,
            status=conv_status,
            date_from=date_from,
            date_to=date_to,
            sort_col=st.session_state.conv_explorer_sort_col,
            sort_dir=st.session_state.conv_explorer_sort_dir,
            page=st.session_state.conv_explorer_page,
            page_size=st.session_state.conv_explorer_page_size,
            archetype_filter=conv_archetype_f,
        )

        total_pages_conv = max(1, (total_count_conv + page_size - 1) // page_size)
        start_row_conv = (st.session_state.conv_explorer_page - 1) * page_size + 1
        end_row_conv = min(st.session_state.conv_explorer_page * page_size, total_count_conv)
        if total_count_conv > 0:
            st.markdown(f"**Showing {start_row_conv}–{end_row_conv} of {total_count_conv} conversations**")
        else:
            st.markdown("**0 conversations** found")

        if total_pages_conv > 1:
            pg_col1, pg_col2, pg_col3, pg_col4 = st.columns([1, 1, 1, 4])
            with pg_col1:
                if st.button("← Prev", disabled=st.session_state.conv_explorer_page <= 1, width="stretch", key="conv_explorer_prev"):
                    st.session_state.conv_explorer_page -= 1
                    st.rerun()
            with pg_col2:
                new_page_conv = st.number_input(
                    "Page", min_value=1, max_value=total_pages_conv,
                    value=st.session_state.conv_explorer_page, key="conv_explorer_page_input"
                )
                if new_page_conv != st.session_state.conv_explorer_page:
                    st.session_state.conv_explorer_page = new_page_conv
                    st.rerun()
            with pg_col3:
                if st.button("Next →", disabled=st.session_state.conv_explorer_page >= total_pages_conv, width="stretch", key="conv_explorer_next"):
                    st.session_state.conv_explorer_page += 1
                    st.rerun()

        if sessions_conv:
            conv_table_data = []
            for s in sessions_conv:
                row = {
                    "Conversation ID": s["conversation_id"][:20] + "..." if s["conversation_id"] and len(s["conversation_id"]) > 20 else (s["conversation_id"] or "—"),
                    "Created": s["created_at"][:19] if s["created_at"] else "—",
                    "Status": s.get("status") or "—",
                    "Sessions": s.get("session_count") or "—",
                    "Model": s.get("model") or "—",
                    "Words": s.get("word_count") or "—",
                    "Decisions": s.get("decisions_count") or 0,
                    "Errors": s.get("errors_count") or 0,
                }
                arch = s.get("dominant_archetype")
                if arch:
                    row["Sentiment"] = arch
                avg_s = s.get("avg_sentiment")
                if avg_s is not None:
                    row["Avg Sent"] = f"{avg_s:.3f}"
                frust = s.get("frustration_count")
                if frust and frust > 0:
                    row["Frustrating"] = frust
                conv_table_data.append(row)
            df_conv = pd.DataFrame(conv_table_data)
            conv_event = st.dataframe(
                df_conv, width="stretch", hide_index=True,
                on_select="rerun", selection_mode="single-row",
                key="conv_explorer_table",
            )
            download_csv(conv_table_data, "conversations_export.csv", "Download Conversations CSV")

            if conv_event.selection and conv_event.selection.rows:
                idx = conv_event.selection.rows[0]
                selected_conv_id = sessions_conv[idx]["conversation_id"]
                st.session_state.conv_explorer_selected = selected_conv_id

            if st.session_state.conv_explorer_selected:
                conv_detail = _cached_conversation_detail(st.session_state.conv_explorer_selected)
                if conv_detail:
                    st.divider()
                    st.subheader(f"Conversation: {st.session_state.conv_explorer_selected[:30]}...")

                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.json({
                            "conversation_id": conv_detail["conversation_id"],
                            "created_at": conv_detail.get("created_at"),
                            "completed_at": conv_detail.get("completed_at"),
                            "status": conv_detail.get("status"),
                            "model": conv_detail.get("model"),
                            "composer_mode": conv_detail.get("composer_mode"),
                            "git_branch": conv_detail.get("git_branch"),
                            "narrative_word_count": conv_detail.get("narrative_word_count"),
                        })
                    with col_b:
                        st.metric("Sessions", conv_detail.get("session_count", 0))
                        if conv_detail.get("agg_stats"):
                            st.metric("Total Events", conv_detail["agg_stats"].get("total_events", 0))
                            st.metric("File Edits", conv_detail["agg_stats"].get("total_file_edits", 0))
                            st.metric("Tool Calls", conv_detail["agg_stats"].get("total_tool_uses", 0))
                            st.metric("Thinking Time", format_duration_ms(conv_detail["agg_stats"].get("total_thinking_time_ms")))
                            st.metric("Net Code Change", format_number(conv_detail["agg_stats"].get("net_code_change", 0)))

                    # Narrative
                    if conv_detail.get("narrative"):
                        st.markdown("---")
                        st.subheader("Narrative")
                        st.markdown(conv_detail["narrative"])

                    # Member sessions
                    if conv_detail.get("sessions"):
                        st.markdown("---")
                        st.subheader(f"Member Sessions ({len(conv_detail['sessions'])})")
                        sess_display = []
                        for s in conv_detail["sessions"]:
                            sess_display.append({
                                "Session ID": s["session_id"][:20] + "..." if len(s["session_id"]) > 20 else s["session_id"],
                                "Created": s["created_at"][:19] if s["created_at"] else "—",
                                "Status": s.get("status") or "—",
                                "Model": s.get("model") or "—",
                                "Duration": format_duration_ms(s.get("duration_ms")),
                                "Events": s.get("total_events") or 0,
                                "File Edits": s.get("total_file_edits") or 0,
                            })
                        st.dataframe(pd.DataFrame(sess_display), width="stretch", hide_index=True)
        else:
            empty_state(":mag:", "No conversations match the current filters.")

# ---------------------------------------------------------------------------
# Page 5: Tool Analytics
# ---------------------------------------------------------------------------

elif page == "Tool Analytics":
    st.title("Tool Analytics")

    if not check_db_accessible():
        st.stop()

    with st.spinner("Loading tool analytics..."):
        freq_table = _cached_tool_frequency_table()
        trend_data = _cached_tool_time_series(top_n=5, date_from=date_from, date_to=date_to)

    # Tool frequency table
    st.subheader("Tool Usage Frequency")
    if freq_table:
        df_freq = pd.DataFrame(freq_table)
        st.dataframe(df_freq, width="stretch", hide_index=True)
        download_csv(freq_table, "tool_frequency.csv", "Download Tool Data CSV")
    else:
        empty_state(":wrench:", "No tool data available.")

    st.divider()

    # Top tools chart
    st.subheader("Top 15 Tools by Usage")
    top_15 = freq_table[:15] if freq_table else []
    if top_15:
        fig = px.bar(
            top_15, x="tool", y="total_calls",
            labels={"tool": "Tool", "total_calls": "Total Calls"},
            color="total_calls",
            color_continuous_scale="Blues",
        )
        fig.update_layout(height=400, margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, width="stretch")

    st.divider()

    # Tool trends over time
    st.subheader("Tool Usage Trends (Top 5 Tools)")
    if trend_data:
        fig = go.Figure()
        tools_in_data = [k for k in trend_data[0].keys() if k != "day"]
        for tool in tools_in_data:
            fig.add_trace(go.Scatter(
                x=[d["day"] for d in trend_data],
                y=[d[tool] for d in trend_data],
                mode="lines+markers",
                name=tool,
            ))
        fig.update_layout(
            xaxis_title="Date",
            yaxis_title="Tool Calls",
            height=400,
            margin=dict(l=0, r=0, t=0, b=0),
            hovermode="x unified",
        )
        st.plotly_chart(fig, width="stretch")
    else:
        empty_state(":chart_with_downwards_trend:", "No trend data in the selected range.")

    st.divider()

    # Success rate chart
    st.subheader("Tool Success Rates")
    if freq_table:
        sr_data = [t for t in freq_table if t["total_calls"] >= 5]
        if sr_data:
            fig = px.bar(
                sr_data, x="tool", y="success_rate",
                labels={"tool": "Tool", "success_rate": "Success Rate (%)"},
                color="success_rate",
                color_continuous_scale="RdYlGn",
            )
            fig.update_layout(height=350, margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig, width="stretch")
        else:
            empty_state(":bar_chart:", "Insufficient data for success rate chart (need >= 5 calls per tool).")

    st.divider()

    # Tool duration comparison (success vs failure)
    st.subheader("Tool Duration: Success vs Failure")
    dur_comparison = _cached_tool_duration_comparison()
    if dur_comparison:
        dur_df = pd.DataFrame(dur_comparison)
        # Only show tools with duration data
        dur_df = dur_df[(dur_df["avg_success_duration_ms"] > 0) | (dur_df["avg_failure_duration_ms"] > 0)]
        if not dur_df.empty:
            # Top 10 by absolute difference
            dur_df = dur_df.head(10)
            fig_dur = go.Figure()
            fig_dur.add_trace(go.Bar(
                y=dur_df["tool"], x=dur_df["avg_success_duration_ms"],
                name="Avg Success Duration", orientation="h",
                marker_color="#2ecc71",
            ))
            fig_dur.add_trace(go.Bar(
                y=dur_df["tool"], x=dur_df["avg_failure_duration_ms"],
                name="Avg Failure Duration", orientation="h",
                marker_color="#e74c3c",
            ))
            fig_dur.update_layout(
                barmode="group",
                height=max(300, len(dur_df) * 35),
                margin=dict(l=0, r=0, t=0, b=0),
                xaxis_title="Duration (ms)",
            )
            st.plotly_chart(fig_dur, width="stretch")
            dur_display = []
            for _, row in dur_df.iterrows():
                dur_display.append({
                    "Tool": row["tool"],
                    "Avg Success (ms)": row["avg_success_duration_ms"],
                    "Avg Failure (ms)": row["avg_failure_duration_ms"],
                    "Diff (ms)": row["duration_diff_ms"],
                })
            st.dataframe(pd.DataFrame(dur_display), width="stretch", hide_index=True)
        else:
            st.info("No duration breakdown data available.")
    else:
        st.info("No tool duration comparison data available.")

# ---------------------------------------------------------------------------
# Page 5: File Activity
# ---------------------------------------------------------------------------

elif page == "File Activity":
    st.title("File Activity")

    if not check_db_accessible():
        st.stop()

    with st.spinner("Loading file activity data..."):
        top_files = _cached_top_edited_files(limit=20, date_from=date_from, date_to=date_to)
        changes = _cached_code_changes_per_session(date_from=date_from, date_to=date_to)

    # Top edited files
    st.subheader("Top 20 Most-Edited Files")
    if top_files:
        df_files = pd.DataFrame(top_files)
        st.dataframe(df_files, width="stretch", hide_index=True)
        download_csv(top_files, "top_edited_files.csv", "Download File Data CSV")

        fig = px.bar(
            top_files, x="sessions_touched", y="file", orientation="h",
            labels={"file": "File", "sessions_touched": "Sessions Touched"},
            color="sessions_touched",
            color_continuous_scale="Viridis",
        )
        fig.update_layout(height=500, margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, width="stretch")
    else:
        empty_state(":file_folder:", "No file edit data available.")

    st.divider()

    # Code changes per session
    st.subheader("Code Changes per Session")
    if changes:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=[c["created_at"][:19] for c in changes],
            y=[c["total_chars_added"] for c in changes],
            mode="markers",
            name="Chars Added",
            marker=dict(color="#2ecc71", size=8),
        ))
        fig.add_trace(go.Scatter(
            x=[c["created_at"][:19] for c in changes],
            y=[c["total_chars_removed"] for c in changes],
            mode="markers",
            name="Chars Removed",
            marker=dict(color="#e74c3c", size=8),
        ))
        fig.update_layout(
            xaxis_title="Date",
            yaxis_title="Characters",
            height=350,
            margin=dict(l=0, r=0, t=0, b=0),
            hovermode="x unified",
        )
        st.plotly_chart(fig, width="stretch")

        st.markdown("---")
        st.subheader("Net Code Changes")
        fig2 = px.bar(
            changes, x="created_at", y="net_code_change",
            labels={"created_at": "Date", "net_code_change": "Net Code Change"},
            color="net_code_change",
            color_continuous_scale="RdYlGn",
        )
        fig2.update_layout(height=300, margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig2, width="stretch")

        changes_export = []
        for c in changes:
            changes_export.append({
                "session_id": c["session_id"],
                "created_at": c["created_at"],
                "chars_added": c["total_chars_added"],
                "chars_removed": c["total_chars_removed"],
                "net_change": c["net_code_change"],
                "file_edits": c["total_file_edits"],
            })
        download_csv(changes_export, "code_changes.csv", "Download Code Changes CSV")
    else:
        empty_state(":chart_with_downwards_trend:", "No code change data available.")

# ---------------------------------------------------------------------------
# Page 6: Model Comparison
# ---------------------------------------------------------------------------

elif page == "Model Comparison":
    st.title("Model Comparison")

    if not check_db_accessible():
        st.stop()

    with st.spinner("Loading model comparison data..."):
        model_stats = _cached_model_comparison()
        shell_by_model = _cached_shell_failures_by_model()
        model_over_time = _cached_model_usage_over_time(days=90)
        tool_by_model = _cached_tool_usage_by_model()

    if not model_stats:
        empty_state(":robot_face:", "No model data available. Sessions may not have model information recorded.")
        st.stop()

    # Per-model KPI table
    st.subheader("Performance by Model")
    shell_map = {s["model"]: s for s in shell_by_model}
    display_models = []
    for m in model_stats:
        shell_info = shell_map.get(m["model"], {})
        display_models.append({
            "Model": m["model"],
            "Sessions": m["total_sessions"],
            "Avg Duration": format_duration_ms(m["avg_duration_ms"]),
            "Avg Events": f'{m["avg_events"]:.0f}',
            "Avg File Edits": f'{m["avg_file_edits"]:.0f}',
            "Avg Tool Uses": f'{m["avg_tool_uses"]:.0f}',
            "Avg Thinking Time": format_duration_ms(m["avg_thinking_time_ms"]),
            "Total File Edits": m["total_file_edits"],
            "Total Chars Added": m["total_chars_added"],
            "Total Chars Removed": m["total_chars_removed"],
            "Shell Failures": shell_info.get("total_shell_failures", 0),
            "Shell Failure Rate": f"{shell_info.get('shell_failure_rate_pct', 0)}%",
        })
    df_models = pd.DataFrame(display_models)
    st.dataframe(df_models, width="stretch", hide_index=True)
    download_csv(display_models, "model_comparison.csv", "Download Model Data CSV")

    st.divider()

    # Sessions per model bar chart
    col_m1, col_m2 = st.columns(2)
    with col_m1:
        st.subheader("Sessions per Model")
        fig = px.bar(
            model_stats, x="model", y="total_sessions",
            labels={"model": "Model", "total_sessions": "Sessions"},
            color="total_sessions",
            color_continuous_scale="Blues",
        )
        fig.update_layout(height=350, margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, width="stretch")

    with col_m2:
        st.subheader("Avg Duration by Model")
        fig = px.bar(
            model_stats, x="model", y="avg_duration_ms",
            labels={"model": "Model", "avg_duration_ms": "Avg Duration (ms)"},
            color="avg_duration_ms",
            color_continuous_scale="Viridis",
        )
        fig.update_layout(height=350, margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, width="stretch")

    st.divider()

    # Model usage over time
    st.subheader("Model Usage Over Time (Last 90 Days)")
    if model_over_time:
        df_ot = pd.DataFrame(model_over_time)
        fig = px.line(
            df_ot, x="day", y="sessions", color="model",
            labels={"day": "Date", "sessions": "Sessions", "model": "Model"},
            markers=True,
        )
        fig.update_layout(height=400, margin=dict(l=0, r=0, t=0, b=0), hovermode="x unified")
        st.plotly_chart(fig, width="stretch")
    else:
        empty_state(":chart_with_downwards_trend:", "No model usage timeline data.")

    st.divider()

    # Tool usage stacked by model
    st.subheader("Tool Usage by Model")
    if tool_by_model:
        df_tbm = pd.DataFrame(tool_by_model)
        # Pivot for stacked bar
        pivot = df_tbm.pivot_table(index="model", columns="tool", values="total_calls", aggfunc="sum", fill_value=0)
        # Show only top tools to avoid massive chart
        top_tools_global = pivot.sum().sort_values(ascending=False).head(10).index.tolist()
        pivot_top = pivot[top_tools_global]

        fig = px.bar(
            pivot_top,
            x=pivot_top.index,
            y=[col for col in pivot_top.columns],
            labels={"value": "Calls", "model": "Model"},
            barmode="stack",
        )
        fig.update_layout(height=400, margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, width="stretch")
    else:
        empty_state(":wrench:", "No tool-by-model data available.")

# ---------------------------------------------------------------------------
# Page 7: Error Tracking
# ---------------------------------------------------------------------------

elif page == "Error Tracking":
    st.title("Error Tracking")

    if not check_db_accessible():
        st.stop()

    with st.spinner("Loading error data..."):
        error_summary = _cached_error_summary()
        shell_kpi = _cached_shell_failure_kpi()
        failing_tools = _cached_top_failing_tools(n=10)
        errors_ts = _cached_errors_time_series(days=30)
        failed_sessions = _cached_recent_failed_sessions(limit=20)

    # KPI cards
    error_rate = (
        round((error_summary["total_tool_failures"] / error_summary["total_tool_calls"]) * 100, 2)
        if error_summary["total_tool_calls"] > 0 else 0
    )

    kpi_col1, kpi_col2, kpi_col3, kpi_col4, kpi_col5 = st.columns(5)
    kpi_col1.metric("Tool Failures", format_number(error_summary["total_tool_failures"]))
    kpi_col2.metric("Tool Errors", format_number(error_summary["total_tool_errors"]))
    kpi_col3.metric("Shell Failures", format_number(shell_kpi["total_shell_failures"]))
    kpi_col4.metric("Failed Sessions", format_number(error_summary["failed_sessions"]))
    kpi_col5.metric("Overall Failure Rate", f"{error_rate}%")

    st.divider()

    col_e1, col_e2 = st.columns(2)

    with col_e1:
        st.subheader("Top 10 Failing Tools")
        if failing_tools:
            fig = px.bar(
                failing_tools, x="failures", y="tool", orientation="h",
                labels={"failures": "Failures", "tool": "Tool"},
                color="failures",
                color_continuous_scale="Reds",
            )
            fig.update_layout(height=350, margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig, width="stretch")
        else:
            empty_state(":white_check_mark:", "No tool failures recorded. Great job!")

    with col_e2:
        st.subheader("Failures & Errors Over Time (Last 30 Days)")
        if errors_ts:
            df_err = pd.DataFrame(errors_ts)
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df_err["day"], y=df_err["failures"],
                mode="lines+markers", name="Failures",
                line=dict(color="#e67e22"),
            ))
            fig.add_trace(go.Scatter(
                x=df_err["day"], y=df_err["errors"],
                mode="lines+markers", name="Errors",
                line=dict(color="#e74c3c"),
            ))
            fig.update_layout(
                xaxis_title="Date",
                yaxis_title="Count",
                height=350,
                margin=dict(l=0, r=0, t=0, b=0),
                hovermode="x unified",
            )
            st.plotly_chart(fig, width="stretch")
        else:
            empty_state(":chart_with_downwards_trend:", "No error timeline data.")

    st.divider()

    # Recent failed sessions table
    st.subheader("Recent Failed Sessions")
    if failed_sessions:
        fail_display = []
        for fs in failed_sessions:
            fail_display.append({
                "Session ID": fs["session_id"][:20] + "..." if len(fs["session_id"]) > 20 else fs["session_id"],
                "Created": fs["created_at"][:19] if fs["created_at"] else "—",
                "Model": fs.get("model") or "—",
                "Status": fs.get("status") or "—",
                "Tool Failures": fs.get("total_tool_failures") or 0,
                "Tool Errors": fs.get("total_tool_errors") or 0,
                "Duration": format_duration_ms(fs.get("duration_ms")),
            })
        df_fail = pd.DataFrame(fail_display)
        download_csv(fail_display, "failed_sessions.csv", "Download Failed Sessions CSV")

        # Expandable failure breakdown
        fail_event = st.dataframe(df_fail, width="stretch", hide_index=True, on_select="rerun", selection_mode="single-row", key="error_fail_table")
        if fail_event.selection and fail_event.selection.rows:
            idx = fail_event.selection.rows[0]
            selected_fail = failed_sessions[idx]
            if selected_fail.get("failure_breakdown"):
                st.expander(f"Failure Breakdown: {selected_fail['session_id'][:20]}...", expanded=True)
                st.json(selected_fail["failure_breakdown"])
    else:
        empty_state(":tada:", "No failed sessions found. All sessions completed successfully!")

# ---------------------------------------------------------------------------
# Page 8: Event Timeline
# ---------------------------------------------------------------------------

elif page == "Event Timeline":
    st.title("Event Timeline")

    if not check_db_accessible():
        st.stop()

    with st.spinner("Loading event data..."):
        event_dist = _cached_event_type_distribution()
        recent_events = _cached_recent_events(limit=200, event_type_filter="")
        hourly_volume = _cached_hourly_event_volume(hours=24)

    # Event type distribution chart
    st.subheader("Event Type Distribution")
    if event_dist:
        fig = px.bar(
            event_dist, x="count", y="event_type", orientation="h",
            labels={"count": "Events", "event_type": "Event Type"},
            color="count",
            color_continuous_scale="Viridis",
        )
        fig.update_layout(height=400, margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, width="stretch")
    else:
        empty_state(":clock1:", "No event data available. Run event backfill first.", action="python narratives_db.py --backfill-events")

    st.divider()

    # Hourly event volume
    st.subheader("Hourly Event Volume (Last 24 Hours)")
    if hourly_volume:
        fig = px.line(
            hourly_volume, x="hour", y="count", color="event_type",
            markers=True, labels={"hour": "Hour", "count": "Events", "event_type": "Event Type"},
        )
        fig.update_layout(height=350, margin=dict(l=0, r=0, t=0, b=0), hovermode="x unified")
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("No hourly volume data available.")

    st.divider()

    # Recent events table
    st.subheader("Recent Events")
    if recent_events:
        event_types_list = ["All"] + [e["event_type"] for e in event_dist] if event_dist else ["All"]
        selected_event_type = st.selectbox("Filter by Event Type", event_types_list, key="event_type_filter_select")
        event_filter = "" if selected_event_type == "All" else selected_event_type

        if event_filter:
            recent_events = _cached_recent_events(limit=200, event_type_filter=event_filter)

        event_table_data = []
        for ev in recent_events:
            detail = {}
            if ev.get("detail_json"):
                try:
                    detail = json.loads(ev["detail_json"])
                except (json.JSONDecodeError, TypeError):
                    pass
            event_table_data.append({
                "Timestamp": ev["timestamp"][:23] if ev.get("timestamp") else "\u2014",
                "Session ID": ev["session_id"][:20] + "..." if ev.get("session_id") and len(ev["session_id"]) > 20 else (ev["session_id"] or "\u2014"),
                "Event Type": ev.get("event_type") or "\u2014",
                "Hook Event": ev.get("hook_event_name") or "\u2014",
                "Model": ev.get("model") or "\u2014",
                "Detail": json.dumps(detail)[:100] if detail else "",
            })
        st.dataframe(pd.DataFrame(event_table_data), width="stretch", hide_index=True)
        download_csv(event_table_data, "recent_events.csv", "Download Events CSV")
    else:
        empty_state(":clock1:", "No recent events found.", action="python narratives_db.py --backfill-events")

    st.divider()

    # Session event timeline
    st.subheader("Session Event Timeline")
    if recent_events:
        session_ids = sorted(set(ev["session_id"] for ev in recent_events if ev.get("session_id")))
        if session_ids:
            selected_session = st.selectbox(
                "Select Session",
                options=session_ids,
                format_func=lambda sid: sid[:40] + "...",
                key="event_timeline_session_select",
            )
            if selected_session:
                timeline = _cached_event_timeline_for_session(selected_session)
                if timeline:
                    st.markdown(f"**{len(timeline)} events** for session `{selected_session[:20]}...`")
                    timeline_data = []
                    for ev in timeline:
                        detail = {}
                        if ev.get("detail_json"):
                            try:
                                detail = json.loads(ev["detail_json"])
                            except (json.JSONDecodeError, TypeError):
                                pass
                        timeline_data.append({
                            "Seq": ev.get("sequence"),
                            "Timestamp": ev["timestamp"][:23] if ev.get("timestamp") else "\u2014",
                            "Event Type": ev.get("event_type") or "\u2014",
                            "Hook Event": ev.get("hook_event_name") or "\u2014",
                            "Model": ev.get("model") or "\u2014",
                            "Generation ID": ev.get("generation_id", "")[:16] if ev.get("generation_id") else "",
                            "Detail": json.dumps(detail)[:150] if detail else "",
                        })
                    st.dataframe(pd.DataFrame(timeline_data), width="stretch", hide_index=True)
                else:
                    st.info(f"No events found for session {selected_session}.")
        else:
            st.info("No session IDs available from recent events.")
    else:
        st.info("Load recent events first to see session timeline.")

# ---------------------------------------------------------------------------
# Page 9: Sentiment Arcs
# ---------------------------------------------------------------------------

elif page == "Sentiment Arcs":
    st.title("Sentiment Arcs")

    if not check_db_accessible():
        st.stop()

    with st.spinner("Loading sentiment arc data..."):
        arc_kpis = _cached_arc_kpi_stats()
        archetypes = _cached_archetype_distribution()
        ts_data = _cached_arc_time_series(date_from=date_from, date_to=date_to)
        frustrating = _cached_top_frustrating_sessions(limit=10)
        errors = _cached_arc_error_sessions(limit=10)
        task_kpis = _cached_task_completion_kpi()
        task_by_archetype = _cached_task_completion_by_archetype()
        failed_task = _cached_failed_task_sessions(limit=10)

    # If zero analyzed sessions, show setup message
    if arc_kpis["total_analyzed"] == 0:
        st.info(":chart_with_downwards_trend: No sentiment arc data yet. Run the analysis first:")
        st.code("python .cursor/hooks/sentiment_arc/batch_runner.py", language="bash")
        st.stop()

    # --- KPI Row ---
    col1, col2, col3, col4, col5, col6, col7 = st.columns(7)
    col1.metric("Sessions Analyzed", format_number(arc_kpis["total_analyzed"]))
    col2.metric("Smooth Sessions", f"{arc_kpis['smooth_pct']}%", delta=arc_kpis["smooth_count"])
    col3.metric("Frustrating Sessions", f"{arc_kpis['frustrating_pct']}%", delta=arc_kpis["frustrating_count"])
    col4.metric("Avg Arc Slope", f"{arc_kpis['avg_arc_slope']:.4f}")
    col5.metric("Top Archetype", arc_kpis["top_archetype"] or "—")
    col6.metric("Mismatched Effort", arc_kpis["mismatched_effort_count"])
    if task_kpis["total_evaluated"] > 0:
        col7.metric("Task Completion", f"{task_kpis['completed_pct']}%", delta=task_kpis["completed"])
    else:
        col7.metric("Task Completion", "N/A", help="Run with task completion enabled to see metrics")

    st.markdown("---")

    # --- Archetype Distribution ---
    st.subheader("Archetype Distribution")
    if archetypes:
        # Color coding
        ARCHETYPE_COLORS = {
            "smooth_convergence": "#2ecc71",
            "rapid_resolution": "#27ae60",
            "steady_friction": "#f39c12",
            "inconclusive": "#95a5a6",
            "escalating_frustration": "#e74c3c",
            "mismatched_effort": "#c0392b",
            "looping": "#8e44ad",
            "abandoned": "#d35400",
            "too_short": "#bdc3c7",
            "error": "#7f8c8d",
        }
        fig = px.bar(
            archetypes, x="count", y="archetype", orientation="h",
            labels={"count": "Sessions", "archetype": "Archetype"},
            color="archetype",
            color_discrete_map=ARCHETYPE_COLORS,
        )
        fig.update_layout(height=max(300, len(archetypes) * 35), margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, width="stretch")
    else:
        empty_state(":bar_chart:", "No archetype data available.")

    st.divider()

    # --- Arc Timeline ---
    st.subheader("Archetype Timeline")
    if ts_data:
        df_ts = pd.DataFrame(ts_data)
        fig = px.area(
            df_ts, x="day", y="count", color="archetype",
            labels={"day": "Date", "count": "Sessions", "archetype": "Archetype"},
        )
        fig.update_layout(height=350, margin=dict(l=0, r=0, t=0, b=0), hovermode="x unified")
        st.plotly_chart(fig, width="stretch")
    else:
        empty_state(":chart_with_downwards_trend:", "No timeline data in selected date range.")

    st.divider()

    # --- Session Arc Explorer ---
    st.subheader("Session Arc Explorer")

    # Initialize explorer state
    if "arc_explorer_page" not in st.session_state:
        st.session_state.arc_explorer_page = 1
    if "arc_explorer_page_size" not in st.session_state:
        st.session_state.arc_explorer_page_size = 25
    if "arc_explorer_selected" not in st.session_state:
        st.session_state.arc_explorer_selected = None

    # Filters
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        arc_search = st.text_input("Search Session ID", placeholder="e.g. 67a132c8...", key="arc_search")
    with col_f2:
        all_archetypes_list = [a["archetype"] for a in archetypes] if archetypes else []
        archetype_options = ["All"] + sorted(all_archetypes_list)
        arc_archetype = st.selectbox("Archetype", archetype_options, key="arc_archetype_filter")
        archetype_filter = "" if arc_archetype == "All" else arc_archetype

    # Pagination controls
    page_size_arc = st.select_slider(
        "Rows per page", options=[25, 50, 100], value=st.session_state.arc_explorer_page_size, key="arc_page_size_slider"
    )
    if page_size_arc != st.session_state.arc_explorer_page_size:
        st.session_state.arc_explorer_page_size = page_size_arc
        st.session_state.arc_explorer_page = 1

    # Fetch data
    sort_col = st.session_state.get("arc_sort_col", "analyzed_at")
    sort_dir = st.session_state.get("arc_sort_dir", "DESC")
    arc_sessions, total_arc_count = _cached_arc_session_list(
        search=arc_search,
        archetype_filter=archetype_filter,
        date_from=date_from,
        date_to=date_to,
        sort_col=sort_col,
        sort_dir=sort_dir,
        page=st.session_state.arc_explorer_page,
        page_size=st.session_state.arc_explorer_page_size,
    )

    total_arc_pages = max(1, (total_arc_count + page_size_arc - 1) // page_size_arc)
    start_row_arc = (st.session_state.arc_explorer_page - 1) * page_size_arc + 1
    end_row_arc = min(st.session_state.arc_explorer_page * page_size_arc, total_arc_count)
    if total_arc_count > 0:
        st.markdown(f"**Showing {start_row_arc}–{end_row_arc} of {total_arc_count} sessions**")
    else:
        st.markdown("**0 sessions** found")

    # Pagination buttons
    if total_arc_pages > 1:
        pg_col1, pg_col2, pg_col3, pg_col4 = st.columns([1, 1, 1, 4])
        with pg_col1:
            if st.button("← Prev", disabled=st.session_state.arc_explorer_page <= 1, width="stretch", key="arc_prev"):
                st.session_state.arc_explorer_page -= 1
                st.rerun()
        with pg_col2:
            new_page_arc = st.number_input(
                "Page", min_value=1, max_value=total_arc_pages,
                value=st.session_state.arc_explorer_page, key="arc_page_input"
            )
            if new_page_arc != st.session_state.arc_explorer_page:
                st.session_state.arc_explorer_page = new_page_arc
                st.rerun()
        with pg_col3:
            if st.button("Next →", disabled=st.session_state.arc_explorer_page >= total_arc_pages, width="stretch", key="arc_next"):
                st.session_state.arc_explorer_page += 1
                st.rerun()

    if arc_sessions:
        COMPLETION_LABELS = {
            "completed": ("Completed", "#2ecc71"),
            "partial": ("Partial", "#f39c12"),
            "failed": ("Failed", "#e74c3c"),
            "abandoned": ("Abandoned", "#95a5a6"),
        }
        table_data = []
        for s in arc_sessions:
            tc_label = s.get("task_completion_label") or ""
            if tc_label and tc_label != "unknown":
                display, _ = COMPLETION_LABELS.get(tc_label, (tc_label, ""))
                completion_display = display
            else:
                completion_display = "—"

            table_data.append({
                "Session ID": s["session_id"][:20] + "..." if s["session_id"] and len(s["session_id"]) > 20 else (s["session_id"] or "—"),
                "Created": s["session_created"][:19] if s.get("session_created") else "—",
                "Archetype": s["archetype"],
                "Arc Slope": f'{s["arc_slope"]:.4f}' if s["arc_slope"] is not None else "—",
                "Avg Sentiment": f'{s["avg_sentiment"]:.3f}' if s["avg_sentiment"] is not None else "—",
                "Turns": s["turn_count"],
                "Mismatched": "Yes" if s.get("mismatched_effort_signal") else "No",
                "Completion": completion_display,
            })
        df_arc = pd.DataFrame(table_data)
        arc_event = st.dataframe(
            df_arc, width="stretch", hide_index=True,
            on_select="rerun", selection_mode="single-row",
            key="arc_table",
        )
        download_csv(table_data, "sentiment_arcs.csv", "Download Sentiment Arcs CSV")

        # Row click → detail
        if arc_event.selection and arc_event.selection.rows:
            idx = arc_event.selection.rows[0]
            selected_arc_id = arc_sessions[idx]["session_id"]
            st.session_state.arc_explorer_selected = selected_arc_id

        # Detail section
        if st.session_state.arc_explorer_selected:
            detail = _cached_arc_session_detail(st.session_state.arc_explorer_selected)
            if detail:
                st.divider()
                st.subheader(f"Arc: {st.session_state.arc_explorer_selected[:30]}...")

                # Error message
                if detail.get("error_message"):
                    st.warning(f"Analysis error: {detail['error_message']}")

                # Too short info
                if detail.get("archetype") == "too_short":
                    st.info("Session too short for meaningful analysis.")

                # Feature metrics
                col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                col_m1.metric("Archetype", detail.get("archetype", "—"))
                col_m2.metric("Arc Slope", f'{detail.get("arc_slope", 0):.4f}' if detail.get("arc_slope") is not None else "—")
                col_m3.metric("Avg Sentiment", f'{detail.get("avg_sentiment", 0):.3f}' if detail.get("avg_sentiment") is not None else "—")
                col_m4.metric("Recovery Events", detail.get("recovery_events", 0))

                # Arc chart
                smoothed = detail.get("smoothed_arc")
                raw = detail.get("per_turn_sentiments")
                if smoothed:
                    fig = go.Figure()
                    if raw:
                        fig.add_trace(go.Scatter(
                            y=raw, mode="markers", name="Raw Scores",
                            marker=dict(size=4, opacity=0.4, color="#7f8c8d"),
                        ))
                    fig.add_trace(go.Scatter(
                        y=smoothed, mode="lines", name="Smoothed Arc",
                        line=dict(color="#3498db", width=2),
                    ))
                    fig.add_shape(
                        type="line", x0=0, y0=0, x1=len(smoothed), y1=0,
                        line=dict(color="#e74c3c", width=1, dash="dash"),
                    )
                    fig.update_layout(
                        xaxis_title="Turn Number",
                        yaxis_title="Sentiment",
                        yaxis_range=[-1.0, 1.0],
                        height=300,
                        margin=dict(l=0, r=0, t=0, b=0),
                        hovermode="x unified",
                    )
                    st.plotly_chart(fig, width="stretch")
                else:
                    st.info("No arc chart data available for this session.")

    else:
        empty_state(":mag:", "No sessions match the current filters.")

    st.divider()

    # --- Top Frustrating Sessions ---
    with st.expander("Top Frustrating Sessions"):
        if frustrating:
            fail_display = []
            for fs in frustrating:
                fail_display.append({
                    "Session ID": fs["session_id"][:20] + "..." if fs["session_id"] and len(fs["session_id"]) > 20 else (fs["session_id"] or "—"),
                    "Archetype": fs["archetype"],
                    "Arc Slope": f'{fs["arc_slope"]:.4f}' if fs["arc_slope"] is not None else "—",
                    "Avg Sentiment": f'{fs["avg_sentiment"]:.3f}' if fs["avg_sentiment"] is not None else "—",
                    "Created": fs["session_created"][:19] if fs.get("session_created") else "—",
                    "Duration": format_duration_ms(fs.get("duration_ms")),
                })
            df_frust = pd.DataFrame(fail_display)
            st.dataframe(df_frust, width="stretch", hide_index=True)
            download_csv(fail_display, "frustrating_sessions.csv", "Download Frustrating Sessions CSV")
        else:
            st.info(":tada: No frustrating sessions detected.")

    # --- Task Completion by Archetype ---
    st.divider()
    st.subheader("Task Completion by Archetype")
    if task_kpis["total_evaluated"] > 0 and task_by_archetype:
        col_tc1, col_tc2, col_tc3, col_tc4 = st.columns(4)
        col_tc1.metric("Completed", task_kpis["completed"], f"{task_kpis['completed_pct']}%")
        col_tc2.metric("Partial", task_kpis["partial"], f"{task_kpis['partial_pct']}%")
        col_tc3.metric("Failed", task_kpis["failed"], f"{task_kpis['failed_pct']}%")
        col_tc4.metric("Abandoned", task_kpis["abandoned"], f"{task_kpis['abandoned_pct']}%")

        st.markdown("---")

        # Stacked bar chart: completion distribution by archetype
        tc_rows = []
        for row in task_by_archetype:
            tc_rows.append({
                "Archetype": row["archetype"],
                "Completed": row["completed"],
                "Partial": row["partial"],
                "Failed": row["failed"],
                "Abandoned": row["abandoned"],
                "Completion Rate": f"{row['completion_rate']}%",
            })
        tc_df = pd.DataFrame(tc_rows)

        # Create stacked bar using plotly
        fig_tc = go.Figure()
        fig_tc.add_trace(go.Bar(
            y=tc_df["Archetype"], x=tc_df["Completed"], name="Completed",
            orientation="h", marker_color="#2ecc71",
        ))
        fig_tc.add_trace(go.Bar(
            y=tc_df["Archetype"], x=tc_df["Partial"], name="Partial",
            orientation="h", marker_color="#f39c12",
        ))
        fig_tc.add_trace(go.Bar(
            y=tc_df["Archetype"], x=tc_df["Failed"], name="Failed",
            orientation="h", marker_color="#e74c3c",
        ))
        fig_tc.add_trace(go.Bar(
            y=tc_df["Archetype"], x=tc_df["Abandoned"], name="Abandoned",
            orientation="h", marker_color="#95a5a6",
        ))
        fig_tc.update_layout(
            barmode="stack",
            height=max(300, len(tc_df) * 35),
            margin=dict(l=0, r=0, t=0, b=0),
            xaxis_title="Sessions",
        )
        st.plotly_chart(fig_tc, width="stretch")

        st.markdown("---")
        st.dataframe(tc_df, width="stretch", hide_index=True)
    else:
        st.info(
            "No task completion data yet. Run with task completion enabled:\n"
            "`python .cursor/hooks/sentiment_arc/batch_runner.py`"
        )

    # --- Failed Task Sessions ---
    st.divider()
    with st.expander("Failed Tasks (Frustrating + Incomplete)", expanded=False):
        if failed_task:
            ft_display = []
            for ft in failed_task:
                ft_display.append({
                    "Session ID": ft["session_id"][:20] + "..." if ft["session_id"] and len(ft["session_id"]) > 20 else (ft["session_id"] or "—"),
                    "Archetype": ft["archetype"],
                    "Completion": ft.get("task_completion_label", "—"),
                    "Completion Score": f'{ft["task_completion_score"]:.2f}' if ft.get("task_completion_score") is not None else "—",
                    "Explanation": ft.get("task_completion_explanation", "—"),
                    "Arc Slope": f'{ft["arc_slope"]:.4f}' if ft.get("arc_slope") is not None else "—",
                    "Created": ft["session_created"][:19] if ft.get("session_created") else "—",
                })
            st.dataframe(pd.DataFrame(ft_display), width="stretch", hide_index=True)
        else:
            st.info(":tada: No frustrating sessions with failed tasks detected.")

    # --- Analysis Errors ---
    with st.expander("Analysis Errors"):
        if errors:
            err_display = []
            for e in errors:
                err_display.append({
                    "Session ID": e["session_id"][:20] + "..." if e["session_id"] and len(e["session_id"]) > 20 else (e["session_id"] or "—"),
                    "Error": e.get("error_message", "—"),
                    "Analyzed At": e["analyzed_at"][:19] if e.get("analyzed_at") else "—",
                })
            st.dataframe(pd.DataFrame(err_display), width="stretch", hide_index=True)
        else:
            st.info(":white_check_mark: No analysis errors recorded.")

    st.divider()

    # --- Advanced Analysis ---
    st.subheader("Advanced Analysis")

    # Task Completion Session Explorer
    with st.expander("Task Completion Session Explorer"):
        tc_label_filter = st.selectbox(
            "Filter by label", ["All", "completed", "partial", "failed", "abandoned"],
            key="tc_label_filter_select", label_visibility="collapsed"
        )
        label_filter = "" if tc_label_filter == "All" else tc_label_filter
        tc_sessions = _cached_task_completion_session_list(label_filter=label_filter, limit=50)
        if tc_sessions:
            tc_display = []
            for tc in tc_sessions:
                tc_display.append({
                    "Session ID": tc["session_id"][:20] + "..." if tc["session_id"] and len(tc["session_id"]) > 20 else (tc["session_id"] or "—"),
                    "Archetype": tc["archetype"],
                    "Completion": tc.get("task_completion_label", "—"),
                    "Score": f'{tc["task_completion_score"]:.2f}' if tc.get("task_completion_score") is not None else "—",
                    "Explanation": tc.get("task_completion_explanation", "—"),
                    "Created": tc["session_created"][:19] if tc.get("session_created") else "—",
                })
            st.dataframe(pd.DataFrame(tc_display), width="stretch", hide_index=True)
            download_csv(tc_display, "task_completion_sessions.csv", "Download Task Completion CSV")
        else:
            st.info("No task completion sessions found for the selected filter.")

    # Mismatched Effort Analysis
    with st.expander("Highest Mismatched Effort Sessions"):
        mismatched = _cached_mismatched_effort_top_sessions(limit=20)
        if mismatched:
            mm_display = []
            for mm in mismatched:
                mm_display.append({
                    "Session ID": mm["session_id"][:20] + "..." if mm["session_id"] and len(mm["session_id"]) > 20 else (mm["session_id"] or "—"),
                    "Archetype": mm["archetype"],
                    "Mismatch Score": f'{mm["mismatched_effort_score"]:.4f}' if mm.get("mismatched_effort_score") is not None else "—",
                    "User Self Distance": f'{mm["user_self_distance"]:.4f}' if mm.get("user_self_distance") is not None else "—",
                    "Model Relevance Trend": f'{mm["model_relevance_trend"]:.4f}' if mm.get("model_relevance_trend") is not None else "—",
                    "Arc Slope": f'{mm["arc_slope"]:.4f}' if mm.get("arc_slope") is not None else "—",
                    "Created": mm["session_created"][:19] if mm.get("session_created") else "—",
                })
            st.dataframe(pd.DataFrame(mm_display), width="stretch", hide_index=True)
            download_csv(mm_display, "mismatched_effort.csv", "Download Mismatched Effort CSV")
        else:
            st.info("No mismatched effort data available.")

    # Abandoned Candidate Sessions
    with st.expander("Abandoned Candidate Sessions"):
        abandoned = _cached_abandoned_candidate_sessions(limit=20)
        if abandoned:
            ab_display = []
            for ab in abandoned:
                ab_display.append({
                    "Session ID": ab["session_id"][:20] + "..." if ab["session_id"] and len(ab["session_id"]) > 20 else (ab["session_id"] or "—"),
                    "Archetype": ab["archetype"],
                    "Arc Slope": f'{ab["arc_slope"]:.4f}' if ab.get("arc_slope") is not None else "—",
                    "Inter-Arrival Trend": f'{ab["inter_arrival_trend"]:.4f}' if ab.get("inter_arrival_trend") is not None else "—",
                    "Mean Inter-Arrival": f'{ab["mean_inter_arr"]:.2f}' if ab.get("mean_inter_arr") is not None else "—",
                    "Avg Sentiment": f'{ab["avg_sentiment"]:.3f}' if ab.get("avg_sentiment") is not None else "—",
                    "Created": ab["session_created"][:19] if ab.get("session_created") else "—",
                })
            st.dataframe(pd.DataFrame(ab_display), width="stretch", hide_index=True)
        else:
            st.info("No abandoned candidate sessions detected.")

    # Archetype Examples Explorer
    with st.expander("Explore Archetype Samples"):
        all_archetypes_for_examples = [a["archetype"] for a in archetypes] if archetypes else []
        if all_archetypes_for_examples:
            example_archetype = st.selectbox(
                "Select archetype", sorted(all_archetypes_for_examples),
                key="archetype_examples_select"
            )
            examples = _cached_arc_archetype_examples(archetype=example_archetype, limit=5)
            if examples:
                ex_display = []
                for ex in examples:
                    ex_display.append({
                        "Session ID": ex["session_id"][:20] + "..." if ex["session_id"] and len(ex["session_id"]) > 20 else (ex["session_id"] or "—"),
                        "Arc Slope": f'{ex["arc_slope"]:.4f}' if ex.get("arc_slope") is not None else "—",
                        "Avg Sentiment": f'{ex["avg_sentiment"]:.3f}' if ex.get("avg_sentiment") is not None else "—",
                        "Turns": ex.get("turn_count", "—"),
                        "Created": ex["session_created"][:19] if ex.get("session_created") else "—",
                    })
                st.dataframe(pd.DataFrame(ex_display), width="stretch", hide_index=True)
            else:
                st.info(f"No examples found for {example_archetype}.")
        else:
            st.info("No archetypes available for exploration.")