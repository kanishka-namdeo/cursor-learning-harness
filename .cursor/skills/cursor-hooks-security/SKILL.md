# SKILL.md: Cursor Hooks Security

## Description
Expertise in building security-focused Cursor hooks for secret detection, vulnerability scanning, PII protection, dependency scanning, and integrating with security partners like Semgrep, Snyk, 1Password, and MCP governance tools.

## When to Use
- User needs security scanning in AI workflows
- Implementing secret detection and prevention
- Integrating vulnerability scanners (Semgrep, Snyk)
- Managing MCP server governance
- Enforcing security policies on agent actions
- Scanning for PII and sensitive data

## Capabilities
- Detect and block secrets/credentials
- Integrate vulnerability scanning tools
- Implement MCP governance patterns
- Scan for PII and sensitive information
- Enforce security policies pre-execution
- Create audit trails for security decisions

## Partner Integrations

### Semgrep (Code Security)

**Pattern**: Real-time vulnerability scanning

```bash
#!/bin/bash
# .cursor/hooks/semgrep-scan.sh

input=$(cat)
file_path=$(echo "$input" | jq -r '.file_path')

# Run Semgrep on edited file
if [[ "$file_path" == *.py ]] || [[ "$file_path" == *.ts ]]; then
  semgrep --config auto --quiet "$file_path" 2>/dev/null
  if [ $? -ne 0 ]; then
    echo '{"permission": "deny", "user_message": "Security issues found by Semgrep"}'
    exit 2
  fi
fi

echo '{"permission": "allow"}'
exit 0
```

**Configuration**:
```json
{
  "hooks": {
    "afterFileEdit": [
      {
        "command": "./hooks/semgrep-scan.sh",
        "failClosed": true
      }
    ]
  }
}
```

### Snyk (Dependency Security)

**Pattern**: Dependency vulnerability scanning

```bash
#!/bin/bash
# .cursor/hooks/snyk-check.sh

input=$(cat)
command=$(echo "$input" | jq -r '.command')

# Check npm/pip install commands
if [[ "$command" =~ ^npm[[:space:]]+(install|i) ]] || \
   [[ "$command" =~ ^pip[[:space:]]+(install|-i) ]]; then
  
  # Extract package name
  package=$(echo "$command" | grep -oP '(?<=(install|i)\s)[^\s@]+')
  
  # Run Snyk test
  snyk test "$package" --quiet 2>/dev/null
  if [ $? -ne 0 ]; then
    echo '{"permission": "deny", "user_message": "Package has known vulnerabilities"}'
    exit 2
  fi
fi

echo '{"permission": "allow"}'
exit 0
```

### 1Password (Secrets Management)

**Pattern**: Validate environment files

```bash
#!/bin/bash
# .cursor/hooks/validate-env.sh

input=$(cat)
file_path=$(echo "$input" | jq -r '.file_path')

# Check if .env file
if [[ "$file_path" == *".env"* ]]; then
  # Verify 1Password secrets are mounted
  if ! grep -q "OP_.*=" "$file_path" 2>/dev/null; then
    cat << EOF
{
  "permission": "deny",
  "user_message": ".env file should use 1Password secrets (OP_* variables)",
  "agent_message": "This project uses 1Password Environments. Mount secrets before writing .env files."
}
EOF
    exit 2
  fi
fi

echo '{"permission": "allow"}'
exit 0
```

## Security Patterns

### Pattern 1: Secret Detection

```python
#!/usr/bin/env python3
import json, sys, re

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
            'user_message': f'Potential secrets: {", ".join(secrets)}',
            'agent_message': f'Detected patterns: {secrets}'
        }))
    else:
        print(json.dumps({'permission': 'allow'}))

if __name__ == '__main__':
    main()
```

### Pattern 2: PII Detection

```python
#!/usr/bin/env python3
import json, sys, re

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

### Pattern 3: MCP Governance

```bash
#!/bin/bash
# .cursor/hooks/mcp-governance.sh

input=$(cat)
tool_name=$(echo "$input" | jq -r '.tool_name')
tool_input=$(echo "$input" | jq -r '.tool_input')

# Block dangerous MCP tools
case "$tool_name" in
  *"delete"*|*"drop"*|*"destroy"*)
    echo '{"permission": "ask", "user_message": "Destructive MCP operation requires approval"}'
    exit 0
    ;;
  *"admin"*|*"root"*|*"sudo"*)
    echo '{"permission": "deny", "user_message": "Admin operations blocked"}'
    exit 2
    ;;
esac

# Log all MCP usage
echo "$(date -Iseconds) | $tool_name" >> /tmp/mcp-audit.log

echo '{"permission": "allow"}'
exit 0
```

**Configuration**:
```json
{
  "hooks": {
    "beforeMCPExecution": [
      {
        "command": "./hooks/mcp-governance.sh",
        "failClosed": true
      }
    ]
  }
}
```

### Pattern 4: Command Injection Prevention

```bash
#!/bin/bash
# .cursor/hooks/injection-check.sh

input=$(cat)
command=$(echo "$input" | jq -r '.command')

# Check for injection patterns
injection_patterns=(
  '\$\('          # Command substitution
  '`'             # Backtick execution
  '\|'            # Pipe (when suspicious)
  '&&'            # Command chaining
  ';'             # Command separator
  '\|&'           # Pipe stderr
  '>&'            # Redirect stderr
)

for pattern in "${injection_patterns[@]}"; do
  if [[ "$command" =~ $pattern ]]; then
    echo '{"permission": "ask", "user_message": "Command contains shell metacharacters"}'
    exit 0
  fi
done

echo '{"permission": "allow"}'
exit 0
```

## Commands

`/hooks-security-secrets`: Create secret detection hook  
`/hooks-security-pii`: Create PII scanning hook  
`/hooks-security-mcp`: Create MCP governance hook  
`/hooks-security-deps`: Create dependency scanning hook  

## Workflows

### Implementing Security Gate

1. **Identify Risks**: What security concerns exist?
2. **Choose Patterns**: Select appropriate detection patterns
3. **Set failClosed**: `true` for security-critical hooks
4. **Add Logging**: Log all security decisions
5. **Test**: Verify patterns catch issues without false positives

### Integrating Security Tools

1. **Install Tool**: Semgrep, Snyk, etc.
2. **Create Hook**: Wrap tool in hook script
3. **Parse Output**: Extract security findings
4. **Return Decision**: Allow/deny based on results
5. **Configure**: Add to hooks.json with failClosed

## Security Considerations

✅ **ALWAYS DO**:
- Set `failClosed: true` for security hooks
- Log all security decisions
- Keep patterns updated
- Test for false positives/negatives
- Use defense in depth

❌ **NEVER DO**:
- Rely solely on hooks for security
- Store detection patterns in code
- Skip logging
- Block without explanation

## References

- Official Docs: https://cursor.com/docs/agent/hooks
- Partner Integrations: https://cursor.com/blog/hooks-partners
- Semgrep: https://semgrep.dev/
- Snyk: https://snyk.io/

## Related Skills

- See `.cursor/skills/cursor-hooks-core/SKILL.md` for fundamentals
- See `.cursor/skills/cursor-hooks-python/SKILL.md` for Python patterns
- See `.cursor/skills/cursor-hooks-governance/SKILL.md` for enterprise governance
