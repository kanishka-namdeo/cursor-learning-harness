# Contributing to Cursor Learning Harness

Thank you for contributing! This project hooks into Cursor IDE's event lifecycle to capture AI coding sessions and improve agent behavior over time.

## Development Setup

```bash
python -m venv .venv
.venv/Scripts\python.exe -m pip install -r .cursor/hooks/requirements.txt
.venv/Scripts\python.exe -m pip install sentence-transformers torch scikit-learn numpy tqdm streamlit plotly pytest
```

## Running Tests

```bash
pytest
```

## Architecture Overview

See [DOCS.md](DOCS.md) for full documentation including:
- Hooks system architecture
- Database schema (SQLite, 11 tables, schema v8)
- Skills system (20+ specialized skill files)
- MCP integration (11 configured servers)
- CLI tools and troubleshooting

## Code Style

This project uses Ruff for linting and formatting:

```bash
ruff check .
ruff format .
```

## Adding Hooks

New hooks should be added to `.cursor/hooks.json`. See existing hooks for patterns.
All hooks must:
- Output `{"permission": "allow"}` on success
- Be fail-open (never block the Cursor agent workflow on error)
- Write diagnostics to stderr on failure
