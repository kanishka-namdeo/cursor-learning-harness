"""Configure Python path so tests can import sentiment_arc modules."""

import sys
from pathlib import Path

# Add the hooks directory to sys.path so sentiment_arc can be imported
_HOOKS_DIR = Path(__file__).parent
if str(_HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(_HOOKS_DIR))
