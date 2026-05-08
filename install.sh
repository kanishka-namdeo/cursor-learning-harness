#!/usr/bin/env bash
set -e

echo "Setting up Cursor Learning Harness..."

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3.13+ is required. Please install Python first."
    echo "Download from https://www.python.org/downloads/"
    exit 1
fi

# Create virtual environment
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate and install dependencies
source .venv/bin/activate
echo "Installing dependencies..."
pip install -e ".[dashboard,ml]"

# Set up LLM config if missing
if [ ! -f ".cursor/llm.env" ]; then
    cp .cursor/llm.env.example .cursor/llm.env
    echo ""
    echo "Created .cursor/llm.env - please edit it with your API key"
fi

# Ensure state directory exists
mkdir -p .cursor/hooks/state
touch .cursor/hooks/state/.gitkeep

echo ""
echo "Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit .cursor/llm.env with your LLM API key"
echo "  2. Open this project in Cursor - hooks auto-activate on session start"
echo "  3. Launch dashboard: streamlit run .cursor/hooks/dashboard/dashboard.py"
echo ""
