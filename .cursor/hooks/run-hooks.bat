@echo off
REM Hook runner for Windows - redirects to Python
set HOOK_SCRIPT=%~1
if defined HOOK_SCRIPT (
  d:\test_agent\learning_agent\.venv\Scripts\python.exe "%HOOK_SCRIPT%"
)
