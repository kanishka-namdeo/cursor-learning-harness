#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: run-hook.sh <script.py> [args...]" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"

SCRIPT_NAME="$1"
shift

TARGET_SCRIPT="$SCRIPT_DIR/$SCRIPT_NAME"

if [ ! -f "$TARGET_SCRIPT" ]; then
    echo "Error: Hook script not found: $TARGET_SCRIPT" >&2
    exit 1
fi

if [ -x "$VENV_PYTHON" ]; then
    exec "$VENV_PYTHON" "$TARGET_SCRIPT" "$@"
else
    exec python "$TARGET_SCRIPT" "$@"
fi
