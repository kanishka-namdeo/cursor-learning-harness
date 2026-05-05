# SKILL.md: Cursor Hooks Governance

## Description
Expertise in enterprise Cursor hooks governance, covering audit logging, policy enforcement, team hook distribution (MDM, cloud), compliance reporting, and managing hooks at organizational scale.

## When to Use
- User needs enterprise-grade hook governance
- Implementing audit trails and compliance
- Distributing hooks across teams
- Enforcing organizational policies
- Managing hooks via MDM or cloud distribution
- Creating governance dashboards and reports

## Capabilities
- Design enterprise hook architectures
- Implement comprehensive audit logging
- Enforce organizational policies
- Distribute hooks via MDM/cloud
- Create compliance reports
- Manage hook configurations at scale

## Configuration Hierarchy

### Enterprise Distribution

**System-wide Locations**:
- **macOS**: `/Library/Application Support/Cursor/hooks.json`
- **Linux/WSL**: `/etc/cursor/hooks.json`
- **Windows**: `C:\ProgramData\Cursor\hooks.json`

**Cloud Distribution** (Enterprise):
- Configure in [Cursor Dashboard](https://cursor.com/dashboard/team-content?section=hooks)
- Syncs every 30 minutes to team members
- OS-specific hook targeting

### Priority Order

```
Enterprise (MDM) → Team (Cloud) → Project → User
```

## Governance Patterns

### Pattern 1: Comprehensive Audit Logging

```typescript
// .cursor/hooks/enterprise-audit.ts
import { stdin } from 'bun';
import { appendFile } from 'node:fs/promises';

type AuditEvent = {
  timestamp: string;
  user_email: string;
  hook_event: string;
  conversation_id: string;
  workspace: string;
  details: any;
};

async function log(event: AuditEvent) {
  const line = JSON.stringify(event) + '\n';
  const logPath = process.env.AUDIT_LOG_PATH || '/var/log/cursor-audit.jsonl';
  
  try {
    await appendFile(logPath, line, 'utf8');
  } catch (error) {
    console.error('Audit log failed:', error);
  }
}

async function main() {
  const input = await parseInput();
  
  const event: AuditEvent = {
    timestamp: new Date().toISOString(),
    user_email: process.env.CURSOR_USER_EMAIL || 'unknown',
    hook_event: input.hook_event_name,
    conversation_id: input.conversation_id,
    workspace: input.workspace_roots?.[0] || 'unknown',
    details: input
  };
  
  await log(event);
  console.log(JSON.stringify({ permission: 'allow' }));
}

main();
```

### Pattern 2: Policy Enforcement

```bash
#!/bin/bash
# .cursor/hooks/policy-enforcement.sh

input=$(cat)
command=$(echo "$input" | jq -r '.command')
user_email="${CURSOR_USER_EMAIL:-unknown}"

# Load policies from central location
POLICY_FILE="/etc/cursor/policies.json"
if [[ -f "$POLICY_FILE" ]]; then
  # Check command against policy
  blocked=$(jq -r ".blocked_commands[]" "$POLICY_FILE" 2>/dev/null)
  
  for pattern in $blocked; do
    if [[ "$command" =~ $pattern ]]; then
      echo "{\"permission\": \"deny\", \"user_message\": \"Blocked by organizational policy\"}"
      exit 2
    fi
  done
fi

# Log policy check
echo "$(date -Iseconds) | $user_email | policy_check" >> /var/log/cursor-policy.log

echo '{"permission": "allow"}'
exit 0
```

### Pattern 3: Team Hook Distribution

**Cloud Configuration** (Dashboard):

```json
{
  "version": 1,
  "hooks": {
    "beforeShellExecution": [
      {
        "command": "/managed/hooks/security-scan.sh",
        "matcher": "curl|wget|npm|pip",
        "failClosed": true
      }
    ],
    "afterFileEdit": [
      {
        "command": "/managed/hooks/format.sh"
      }
    ]
  }
}
```

**MDM Deployment** (Intune/Jamf):

```bash
#!/bin/bash
# Deploy hooks via MDM
# macOS (Jamf)

HOOKS_DIR="/Library/Application Support/Cursor"
mkdir -p "$HOOKS_DIR"

cat > "$HOOKS_DIR/hooks.json" << 'EOF'
{
  "version": 1,
  "hooks": {
    "beforeShellExecution": [
      {"command": "/Library/Application Support/Cursor/hooks/security.sh"}
    ]
  }
}
EOF

chmod 644 "$HOOKS_DIR/hooks.json"
```

### Pattern 4: Compliance Reporting

```python
#!/usr/bin/env python3
# .cursor/hooks/compliance-report.py

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

def generate_report(days: int = 7):
    log_path = Path('/var/log/cursor-audit.jsonl')
    if not log_path.exists():
        return {'error': 'No audit log found'}
    
    cutoff = datetime.now() - timedelta(days=days)
    stats = {
        'total_events': 0,
        'denied_events': 0,
        'users': set(),
        'hook_types': {},
        'top_blocked': []
    }
    
    with open(log_path) as f:
        for line in f:
            event = json.loads(line)
            event_time = datetime.fromisoformat(event['timestamp'])
            
            if event_time < cutoff:
                continue
            
            stats['total_events'] += 1
            stats['users'].add(event['user_email'])
            
            hook_type = event['hook_event']
            stats['hook_types'][hook_type] = stats['hook_types'].get(hook_type, 0) + 1
            
            if event.get('permission') == 'deny':
                stats['denied_events'] += 1
    
    return {
        'period_days': days,
        'total_events': stats['total_events'],
        'denied_events': stats['denied_events'],
        'unique_users': len(stats['users']),
        'hook_breakdown': stats['hook_types'],
        'generated_at': datetime.now().isoformat()
    }

if __name__ == '__main__':
    print(json.dumps(generate_report(), indent=2))
```

## Commands

`/hooks-governance-audit`: Create enterprise audit logging  
`/hooks-governance-policy`: Create policy enforcement hook  
`/hooks-governance-report`: Generate compliance report  
`/hooks-governance-mdm`: Set up MDM distribution  

## Workflows

### Enterprise Hook Deployment

1. **Define Policies**: What rules to enforce?
2. **Create Hooks**: Implement enforcement logic
3. **Choose Distribution**: MDM, cloud, or project
4. **Deploy**: Push to all team members
5. **Monitor**: Track compliance and issues

### Audit Implementation

1. **Define Schema**: What to log?
2. **Choose Storage**: Local file, SIEM, cloud
3. **Implement Logging**: All hook events
4. **Add Retention**: Log rotation policies
5. **Create Reports**: Compliance dashboards

## Security Considerations

✅ **ALWAYS DO**:
- Log all security decisions
- Protect audit logs from tampering
- Implement least-privilege hooks
- Regular policy reviews
- Test hook deployments

❌ **NEVER DO**:
- Store secrets in hook configs
- Skip audit logging
- Deploy untested hooks
- Allow hook bypass
- Ignore compliance requirements

## References

- Official Docs: https://cursor.com/docs/agent/hooks
- Team Distribution: https://cursor.com/docs/hooks.md#team-distribution
- Enterprise Features: https://cursor.com/enterprise

## Related Skills

- See `.cursor/skills/cursor-hooks-core/SKILL.md` for fundamentals
- See `.cursor/skills/cursor-hooks-security/SKILL.md` for security patterns
- See `.cursor/skills/cursor-hooks-subagent/SKILL.md` for subagent governance
