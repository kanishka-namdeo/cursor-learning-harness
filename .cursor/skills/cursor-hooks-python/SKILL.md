# SKILL.md: Cursor Hooks with Python

## Description

Expertise in building Cursor hooks using Python, covering JSON input/output handling, YAML parsing for manifest validation, rich library usage for complex data processing, and Python-specific patterns for security guards, access control, and data transformation hooks.

## When to Use

- User needs rich parsing libraries (YAML, JSON Schema, regex) for hook logic
- Building hooks that require structured data validation (Kubernetes manifests, config files)
- When Bash is too limited for parsing complex formats
- Leveraging Python's extensive ecosystem for security scanning, data analysis, or format conversion
- Cross-platform hook scripts that need consistent behavior across OSes

## Capabilities

- Parse complex file formats (YAML, JSON, TOML, XML) with mature Python libraries
- Implement schema validation for hook input/output
- Use Python's regex engine for advanced pattern matching
- Integrate with external APIs for security scanning or data enrichment
- Handle encoding/decoding edge cases robustly
- Build production-ready hooks with comprehensive error handling

## Prerequisites

### Required Setup

**Python 3.8+**:
```bash
# Verify installation
python3 --version
```

**Virtual Environment** (recommended):
```bash
python3 -m venv .cursor/hooks/.venv
source .cursor/hooks/.venv/bin/activate  # Linux/macOS
.cursor\hooks\.venv\Scripts\activate     # Windows
```

**Common Dependencies**:
```bash
pip install pyyaml jsonschema requests
```

### Script Setup

**Shebang**:
```python
#!/usr/bin/env python3
# Always start with proper shebang
```

**Make Executable**:
```bash
chmod +x .cursor/hooks/script.py
```

## Core Patterns

### Pattern 1: Read and Parse JSON Input

```python
#!/usr/bin/env python3
import json
import sys

def main():
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(json.dumps({
            'error': f'Invalid JSON: {e}',
            'permission': 'allow'  # Fail-open
        }))
        sys.exit(0)

    # Access hook-specific fields
    command = payload.get('command', '')
    cwd = payload.get('cwd', '.')

    # Process and respond
    print(json.dumps({'permission': 'allow'}))

if __name__ == '__main__':
    main()
```

### Pattern 2: YAML Manifest Validation (Kubernetes Guard)

Complete example from Cursor docs - validates Kubernetes manifests before `kubectl apply`:

```python
#!/usr/bin/env python3
import json
import shlex
import sys
from pathlib import Path

import yaml

SENSITIVE_NAMESPACES = {"prod", "production"}

def main() -> None:
    payload = json.load(sys.stdin)
    command = payload.get("command", "")
    cwd = Path(payload.get("cwd") or ".")
    response = {"continue": True, "permission": "allow"}

    try:
        args = shlex.split(command)
    except ValueError:
        print(json.dumps(response))
        return

    # Only intercept kubectl apply -f
    if len(args) < 2 or args[0] != "kubectl" or args[1] != "apply" or "-f" not in args:
        print(json.dumps(response))
        return

    f_index = args.index("-f")
    if f_index + 1 >= len(args):
        print(json.dumps(response))
        return

    manifest_arg = args[f_index + 1]
    manifest_path = (cwd / manifest_arg).resolve()

    if not manifest_path.exists():
        print(json.dumps(response))
        return

    # Check CLI namespace flag
    cli_namespace = None
    for i, arg in enumerate(args):
        if arg in ("-n", "--namespace") and i + 1 < len(args):
            cli_namespace = args[i + 1]
        elif arg.startswith("--namespace="):
            cli_namespace = arg.split("=", 1)[1]
        elif arg.startswith("-n="):
            cli_namespace = arg.split("=", 1)[1]

    # Parse and inspect YAML manifests
    try:
        documents = list(yaml.safe_load_all(manifest_path.read_text()))
    except (OSError, yaml.YAMLError) as exc:
        sys.stderr.write(f"Failed to read/parse {manifest_path}: {exc}\n")
        print(json.dumps(response))
        return

    if cli_namespace in SENSITIVE_NAMESPACES or any(
        (doc or {}).get("metadata", {}).get("namespace") in SENSITIVE_NAMESPACES
        for doc in documents
    ):
        response.update(
            {
                "permission": "ask",
                "user_message": "kubectl apply to prod requires manual approval.",
                "agent_message": f"{manifest_path.name} includes protected namespaces; confirm with your team before continuing.",
            }
        )

    print(json.dumps(response))

if __name__ == "__main__":
    main()
```

**Configuration**:
```json
{
  "hooks": {
    "beforeShellExecution": [
      {
        "command": "python3 .cursor/hooks/kube_guard.py"
      }
    ]
  }
}
```

Install PyYAML (for example, `pip install pyyaml`) wherever your hook scripts run so the parser import succeeds.

### Pattern 3: JSON Schema Validation

```python
#!/usr/bin/env python3
import json
import sys
from jsonschema import validate, ValidationError

# Define expected schema for beforeShellExecution input
SCHEMA = {
    "type": "object",
    "required": ["command"],
    "properties": {
        "command": {"type": "string"},
        "cwd": {"type": "string"},
        "sandbox": {"type": "boolean"}
    }
}

def main():
    try:
        payload = json.load(sys.stdin)
        validate(instance=payload, schema=SCHEMA)
    except ValidationError as e:
        print(json.dumps({
            'permission': 'deny',
            'user_message': f'Invalid hook input: {e.message}'
        }))
        sys.exit(0)
    except json.JSONDecodeError:
        print(json.dumps({'permission': 'allow'}))
        sys.exit(0)

    # Process validated payload
    command = payload['command']

    # Your validation logic here
    print(json.dumps({'permission': 'allow'}))

if __name__ == '__main__':
    main()
```

### Pattern 4: Secret Detection with Regex

```python
#!/usr/bin/env python3
import json
import sys
import re

SECRET_PATTERNS = [
    (r'(?i)(aws_secret|aws_access).{0,20}[=:].{0,40}', 'AWS Credentials'),
    (r'(?i)(api[_-]?key|apikey).{0,20}[=:].{0,40}', 'API Key'),
    (r'(?i)(password|passwd|pwd).{0,20}[=:].{0,40}', 'Password'),
    (r'-----BEGIN (RSA |EC )?PRIVATE KEY', 'Private Key'),
    (r'ghp_[a-zA-Z0-9]{36}', 'GitHub Personal Token'),
    (r'sk-[a-zA-Z0-9]{48}', 'OpenAI API Key'),
]

def scan_secrets(text):
    found = []
    for pattern, name in SECRET_PATTERNS:
        if re.search(pattern, text):
            found.append(name)
    return found

def main():
    payload = json.load(sys.stdin)
    content = payload.get('content', '')

    secrets = scan_secrets(content)
    if secrets:
        print(json.dumps({
            'permission': 'deny',
            'user_message': f'Potential secrets detected: {", ".join(secrets)}',
            'agent_message': f'Detected sensitive patterns: {secrets}. Use environment variables or secret management instead.'
        }))
    else:
        print(json.dumps({'permission': 'allow'}))

if __name__ == '__main__':
    main()
```

**Configuration** (for `beforeReadFile` hook):
```json
{
  "hooks": {
    "beforeReadFile": [
      {
        "command": "python3 .cursor/hooks/secret-scan.py",
        "failClosed": true
      }
    ]
  }
}
```

### Pattern 5: HTTP Integration for External Validation

```python
#!/usr/bin/env python3
import json
import sys
import urllib.request
import urllib.error

VALIDATION_URL = "https://api.example.com/validate-command"

def main():
    payload = json.load(sys.stdin)
    command = payload.get('command', '')

    # Skip validation for safe commands
    if command.startswith(('ls ', 'cat ', 'echo ')):
        print(json.dumps({'permission': 'allow'}))
        return

    # Validate risky commands externally
    try:
        data = json.dumps({'command': command}).encode('utf-8')
        req = urllib.request.Request(
            VALIDATION_URL,
            data=data,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read())

        if result.get('safe'):
            print(json.dumps({'permission': 'allow'}))
        else:
            print(json.dumps({
                'permission': 'deny',
                'user_message': f'Command blocked: {result.get("reason", "security policy")}'
            }))

    except (urllib.error.URLError, TimeoutError):
        # Fail-open on network errors
        print(json.dumps({
            'permission': 'allow',
            'warning': 'External validation unavailable'
        }))

if __name__ == '__main__':
    main()
```

## Complete Examples

### Example 1: PII Detection Hook

```python
#!/usr/bin/env python3
"""Detect PII in files before they're sent to the model."""
import json
import sys
import re

PII_PATTERNS = [
    (r'\b\d{3}-\d{2}-\d{4}\b', 'SSN'),
    (r'\b\d{16}\b', 'Credit Card'),
    (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', 'Email'),
    (r'\b\d{3}-\d{3}-\d{4}\b', 'Phone Number'),
]

def scan_pii(text):
    found = []
    for pattern, type_ in PII_PATTERNS:
        matches = re.findall(pattern, text)
        if matches:
            found.append(f'{type_} ({len(matches)} found)')
    return found

def main():
    payload = json.load(sys.stdin)
    content = payload.get('content', '')

    pii = scan_pii(content)
    if pii:
        print(json.dumps({
            'permission': 'ask',
            'user_message': f'Potential PII detected: {", ".join(pii)}',
            'agent_message': 'Consider using placeholder data or encryption for PII'
        }))
    else:
        print(json.dumps({'permission': 'allow'}))

if __name__ == '__main__':
    main()
```

### Example 2: TOML Config Validator

```python
#!/usr/bin/env python3
"""Validate TOML configuration files before the agent reads them."""
import json
import sys
import tomllib  # Python 3.11+

def main():
    payload = json.load(sys.stdin)
    file_path = payload.get('file_path', '')
    content = payload.get('content', '')

    # Only validate TOML files
    if not file_path.endswith('.toml'):
        print(json.dumps({'permission': 'allow'}))
        return

    try:
        tomllib.loads(content)
        print(json.dumps({'permission': 'allow'}))
    except tomllib.TOMLDecodeError as e:
        print(json.dumps({
            'permission': 'deny',
            'user_message': f'Invalid TOML file: {e}'
        }))

if __name__ == '__main__':
    main()
```

### Example 3: Compliance Report Generator (postToolUse)

```python
#!/usr/bin/env python3
"""Parse and aggregate compliance data from hook events."""
import json
import sys
from datetime import datetime
from pathlib import Path

REPORT_DIR = Path('.cursor/hooks/state')
REPORT_FILE = REPORT_DIR / 'compliance-report.json'

def main():
    payload = json.load(sys.stdin)
    tool_name = payload.get('tool_name', '')
    tool_input = payload.get('tool_input', {})
    duration = payload.get('duration', 0)

    # Load existing report
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    if REPORT_FILE.exists():
        report = json.loads(REPORT_FILE.read_text())
    else:
        report = {'events': [], 'total_duration_ms': 0}

    # Append event
    event = {
        'timestamp': datetime.now().isoformat(),
        'tool': tool_name,
        'duration_ms': duration,
    }
    report['events'].append(event)
    report['total_duration_ms'] += duration

    # Keep only last 1000 events
    report['events'] = report['events'][-1000:]

    REPORT_FILE.write_text(json.dumps(report, indent=2))

    # No output needed for postToolUse audit
    print(json.dumps({}))

if __name__ == '__main__':
    main()
```

## Error Handling

### Graceful Degradation

```python
#!/usr/bin/env python3
import json
import sys

def safe_main():
    try:
        payload = json.load(sys.stdin)
        # Process payload
        print(json.dumps({'permission': 'allow'}))
    except json.JSONDecodeError as e:
        # Log to stderr, fail-open
        print(f'[hook] JSON error: {e}', file=sys.stderr)
        print(json.dumps({'permission': 'allow'}))
    except Exception as e:
        print(f'[hook] Error: {e}', file=sys.stderr)
        print(json.dumps({'permission': 'allow'}))

if __name__ == '__main__':
    safe_main()
```

### Timeout Configuration

```json
{
  "hooks": {
    "beforeShellExecution": [
      {
        "command": "python3 .cursor/hooks/validate.py",
        "timeout": 10
      }
    ]
  }
}
```

### Fail-Closed Configuration

For security-critical hooks:
```json
{
  "hooks": {
    "beforeMCPExecution": [
      {
        "command": "python3 .cursor/hooks/security-check.py",
        "failClosed": true
      }
    ]
  }
}
```

## Debugging

### Local Testing

```bash
# Create test input
echo '{"command": "kubectl apply -f deploy.yaml"}' > test-input.json

# Run hook
cat test-input.json | python3 .cursor/hooks/kube_guard.py

# Check output
echo "Exit code: $?"
```

### Logging

```python
import logging
import sys

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    stream=sys.stderr  # Use stderr to avoid stdout pollution
)

logging.debug(f'Hook input: {payload}')
```

### Environment Variables

```python
import os

log_level = os.environ.get('HOOK_LOG_LEVEL', 'info')
validation_url = os.environ.get('VALIDATION_URL')
```

## Commands

`/hooks-py-setup`: Set up Python hooks with virtual environment  
`/hooks-py-validate`: Create YAML/JSON validation hook  
`/hooks-py-secrets`: Create secret detection hook  
`/hooks-py-compliance`: Create compliance reporting hook  

## Workflows

### Creating a New Python Hook

1. **Install Dependencies**:
   ```bash
   pip install pyyaml  # or other needed packages
   ```

2. **Create Script**:
   ```python
   #!/usr/bin/env python3
   import json
   import sys

   def main():
       payload = json.load(sys.stdin)
       # Process payload
       print(json.dumps({'permission': 'allow'}))

   if __name__ == '__main__':
       main()
   ```

3. **Make Executable**:
   ```bash
   chmod +x .cursor/hooks/my-hook.py
   ```

4. **Configure hooks.json**:
   ```json
   {
     "hooks": {
       "beforeShellExecution": [
         {
           "command": "python3 .cursor/hooks/my-hook.py",
           "timeout": 10
         }
       ]
     }
   }
   ```

5. **Test**: Run with sample JSON input

### Adding Schema Validation

1. **Define Schema**:
   ```python
   from jsonschema import validate

   SCHEMA = {"type": "object", "required": ["command"]}
   ```

2. **Validate Input**:
   ```python
   payload = json.load(sys.stdin)
   validate(instance=payload, schema=SCHEMA)
   ```

3. **Handle Errors**:
   ```python
   except ValidationError as e:
       print(json.dumps({'permission': 'deny', 'user_message': str(e)}))
   ```

## Security Considerations

### Critical Security Rules

✅ **ALWAYS DO**:
- Validate all input with try/except
- Use `failClosed: true` for security hooks
- Log security decisions to stderr
- Use virtual environments to pin dependencies
- Validate file paths before accessing filesystem

❌ **NEVER DO**:
- Use `exec()` or `eval()` on hook input
- Store secrets in hook scripts
- Skip error handling
- Use `subprocess.run(shell=True)` with untrusted input
- Expose sensitive data in stdout

### Input Sanitization

```python
# Safe: parse with json.load
payload = json.load(sys.stdin)
command = payload.get('command', '')

# Unsafe: don't do this
import ast
payload = ast.literal_eval(sys.stdin.read())  # Can be exploited
```

## Performance Resources

**Optimization Tips**:
- Use `json.load(sys.stdin)` directly (faster than reading then parsing)
- Minimize imports in hook entry point
- Set appropriate timeouts (10-30s)
- Use matchers to reduce invocations
- Prefer built-in libraries over third-party when possible

**Python Advantages**:
- Rich ecosystem of parsing/validation libraries
- Cross-platform consistency
- Excellent regex engine
- Mature error handling patterns
- JSON Schema support via `jsonschema`

## Testing Resources

**Testing Strategy**:
1. Unit test validation logic with `pytest`
2. Integration test with sample JSON input
3. Test error scenarios (malformed JSON, missing fields)
4. Verify fail-open vs fail-closed behavior

**Example Test**:
```python
# .cursor/hooks/__tests__/test_kube_guard.py
import json
import subprocess
import pytest

def test_allows_safe_command():
    result = subprocess.run(
        ['python3', '.cursor/hooks/kube_guard.py'],
        input=json.dumps({'command': 'ls', 'cwd': '/test'}),
        capture_output=True, text=True
    )
    output = json.loads(result.stdout)
    assert output['permission'] == 'allow'

def test_asks_for_prod_namespace():
    # Create a test manifest with prod namespace
    result = subprocess.run(
        ['python3', '.cursor/hooks/kube_guard.py'],
        input=json.dumps({
            'command': 'kubectl apply -f test-manifest.yaml',
            'cwd': '/test'
        }),
        capture_output=True, text=True
    )
    output = json.loads(result.stdout)
    assert output['permission'] in ('ask', 'allow')
```

## References

- Official Docs: https://cursor.com/docs/agent/hooks
- PyYAML: https://pyyaml.org/
- JSON Schema: https://python-jsonschema.readthedocs.io/
- Python json module: https://docs.python.org/3/library/json.html

## Related Skills

- See `.cursor/skills/cursor-hooks-core/SKILL.md` for hooks fundamentals
- See `.cursor/skills/cursor-hooks-bash/SKILL.md` for simple script hooks
- See `.cursor/skills/cursor-hooks-python/SKILL.md` for Python hooks
- See `.cursor/skills/cursor-hooks-security/SKILL.md` for security scanning patterns
