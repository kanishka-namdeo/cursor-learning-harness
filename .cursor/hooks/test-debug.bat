@echo off
set HOOKS_DIR=%~dp0state
echo [%date% %time%] HOOK TRIGGERED: beforeShellExecution >> "%HOOKS_DIR%\hooks-test.log"
echo. >> "%HOOKS_DIR%\hooks-test.log"
