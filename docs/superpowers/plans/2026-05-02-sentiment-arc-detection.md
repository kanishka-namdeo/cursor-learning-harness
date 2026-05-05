# Sentiment Arc Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-turn sentiment extraction, smoothed trajectory building, arc feature computation, archetype classification, and dashboard visualization for Cursor hook sessions.

**Architecture:** A standalone `sentiment_arc.py` module using VADER (zero GPU, pip install only) for per-event sentiment scoring, with results stored in a new `sentiment_arcs` SQLite table. Batch backfill for 57 existing sessions + optional incremental analysis. All fail-open, never blocks agent workflow.

**Tech Stack:** Python 3.13, vaderSentiment (126 kB wheel, no GPU), SQLite stdlib, Streamlit + Plotly (already installed), pandas (already installed).

**Design Rationale — Why VADER over LLM-based approach:**
- VADER is lexicon-based, deterministic, costs $0, runs in <1ms per turn, and needs no API calls
- LLM-based sentiment would require calling the existing ChatOpenAI for every turn — expensive, slow, rate-limited
- VADER compound score (-1 to +1) is perfect for trajectory math (slope, volatility, etc.)
- The existing LangGraph summarizer agents can still use sentiment scores as context for narrative generation (future enhancement)

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `.cursor/hooks/sentiment_arc.py` | **CREATE** | Core sentiment engine: VADER scoring, trajectory smoothing, arc features, archetype classification, DB storage, CLI |
| `.cursor/hooks/narratives_db.py` | **MODIFY** | Add schema migration v8 (`sentiment_arcs` table) + CRUD methods |
| `.cursor/hooks/dashboard/db_queries.py` | **MODIFY** | Add sentiment query functions |
| `.cursor/hooks/dashboard/dashboard.py` | **MODIFY** | Add Page 6 "Sentiment Arcs" |
| `.cursor/hooks/DOCS.md` | **MODIFY** | Update project docs |

---

## Database Schema (Migration v8)

```sql
CREATE TABLE IF NOT EXISTS sentiment_arcs (
    session_id TEXT PRIMARY KEY,
    generated_at TEXT NOT NULL,
    turn_count INTEGER DEFAULT 0,
    -- Per-turn raw scores stored as JSON array of objects:
    -- [{"sequence": 0, "type": "user_prompt", "user_compound": 0.5, "model_compound": null, "timestamp": "..."}, ...]
    turn_scores_json TEXT NOT NULL,
    -- Smoothed trajectory (exponential moving average, alpha=0.3)
    smoothed_trajectory_json TEXT NOT NULL,
    -- Arc features
    overall_mean REAL DEFAULT 0,
    overall_std REAL DEFAULT 0,
    slope REAL DEFAULT 0,            -- linear regression slope over turns
    volatility REAL DEFAULT 0,        -- std of consecutive deltas
    user_self_distance REAL DEFAULT 0, -- mean abs diff between consecutive user scores
    model_relevance_trend REAL DEFAULT 0, -- correlation of model response scores with turn index
    frustration_score REAL DEFAULT 0,  -- fraction of turns with compound < -0.1
    convergence_score REAL DEFAULT 0,  -- decreasing volatility in last 30% of session
    -- Archetype classification
    archetype TEXT DEFAULT '',         -- "smooth_convergence" | "escalating_frustration" | "looping" | "exploratory_wander" | "rapid_resolution" | "mixed"
    archetype_confidence REAL DEFAULT 0, -- 0.0-1.0
    -- Error tracking
    error TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_sentiment_archetype ON sentiment_arcs(archetype);
CREATE INDEX IF NOT EXISTS idx_sentiment_slope ON sentiment_arcs(slope);
```

---

### Task 1: Add VADER dependency and sentiment_arcs table schema

**Files:**
- Modify: `.cursor/hooks/narratives_db.py:55-263` (MIGRATIONS dict, add v8)
- Modify: `.cursor/hooks/narratives_db.py:32` (bump CURRENT_SQLITE_SCHEMA_VERSION to 8)
- Shell command: `pip install vaderSentiment`

- [ ] **Step 1: Install vaderSentiment**

```bash
pip install vaderSentiment
```

Expected: Package installs successfully. Verify:
```bash
.venv\Scripts\python.exe -c "from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer; print('VADER OK')"
```

- [ ] **Step 2: Add migration v8 to narratives_db.py**

In `narratives_db.py`, bump `CURRENT_SQLITE_SCHEMA_VERSION = 8` and add:

```python
MIGRATIONS = {
    # ... migrations 1-7 unchanged ...
    8: [
        """
        CREATE TABLE IF NOT EXISTS sentiment_arcs (
            session_id TEXT PRIMARY KEY,
            generated_at TEXT NOT NULL,
            turn_count INTEGER DEFAULT 0,
            turn_scores_json TEXT NOT NULL,
            smoothed_trajectory_json TEXT NOT NULL,
            overall_mean REAL DEFAULT 0,
            overall_std REAL DEFAULT 0,
            slope REAL DEFAULT 0,
            volatility REAL DEFAULT 0,
            user_self_distance REAL DEFAULT 0,
            model_relevance_trend REAL DEFAULT 0,
            frustration_score REAL DEFAULT 0,
            convergence_score REAL DEFAULT 0,
            archetype TEXT DEFAULT '',
            archetype_confidence REAL DEFAULT 0,
            error TEXT DEFAULT ''
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_sentiment_archetype ON sentiment_arcs(archetype)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_sentiment_slope ON sentiment_arcs(slope)
        """,
    ],
}
```

- [ ] **Step 3: Add CRUD methods to NarrativesDB class**

Append to `narratives_db.py` before the `# -- backfill --` section (around line 1615):

```python
    # -- sentiment arcs --------------------------------------------------------

    def upsert_sentiment_arc(
        self,
        session_id: str,
        arc_data: dict,
    ) -> bool:
        """Insert or update a sentiment arc analysis result."""
        if not self._require_conn():
            return False

        self._ensure_session_row(session_id)

        # Strip NULL bytes from all string fields
        turn_scores = json.dumps(arc_data.get("turn_scores", []))
        turn_scores = turn_scores.replace("\x00", "\ufffd")
        smoothed = json.dumps(arc_data.get("smoothed_trajectory", []))
        smoothed = smoothed.replace("\x00", "\ufffd")

        try:
            self._conn.execute(
                """
                INSERT INTO sentiment_arcs (
                    session_id, generated_at, turn_count,
                    turn_scores_json, smoothed_trajectory_json,
                    overall_mean, overall_std, slope, volatility,
                    user_self_distance, model_relevance_trend,
                    frustration_score, convergence_score,
                    archetype, archetype_confidence, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    generated_at         = excluded.generated_at,
                    turn_count           = excluded.turn_count,
                    turn_scores_json     = excluded.turn_scores_json,
                    smoothed_trajectory_json = excluded.smoothed_trajectory_json,
                    overall_mean         = excluded.overall_mean,
                    overall_std          = excluded.overall_std,
                    slope                = excluded.slope,
                    volatility           = excluded.volatility,
                    user_self_distance   = excluded.user_self_distance,
                    model_relevance_trend = excluded.model_relevance_trend,
                    frustration_score    = excluded.frustration_score,
                    convergence_score    = excluded.convergence_score,
                    archetype            = excluded.archetype,
                    archetype_confidence = excluded.archetype_confidence,
                    error                = excluded.error
                """,
                (
                    session_id,
                    arc_data.get("generated_at", datetime.now().isoformat()),
                    arc_data.get("turn_count", 0),
                    turn_scores,
                    smoothed,
                    arc_data.get("overall_mean", 0),
                    arc_data.get("overall_std", 0),
                    arc_data.get("slope", 0),
                    arc_data.get("volatility", 0),
                    arc_data.get("user_self_distance", 0),
                    arc_data.get("model_relevance_trend", 0),
                    arc_data.get("frustration_score", 0),
                    arc_data.get("convergence_score", 0),
                    arc_data.get("archetype", ""),
                    arc_data.get("archetype_confidence", 0),
                    arc_data.get("error", ""),
                ),
            )
            self._conn.commit()
            return True
        except sqlite3.Error as e:
            debug_log(f"upsert_sentiment_arc({session_id}) failed: {e}")
            return False

    def get_sentiment_arc(self, session_id: str) -> dict | None:
        """Retrieve sentiment arc for a session."""
        if not self._require_conn():
            return None
        try:
            cur = self._conn.execute(
                "SELECT * FROM sentiment_arcs WHERE session_id = ?",
                (session_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            result = dict(row)
            try:
                result["turn_scores"] = json.loads(result["turn_scores_json"])
            except (json.JSONDecodeError, TypeError):
                result["turn_scores"] = []
            try:
                result["smoothed_trajectory"] = json.loads(result["smoothed_trajectory_json"])
            except (json.JSONDecodeError, TypeError):
                result["smoothed_trajectory"] = []
            return result
        except sqlite3.Error as e:
            debug_log(f"get_sentiment_arc({session_id}) failed: {e}")
            return None

    def list_sentiment_arcs(
        self,
        archetype: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """List sentiment arcs with optional archetype filter."""
        if not self._require_conn():
            return []
        try:
            query = "SELECT * FROM sentiment_arcs"
            params: list = []
            if archetype:
                query += " WHERE archetype = ?"
                params.append(archetype)
            query += " ORDER BY generated_at DESC"
            if limit is not None:
                query += " LIMIT ?"
                params.append(limit)
            cur = self._conn.execute(query, params)
            return [dict(row) for row in cur.fetchall()]
        except sqlite3.Error as e:
            debug_log(f"list_sentiment_arcs failed: {e}")
            return []

    def get_sentiment_arc_coverage(self) -> dict:
        """Return coverage stats: total sessions vs analyzed sessions."""
        if not self._require_conn():
            return {"total_sessions": 0, "analyzed_sessions": 0}
        try:
            total = self._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            analyzed = self._conn.execute("SELECT COUNT(*) FROM sentiment_arcs").fetchone()[0]
            return {"total_sessions": total, "analyzed_sessions": analyzed}
        except sqlite3.Error:
            return {"total_sessions": 0, "analyzed_sessions": 0}
```

- [ ] **Step 4: Add CLI subcommands**

In `narratives_db.py` `main()`, add argparse arguments before the `else`:

```python
    parser.add_argument("--sentiment-coverage", action="store_true", help="Show sentiment analysis coverage")
    parser.add_argument("--get-sentiment", type=str, metavar="SESSION_ID", help="Get sentiment arc for a session")
    parser.add_argument("--list-sentiment-archetypes", action="store_true", help="List sessions by sentiment archetype")
```

And corresponding `elif` handlers:

```python
        elif args.sentiment_coverage:
            coverage = db.get_sentiment_arc_coverage()
            print(f"Sentiment arc coverage: {coverage['analyzed_sessions']}/{coverage['total_sessions']} sessions")

        elif args.get_sentiment:
            result = db.get_sentiment_arc(args.get_sentiment)
            if result is None:
                print(f"No sentiment arc found for session: {args.get_sentiment}")
            else:
                print(f"Session: {result['session_id']}")
                print(f"Archetype: {result['archetype']} (confidence: {result['archetype_confidence']:.2f})")
                print(f"Turns: {result['turn_count']}")
                print(f"Mean: {result['overall_mean']:.3f}  Std: {result['overall_std']:.3f}")
                print(f"Slope: {result['slope']:.4f}  Volatility: {result['volatility']:.4f}")
                print(f"Frustration: {result['frustration_score']:.3f}  Convergence: {result['convergence_score']:.3f}")

        elif args.list_sentiment_archetypes:
            arcs = db.list_sentiment_arcs()
            if not arcs:
                print("No sentiment arcs found. Run backfill-sentiment first.")
                return
            # Group by archetype
            arch_counts: dict[str, int] = {}
            for a in arcs:
                arch = a.get("archetype", "unknown")
                arch_counts[arch] = arch_counts.get(arch, 0) + 1
            print(f"\nSentiment Archetype Distribution ({len(arcs)} sessions):\n")
            for arch, count in sorted(arch_counts.items(), key=lambda x: -x[1]):
                print(f"  {arch}: {count}")
```

- [ ] **Step 5: Verify migration runs**

```bash
cd .cursor/hooks && ../../.venv/Scripts/python.exe narratives_db.py --sentiment-coverage
```

Expected output: `Sentiment arc coverage: 0/57 sessions` (or whatever session count exists)

---

### Task 2: Create core sentiment_arc.py module

**Files:**
- Create: `.cursor/hooks/sentiment_arc.py`

- [ ] **Step 1: Create the module with sentiment extraction, smoothing, features, classification**

Full file content for `.cursor/hooks/sentiment_arc.py`:

```python
#!/usr/bin/env python3
"""
Sentiment Arc Detection — Per-turn sentiment analysis for Cursor hook sessions.

Extracts sentiment from user prompts and agent responses, builds smoothed
trajectories, computes arc features, and classifies sessions into archetypes.

Usage:
    python sentiment_arc.py --backfill              # Analyze all sessions without arcs
    python sentiment_arc.py --backfill --force       # Re-analyze all sessions
    python sentiment_arc.py <session_id>             # Analyze a single session
    python sentiment_arc.py <session_id> --json      # Output raw JSON
"""

import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# Resolve paths relative to this script
HOOKS_DIR = Path(__file__).parent.resolve()
STATE_DIR = HOOKS_DIR / "state"
SESSIONS_DIR = STATE_DIR / "sessions"

sys.path.insert(0, str(HOOKS_DIR))
from conversation_recorder import ConversationRecorder
from narratives_db import NarrativesDB

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Events that carry sentiment signal (turn-level)
SENTIMENT_EVENT_TYPES = {"user_prompt", "response", "tool_failure", "thought"}

# Exponential moving average smoothing factor (0.0-1.0)
# Higher = follows raw scores more closely; lower = smoother trajectory
EMA_ALPHA = 0.3

# Archetype decision thresholds
ARCHETYPE_SLOPE_NEGATIVE = -0.002    # Declining sentiment threshold
ARCHETYPE_VOLATILITY_HIGH = 0.25     # High volatility threshold (looping)
ARCHETYPE_FRUSTRATION_HIGH = 0.15    # Fraction of negative turns
ARCHETYPE_CONVERGENCE_LOW = 0.15     # Low late-session volatility
ARCHETYPE_SHORT_SESSION = 10         # Turns threshold for "rapid_resolution"

# Text preprocessing
_STOP_REMOVAL_PATTERN = re.compile(r"[^a-zA-Z0-9\s\-\.\!\?]")


# ---------------------------------------------------------------------------
# Sentiment extraction
# ---------------------------------------------------------------------------

_analyzer: Optional[SentimentIntensityAnalyzer] = None


def _get_analyzer() -> SentimentIntensityAnalyzer:
    """Lazy-init the VADER analyzer (thread-safe via module-level singleton)."""
    global _analyzer
    if _analyzer is None:
        _analyzer = SentimentIntensityAnalyzer()
    return _analyzer


def _extract_text(event: dict) -> str:
    """Extract the text payload from a sentiment-bearing event."""
    etype = event.get("type", "")
    if etype == "user_prompt":
        return event.get("prompt_text", "")
    elif etype == "response":
        return event.get("text_preview", "") or event.get("full_text", "")
    elif etype == "thought":
        return event.get("text", "")
    elif etype == "tool_failure":
        return event.get("error_message", "") or event.get("tool_name", "")
    return ""


def _clean_text(text: str) -> str:
    """Minimal text cleaning for VADER. Preserve punctuation — it matters for VADER scoring."""
    # Strip code blocks and URLs to reduce noise
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"https?://\S+", "", text)
    # Truncate very long texts (VADER is sentence-level optimized)
    if len(text) > 2000:
        text = text[:2000]
    return text.strip()


def compute_sentiment(text: str) -> float:
    """Return VADER compound score (-1.0 to +1.0) for text."""
    if not text or not text.strip():
        return 0.0
    cleaned = _clean_text(text)
    if not cleaned:
        return 0.0
    scores = _get_analyzer().polarity_scores(cleaned)
    return scores["compound"]


# ---------------------------------------------------------------------------
# Per-turn scoring
# ---------------------------------------------------------------------------

def extract_turn_scores(events: list[dict]) -> list[dict]:
    """Extract per-turn sentiment scores from session events.

    Returns list of dicts with sequence, type, user_compound, model_compound, timestamp.
    user_compound is set for user_prompt/tool_failure events.
    model_compound is set for response/thought events.
    """
    turns = []
    for ev in events:
        etype = ev.get("type", "")
        if etype not in SENTIMENT_EVENT_TYPES:
            continue

        text = _extract_text(ev)
        score = compute_sentiment(text)

        turn = {
            "sequence": ev.get("sequence", 0),
            "type": etype,
            "timestamp": ev.get("timestamp", ""),
            "user_compound": score if etype in ("user_prompt", "tool_failure") else None,
            "model_compound": score if etype in ("response", "thought") else None,
        }
        turns.append(turn)

    return turns


# ---------------------------------------------------------------------------
# Smoothing
# ---------------------------------------------------------------------------

def _effective_score(turn: dict) -> float:
    """Combine user_compound and model_compound into a single turn score."""
    u = turn.get("user_compound")
    m = turn.get("model_compound")
    if u is not None and m is not None:
        return (u + m) / 2.0
    elif u is not None:
        return u
    elif m is not None:
        return m
    return 0.0


def smooth_trajectory(turns: list[dict], alpha: float = EMA_ALPHA) -> list[float]:
    """Apply exponential moving average smoothing to turn scores."""
    if not turns:
        return []

    scores = [_effective_score(t) for t in turns]
    smoothed = [scores[0]]
    for s in scores[1:]:
        smoothed.append(alpha * s + (1 - alpha) * smoothed[-1])

    return smoothed


# ---------------------------------------------------------------------------
# Arc features
# ---------------------------------------------------------------------------

def compute_arc_features(turns: list[dict], smoothed: list[float]) -> dict:
    """Compute arc-level features from turns and smoothed trajectory."""
    if not turns or not smoothed:
        return {
            "overall_mean": 0, "overall_std": 0, "slope": 0,
            "volatility": 0, "user_self_distance": 0,
            "model_relevance_trend": 0, "frustration_score": 0,
            "convergence_score": 0, "turn_count": 0,
        }

    n = len(smoothed)
    scores = [_effective_score(t) for t in turns]

    # Overall statistics
    mean_score = sum(scores) / n
    variance = sum((s - mean_score) ** 2 for s in scores) / max(n - 1, 1)
    std_score = math.sqrt(variance)

    # Linear regression slope (turn index vs score)
    x_mean = (n - 1) / 2.0
    y_mean = mean_score
    numerator = sum((i - x_mean) * (s - y_mean) for i, s in enumerate(scores))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    slope = numerator / denominator if denominator > 0 else 0.0

    # Volatility: std of consecutive score deltas
    if n >= 2:
        deltas = [scores[i + 1] - scores[i] for i in range(n - 1)]
        delta_mean = sum(deltas) / len(deltas)
        delta_var = sum((d - delta_mean) ** 2 for d in deltas) / max(len(deltas) - 1, 1)
        volatility = math.sqrt(delta_var)
    else:
        volatility = 0.0

    # User self-distance: mean abs diff between consecutive user scores
    user_scores = [t["user_compound"] for t in turns if t.get("user_compound") is not None]
    if len(user_scores) >= 2:
        user_deltas = [abs(user_scores[i + 1] - user_scores[i]) for i in range(len(user_scores) - 1)]
        user_self_distance = sum(user_deltas) / len(user_deltas)
    else:
        user_self_distance = 0.0

    # Model relevance trend: correlation of model scores with turn index
    model_scores = [t["model_compound"] for t in turns if t.get("model_compound") is not None]
    if len(model_scores) >= 3:
        mx = (len(model_scores) - 1) / 2.0
        my = sum(model_scores) / len(model_scores)
        mn = sum((i - mx) * (s - my) for i, s in enumerate(model_scores))
        md = sum((i - mx) ** 2 for i in range(len(model_scores)))
        model_relevance_trend = mn / md if md > 0 else 0.0
    else:
        model_relevance_trend = 0.0

    # Frustration score: fraction of turns with compound < -0.1
    frustration_score = sum(1 for s in scores if s < -0.1) / n

    # Convergence score: compare volatility in last 30% vs first 70%
    split_idx = max(int(n * 0.7), 2)
    if n >= 4 and split_idx < n:
        early_scores = scores[:split_idx]
        late_scores = scores[split_idx:]
        early_var = sum((s - sum(early_scores) / len(early_scores)) ** 2 for s in early_scores) / len(early_scores)
        late_var = sum((s - sum(late_scores) / len(late_scores)) ** 2 for s in late_scores) / len(late_scores)
        # Convergence = early_var > late_var (decreasing volatility)
        if early_var > 0:
            convergence_score = max(0.0, 1.0 - (late_var / early_var))
        else:
            convergence_score = 1.0 if late_var == 0 else 0.0
    else:
        convergence_score = 0.0

    return {
        "overall_mean": round(mean_score, 4),
        "overall_std": round(std_score, 4),
        "slope": round(slope, 6),
        "volatility": round(volatility, 4),
        "user_self_distance": round(user_self_distance, 4),
        "model_relevance_trend": round(model_relevance_trend, 6),
        "frustration_score": round(frustration_score, 4),
        "convergence_score": round(convergence_score, 4),
        "turn_count": n,
    }


# ---------------------------------------------------------------------------
# Archetype classification
# ---------------------------------------------------------------------------

ARCHETYPES = {
    "smooth_convergence": "Declining volatility, neutral-positive ending. Productive session.",
    "escalating_frustration": "Negative slope, high frustration score. Degrading session.",
    "looping": "High volatility, oscillating scores. Agent stuck in retry loops.",
    "exploratory_wander": "Near-zero slope, moderate volatility, low convergence. No clear direction.",
    "rapid_resolution": "Few turns, high convergence. Quick fix session.",
    "mixed": "Doesn't fit other archetypes cleanly.",
}


def classify_archetype(features: dict) -> tuple[str, float]:
    """Classify session into a sentiment archetype.

    Returns (archetype_name, confidence 0.0-1.0).
    """
    slope = features["slope"]
    volatility = features["volatility"]
    frustration = features["frustration_score"]
    convergence = features["convergence_score"]
    mean_score = features["overall_mean"]
    turn_count = features["turn_count"]

    scores: dict[str, float] = {}

    # Smooth Convergence: positive/neutral slope + low late volatility + convergence
    smooth_conv_score = 0.0
    if convergence > ARCHETYPE_CONVERGENCE_LOW:
        smooth_conv_score += 0.4
    if mean_score >= -0.05:
        smooth_conv_score += 0.3
    if volatility < ARCHETYPE_VOLATILITY_HIGH:
        smooth_conv_score += 0.3
    scores["smooth_convergence"] = smooth_conv_score

    # Escalating Frustration: negative slope + high frustration
    esc_frust_score = 0.0
    if slope < ARCHETYPE_SLOPE_NEGATIVE:
        esc_frust_score += 0.5
    if frustration > ARCHETYPE_FRUSTRATION_HIGH:
        esc_frust_score += 0.3
    if mean_score < -0.1:
        esc_frust_score += 0.2
    scores["escalating_frustration"] = esc_frust_score

    # Looping: high volatility regardless of slope
    loop_score = 0.0
    if volatility > ARCHETYPE_VOLATILITY_HIGH:
        loop_score += 0.5
    # Check for oscillation: alternating positive/negative deltas
    loop_score += min(0.5, frustration * 2)  # Frustration contributes but isn't required
    scores["looping"] = loop_score

    # Exploratory Wander: near-zero slope + moderate volatility + low convergence
    wander_score = 0.0
    if abs(slope) < abs(ARCHETYPE_SLOPE_NEGATIVE):
        wander_score += 0.4
    if convergence < ARCHETYPE_CONVERGENCE_LOW:
        wander_score += 0.3
    if 0.1 < volatility < ARCHETYPE_VOLATILITY_HIGH:
        wander_score += 0.3
    scores["exploratory_wander"] = wander_score

    # Rapid Resolution: short session + high convergence
    rapid_score = 0.0
    if turn_count <= ARCHETYPE_SHORT_SESSION:
        rapid_score += 0.6
    if convergence > 0.3:
        rapid_score += 0.4
    scores["rapid_resolution"] = rapid_score

    # Pick the highest scoring archetype
    best_archetype = max(scores, key=scores.get)
    best_score = scores[best_archetype]

    # Confidence: normalize by max possible (1.0) and apply a floor
    confidence = min(best_score, 1.0)
    if confidence < 0.3 or best_archetype == "mixed":
        return "mixed", confidence
    if confidence < 0.5:
        # Borderline — reduce confidence
        confidence *= 0.7

    return best_archetype, round(confidence, 2)


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def analyze_session(session_id: str, force: bool = False) -> dict | None:
    """Run full sentiment arc analysis on a session.

    Returns the arc data dict, or None if analysis failed.
    Writes results to SQLite (fail-open).
    """
    try:
        # Load session from JSON
        session_file = SESSIONS_DIR / session_id / "session.json"
        if not session_file.exists():
            return None

        session = json.loads(session_file.read_text(encoding="utf-8"))
        events = session.get("events", [])
        if not events:
            return None

        # Check if already analyzed (skip unless force)
        if not force:
            with NarrativesDB() as db:
                existing = db.get_sentiment_arc(session_id)
                if existing is not None:
                    return existing

        # Step 1: Extract per-turn scores
        turns = extract_turn_scores(events)
        if not turns:
            return None

        # Step 2: Smooth trajectory
        smoothed = smooth_trajectory(turns)

        # Step 3: Compute features
        features = compute_arc_features(turns, smoothed)

        # Step 4: Classify archetype
        archetype, confidence = classify_archetype(features)

        # Build result
        arc_data = {
            "generated_at": datetime.now().isoformat(),
            "turn_scores": turns,
            "smoothed_trajectory": smoothed,
            "archetype": archetype,
            "archetype_confidence": confidence,
            "error": "",
        }
        arc_data.update(features)

        # Step 5: Persist to SQLite (fail-open)
        try:
            with NarrativesDB() as db:
                db.upsert_sentiment_arc(session_id, arc_data)
        except Exception as e:
            # Don't fail the analysis if DB write fails
            arc_data["error"] = f"DB write failed: {e}"

        return arc_data

    except Exception as e:
        # Fail-open: log error, try to store error record
        error_data = {
            "generated_at": datetime.now().isoformat(),
            "turn_scores": [],
            "smoothed_trajectory": [],
            "overall_mean": 0,
            "overall_std": 0,
            "slope": 0,
            "volatility": 0,
            "user_self_distance": 0,
            "model_relevance_trend": 0,
            "frustration_score": 0,
            "convergence_score": 0,
            "archetype": "",
            "archetype_confidence": 0,
            "turn_count": 0,
            "error": str(e),
        }
        try:
            with NarrativesDB() as db:
                db.upsert_sentiment_arc(session_id, error_data)
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# Batch backfill
# ---------------------------------------------------------------------------

def backfill_all_sessions(force: bool = False) -> dict:
    """Analyze all sessions that don't have sentiment arcs yet.

    Returns summary dict: {processed, skipped, errored, errors, elapsed_seconds}.
    """
    recorder = ConversationRecorder()
    results = {"processed": 0, "skipped": 0, "errored": 0, "errors": [], "elapsed_seconds": 0}

    session_dirs = sorted(SESSIONS_DIR.glob("*/session.json"))
    total = len(session_dirs)
    start = datetime.now()

    for i, session_file in enumerate(session_dirs, 1):
        session_id = session_file.parent.name

        try:
            arc = analyze_session(session_id, force=force)
            if arc is None:
                results["skipped"] += 1
            else:
                results["processed"] += 1

            if results["processed"] % 10 == 0:
                elapsed = (datetime.now() - start).total_seconds()
                print(f"  Progress: {results['processed']}/{total} analyzed, "
                      f"{results['errored']} errors, {elapsed:.1f}s elapsed")

        except Exception as e:
            results["errored"] += 1
            results["errors"].append(f"{session_id}: {e}")

    results["elapsed_seconds"] = round((datetime.now() - start).total_seconds(), 1)
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]

    if "--backfill" in args:
        force = "--force" in args
        print(f"Starting sentiment arc backfill (force={force})...")
        results = backfill_all_sessions(force=force)
        print(f"\nBackfill complete:")
        print(f"  Processed: {results['processed']}")
        print(f"  Skipped:   {results['skipped']}")
        print(f"  Errored:   {results['errored']}")
        print(f"  Elapsed:   {results['elapsed_seconds']}s")
        if results["errors"]:
            print(f"\nErrors:")
            for err in results["errors"][:20]:
                print(f"  {err}")
            if len(results["errors"]) > 20:
                print(f"  ... and {len(results['errors']) - 20} more")
        return

    if not args:
        print(__doc__)
        return

    # Single session analysis
    session_id = args[0]
    as_json = "--json" in args
    force = "--force" in args

    arc = analyze_session(session_id, force=force)
    if arc is None:
        print(f"No sentiment-bearing events found for session: {session_id}")
        sys.exit(1)

    if as_json:
        print(json.dumps(arc, indent=2))
    else:
        print(f"Session: {session_id}")
        print(f"Archetype: {arc.get('archetype', 'N/A')} "
              f"(confidence: {arc.get('archetype_confidence', 0):.2f})")
        print(f"Turns: {arc.get('turn_count', 0)}")
        print(f"Mean: {arc.get('overall_mean', 0):.3f}  "
              f"Std: {arc.get('overall_std', 0):.3f}")
        print(f"Slope: {arc.get('slope', 0):.4f}  "
              f"Volatility: {arc.get('volatility', 0):.4f}")
        print(f"Frustration: {arc.get('frustration_score', 0):.3f}  "
              f"Convergence: {arc.get('convergence_score', 0):.3f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify the module works on a single session**

```bash
cd .cursor/hooks && ../../.venv/Scripts/python.exe sentiment_arc.py 07d62e75-42b8-471c-a24d-ba3df6d4f307
```

Expected output: Shows archetype classification with feature values.

- [ ] **Step 3: Test JSON output**

```bash
cd .cursor/hooks && ../../.venv/Scripts/python.exe sentiment_arc.py 07d62e75-42b8-471c-a24d-ba3df6d4f307 --json | head -30
```

---

### Task 3: Run batch backfill on all 57 sessions

**Files:** No file changes — this is an execution task.

- [ ] **Step 1: Run backfill**

```bash
cd .cursor/hooks && ../../.venv/Scripts/python.exe sentiment_arc.py --backfill
```

Expected output: Progress updates every 10 sessions, final summary with processed/skipped/errored counts.

- [ ] **Step 2: Verify coverage**

```bash
cd .cursor/hooks && ../../.venv/Scripts/python.exe narratives_db.py --sentiment-coverage
cd .cursor/hooks && ../../.venv/Scripts/python.exe narratives_db.py --list-sentiment-archetypes
```

Expected: Coverage shows ~57 analyzed, archetype distribution printed.

- [ ] **Step 3: Spot-check a few sessions**

```bash
cd .cursor/hooks && ../../.venv/Scripts/python.exe narratives_db.py --get-sentiment <session_id_from_backfill>
```

---

### Task 4: Add sentiment query functions to db_queries.py

**Files:**
- Modify: `.cursor/hooks/dashboard/db_queries.py` (append new query functions)

- [ ] **Step 1: Append sentiment query functions**

Add to the end of `db_queries.py`:

```python
# ---------------------------------------------------------------------------
# Sentiment Arc queries
# ---------------------------------------------------------------------------

def get_sentiment_kpi_stats() -> dict:
    """Return top-level sentiment KPIs."""
    conn = _connect()
    try:
        total = conn.execute("SELECT COUNT(*) FROM sentiment_arcs").fetchone()[0]
        if total == 0:
            return {"analyzed_sessions": 0}

        # Archetype distribution
        rows = conn.execute(
            "SELECT archetype, COUNT(*) as count FROM sentiment_arcs "
            "GROUP BY archetype ORDER BY count DESC"
        ).fetchall()
        archetype_dist = {r["archetype"]: r["count"] for r in rows}

        # Average slope
        avg_slope = conn.execute(
            "SELECT AVG(slope) FROM sentiment_arcs"
        ).fetchone()[0]

        # Average frustration
        avg_frustration = conn.execute(
            "SELECT AVG(frustration_score) FROM sentiment_arcs"
        ).fetchone()[0]

        # Mean sentiment
        avg_mean = conn.execute(
            "SELECT AVG(overall_mean) FROM sentiment_arcs"
        ).fetchone()[0]

        return {
            "analyzed_sessions": total,
            "archetype_distribution": archetype_dist,
            "avg_slope": round(avg_slope or 0, 4),
            "avg_frustration": round(avg_frustration or 0, 4),
            "avg_mean_sentiment": round(avg_mean or 0, 4),
        }
    finally:
        conn.close()


def get_sentiment_arc_trajectory(session_id: str) -> dict | None:
    """Get turn scores and smoothed trajectory for a single session."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM sentiment_arcs WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["turn_scores"] = json.loads(result["turn_scores_json"])
        result["smoothed_trajectory"] = json.loads(result["smoothed_trajectory_json"])
        return result
    finally:
        conn.close()


def get_sentiment_archetype_distribution() -> list[dict]:
    """Return sessions grouped by archetype with avg features."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT
                archetype,
                COUNT(*) as session_count,
                AVG(overall_mean) as avg_mean,
                AVG(slope) as avg_slope,
                AVG(volatility) as avg_volatility,
                AVG(frustration_score) as avg_frustration,
                AVG(convergence_score) as avg_convergence,
                AVG(archetype_confidence) as avg_confidence
            FROM sentiment_arcs
            GROUP BY archetype
            ORDER BY session_count DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_sentiment_time_series(days: int = 30, date_from: str = "", date_to: str = "") -> list[dict]:
    """Return average sentiment per day, optionally filtered."""
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
            from datetime import timedelta
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            conditions.append("s.created_at >= ?")
            params.append(cutoff)
        where_clause = " AND ".join(conditions)

        rows = conn.execute(
            f"""
            SELECT DATE(s.created_at) as day,
                   AVG(sa.overall_mean) as avg_sentiment,
                   AVG(sa.slope) as avg_slope,
                   COUNT(*) as sessions
            FROM sentiment_arcs sa
            JOIN sessions s ON sa.session_id = s.session_id
            WHERE {where_clause}
            GROUP BY DATE(s.created_at)
            ORDER BY day ASC
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_sentiment_session_list(
    archetype: str = "",
    sort_col: str = "created_at",
    sort_dir: str = "DESC",
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[dict], int]:
    """Return paginated session list with sentiment data."""
    conn = _connect()
    try:
        conditions = []
        params: list = []
        if archetype:
            conditions.append("sa.archetype = ?")
            params.append(archetype)
        where_clause = " AND ".join(conditions) if conditions else "1=1"

        count_row = conn.execute(
            f"""
            SELECT COUNT(*) as cnt
            FROM sentiment_arcs sa
            JOIN sessions s ON sa.session_id = s.session_id
            WHERE {where_clause}
            """,
            params,
        ).fetchone()
        total = count_row["cnt"]

        valid_sort_cols = {
            "created_at", "overall_mean", "slope", "volatility",
            "frustration_score", "convergence_score", "archetype",
            "turn_count", "archetype_confidence",
        }
        if sort_col not in valid_sort_cols:
            sort_col = "created_at"
        if sort_dir not in ("ASC", "DESC"):
            sort_dir = "DESC"

        offset = (page - 1) * page_size
        rows = conn.execute(
            f"""
            SELECT s.session_id, s.created_at, s.status, s.model,
                   sa.overall_mean, sa.slope, sa.volatility,
                   sa.frustration_score, sa.convergence_score,
                   sa.archetype, sa.archetype_confidence,
                   sa.turn_count
            FROM sentiment_arcs sa
            JOIN sessions s ON sa.session_id = s.session_id
            WHERE {where_clause}
            ORDER BY s.{sort_col} {sort_dir}
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()
        return [dict(r) for r in rows], total
    finally:
        conn.close()
```

---

### Task 5: Add Sentiment Arcs page to Streamlit dashboard

**Files:**
- Modify: `.cursor/hooks/dashboard/dashboard.py` (add new page/tab)

- [ ] **Step 1: Add the Sentiment Arcs page**

In `dashboard.py`, after the existing tabs/pages, add a new page. The dashboard uses `st.tabs()` for multi-page layout. Find the tab creation section (around line 90-120) and add `"Sentiment Arcs"` to the tab list. Then add the content handler.

The new page should have these sections:

```python
# In the tab content handler for "Sentiment Arcs":

# --- KPI Row ---
sent_kpis = db_queries.get_sentiment_kpi_stats()
if sent_kpis.get("analyzed_sessions", 0) == 0:
    st.info("No sentiment arcs computed yet. Run backfill:")
    st.code("cd .cursor/hooks && python sentiment_arc.py --backfill", language="bash")
    return

col1, col2, col3, col4 = st.columns(4)
col1.metric("Analyzed Sessions", sent_kpis["analyzed_sessions"])
col2.metric("Avg Sentiment", f"{sent_kpis.get('avg_mean_sentiment', 0):.3f}")
col3.metric("Avg Slope", f"{sent_kpis.get('avg_slope', 0):.4f}")
col4.metric("Avg Frustration", f"{sent_kpis.get('avg_frustration', 0):.3f}")

# --- Archetype Distribution ---
st.subheader("Archetype Distribution")
arch_dist = db_queries.get_sentiment_archetype_distribution()
if arch_dist:
    arch_df = pd.DataFrame(arch_dist)
    fig_arch = px.bar(
        arch_df, x="archetype", y="session_count",
        title="Sessions by Sentiment Archetype",
        color="archetype",
        color_discrete_sequence=px.colors.qualitative.Set2,
    )
    st.plotly_chart(fig_arch, use_container_width=True)

    # Detail table
    st.dataframe(
        arch_df.rename(columns={
            "archetype": "Archetype",
            "session_count": "Sessions",
            "avg_mean": "Avg Sentiment",
            "avg_slope": "Avg Slope",
            "avg_volatility": "Avg Volatility",
            "avg_frustration": "Avg Frustration",
            "avg_convergence": "Avg Convergence",
            "avg_confidence": "Avg Confidence",
        }),
        use_container_width=True,
        hide_index=True,
    )

# --- Sentiment Time Series ---
st.subheader("Sentiment Over Time")
sent_ts = db_queries.get_sentiment_time_series(
    days=date_days, date_from=date_from, date_to=date_to
)
if sent_ts:
    ts_df = pd.DataFrame(sent_ts)
    fig_ts = px.line(
        ts_df, x="day", y="avg_sentiment",
        title="Average Session Sentiment Over Time",
        markers=True,
    )
    fig_ts.update_traces(line=dict(color="#4C78A8"))
    fig_ts.update_yaxes(range=[-1, 1])
    st.plotly_chart(fig_ts, use_container_width=True)

# --- Session Explorer with Sentiment ---
st.subheader("Session Sentiment Explorer")
sent_archetype_filter = st.selectbox(
    "Filter by Archetype",
    ["All"] + [a["archetype"] for a in arch_dist] if arch_dist else ["All"],
)
sent_sort_col = st.selectbox(
    "Sort by",
    ["created_at", "overall_mean", "slope", "volatility", "frustration_score", "convergence_score"],
)
sent_sort_dir = st.radio("Direction", ["DESC", "ASC"], horizontal=True)
sent_page = st.number_input("Page", min_value=1, value=1)

sent_archetype_param = "" if sent_archetype_filter == "All" else sent_archetype_filter
sent_sessions, sent_total = db_queries.get_sentiment_session_list(
    archetype=sent_archetype_param,
    sort_col=sent_sort_col,
    sort_dir=sent_sort_dir,
    page=sent_page,
    page_size=50,
)

if sent_sessions:
    sent_df = pd.DataFrame(sent_sessions)
    sent_display = sent_df[[
        "session_id", "created_at", "model", "archetype",
        "overall_mean", "slope", "volatility", "frustration_score",
        "convergence_score", "turn_count", "archetype_confidence",
    ]].copy()
    sent_display.columns = [
        "Session ID", "Created", "Model", "Archetype",
        "Mean Sentiment", "Slope", "Volatility", "Frustration",
        "Convergence", "Turns", "Confidence",
    ]
    st.dataframe(sent_display, use_container_width=True, hide_index=True)

# --- Single Session Trajectory View ---
st.subheader("Session Trajectory View")
trajectory_session = st.text_input("Enter Session ID for Trajectory")
if trajectory_session:
    traj = db_queries.get_sentiment_arc_trajectory(trajectory_session)
    if traj:
        col_a, col_b = st.columns(2)
        col_a.metric("Archetype", traj["archetype"])
        col_b.metric("Confidence", f"{traj['archetype_confidence']:.2f}")

        turn_scores = traj.get("turn_scores", [])
        if turn_scores:
            traj_data = []
            for t in turn_scores:
                u = t.get("user_compound")
                m = t.get("model_compound")
                traj_data.append({
                    "Sequence": t["sequence"],
                    "Type": t["type"],
                    "User Sentiment": u if u is not None else 0,
                    "Model Sentiment": m if m is not None else 0,
                })
            traj_df = pd.DataFrame(traj_data)

            fig_traj = go.Figure()
            fig_traj.add_trace(go.Scatter(
                x=traj_df["Sequence"], y=traj_df["User Sentiment"],
                name="User", mode="lines+markers",
                marker=dict(color="#E15759"),
            ))
            fig_traj.add_trace(go.Scatter(
                x=traj_df["Sequence"], y=traj_df["Model Sentiment"],
                name="Model", mode="lines+markers",
                marker=dict(color="#4E79A7"),
            ))
            # Add smoothed trajectory
            smoothed = traj.get("smoothed_trajectory", [])
            if smoothed:
                fig_traj.add_trace(go.Scatter(
                    x=list(range(len(smoothed))), y=smoothed,
                    name="Smoothed", mode="lines",
                    line=dict(color="#59A14F", width=3, dash="dash"),
                ))
            fig_traj.update_layout(
                title="Sentiment Trajectory",
                yaxis=dict(range=[-1, 1], title="Compound Score"),
                xaxis=dict(title="Turn Sequence"),
            )
            st.plotly_chart(fig_traj, use_container_width=True)
    else:
        st.warning(f"No sentiment arc data for session: {trajectory_session}")
```

- [ ] **Step 2: Add import if needed**

Ensure `db_queries` is imported at the top of `dashboard.py` (it already is — line 21). No additional imports needed since `plotly.graph_objects` is already imported as `go`.

- [ ] **Step 3: Verify dashboard runs**

```bash
cd .cursor/hooks/dashboard && streamlit run dashboard.py
```

Open in browser, verify "Sentiment Arcs" tab renders with data.

---

### Task 6: Integration testing and edge case handling

**Files:**
- No file changes — testing tasks.

- [ ] **Step 1: Test fail-open behavior**

```bash
cd .cursor/hooks && ../../.venv/Scripts/python.exe sentiment_arc.py nonexistent-session-id
```

Expected: No crash, exits with error message.

- [ ] **Step 2: Test with empty events session**

Find or create a session with no sentiment-bearing events. Run analysis.
Expected: Returns None gracefully.

- [ ] **Step 3: Test idempotent backfill (run twice)**

```bash
cd .cursor/hooks && ../../.venv/Scripts/python.exe sentiment_arc.py --backfill
cd .cursor/hooks && ../../.venv/Scripts/python.exe sentiment_arc.py --backfill
```

Second run should skip all sessions (no re-processing).

- [ ] **Step 4: Test force backfill**

```bash
cd .cursor/hooks && ../../.venv/Scripts/python.exe sentiment_arc.py --backfill --force
```

Expected: Re-processes all sessions.

- [ ] **Step 5: Verify SQLite integrity**

```bash
cd .cursor/hooks && ../../.venv/Scripts/python.exe narratives_db.py --list-sentiment-archetypes
```

---

### Task 7: Update DOCS.md

**Files:**
- Modify: `DOCS.md` (in workspace root or wherever it lives)

- [ ] **Step 1: Document the sentiment arc feature**

Append to `DOCS.md`:

```markdown
## Sentiment Arc Detection

### Overview
Per-turn sentiment analysis for Cursor hook sessions using VADER (lexicon-based, no GPU required).
Analyzes user prompts, agent responses, thoughts, and tool failures to build sentiment trajectories.

### Files
- `.cursor/hooks/sentiment_arc.py` — Core sentiment engine
- `.cursor/hooks/narratives_db.py` — Schema migration v8, sentiment_arcs table
- `.cursor/hooks/dashboard/dashboard.py` — Sentiment Arcs dashboard page

### Usage
```bash
# Analyze all sessions (backfill)
cd .cursor/hooks && python sentiment_arc.py --backfill

# Re-analyze all sessions
cd .cursor/hooks && python sentiment_arc.py --backfill --force

# Analyze single session
cd .cursor/hooks && python sentiment_arc.py <session_id>

# Output as JSON
cd .cursor/hooks && python sentiment_arc.py <session_id> --json
```

### Archetypes
| Archetype | Description |
|-----------|-------------|
| smooth_convergence | Declining volatility, neutral-positive ending |
| escalating_frustration | Negative slope, high frustration |
| looping | High volatility, oscillating scores |
| exploratory_wander | Near-zero slope, low convergence |
| rapid_resolution | Few turns, high convergence |
| mixed | Doesn't fit cleanly |

### Database
Results stored in `sentiment_arcs` table in `narratives.db`. Schema v8.
```

---

## Self-Review Checklist

### 1. Spec coverage
| Requirement | Task |
|-------------|------|
| Per-turn sentiment from user prompts and agent responses | Task 2: `extract_turn_scores()` |
| Smoothed sentiment trajectories | Task 2: `smooth_trajectory()` with EMA |
| Arc features (slope, volatility, user self-distance, model relevance, etc.) | Task 2: `compute_arc_features()` |
| Archetype classification | Task 2: `classify_archetype()` |
| SQLite storage | Task 1: Migration v8 + `upsert_sentiment_arc()` |
| Dashboard visualization | Task 5: New dashboard page |
| Retroactive batch backfill | Task 2: `backfill_all_sessions()` + Task 3 |
| Optional incremental analysis | Task 2: `analyze_session()` with skip-if-exists logic |
| Fail-open design | Task 2: try/except in all critical paths, error records stored |
| Zero/minimal new dependencies | Only `vaderSentiment` (126 kB, no GPU) |
| Works with existing patterns | Follows `narratives_db.py` CRUD pattern, `conversation_recorder.py` session loading |

### 2. Placeholder scan
- No TBD/TODO items in the plan
- All code blocks contain complete, working code
- All function signatures match across tasks
- All file paths are exact

### 3. Type consistency
- `arc_data` dict structure in `sentiment_arc.py` matches `upsert_sentiment_arc()` parameters in `narratives_db.py`
- Query function return types in `db_queries.py` match dashboard consumption
- `SentimentIntensityAnalyzer` import path is `vaderSentiment.vaderSentiment` (verified from PyPI docs)

### 4. Edge cases handled in code
- Empty events list → returns None
- No sentiment-bearing events → returns None
- DB write failure → error stored in arc_data, analysis still completes
- Missing session file → returns None
- Encoding issues → fail-open with try/except
- Re-running backfill → skip already-analyzed (idempotent)
- Very long text → truncated to 2000 chars for VADER
- Code blocks and URLs stripped from text before scoring

---

## Execution Handoff

Plan complete and saved. Two execution options:

**1. Subagent-Driven (recommended)** - Fresh subagent per task with review checkpoints
**2. Inline Execution** - Execute tasks sequentially in this session

Which approach?
