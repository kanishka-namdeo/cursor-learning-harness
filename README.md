<p align="center">
  <img src="assets/logo-128x128.png" alt="Cursor Learning Harness Logo" width="128" height="128">
</p>

<h1 align="center">Cursor Learning Harness</h1>

<p align="center">
  <strong>Self-Improving AI Coding Assistant with LangGraph & LangChain</strong>
</p>

<p align="center">
  <span style="display:inline-block;padding:4px 12px;margin:2px 4px;background:#3b82f622;border:1px solid #3b82f6;border-radius:6px;color:#60a5fa;font-size:13px;font-weight:500;font-family:system-ui,sans-serif;">Python 3.13+</span>
  <span style="display:inline-block;padding:4px 12px;margin:2px 4px;background:#10b98122;border:1px solid #10b981;border-radius:6px;color:#34d399;font-size:13px;font-weight:500;font-family:system-ui,sans-serif;">LangGraph 0.2+</span>
  <span style="display:inline-block;padding:4px 12px;margin:2px 4px;background:#f59e0b22;border:1px solid #f59e0b;border-radius:6px;color:#fbbf24;font-size:13px;font-weight:500;font-family:system-ui,sans-serif;">MIT License</span>
  <span style="display:inline-block;padding:4px 12px;margin:2px 4px;background:#f9731622;border:1px solid #f97316;border-radius:6px;color:#fb923c;font-size:13px;font-weight:500;font-family:system-ui,sans-serif;">SQLite 3</span>
  <span style="display:inline-block;padding:4px 12px;margin:2px 4px;background:#ef444422;border:1px solid #ef4444;border-radius:6px;color:#f87171;font-size:13px;font-weight:500;font-family:system-ui,sans-serif;">Streamlit</span>
</p>

<p align="center">
  <em>Records every AI coding session, generates narrative summaries, tracks sentiment arcs, and continuously improves agent behavior over time.</em>
</p>

---

## At a Glance

<p align="center">
<table border="0" cellpadding="8" cellspacing="0" width="100%">
<tr>
<td width="50%" style="background:#161b22;border:1px solid #30363d;border-radius:10px;padding:16px;vertical-align:top;">
<strong style="color:#60a5fa;font-size:15px;font-family:system-ui,sans-serif;">Session Recording</strong><br>
<span style="color:#8b949e;font-size:13px;font-family:system-ui,sans-serif;">Captures the full lifecycle of Cursor AI coding sessions — initial thoughts, tool calls, shell commands, file edits, and final output</span>
</td>
<td width="50%" style="background:#161b22;border:1px solid #30363d;border-radius:10px;padding:16px;vertical-align:top;">
<strong style="color:#a78bfa;font-size:15px;font-family:system-ui,sans-serif;">AI Summarization</strong><br>
<span style="color:#8b949e;font-size:13px;font-family:system-ui,sans-serif;">Uses LangGraph agents to generate human-readable narrative summaries of each session</span>
</td>
</tr>
<tr><td colspan="2" height="8"></td></tr>
<tr>
<td width="50%" style="background:#161b22;border:1px solid #30363d;border-radius:10px;padding:16px;vertical-align:top;">
<strong style="color:#22d3ee;font-size:15px;font-family:system-ui,sans-serif;">Sentiment Arc Analysis</strong><br>
<span style="color:#8b949e;font-size:13px;font-family:system-ui,sans-serif;">Classifies sessions into archetypes (smooth convergence, escalating frustration, looping, etc.) based on emotional trajectory</span>
</td>
<td width="50%" style="background:#161b22;border:1px solid #30363d;border-radius:10px;padding:16px;vertical-align:top;">
<strong style="color:#34d399;font-size:15px;font-family:system-ui,sans-serif;">Self-Improving Loop</strong><br>
<span style="color:#8b949e;font-size:13px;font-family:system-ui,sans-serif;">Extracts actionable patterns from session telemetry and generates Cursor rules to improve agent behavior over time</span>
</td>
</tr>
</table>
</p>

---

## Tech Stack

<p align="center">
  <span style="display:inline-block;padding:3px 10px;margin:2px;background:#10b98122;border:1px solid #10b98155;border-radius:4px;color:#34d399;font-size:12px;font-family:system-ui,sans-serif;">LangChain 0.3+</span>
  <span style="display:inline-block;padding:3px 10px;margin:2px;background:#10b98122;border:1px solid #10b98155;border-radius:4px;color:#34d399;font-size:12px;font-family:system-ui,sans-serif;">OpenAI API</span>
  <span style="display:inline-block;padding:3px 10px;margin:2px;background:#f9731622;border:1px solid #f9731655;border-radius:4px;color:#fb923c;font-size:12px;font-family:system-ui,sans-serif;">HuggingFace</span>
  <span style="display:inline-block;padding:3px 10px;margin:2px;background:#ee4c2c22;border:1px solid #ee4c2c55;border-radius:4px;color:#f87171;font-size:12px;font-family:system-ui,sans-serif;">PyTorch 2.0+</span>
  <span style="display:inline-block;padding:3px 10px;margin:2px;background:#6366f122;border:1px solid #6366f155;border-radius:4px;color:#818cf8;font-size:12px;font-family:system-ui,sans-serif;">Plotly</span>
  <span style="display:inline-block;padding:3px 10px;margin:2px;background:#fbbf2422;border:1px solid #fbbf2455;border-radius:4px;color:#fbbf24;font-size:12px;font-family:system-ui,sans-serif;">Ruff</span>
  <span style="display:inline-block;padding:3px 10px;margin:2px;background:#0a9edc22;border:1px solid #0a9edc55;border-radius:4px;color:#38bdf8;font-size:12px;font-family:system-ui,sans-serif;">pytest</span>
</p>

## Features

- **Session Recording**: Captures the full lifecycle of Cursor AI coding sessions — initial thoughts, tool calls, shell commands, file edits, and final output
- **AI-Powered Summarization**: Uses LangGraph agents to generate human-readable narrative summaries of each session
- **Two-Level Summarization**: Session-level narratives (from raw events) and conversation-level narratives (aggregated from session summaries)
- **Sentiment Arc Analysis**: Classifies sessions into archetypes (smooth convergence, escalating frustration, looping, etc.) based on emotional trajectory
- **Self-Improving Learning Loop**: Extracts actionable patterns from session telemetry and generates Cursor rules to improve agent behavior
- **Dual Storage**: Session data written to both JSON files (primary) and SQLite (queryable mirror)
- **Streamlit Dashboard**: Interactive UI for exploring sessions, narratives, tool analytics, and file activity
- **Fail-Open Design**: Hooks never block the Cursor agent workflow on error

## Quick Start

### Prerequisites

- Python 3.13+
- [Cursor IDE](https://cursor.sh/)

### Setup

```bash
# Create and activate virtual environment
python -m venv .venv
.venv/Scripts\python.exe -m pip install -r .cursor/hooks/requirements.txt

# Install additional dependencies
.venv/Scripts\python.exe -m pip install \
  sentence-transformers torch scikit-learn numpy tqdm \
  streamlit plotly pytest

# Populate SQLite database from existing JSON sessions
.venv/Scripts\python.exe .cursor/hooks/narratives_db.py --backfill
```

### Usage

```bash
# Start the summarizer daemon (auto-starts on sessionStart via hooks.json)
.venv/Scripts\python.exe .cursor/hooks/summarizer_daemon.py --start

# Run sentiment arc analysis
.venv/Scripts\python.exe run_sentiment_arc.py

# Launch the dashboard
cd .cursor/hooks/dashboard
streamlit run dashboard.py

# View sessions via CLI
.venv/Scripts\python.exe .cursor/hooks/view.py
```

## Architecture

```mermaid
flowchart TD
    Cursor["Cursor IDE"] --> Hooks[".cursor/hooks.json"]
    Hooks -->|"sessionStart"| SessionStart["session_start.py"]
    Hooks -->|"sessionEnd"| SessionEnd["session_end.py"]
    Hooks -->|"preToolUse, postToolUse, etc."| Recorder["ConversationRecorder"]
    Recorder --> SessionJSON["session.json"]
    Recorder --> SQLite["narratives_db.py"]
    SessionEnd -->|"trigger"| Daemon["summarizer_daemon.py"]
    Daemon -->|"invokes"| Summarizer["summarizer_agent.py"]
    Summarizer -->|"writes"| SummaryMD["summary_narrative.md"]
    SessionEnd -->|"check"| ConvSummarizer["conversation_summarizer_agent.py"]
```

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                      Cursor IDE Events                          │
│  sessionStart · toolUse · shellCommand · fileEdit · MCP calls   │
└────────────────────────────┬────────────────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │   Hooks Router   │
                    │  (hooks.json)    │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼──────┐ ┌────▼─────┐ ┌──────▼──────┐
     │  Session JSON │ │  SQLite   │ │  Summarizer │
     │  (Primary)    │ │  (Mirror) │ │   Daemon    │
     └───────────────┘ └──────────┘ └──────┬──────┘
                                           │
                              ┌────────────▼────────────┐
                              │    LangGraph Agent       │
                              │  (StateGraph Pipeline)   │
                              └────────────┬────────────┘
                                           │
                    ┌──────────────────────┼──────────────────────┐
                    │                      │                      │
           ┌────────▼────────┐   ┌────────▼────────┐   ┌────────▼────────┐
           │  Narrative      │   │  Sentiment      │   │  Learning       │
           │  Summaries      │   │  Arc Analysis   │   │  Analyzer       │
           └─────────────────┘   └─────────────────┘   └────────┬────────┘
                                                                │
                                                       ┌────────▼────────┐
                                                       │  Cursor Rules   │
                                                       │  (.mdc files)   │
                                                       └─────────────────┘
```

## Project Structure

```
cursor-learning-harness/
├── .cursor/
│   ├── hooks/                  # Hook scripts (Python)
│   │   ├── session_start.py    # Session initialization
│   │   ├── session_end.py      # Session finalization
│   │   ├── summarizer_agent.py # LangGraph summarization
│   │   ├── narratives_db.py    # SQLite database ops
│   │   ├── learning_analyzer.py# Pattern extraction
│   │   └── dashboard/          # Streamlit dashboard
│   ├── rules/                  # Auto-generated learning rules
│   ├── skills/                 # Agent skill definitions
│   └── hooks.json              # Event routing configuration
├── assets/                     # Repository graphics
├── DOCS.md                     # Full documentation (1600+ lines)
├── README.md                   # This file
└── .venv/                      # Python virtual environment
```

## Sentiment Arc Analysis

Classifies sessions into archetypes based on emotional trajectory:

- **Smooth convergence** -- session resolved cleanly
- **Escalating frustration** -- things get worse over time
- **Looping** -- agent repeats failed approaches
- **Mismatched effort** -- user is clear but agent relevance degrades
- **Rapid resolution, steady friction, abandoned, inconclusive**

Uses `cardiffnlp/twitter-roberta-base-sentiment-latest` for per-turn sentiment scoring and `sentence-transformers/all-MiniLM-L6-v2` for geometric features (user self-distance, model relevance trend).

```bash
.venv/Scripts\python.exe run_sentiment_arc.py
```

## Learning Loop

The learning analyzer extracts patterns from session telemetry and generates Cursor rules (`.mdc` format) to improve agent behavior over time:

1. **Extract** -- tool failures, file hotspots, sentiment patterns, subagent patterns, user corrections, and more
2. **Score** -- correlate rules with sentiment outcomes (positive/negative effectiveness)
3. **Prune** -- remove noise, cap at 25 active rules
4. **Apply** -- rules auto-apply via `.cursor/rules/learning-critical.mdc`

```bash
.venv/Scripts\python.exe .cursor/hooks/learning_analyzer.py --bootstrap
```

See [DOCS.md](DOCS.md) for full documentation including hooks system architecture, database schema details, skills system, MCP integration, CLI tools, and troubleshooting.

## Setup Social Preview

To enable the social preview image for this repository:

1. Go to **Settings** > **Social Preview** in your GitHub repository
2. Click **Edit** and upload `assets/social-preview.png` (1280x640)
3. This image will appear when sharing the repo on Twitter, Discord, etc.

---

<p align="center">
  <span style="color:#8b949e;font-size:13px;font-family:system-ui,sans-serif;">Built with</span><br>
  <span style="display:inline-block;padding:3px 10px;margin:2px;background:#10b98122;border:1px solid #10b98155;border-radius:4px;color:#34d399;font-size:12px;font-family:system-ui,sans-serif;">LangGraph</span>
  <span style="display:inline-block;padding:3px 10px;margin:2px;background:#10b98122;border:1px solid #10b98155;border-radius:4px;color:#34d399;font-size:12px;font-family:system-ui,sans-serif;">LangChain</span>
  <span style="display:inline-block;padding:3px 10px;margin:2px;background:#3b82f622;border:1px solid #3b82f655;border-radius:4px;color:#60a5fa;font-size:12px;font-family:system-ui,sans-serif;">Python</span>
  <span style="display:inline-block;padding:3px 10px;margin:2px;background:#f9731622;border:1px solid #f9731655;border-radius:4px;color:#fb923c;font-size:12px;font-family:system-ui,sans-serif;">SQLite</span>
</p>

<p align="center">
  <a href="#cursor-learning-harness">Back to top</a>
</p>

## License

MIT
