# SKILL.md: Cursor Hooks with Bash

## Description
Expertise in building lightweight Cursor hooks using Bash shell scripts, covering JSON parsing with jq, command validation, exit code handling, logging patterns, and quick automation for security gates, audits, and simple validations.

## When to Use
- User needs simple, fast hooks without runtime dependencies
- Implementing quick command validation or blocking
- Creating audit logging hooks
- Setting up basic security gates
- When TypeScript/Python would be overkill for the use case
- Need maximum portability across systems

## Capabilities
- Parse JSON input with jq
- Validate shell commands with regex
- Handle exit codes correctly (0=success, 2=block)
- Implement logging and auditing
- Create JSON output for Cursor
- Chain multiple validation checks
- Debug hook execution issues

## Prerequisites

### Required Tools

**jq** (JSON processor):
```bash
# macOS
brew install jq

# Linux
sudo apt install jq  # Debian/Ubuntu
sudo dnf install jq  # Fedora

# Windows (via WSL or Git Bash)
```

**Verify Installation**:
```bash
jq --version
```

### Script Setup

**Make Executable**:
```bash
chmod +x .cursor/hooks/script.sh
```

**Shebang**:
```bash
#!/bin/bash
# Always start with proper shebang
```

## Core Patterns

### Pattern 1: Read and Parse JSON Input

```bash
#!/bin/bash

# Read JSON from stdin
input=$(cat)

# Parse fields with jq
command=$(echo "$input" | jq -r '.command // empty')
cwd=$(echo "$input" | jq -r '.cwd // empty')

# Use parsed values
echo "Command: $command"
echo "Working directory: $cwd"
```

**Safe Parsing with Defaults**:
```bash
# Use // empty to handle missing fields
command=$(echo "$input" | jq -r '.command // "unknown"')

# Check if field exists
if echo "$input" | jq -e '.command' > /dev/null; then
  command=$(echo "$input" | jq -r '.command')
fi
```

### Pattern 2: Output JSON Response

```bash
#!/bin/bash

# Simple allow response
cat << EOF
{
  "permission": "allow"
}
EOF

# Deny with messages
cat << EOF
{
  "permission": "deny",
  "user_message": "Command blocked for security",
  "agent_message": "Security policy violation detected"
}
EOF

# Ask for approval
cat << EOF
{
  "permission": "ask",
  "user_message": "This command requires approval",
  "agent_message": "Please review and approve this command"
}
EOF
```

**Using jq for Complex Output**:
```bash
#!/bin/bash

permission="allow"
user_message=""

jq -n \
  --arg perm "$permission" \
  --arg msg "$user_message" \
  '{permission: $perm, user_message: $msg}'
```

### Pattern 3: Command Validation

```bash
#!/bin/bash

input=$(cat)
command=$(echo "$input" | jq -r '.command')

# Block dangerous patterns
if [[ "$command" =~ ^rm[[:space:]]+-rf[[:space:]]+/ ]]; then
  cat << EOF
{
  "permission": "deny",
  "user_message": "Recursive delete from root is blocked",
  "agent_message": "Dangerous command pattern: rm -rf /"
}
EOF
  exit 2
fi

# Allow safe commands
echo '{"permission": "allow"}'
exit 0
```

**Multiple Pattern Checks**:
```bash
#!/bin/bash

command=$(cat | jq -r '.command')

# Check 1: Block curl | bash
if [[ "$command" =~ curl.*\|[[:space:]]*(ba)?sh ]]; then
  echo '{"permission": "deny", "user_message": "Piping curl to shell is blocked"}'
  exit 2
fi

# Check 2: Block wget | bash
if [[ "$command" =~ wget.*\|[[:space:]]*(ba)?sh ]]; then
  echo '{"permission": "deny", "user_message": "Piping wget to shell is blocked"}'
  exit 2
fi

# Check 3: Block chmod 777
if [[ "$command" =~ chmod[[:space:]]+777 ]]; then
  echo '{"permission": "deny", "user_message": "Setting world-writable permissions is blocked"}'
  exit 2
fi

# All checks passed
echo '{"permission": "allow"}'
exit 0
```

### Pattern 4: Logging and Auditing

```bash
#!/bin/bash

# audit.sh - Log all hook invocations

timestamp=$(date '+%Y-%m-%d %H:%M:%S')
input=$(cat)

# Create log directory
mkdir -p "$(dirname /tmp/cursor-audit.log)"

# Write timestamped entry
echo "[$timestamp] $input" >> /tmp/cursor-audit.log

# Always allow (audit doesn't block)
echo '{"permission": "allow"}'
exit 0
```

**Structured Logging**:
```bash
#!/bin/bash

input=$(cat)
command=$(echo "$input" | jq -r '.command')
timestamp=$(date -Iseconds)

# JSON log entry
log_entry=$(jq -n \
  --arg ts "$timestamp" \
  --arg cmd "$command" \
  '{timestamp: $ts, command: $cmd, event: "before_shell_execution"}')

echo "$log_entry" >> /tmp/cursor-audit.jsonl

echo '{"permission": "allow"}'
exit 0
```

### Pattern 5: Git Command Blocking

Complete example from Cursor docs:

```bash
#!/bin/bash

# .cursor/hooks/block-git.sh
# Block git commands, suggest using gh CLI instead

echo "Hook execution started" >> /tmp/hooks.log

# Read JSON input
input=$(cat)
echo "Received input: $input" >> /tmp/hooks.log

# Parse command
command=$(echo "$input" | jq -r '.command // empty')
echo "Parsed command: '$command'" >> /tmp/hooks.log

# Check for git commands
if [[ "$command" =~ git[[:space:]] ]] || [[ "$command" == "git" ]]; then
  echo "Git command detected - blocking: '$command'" >> /tmp/hooks.log
  
  cat << EOF
{
  "continue": true,
  "permission": "deny",
  "user_message": "Git command blocked. Please use the GitHub CLI (gh) tool instead.",
  "agent_message": "The git command '$command' has been blocked. Instead use 'gh' CLI:\n- Instead of 'git clone', use 'gh repo clone'\n- Instead of 'git push', use 'gh repo sync'\n- Check for equivalent gh commands for other operations"
}
EOF
  exit 2
  
elif [[ "$command" =~ gh[[:space:]] ]] || [[ "$command" == "gh" ]]; then
  echo "GitHub CLI command detected - asking for permission: '$command'" >> /tmp/hooks.log
  
  cat << EOF
{
  "continue": true,
  "permission": "ask",
  "user_message": "GitHub CLI command requires permission: $command",
  "agent_message": "The command '$command' uses GitHub CLI (gh) which can interact with your repositories. Please review and approve."
}
EOF
  exit 0
  
else
  echo "Non-git/non-gh command - allowing: '$command'" >> /tmp/hooks.log
  echo '{"continue": true, "permission": "allow"}'
  exit 0
fi
```

## Complete Examples

### Example 1: Simple Audit Hook

```bash
#!/bin/bash

# .cursor/hooks/audit.sh
# Logs all hook invocations to /tmp/agent-audit.log

timestamp=$(date '+%Y-%m-%d %H:%M:%S')
json_input=$(cat)

mkdir -p "$(dirname /tmp/agent-audit.log)"
echo "[$timestamp] $json_input" >> /tmp/agent-audit.log

exit 0
```

**Configuration**:
```json
{
  "hooks": {
    "beforeShellExecution": [{ "command": "./hooks/audit.sh" }],
    "afterFileEdit": [{ "command": "./hooks/audit.sh" }],
    "sessionEnd": [{ "command": "./hooks/audit.sh" }]
  }
}
```

### Example 2: Network Command Gate

```bash
#!/bin/bash

# .cursor/hooks/network-gate.sh
# Require approval for network operations

input=$(cat)
command=$(echo "$input" | jq -r '.command')

# List of network commands requiring approval
network_commands=(
  "curl"
  "wget"
  "nc"
  "netcat"
  "scp"
  "rsync"
  "ftp"
  "sftp"
)

# Check if command uses network
for net_cmd in "${network_commands[@]}"; do
  if [[ "$command" =~ ^$net_cmd[[:space:]] ]] || [[ "$command" == "$net_cmd" ]]; then
    cat << EOF
{
  "permission": "ask",
  "user_message": "Network command requires approval: $command",
  "agent_message": "This command makes network calls. Please review the destination and approve if safe."
}
EOF
    exit 0
  fi
done

# Not a network command - allow
echo '{"permission": "allow"}'
exit 0
```

### Example 3: File Edit Formatter

```bash
#!/bin/bash

# .cursor/hooks/format.sh
# Auto-format edited files

input=$(cat)
file_path=$(echo "$input" | jq -r '.file_path')

# Check file extension and format accordingly
if [[ "$file_path" == *.ts ]] || [[ "$file_path" == *.tsx ]]; then
  # TypeScript - run Prettier
  if command -v npx &> /dev/null; then
    npx prettier --write "$file_path" 2>/dev/null
  fi
  
elif [[ "$file_path" == *.py ]]; then
  # Python - run Black
  if command -v black &> /dev/null; then
    black "$file_path" 2>/dev/null
  fi
  
elif [[ "$file_path" == *.go ]]; then
  # Go - run gofmt
  if command -v gofmt &> /dev/null; then
    gofmt -w "$file_path" 2>/dev/null
  fi
fi

# No output needed (fire-and-forget)
echo '{}'
exit 0
```

### Example 4: Destructive Command Blocker

```bash
#!/bin/bash

# .cursor/hooks/block-destructive.sh
# Block potentially destructive commands

input=$(cat)
command=$(echo "$input" | jq -r '.command')

# Destructive patterns
destructive_patterns=(
  "^rm[[:space:]]+-rf[[:space:]]+/"          # rm -rf /
  "^rm[[:space:]]+--no-preserve-root"        # rm --no-preserve-root
  "^:[[:space:]]*{[[:space:]]*:[[:space:]]*|:[[:space:]]*&[[:space:]]*}[[:space:]]*;"  # Fork bomb
  "^mkfs"                                     # Format filesystem
  "^dd[[:space:]].*of=/dev/"                  # Write to block device
  "^chmod[[:space:]]+-R[[:space:]]+777"       # Recursive chmod 777
  "^chown[[:space:]]+-R[[:space:]]+root:root[[:space:]]+/"  # Recursive chown
)

for pattern in "${destructive_patterns[@]}"; do
  if [[ "$command" =~ $pattern ]]; then
    cat << EOF
{
  "permission": "deny",
  "user_message": "Destructive command blocked: $command",
  "agent_message": "This command matches a destructive pattern and has been blocked for safety. Pattern: $pattern"
}
EOF
    exit 2
  fi
done

# All checks passed
echo '{"permission": "allow"}'
exit 0
```

### Example 5: Package Manager Validator

```bash
#!/bin/bash

# .cursor/hooks/package-manager.sh
# Enforce using bun instead of npm/yarn

input=$(cat)
command=$(echo "$input" | jq -r '.command')

# Check if using npm or yarn
if [[ "$command" =~ ^npm[[:space:]] ]]; then
  cat << EOF
{
  "continue": true,
  "permission": "deny",
  "user_message": "This project uses Bun. Please use 'bun' instead of 'npm'.",
  "agent_message": "This project standardizes on Bun for better performance. Replace:\n- 'npm install' → 'bun install'\n- 'npm run dev' → 'bun run dev'\n- 'npm test' → 'bun test'"
}
EOF
  exit 2
  
elif [[ "$command" =~ ^yarn[[:space:]] ]]; then
  cat << EOF
{
  "continue": true,
  "permission": "deny",
  "user_message": "This project uses Bun. Please use 'bun' instead of 'yarn'.",
  "agent_message": "This project standardizes on Bun. Replace yarn commands with bun equivalents."
}
EOF
  exit 2
fi

# Allow bun and other commands
echo '{"permission": "allow"}'
exit 0
```

## Exit Code Handling

### Exit Code Reference

| Exit Code | Meaning | Cursor Behavior |
|-----------|---------|-----------------|
| `0` | Success | Use JSON output |
| `2` | Block | Equivalent to `permission: "deny"` |
| `1` or other | Error | Fail-open (proceed) by default |

### Best Practices

```bash
#!/bin/bash

# ✅ GOOD: Explicit exit codes
if [[ condition ]]; then
  echo '{"permission": "deny"}'
  exit 2  # Explicitly block
else
  echo '{"permission": "allow"}'
  exit 0  # Explicitly allow
fi

# ❌ BAD: Implicit exit
# Don't let script exit with last command's exit code
```

**Fail-Open vs Fail-Closed**:

```bash
#!/bin/bash

# Default: Fail-open (proceeds on hook failure)
# For security-critical hooks, configure in hooks.json:
# { "failClosed": true }

# Handle errors gracefully
if ! command -v jq &> /dev/null; then
  echo "Error: jq not found" >&2
  # Still exit 0 to allow (fail-open)
  echo '{"permission": "allow", "error": "jq not available"}'
  exit 0
fi
```

## Debugging

### Enable Debug Logging

```bash
#!/bin/bash

# Add to any hook script for debugging
exec 2>> /tmp/hooks-debug.log
set -x  # Print commands as they execute

echo "=== Hook started: $(date) ==="
echo "Input: $(cat)"
echo "PWD: $(pwd)"
echo "Environment:"
env | grep CURSOR
```

### Test Hooks Manually

```bash
# Create test input
cat > test-input.json << EOF
{
  "command": "git status",
  "cwd": "/test",
  "sandbox": false
}
EOF

# Run hook with test input
cat test-input.json | .cursor/hooks/block-git.sh

# Check output
echo "Exit code: $?"
```

### Check Hook Execution

```bash
# View recent hook logs
tail -f /tmp/agent-audit.log

# View debug logs
tail -f /tmp/hooks-debug.log

# Check if hook is executable
ls -la .cursor/hooks/script.sh
```

## Advanced Patterns

### Pattern 1: Chained Commands

Handle commands with `&&`, `||`, `;`:

```bash
#!/bin/bash

input=$(cat)
command=$(echo "$input" | jq -r '.command')

# Split chained commands
IFS=';' read -ra COMMANDS <<< "$command"

for cmd in "${COMMANDS[@]}"; do
  # Trim whitespace
  cmd=$(echo "$cmd" | xargs)
  
  # Check each part
  if [[ "$cmd" =~ ^git[[:space:]] ]]; then
    echo '{"permission": "deny", "user_message": "Git commands blocked"}'
    exit 2
  fi
done

echo '{"permission": "allow"}'
exit 0
```

### Pattern 2: Working Directory Validation

```bash
#!/bin/bash

input=$(cat)
command=$(echo "$input" | jq -r '.command')
cwd=$(echo "$input" | jq -r '.cwd')

# Validate working directory exists
if [[ ! -d "$cwd" ]]; then
  echo '{"permission": "deny", "user_message": "Invalid working directory"}'
  exit 2
fi

# Block commands outside project
project_root="$CURSOR_PROJECT_DIR"
if [[ "$cwd" != "$project_root"* ]]; then
  echo '{"permission": "deny", "user_message": "Command outside project root"}'
  exit 2
fi

echo '{"permission": "allow"}'
exit 0
```

### Pattern 3: Rate Limiting

```bash
#!/bin/bash

input=$(cat)
command=$(echo "$input" | jq -r '.command')

RATE_LIMIT_FILE="/tmp/hook-rate-limit"
WINDOW_SECONDS=60
MAX_COMMANDS=10

# Get current timestamp
now=$(date +%s)

# Read rate limit state
declare -A timestamps
if [[ -f "$RATE_LIMIT_FILE" ]]; then
  while IFS='=' read -r key value; do
    timestamps[$key]=$value
  done < "$RATE_LIMIT_FILE"
fi

# Clean old entries
for key in "${!timestamps[@]}"; do
  age=$((now - ${timestamps[$key]}))
  if [[ $age -gt $WINDOW_SECONDS ]]; then
    unset "timestamps[$key]"
  fi
done

# Check rate limit
user_email="${CURSOR_USER_EMAIL:-unknown}"
user_commands=${timestamps[$user_email]:-0}

if [[ $user_commands -ge $MAX_COMMANDS ]]; then
  echo '{"permission": "deny", "user_message": "Rate limit exceeded. Try again later."}'
  exit 2
fi

# Increment counter
timestamps[$user_email]=$((user_commands + 1))

# Save state
for key in "${!timestamps[@]}"; do
  echo "$key=${timestamps[$key]}"
done > "$RATE_LIMIT_FILE"

echo '{"permission": "allow"}'
exit 0
```

## Commands

`/hooks-bash-setup`: Set up Bash hooks with jq  
`/hooks-bash-audit`: Create audit logging hook  
`/hooks-bash-block`: Create command-blocking hook  
`/hooks-bash-format`: Create auto-formatting hook  
`/hooks-bash-validate`: Create validation hook  

## Workflows

### Creating a Simple Block Hook

1. **Create Script**:
   ```bash
   cat > .cursor/hooks/my-hook.sh << 'EOF'
   #!/bin/bash
   input=$(cat)
   command=$(echo "$input" | jq -r '.command')
   
   if [[ "$command" =~ dangerous_pattern ]]; then
     echo '{"permission": "deny"}'
     exit 2
   fi
   
   echo '{"permission": "allow"}'
   exit 0
   EOF
   ```

2. **Make Executable**:
   ```bash
   chmod +x .cursor/hooks/my-hook.sh
   ```

3. **Configure hooks.json**:
   ```json
   {
     "hooks": {
       "beforeShellExecution": [
         {
           "command": ".cursor/hooks/my-hook.sh",
           "matcher": "dangerous_pattern"
         }
       ]
     }
   }
   ```

4. **Test**:
   ```bash
   echo '{"command": "test"}' | .cursor/hooks/my-hook.sh
   ```

### Implementing Security Gate

1. **Identify Patterns**: List commands/patterns to block
2. **Create Regex**: Write bash regex for each pattern
3. **Check Sequentially**: Test patterns in order
4. **Return Decision**: Output JSON with permission and messages
5. **Test Thoroughly**: Verify all patterns work

### Adding Audit Logging

1. **Choose Log Format**: Plain text or JSON lines
2. **Select Log Location**: `/tmp/`, project dir, or custom
3. **Write Timestamp**: Include timestamp in each entry
4. **Log Input**: Save full JSON input for debugging
5. **Rotate Logs**: Implement log rotation if needed

## Security Considerations

### Critical Security Rules

✅ **ALWAYS DO**:
- Quote all variables: `"$var"` not `$var`
- Use `[[ ]]` for conditionals (safer than `[ ]`)
- Validate all input before use
- Sanitize file paths
- Set proper exit codes
- Log security decisions

❌ **NEVER DO**:
- Use `eval` on hook input
- Execute untrusted commands
- Skip input validation
- Trust file paths without checking
- Store secrets in scripts

### Input Sanitization

```bash
#!/bin/bash

input=$(cat)

# ✅ GOOD: Safe parsing with jq
command=$(echo "$input" | jq -r '.command // empty')

# ❌ BAD: Unsafe parsing
# command=$(echo "$input" | grep -o '"command"[[:space:]]*:[[:space:]]*"[^"]*"' | cut -d'"' -f4)

# Validate command doesn't contain injection
if [[ "$command" =~ [$\`\(\)] ]]; then
  echo '{"permission": "deny", "user_message": "Invalid command characters"}'
  exit 2
fi
```

## Performance Resources

**Optimization Tips**:
- Keep hooks minimal and fast (<1s target)
- Use jq for JSON (faster than grep/sed)
- Avoid unnecessary subprocesses
- Set appropriate timeouts (10-30s)
- Use matchers to reduce invocations

**Bash Advantages**:
- No runtime dependencies (except jq)
- Fast startup (<10ms)
- Universal availability
- Simple to debug

## Testing Resources

**Testing Strategy**:
1. Test with valid JSON input
2. Test with missing fields
3. Test with malformed JSON
4. Verify exit codes
5. Test timeout behavior

**Example Tests**:
```bash
#!/bin/bash
# test-hook.sh

# Test 1: Allow safe command
result=$(echo '{"command": "ls"}' | .cursor/hooks/my-hook.sh)
exit_code=$?
[[ $exit_code -eq 0 ]] && echo "✓ Test 1 passed" || echo "✗ Test 1 failed"

# Test 2: Block dangerous command
result=$(echo '{"command": "rm -rf /"}' | .cursor/hooks/my-hook.sh)
exit_code=$?
[[ $exit_code -eq 2 ]] && echo "✓ Test 2 passed" || echo "✗ Test 2 failed"

# Test 3: Handle missing field
result=$(echo '{"cwd": "/test"}' | .cursor/hooks/my-hook.sh)
exit_code=$?
[[ $exit_code -eq 0 ]] && echo "✓ Test 3 passed" || echo "✗ Test 3 failed"
```

## References

- Official Docs: https://cursor.com/docs/agent/hooks
- jq Manual: https://jqlang.github.io/jq/manual/
- Bash Guide: https://mywiki.wooledge.org/BashGuide
- ShellCheck: https://www.shellcheck.net/ (lint your scripts)

## Related Skills

**Core Skills**:
- See `.cursor/skills/cursor-hooks-core/SKILL.md` for hooks fundamentals
- See `.cursor/skills/cursor-hooks-python/SKILL.md` for Python hooks

**Advanced Patterns**:
- See `.cursor/skills/cursor-hooks-security/SKILL.md` for security scanning
- See `.cursor/skills/cursor-hooks-matcher/SKILL.md` for conditional execution
- See `.cursor/skills/cursor-hooks-error-handling/SKILL.md` for error handling
