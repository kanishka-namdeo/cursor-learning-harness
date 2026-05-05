# SKILL.md: Cursor Hooks Subagent Control

## Description
Expertise in controlling Cursor subagents (Task tool) with hooks, covering subagent lifecycle management, validation, follow-up automation, loop control, parallel worker management, and git branch isolation.

## When to Use
- User needs to control subagent creation and execution
- Implementing subagent governance policies
- Creating automated follow-up workflows
- Managing parallel subagent workers
- Enforcing git branch policies for subagents
- Tracking subagent metrics and costs

## Capabilities
- Control subagentStart/subagentStop hooks
- Validate subagent creation
- Implement automated follow-ups
- Manage loop limits
- Track subagent metrics
- Enforce branch policies

## Hook Events

### subagentStart

**When**: Before spawning subagent  
**Use**: Validate, block, or modify subagent creation

```json
// Input
{
  "subagent_id": "abc-123",
  "subagent_type": "generalPurpose",
  "task": "Explore the authentication flow",
  "parent_conversation_id": "conv-456",
  "tool_call_id": "tc-789",
  "subagent_model": "claude-sonnet-4-20250514",
  "is_parallel_worker": false,
  "git_branch": "feature/auth"
}

// Output
{
  "permission": "allow" | "deny",
  "user_message": "Shown when denied"
}
```

| Input Field | Type | Description |
| --- | --- | --- |
| `subagent_id` | string | Unique identifier for this subagent instance |
| `subagent_type` | string | Type of subagent: `generalPurpose`, `explore`, `shell`, etc. |
| `task` | string | The task description given to the subagent |
| `parent_conversation_id` | string | Conversation ID of the parent agent session |
| `tool_call_id` | string | ID of the tool call that triggered the subagent |
| `subagent_model` | string | Model the subagent will use |
| `is_parallel_worker` | boolean | Whether this subagent is running as a parallel worker |
| `git_branch` | string (optional) | Git branch the subagent will operate on, if applicable |

| Output Field | Type | Description |
| --- | --- | --- |
| `permission` | string | `"allow"` to proceed, `"deny"` to block. `"ask"` is not supported for `subagentStart` and is treated as `"deny"`. |
| `user_message` | string (optional) | Message shown to the user when the subagent is denied |

### subagentStop

**When**: Subagent completes/errors/aborts  
**Use**: Trigger follow-ups, track metrics

```json
// Input
{
  "subagent_type": "generalPurpose",
  "status": "completed" | "error" | "aborted",
  "task": "Explore auth flow",
  "description": "Exploring auth flow",
  "summary": "Found JWT implementation...",
  "duration_ms": 45000,
  "message_count": 12,
  "tool_call_count": 8,
  "loop_count": 0,
  "modified_files": ["src/auth.ts"],
  "agent_transcript_path": "/path/to/subagent/transcript.txt"
}

// Output
{
  "followup_message": "Now implement the middleware"
}
```

| Input Field | Type | Description |
| --- | --- | --- |
| `subagent_type` | string | Type of subagent: `generalPurpose`, `explore`, `shell`, etc. |
| `status` | string | `"completed"`, `"error"`, or `"aborted"` |
| `task` | string | The task description given to the subagent |
| `description` | string | Short description of the subagent's purpose |
| `summary` | string | Output summary from the subagent |
| `duration_ms` | number | Execution time in milliseconds |
| `message_count` | number | Number of messages exchanged during the subagent session |
| `tool_call_count` | number | Number of tool calls the subagent made |
| `loop_count` | number | Number of times a `subagentStop` follow-up has already triggered for this subagent (starts at 0) |
| `modified_files` | string[] | Files the subagent modified |
| `agent_transcript_path` | string \| null | Path to the subagent's own transcript file (separate from the parent conversation) |

| Output Field | Type | Description |
| --- | --- | --- |
| `followup_message` | string (optional) | Auto-continue with this message. **Only consumed when `status` is `"completed"`.** |

The `followup_message` field enables loop-style flows where subagent completion triggers the next iteration. Follow-ups are subject to the same configurable loop limit as the `stop` hook (default 5, configurable via `loop_limit`).

### Pattern 1: Subagent Validation

```bash
#!/bin/bash
# .cursor/hooks/validate-subagent.sh

input=$(cat)
subagent_type=$(echo "$input" | jq -r '.subagent_type')
task=$(echo "$input" | jq -r '.task')

# Block expensive subagents during work hours
hour=$(date +%H)
if [[ $hour -ge 9 && $hour -le 17 ]]; then
  if [[ "$subagent_type" == "generalPurpose" ]]; then
    # Check task complexity
    if [[ ${#task} -gt 500 ]]; then
      echo '{"permission": "deny", "user_message": "Large subagents blocked during work hours"}'
      exit 2
    fi
  fi
fi

# Log subagent creation
echo "$(date -Iseconds) | $subagent_type | $task" >> /tmp/subagent-audit.log

echo '{"permission": "allow"}'
exit 0
```

**Configuration**:
```json
{
  "hooks": {
    "subagentStart": [
      {
        "command": ".cursor/hooks/validate-subagent.sh",
        "matcher": "generalPurpose|explore"
      }
    ]
  }
}
```

### Pattern 2: Automated Follow-up

```typescript
// .cursor/hooks/subagent-followup.ts
import { stdin } from 'bun';

type SubagentStopInput = {
  status: 'completed' | 'error' | 'aborted';
  task: string;
  summary: string;
  loop_count: number;
};

async function main() {
  const input = await parseInput<SubagentStopInput>();
  
  // Auto-retry on error (max 2 times)
  if (input.status === 'error' && input.loop_count < 2) {
    console.log(JSON.stringify({
      followup_message: 'Retry with increased verbosity and debug logging'
    }));
    return;
  }
  
  // Chain tasks on success
  if (input.status === 'completed' && input.loop_count === 0) {
    if (input.task.includes('explore')) {
      console.log(JSON.stringify({
        followup_message: 'Now implement the feature based on your exploration'
      }));
      return;
    }
  }
  
  console.log(JSON.stringify({}));
}

main();
```

### Pattern 3: Loop Control

```json
{
  "hooks": {
    "subagentStop": [
      {
        "command": "bun run .cursor/hooks/followup.ts",
        "loop_limit": 3  // Max 3 auto follow-ups
      }
    ]
  }
}
```

**Default**: `loop_limit: 5` for Cursor hooks  
**Unlimited**: Set `loop_limit: null`

### Pattern 4: Branch Isolation

```bash
#!/bin/bash
# .cursor/hooks/branch-check.sh

input=$(cat)
git_branch=$(echo "$input" | jq -r '.git_branch // empty')

# Block subagents on protected branches
protected_branches=("main" "master" "production" "release/*")

for branch in "${protected_branches[@]}"; do
  if [[ "$git_branch" == $branch ]]; then
    echo '{"permission": "deny", "user_message": "Subagents blocked on protected branch: '"$branch"'"}'
    exit 2
  fi
done

# Require feature branch prefix
if [[ -n "$git_branch" && ! "$git_branch" =~ ^feature/ ]]; then
  echo '{"permission": "ask", "user_message": "Subagent on non-feature branch. Recommended: feature/*"}'
  exit 0
fi

echo '{"permission": "allow"}'
exit 0
```

### Pattern 5: Cost Tracking

```typescript
// .cursor/hooks/subagent-metrics.ts
import { appendFile } from 'node:fs/promises';

type MetricsInput = {
  subagent_type: string;
  status: string;
  duration_ms: number;
  message_count: number;
  tool_call_count: number;
};

async function track(input: MetricsInput) {
  const metric = {
    timestamp: new Date().toISOString(),
    ...input,
    estimated_cost: calculateCost(input)
  };
  
  await appendFile('/tmp/subagent-metrics.jsonl', 
    JSON.stringify(metric) + '\n', 'utf8');
}

function calculateCost(input: MetricsInput): number {
  // Rough cost estimation based on tokens
  const inputTokens = input.message_count * 100;  // Estimate
  const outputTokens = input.tool_call_count * 50;
  return (inputTokens * 0.000001 + outputTokens * 0.000003);  // Example rates
}
```

## Commands

`/hooks-subagent-validate`: Create subagent validation hook  
`/hooks-subagent-followup`: Create automated follow-up hook  
`/hooks-subagent-metrics`: Create subagent tracking hook  

## Workflows

### Implementing Subagent Control

1. **Identify Policy**: What subagent behavior to control?
2. **Choose Hook**: subagentStart vs subagentStop
3. **Implement Logic**: Validation or follow-up
4. **Set Loop Limit**: Configure loop_limit
5. **Test**: Verify with sample subagent tasks

### Creating Follow-up Workflow

1. **Define Trigger**: When to follow up?
2. **Craft Message**: What instruction to send?
3. **Set Limit**: How many follow-ups?
4. **Test**: Verify loop behavior

## Security Considerations

✅ **ALWAYS DO**:
- Validate subagent creation
- Track subagent costs
- Set loop limits
- Log subagent activity
- Block on protected branches

❌ **NEVER DO**:
- Allow unlimited follow-ups
- Skip subagent auditing
- Permit on production branches
- Ignore cost accumulation

## References

- Official Docs: https://cursor.com/docs/agent/hooks#subagent-hooks
- Loop Control: https://cursor.com/docs/hooks.md#configuration

## Related Skills

- See `.cursor/skills/cursor-hooks-core/SKILL.md` for fundamentals
- See `.cursor/skills/cursor-hooks-governance/SKILL.md` for enterprise governance
