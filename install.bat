@echo off
echo Setting up Cursor Learning Harness...

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.13+ is required. Please install Python first.
    echo Download from https://www.python.org/downloads/
    exit /b 1
)

REM Create virtual environment
if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
)

REM Activate and install dependencies
call .venv\Scripts\activate.bat
echo Installing dependencies...
pip install -e ".[dashboard,ml]"

REM Set up LLM config if missing
if not exist .cursor\llm.env (
    copy .cursor\llm.env.example .cursor\llm.env >nul
    echo.
    echo Created .cursor\llm.env - please edit it with your API key
)

REM Ensure state directory exists
if not exist .cursor\hooks\state (
    mkdir .cursor\hooks\state
)
if not exist .cursor\hooks\state\.gitkeep (
    echo. > .cursor\hooks\state\.gitkeep
)

echo.
echo Setup complete!
echo.
echo Next steps:
echo   1. Edit .cursor\llm.env with your LLM API key
echo   2. Open this project in Cursor - hooks auto-activate on session start
echo   3. Launch dashboard: streamlit run .cursor\hooks\dashboard\dashboard.py
echo.
