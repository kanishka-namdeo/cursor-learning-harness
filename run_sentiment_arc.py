#!/usr/bin/env python
"""
Entry point for sentiment arc batch analysis.

Run from the workspace root:
    .venv/Scripts/python.exe run_sentiment_arc.py [--dry-run] [--limit N] [--session-id UUID]
"""

import sys
from pathlib import Path

# Add workspace root to path so .cursor package is importable
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

# Import via absolute path since .cursor starts with a dot
import importlib.util
hooks_root = project_root / ".cursor" / "hooks"
sys.path.insert(0, str(hooks_root))

from sentiment_arc.batch_runner import main

if __name__ == "__main__":
    sys.exit(main())
