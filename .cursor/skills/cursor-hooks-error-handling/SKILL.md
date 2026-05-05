# SKILL.md: Cursor Hooks Error Handling

## Description
Expertise in robust Cursor hooks error handling, covering fail-open vs fail-closed configurations, timeout handling, crash recovery, invalid JSON handling, logging, and debugging strategies.

## When to Use
- User needs production-ready hooks
- Implementing security-critical hooks
- Handling edge cases and failures
- Debugging hook execution issues
- Creating resilient hook architectures

## Capabilities
- Configure fail-open vs fail-closed
- Handle timeouts gracefully
- Recover from crashes
- Validate JSON input
- Implement comprehensive logging
- Debug hook execution issues

## Error Handling Patterns

### Pattern 1: Fail-Closed Configuration

```json
{
  "hooks": {
    "beforeMCPExecution": [
      {
        "command": "./hooks/security-check.sh",
        "failClosed": true,  // Block if hook fails
        "timeout": 10
      }
    ],
    "beforeReadFile": [
      {
        "command": "./hooks/access-control.sh",
        "failClosed": true  // Block file reads on error
      }
    ]
  }
}
```

**When to Use**:
- Security-critical validations
- Access control checks
- Compliance requirements

### Pattern 2: Fail-Open (Default)

```json
{
  "hooks": {
    "afterFileEdit": [
      {
        "command": "./hooks/format.sh"
        // failClosed: false (default)
        // Formatting failure shouldn't block workflow
      }
    ]
  }
}
```

**When to Use**:
- Non-critical hooks (formatting, logging)
- Best-effort validations
- Performance optimizations

### Pattern 3: Graceful Timeout Handling

```bash
#!/bin/bash
# .cursor/hooks/timeout-safe.sh

# Set trap for timeout
trap 'echo "{\"error\": \"timeout\"}"; exit 1' TERM

input=$(cat)

# Long-running operation with timeout
if ! result=$(timeout 5s some_operation "$input" 2>&1); then
  # Timeout occurred
  echo '{"permission": "allow", "warning": "Validation timeout"}'
  exit 0
fi

echo "$result"
exit 0
```

**Configuration**:
```json
{
  "hooks": {
    "beforeShellExecution": [
      {
        "command": "./hooks/timeout-safe.sh",
        "timeout": 10
      }
    ]
  }
}
```

### Pattern 4: Invalid JSON Handling

```python
#!/usr/bin/env python3
# .cursor/hooks/safe-json.py

import json
import sys

def main():
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        # Log error but don't crash
        print(json.dumps({
            'error': f'Invalid JSON: {str(e)}',
            'permission': 'allow'  # Fail-open
        }), file=sys.stdout)
        sys.exit(0)
    except Exception as e:
        print(json.dumps({
            'error': str(e),
            'permission': 'allow'
        }), file=sys.stdout)
        sys.exit(0)
    
    # Process valid payload
    print(json.dumps({'permission': 'allow'}))

if __name__ == '__main__':
    main()
```

### Pattern 5: Comprehensive Logging

```bash
#!/bin/bash
# .cursor/hooks/debug-logging.sh

set -euo pipefail

# Enable debug logging
exec 2>> /tmp/hooks-debug.log
set -x  # Print commands

log() {
  echo "[$(date -Iseconds)] $*" >&2
}

log "Hook started"
log "PWD: $(pwd)"
log "Environment:"
env | grep -E '^CURSOR|^CLAUDE' >&2

input=$(cat)
log "Input: $input"

# Validate input
if ! echo "$input" | jq . >/dev/null 2>&1; then
  log "ERROR: Invalid JSON input"
  echo '{"error": "invalid input", "permission": "allow"}'
  exit 0
fi

command=$(echo "$input" | jq -r '.command')
log "Command: $command"

# Process command
log "Processing complete"
echo '{"permission": "allow"}'
exit 0
```

### Pattern 6: Crash Recovery

```typescript
// .cursor/hooks/crash-safe.ts
import { stdin } from 'bun';

async function safeMain() {
  try {
    const input = await parseInput();
    await processHook(input);
    writeOutput({ permission: 'allow' });
  } catch (error) {
    // Log error
    console.error('[hook] Error:', error);
    
    // Write safe output
    writeOutput({
      error: error.message,
      permission: 'allow'  // Fail-open
    });
  }
}

async function processHook(input: any) {
  // Your hook logic here
  // May throw exceptions
}

safeMain();
```

## Debugging Strategies

### Strategy 1: Hook Output Channel

**View in Cursor**:
1. Open Output panel (Cmd+Shift+P → "View: Toggle Output")
2. Select "Hooks" channel
3. View hook execution logs

### Strategy 2: Manual Testing

```bash
# Create test input
cat > test-input.json << 'EOF'
{
  "command": "test command",
  "cwd": "/test",
  "sandbox": false
}
EOF

# Run hook
cat test-input.json | .cursor/hooks/my-hook.sh
echo "Exit code: $?"
```

### Strategy 3: Log Analysis

```bash
# View recent logs
tail -f /tmp/hooks-debug.log

# Filter errors
grep ERROR /tmp/hooks-debug.log

# Count invocations
grep "Hook started" /tmp/hooks-debug.log | wc -l
```

## Commands

`/hooks-error-debug`: Enable debug logging  
`/hooks-error-safe`: Create crash-safe hook  
`/hooks-error-logging`: Set up comprehensive logging  

## Workflows

### Implementing Error Handling

1. **Identify Criticality**: Security vs non-critical?
2. **Choose Mode**: fail-closed vs fail-open
3. **Add Validation**: JSON, input validation
4. **Handle Errors**: Try-catch, graceful degradation
5. **Add Logging**: Debug and audit logs
6. **Test Failures**: Simulate errors, verify behavior

### Debugging Hook Issues

1. **Enable Logging**: Add debug output
2. **Reproduce Issue**: Trigger hook manually
3. **Check Output**: View Hooks output channel
4. **Examine Logs**: Review debug logs
5. **Fix and Retest**: Iterate until resolved

## Security Considerations

✅ **ALWAYS DO**:
- Set failClosed for security hooks
- Validate all input
- Log security decisions
- Handle exceptions gracefully
- Test error scenarios

❌ **NEVER DO**:
- Crash without output
- Expose sensitive data in logs
- Skip input validation
- Ignore timeout handling
- Use fail-open for security

## References

- Official Docs: https://cursor.com/docs/agent/hooks#configuration

## Related Skills

- See `.cursor/skills/cursor-hooks-core/SKILL.md` for fundamentals
- See `.cursor/skills/cursor-hooks-security/SKILL.md` for security patterns
