# SKILL.md: Windows-Specific Cursor Hook Development

## Description

Windows-specific patterns for Cursor hooks development, covering PowerShell scripts, batch files, Windows path handling, Python on Windows, and cross-platform compatibility strategies.

## When to Use

- Developing hooks on Windows where bash is not available
- Writing PowerShell or batch script hooks
- Handling Windows-specific path formats and permissions
- Dealing with CRLF line endings in hook scripts
- Setting up Python virtual environments on Windows
- Troubleshooting hook execution issues on Windows

## Capabilities

- Write PowerShell hooks as alternatives to bash scripts
- Handle Windows path conventions and UNC paths
- Configure Python execution on Windows without shebangs
- Create batch scripts for simple hook logic
- Manage environment variables in Windows format
- Handle Windows file locking and process detection
- Ensure cross-platform compatibility where needed

## Windows Path Conventions

### Absolute Paths in hooks.json

Windows hooks.json uses absolute paths with backslashes. Your current setup uses full Python executable paths:

```json
{
  "hooks": {
    "sessionStart": [
      {
        "command": "C:\\Users\\kanis\\AppData\\Local\\Python\\pythoncore-3.13-64\\python.exe d:\\test_misc\\job_network\\.cursor\\hooks\\session_start.py"
      }
    ]
  }
}
```

**Key Rules**:
- Escape backslashes in JSON: `\\` not `\`
- Use full Python executable path on Windows (no shebang support)
- Quote paths with spaces: `"C:\\Program Files\\Python\\python.exe"`
- Prefer forward slashes in Python code: `Path("d:/test_misc/job_network")` works on Windows

### Path Handling in Python Hooks

```python
from pathlib import Path
import os

# Windows-safe path operations
STATE_DIR = Path("d:/test_misc/job_network/.cursor/hooks/state")
# pathlib automatically handles Windows backslashes internally

# Normalize paths for comparison
normalized = os.path.normpath("d:\\test_misc\\job_network\\.cursor\\hooks")
# Returns: d:\test_misc\job_network\.cursor\hooks

# Check if path is within a directory (prevent traversal)
def is_within_directory(path: Path, directory: Path) -> bool:
    """Check if resolved path is within the specified directory."""
    resolved_path = path.resolve()
    resolved_dir = directory.resolve()
    try:
        resolved_path.relative_to(resolved_dir)
        return True
    except ValueError:
        return False
```

## Core Patterns

### Pattern 1: PowerShell Hook Scripts

PowerShell alternatives to bash hooks.

```powershell
# .cursor/hooks/block-dangerous.ps1

# Read JSON from stdin
$input = $Input | Out-String | ConvertFrom-Json

$command = $input.command

# Check for dangerous patterns
if ($command -match "rm\s+-rf|curl.*\|\s*bash|wget.*\|\s*sh") {
    $output = @{
        permission = "deny"
        user_message = "Dangerous command blocked"
        agent_message = "This command pattern is blocked for security"
    }
    $output | ConvertTo-Json -Compress
    exit 2
}

# Allow safe commands
$output = @{ permission = "allow" }
$output | ConvertTo-Json -Compress
exit 0
```

**Configuration in hooks.json**:

```json
{
  "hooks": {
    "beforeShellExecution": [
      {
        "command": "powershell -ExecutionPolicy Bypass -File d:\\test_misc\\job_network\\.cursor\\hooks\\block-dangerous.ps1"
      }
    ]
  }
}
```

### Pattern 2: Batch Script Hooks

Simple batch scripts for basic hook logic.

```batch
REM .cursor/hooks/audit.bat
@echo off

REM Read input from stdin (limited in batch, use for simple cases)
setlocal enabledelayedexpansion

REM Log the hook trigger
echo [%date% %time%] beforeShellExecution triggered >> d:\test_misc\job_network\.cursor\hooks\state\hooks-audit.log

REM Always allow in batch (complex logic needs Python/PowerShell)
echo {"permission": "allow"}
exit /b 0
```

### Pattern 3: Python Shebang Alternatives

Windows does not support Unix shebangs. Use explicit Python paths.

**In hooks.json**:

```json
{
  "command": "C:\\Users\\kanis\\AppData\\Local\\Python\\pythoncore-3.13-64\\python.exe d:\\test_misc\\job_network\\.cursor\\hooks\\my-hook.py"
}
```

**Or use `py` launcher** (if installed):

```json
{
  "command": "py -3 d:\\test_misc\\job_network\\.cursor\\hooks\\my-hook.py"
}
```

**Or use a batch wrapper**:

```batch
REM .cursor/hooks/my-hook.bat
@echo off
"C:\Users\kanis\AppData\Local\Python\pythoncore-3.13-64\python.exe" "d:\test_misc\job_network\.cursor\hooks\my-hook.py" %*
```

Then reference the batch file in hooks.json:

```json
{
  "command": "d:\\test_misc\\job_network\\.cursor\\hooks\\my-hook.bat"
}
```

### Pattern 4: Environment Variables on Windows

Windows environment variables are case-insensitive and use `%VAR%` syntax.

**In Python hooks**:

```python
import os

# All of these work on Windows (case-insensitive)
project_dir = os.environ.get("CURSOR_PROJECT_DIR")
project_dir = os.environ.get("cursor_project_dir")  # Also works

# In hooks.json, pass variables:
# {
#   "command": "set HOOK_DEBUG=1 && python my-hook.py"
# }
```

**In PowerShell hooks**:

```powershell
# Environment variables
$projectDir = $env:CURSOR_PROJECT_DIR
$version = $env:CURSOR_VERSION

# Set variables for subprocess
$env:MY_HOOK_VAR = "value"
```

### Pattern 5: File Locking on Windows

Windows has exclusive file locking by default. Use careful patterns.

```python
import os
import time
from pathlib import Path

def acquire_lock_windows(session_id, state_dir):
    """Acquire lock using Windows-compatible approach."""
    session_dir = state_dir / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    lock_file = session_dir / ".hook_lock"

    # Atomic file creation - fails if exists
    try:
        # On Windows, exclusive create is atomic
        fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, f"{os.getpid()}|{time.time()}".encode())
        os.close(fd)
        return True
    except FileExistsError:
        # Lock exists - check if stale
        try:
            content = lock_file.read_text().strip()
            parts = content.split("|")
            pid = int(parts[0])
            timestamp = float(parts[1])
            elapsed = time.time() - timestamp

            if elapsed < 120 and _is_process_alive(pid):
                return False
            # Stale lock - remove and retry
            lock_file.unlink()
            return acquire_lock_windows(session_id, state_dir)
        except (ValueError, OSError):
            lock_file.unlink()
            return acquire_lock_windows(session_id, state_dir)


def release_lock_windows(session_id, state_dir):
    lock_file = state_dir / "sessions" / session_id / ".hook_lock"
    try:
        lock_file.unlink()
    except OSError:
        pass  # Already removed
```

### Pattern 6: Process Detection on Windows

`os.kill(pid, 0)` works on Windows Python 3.8+. For older versions, use alternatives.

```python
import subprocess
import ctypes

def is_process_alive_windows(pid: int) -> bool:
    """Check if process is running on Windows."""
    try:
        # Python 3.8+ supports os.kill(pid, 0) on Windows
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def get_process_list_windows():
    """Get list of running process IDs."""
    result = []
    try:
        output = subprocess.check_output(
            ["tasklist", "/FO", "CSV", "/NH"],
            text=True
        )
        for line in output.splitlines():
            parts = line.split(",")
            if len(parts) >= 2:
                try:
                    result.append(int(parts[1].strip('"')))
                except ValueError:
                    pass
    except Exception:
        pass
    return result
```

### Pattern 7: Python Virtual Environment on Windows

Setting up and activating venv on Windows.

```powershell
# Create virtual environment
python -m venv .cursor\hooks\.venv

# Activate (PowerShell)
.cursor\hooks\.venv\Scripts\Activate.ps1

# Activate (CMD)
.cursor\hooks\.venv\Scripts\activate.bat

# Install dependencies
pip install -r .cursor\hooks\requirements.txt
```

**Using venv in hooks.json**:

```json
{
  "command": "d:\\test_misc\\job_network\\.cursor\\hooks\\.venv\\Scripts\\python.exe d:\\test_misc\\job_network\\.cursor\\hooks\\my-hook.py"
}
```

### Pattern 8: JSON Handling in PowerShell

Parsing and generating JSON for hook communication.

```powershell
# Parse JSON from stdin (hook input)
$inputJson = $Input | Out-String | ConvertFrom-Json

# Access fields
$command = $inputJson.command
$cwd = $inputJson.cwd
$toolName = $inputJson.tool_name

# Generate JSON output (hook response)
$output = @{
    permission = "allow"
    user_message = "Command approved"
}

# Output as compact JSON
$output | ConvertTo-Json -Compress

# For nested objects, use Depth parameter
$complexOutput = @{
    permission = "allow"
    env = @{
        VAR1 = "value1"
        VAR2 = "value2"
    }
}
$complexOutput | ConvertTo-Json -Depth 3 -Compress
```

## Common Windows Issues and Workarounds

### Issue: CRLF vs LF Line Endings

Windows defaults to CRLF (`\r\n`). This can cause issues with scripts.

**Fix: Set git to handle line endings**:

```bash
git config --global core.autocrlf false
```

**Fix: Explicit encoding in Python**:

```python
# Read with explicit newline handling
with open(file_path, "r", newline="", encoding="utf-8") as f:
    content = f.read()
```

**Fix: Normalize JSON output**:

```python
# Ensure consistent JSON output
import json
print(json.dumps(data, ensure_ascii=False))  # No CRLF issues
```

### Issue: Long Path Limits

Windows has a 260-character path limit by default.

**Workaround: Use short paths or UNC prefixes**:

```python
from pathlib import Path

# Use relative paths when possible
STATE_DIR = Path(".cursor/hooks/state")

# Or use UNC prefix for long paths
long_path = Path("\\\\?\\d:\\test_misc\\job_network\\.cursor\\hooks\\state\\very\\long\\path")
```

### Issue: File Permissions on Windows

Windows ACLs differ from Unix permissions.

**Workaround: Use Python's permission-aware operations**:

```python
import os
import stat
from pathlib import Path

# Make script executable (best effort on Windows)
script_path = Path("d:/test_misc/job_network/.cursor/hooks/my-hook.py")
# On Windows, this is a no-op but doesn't fail
os.chmod(script_path, script_path.stat().st_mode | stat.S_IEXEC)
```

### Issue: PowerShell Execution Policy

PowerShell may block script execution.

**Workaround: Use Bypass flag**:

```json
{
  "command": "powershell -ExecutionPolicy Bypass -File d:\\path\\to\\script.ps1"
}
```

## Cross-Platform Compatibility

### Pattern: Platform Detection

```python
import sys
import platform

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform == "linux"
IS_MACOS = sys.platform == "darwin"

if IS_WINDOWS:
    # Windows-specific logic
    state_dir = Path("d:/test_misc/job_network/.cursor/hooks/state")
else:
    # Unix-specific logic
    state_dir = Path.home() / ".cursor" / "hooks" / "state"
```

### Pattern: Cross-Platform Path Construction

```python
from pathlib import Path
import os

# Use pathlib for cross-platform paths
HOOKS_DIR = Path(__file__).parent
STATE_DIR = HOOKS_DIR / "state"
SESSIONS_DIR = STATE_DIR / "sessions"

# This works on both Windows and Linux
full_path = STATE_DIR / "sessions" / session_id / "session.json"
```

### Pattern: Cross-Platform Subprocess

```python
import subprocess
import sys

if sys.platform == "win32":
    # Windows: use shell=True for complex commands
    result = subprocess.run(
        f"python {script_path}",
        shell=True,
        capture_output=True,
        text=True,
    )
else:
    # Unix: prefer list form
    result = subprocess.run(
        ["python", script_path],
        capture_output=True,
        text=True,
    )
```

## Commands

`/hooks-win-setup`: Set up Windows-specific hook infrastructure
`/hooks-win-ps1`: Convert a bash hook to PowerShell
`/hooks-win-path`: Fix Windows path issues in hooks
`/hooks-win-venv`: Set up Python virtual environment on Windows

## Workflows

### Setting Up a New Windows Hook

1. **Choose Runtime**: Python, PowerShell, or batch
2. **Create Script**: Write hook logic
3. **Configure hooks.json**: Use full paths, escape backslashes
4. **Test**: Run hook with sample input
5. **Verify**: Check Hooks output channel in Cursor

### Converting Bash to PowerShell

1. **Identify Logic**: What does the bash script do?
2. **Map Commands**: Convert bash syntax to PowerShell
3. **Handle JSON**: Use ConvertFrom/ToJson
4. **Test Equivalence**: Run both with same input, compare output
5. **Update hooks.json**: Point to new PowerShell script

### Debugging Windows Hook Issues

1. **Check Python Path**: Verify executable exists and is correct
2. **Check Script Path**: Ensure path exists and is accessible
3. **Run Manually**: Execute hook command from PowerShell/CMD
4. **Check Encoding**: Verify UTF-8 without BOM for scripts
5. **Review Logs**: Check hook-debug.log and stderr output

## Security Considerations

- Never hardcode credentials in hooks.json or scripts
- Use absolute paths to prevent path injection
- Validate all file paths before access (prevent traversal)
- Set PowerShell execution policy to minimum required
- Do not run hooks as Administrator unless necessary
- Be aware that Windows environment variables are user/session-scoped

## Performance Considerations

- PowerShell startup has overhead (~100-500ms)
- Python startup is faster than PowerShell (~50-100ms)
- Batch scripts are fastest but most limited
- Use Python for complex logic, PowerShell for moderate, batch for simple
- Avoid spawning unnecessary subprocesses on Windows

## References

- Python on Windows: https://docs.python.org/3/using/windows.html
- PowerShell documentation: https://learn.microsoft.com/en-us/powershell/
- Windows path limits: https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation

## Related Skills

- See `.cursor/skills/cursor-hooks-core/SKILL.md` for hook lifecycle fundamentals
- See `.cursor/skills/cursor-hooks-python/SKILL.md` for Python hook patterns
- See `.cursor/skills/cursor-hooks-bash/SKILL.md` for bash patterns (Unix)
- See `.cursor/skills/cursor-hooks-security/SKILL.md` for security patterns
