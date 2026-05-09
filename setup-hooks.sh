#!/usr/bin/env bash
#
# setup-hooks.sh -- Install Cursor Learning Harness hooks into an existing workspace.
#
# Copies the .cursor/ directory structure (hooks, rules, config) into a target
# workspace so teams can adopt the learning harness mid-project.
#
# Excludes runtime state (sessions, logs, SQLite) and user secrets (llm.env).
# Does NOT create venv or install dependencies -- those are managed by the
# target project's own workflow.
#
# Usage:
#   ./setup-hooks.sh [TARGET_DIR]       # Install into TARGET_DIR (default: current dir)
#   ./setup-hooks.sh --dry-run          # Preview what would be copied
#

set -euo pipefail

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# --- Helpers ---
status()  { echo -e "${CYAN}[SETUP]${NC} $*"; }
ok()      { echo -e "${GREEN}[OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()     { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# --- Parse arguments ---
DRY_RUN=false
TARGET_DIR="."

for arg in "$@"; do
    case "$arg" in
        --dry-run)
            DRY_RUN=true
            ;;
        *)
            TARGET_DIR="$arg"
            ;;
    esac
done

# --- Resolve target directory ---
if [ ! -d "$TARGET_DIR" ]; then
    err "Target directory does not exist: $TARGET_DIR"
    exit 1
fi
TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"
status "Target directory: $TARGET_DIR"

# --- Dry-run mode ---
if [ "$DRY_RUN" = true ]; then
    status "DRY RUN MODE -- no changes will be made"
    echo ""
    echo "The following would be copied into $TARGET_DIR/.cursor/:"
    echo ""
fi

# --- Check Python version ---
status "Checking Python..."
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    err "Python is not installed or not in PATH"
    err "Download from https://www.python.org/downloads/"
    exit 1
fi

PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | sed 's/Python //')
MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [ "$MAJOR" -lt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 13 ]; }; then
    err "Python 3.13+ is required (found $PYTHON_VERSION)"
    err "Download from https://www.python.org/downloads/"
    exit 1
fi
ok "Python $PYTHON_VERSION detected"

# --- Source directory (where this script lives) ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_CURSOR_DIR="$SCRIPT_DIR/.cursor"
if [ ! -d "$SOURCE_CURSOR_DIR" ]; then
    err "Cannot find .cursor/ directory at: $SOURCE_CURSOR_DIR"
    err "Run this script from the root of the cursor-learning-harness repository."
    exit 1
fi

# --- Check for existing .cursor/ in target ---
TARGET_CURSOR_DIR="$TARGET_DIR/.cursor"
MERGE_MODE=false
if [ -d "$TARGET_CURSOR_DIR" ]; then
    warn "A .cursor/ directory already exists in the target workspace."
    echo -n "Merge (skip existing files) or Abort? Type 'merge' or 'abort': "
    read -r CHOICE
    if [ "$CHOICE" = "merge" ]; then
        MERGE_MODE=true
        status "Merge mode: existing files will be preserved."
    else
        status "Aborted by user."
        exit 0
    fi
fi

# --- Copy function ---
copy_file() {
    local src="$1"
    local dest="$2"

    if [ "$DRY_RUN" = true ]; then
        echo "  Would copy: $src -> $dest"
        return
    fi

    # Skip if merge mode and dest already exists
    if [ "$MERGE_MODE" = true ] && [ -f "$dest" ]; then
        status "  Already exists, skipping: $(basename "$dest")"
        return
    fi

    local dest_dir
    dest_dir="$(dirname "$dest")"
    if [ ! -d "$dest_dir" ]; then
        mkdir -p "$dest_dir"
    fi
    cp -f "$src" "$dest"
    status "  Copied: $(basename "$dest")"
}

# --- Copy .cursor/ top-level files ---
status "Copying Cursor Learning Harness hooks..."

# Copy hooks.json
if [ -f "$SOURCE_CURSOR_DIR/hooks.json" ]; then
    copy_file "$SOURCE_CURSOR_DIR/hooks.json" "$TARGET_CURSOR_DIR/hooks.json"
else
    warn "hooks.json not found in source"
fi

# Copy llm.env.example
if [ -f "$SOURCE_CURSOR_DIR/llm.env.example" ]; then
    copy_file "$SOURCE_CURSOR_DIR/llm.env.example" "$TARGET_CURSOR_DIR/llm.env.example"

    # Copy llm.env.example -> llm.env only if llm.env absent
    if [ ! -f "$TARGET_CURSOR_DIR/llm.env" ]; then
        if [ "$DRY_RUN" = true ]; then
            echo "  Would create: $TARGET_CURSOR_DIR/llm.env (from example)"
        else
            cp "$SOURCE_CURSOR_DIR/llm.env.example" "$TARGET_CURSOR_DIR/llm.env"
            status "  Created llm.env from example"
        fi
    else
        status "  Preserving existing llm.env"
    fi
fi

# --- Copy hooks/ directory (excluding state/ and plans/) ---
SOURCE_HOOKS="$SOURCE_CURSOR_DIR/hooks"
TARGET_HOOKS="$TARGET_CURSOR_DIR/hooks"

if [ -d "$SOURCE_HOOKS" ]; then
    status "Copying hooks/ directory..."

    if [ "$DRY_RUN" = true ]; then
        # Just show what would be copied
        (cd "$SOURCE_HOOKS" && find . \
            -not -path './state' -not -path './state/*' \
            -not -path './plans' -not -path './plans/*' \
            -type f) | while read -r f; do
            echo "  Would copy: $f"
        done
    else
        # Ensure target exists
        mkdir -p "$TARGET_HOOKS"

        # Copy everything except state/ and plans/
        (cd "$SOURCE_HOOKS" && find . \
            -not -path './state' -not -path './state/*' \
            -not -path './plans' -not -path './plans/*' \
            -type f) | while read -r f; do
            local_src="$SOURCE_HOOKS/$f"
            local_dest="$TARGET_HOOKS/$f"

            if [ "$MERGE_MODE" = true ] && [ -f "$local_dest" ]; then
                status "  Skipping existing: $f"
                continue
            fi

            local_dest_dir="$(dirname "$local_dest")"
            if [ ! -d "$local_dest_dir" ]; then
                mkdir -p "$local_dest_dir"
            fi
            cp -f "$local_src" "$local_dest"
        done
    fi
fi

# --- Copy rules/ directory ---
SOURCE_RULES="$SOURCE_CURSOR_DIR/rules"
TARGET_RULES="$TARGET_CURSOR_DIR/rules"

if [ -d "$SOURCE_RULES" ]; then
    status "Copying rules/ directory..."

    if [ "$DRY_RUN" = true ]; then
        find "$SOURCE_RULES" -type f | while read -r f; do
            echo "  Would copy: rules/$(basename "$f")"
        done
    else
        mkdir -p "$TARGET_RULES"
        find "$SOURCE_RULES" -type f | while read -r f; do
            fname="$(basename "$f")"
            if [ "$MERGE_MODE" = true ] && [ -f "$TARGET_RULES/$fname" ]; then
                status "  Skipping existing: $fname"
                continue
            fi
            cp -f "$f" "$TARGET_RULES/$fname"
        done
    fi
fi

# --- Copy project-level files ---
for file in pyproject.toml install.bat install.sh; do
    if [ -f "$SCRIPT_DIR/$file" ]; then
        if [ "$DRY_RUN" = true ]; then
            echo "  Would copy: $file"
        else
            cp -f "$SCRIPT_DIR/$file" "$TARGET_DIR/$file"
            status "  Copied: $file"
        fi
    fi
done

# --- Ensure state directory and .gitkeep exist ---
STATE_DIR="$TARGET_HOOKS/state"
if [ "$DRY_RUN" = true ]; then
    echo "  Would create: $STATE_DIR/"
    echo "  Would create: $STATE_DIR/.gitkeep"
else
    mkdir -p "$STATE_DIR"
    if [ ! -f "$STATE_DIR/.gitkeep" ]; then
        touch "$STATE_DIR/.gitkeep"
    fi
fi

# --- Summary ---
if [ "$DRY_RUN" = true ]; then
    echo ""
    status "DRY RUN complete. No changes were made."
else
    echo ""
    ok "Cursor Learning Harness hooks installed successfully!"
    echo ""
    echo -e "Next steps:"
    echo "  1. Edit .cursor/llm.env with your LLM API key"
    echo "  2. Install dependencies:"
    echo "     pip install -e '.[dashboard,ml]'"
    echo "  3. Open the project in Cursor -- hooks auto-activate on session start"
    echo ""
    echo "To launch the dashboard:"
    echo "  streamlit run .cursor/hooks/dashboard/dashboard.py"
fi
echo ""
