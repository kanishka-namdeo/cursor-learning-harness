# SKILL.md: Cursor Hooks Matcher Configuration

## Description
Expertise in advanced Cursor hooks matcher configuration for conditional hook execution, covering tool-based matchers, command text matchers, subagent type matchers, and performance optimization.

## When to Use
- User needs conditional hook execution
- Optimizing hook performance with filters
- Targeting specific tools or commands
- Reducing unnecessary hook invocations
- Implementing context-aware hooks

## Capabilities
- Configure tool-based matchers
- Create regex command matchers
- Filter by subagent type
- Combine multiple matchers
- Optimize hook performance

## Matcher Types

### Tool-Based Matchers

**Hooks**: preToolUse, postToolUse, postToolUseFailure

```json
{
  "hooks": {
    "preToolUse": [
      {
        "command": "./hooks/validate-shell.sh",
        "matcher": "Shell"
      },
      {
        "command": "./hooks/validate-read.sh",
        "matcher": "Read"
      },
      {
        "command": "./hooks/validate-mcp.sh",
        "matcher": "MCP: github-*"
      }
    ]
  }
}
```

**Available Matchers**:
- `Shell` - Shell command execution
- `Read` - File read operations
- `Write` - File write operations
- `Grep` - Search operations
- `Delete` - File deletion
- `Task` - Subagent creation
- `MCP: <pattern>` - MCP tools (supports wildcards)

### Command Text Matchers

**Hooks**: beforeShellExecution, afterShellExecution

```json
{
  "hooks": {
    "beforeShellExecution": [
      {
        "command": "./hooks/network-check.sh",
        "matcher": "curl|wget|nc|scp"
      },
      {
        "command": "./hooks/git-policy.sh",
        "matcher": "^git[[:space:]]"
      },
      {
        "command": "./hooks/package-check.sh",
        "matcher": "npm install|pip install|bun add"
      }
    ]
  }
}
```

**Regex Patterns**:
- `curl|wget` - Match network commands
- `^git` - Match git commands
- `install` - Match package installs
- `rm |del` - Match delete operations

### Subagent Type Matchers

**Hooks**: subagentStart, subagentStop

```json
{
  "hooks": {
    "subagentStart": [
      {
        "command": "./hooks/validate-explore.sh",
        "matcher": "explore"
      },
      {
        "command": "./hooks/validate-shell.sh",
        "matcher": "shell"
      }
    ]
  }
}
```

**Available Types**:
- `generalPurpose` - General task subagent
- `explore` - Code exploration subagent
- `shell` - Shell command subagent

### File Access Matchers

**beforeReadFile** - Filter by tool type that is requesting the file read. The matcher runs against the tool type identifier.

```json
{
  "hooks": {
    "beforeReadFile": [
      {
        "command": "./hooks/block-tab-read.sh",
        "matcher": "TabRead"
      },
      {
        "command": "./hooks/audit-agent-read.sh",
        "matcher": "Read"
      }
    ]
  }
}
```

**Available Matchers**:
- `TabRead` - Tab (inline completions) file read
- `Read` - Agent file read

**afterFileEdit** - Filter by tool type that performed the edit.

```json
{
  "hooks": {
    "afterFileEdit": [
      {
        "command": "./hooks/format-agent-edits.sh",
        "matcher": "Write"
      },
      {
        "command": "./hooks/format-tab-edits.sh",
        "matcher": "TabWrite"
      }
    ]
  }
}
```

**Available Matchers**:
- `Write` - Agent file write
- `TabWrite` - Tab (inline completions) file write

### Agent Lifecycle Matchers

These matchers run against fixed event identifiers rather than variable tool names or command text.

**beforeSubmitPrompt** - Matched against the value `UserPromptSubmit`:

```json
{
  "hooks": {
    "beforeSubmitPrompt": [
      {
        "command": "./hooks/validate-prompt.sh",
        "matcher": "UserPromptSubmit"
      }
    ]
  }
}
```

**stop** - Matched against the value `Stop`:

```json
{
  "hooks": {
    "stop": [
      {
        "command": "./hooks/track-completion.sh",
        "matcher": "Stop"
      }
    ]
  }
}
```

**afterAgentResponse** - Matched against the value `AgentResponse`:

```json
{
  "hooks": {
    "afterAgentResponse": [
      {
        "command": "./hooks/audit-response.sh",
        "matcher": "AgentResponse"
      }
    ]
  }
}
```

**afterAgentThought** - Matched against the value `AgentThought`:

```json
{
  "hooks": {
    "afterAgentThought": [
      {
        "command": "./hooks/log-reasoning.sh",
        "matcher": "AgentThought"
      }
    ]
  }
}
```

## Advanced Patterns

### Pattern 1: Multiple Matchers

```json
{
  "hooks": {
    "beforeShellExecution": [
      {
        "command": "./hooks/security-check.sh",
        "matcher": "curl|wget|scp|rsync"
      },
      {
        "command": "./hooks/audit-all.sh"
        // No matcher = runs for all commands
      }
    ]
  }
}
```

### Pattern 2: Exclusion Pattern

```bash
#!/bin/bash
# .cursor/hooks/exclude-dev.sh

input=$(cat)
command=$(echo "$input" | jq -r '.command')

# Skip for dev commands
if [[ "$command" =~ ^(npm|yarn|bun)[[:space:]]+(run[[:space:]]+)?(dev|start|test) ]]; then
  echo '{"permission": "allow"}'
  exit 0
fi

# Check production commands
if [[ "$command" =~ ^(npm|yarn|bun)[[:space:]]+publish ]]; then
  echo '{"permission": "ask", "user_message": "Publish requires approval"}'
  exit 0
fi

echo '{"permission": "allow"}'
exit 0
```

### Pattern 3: Context-Aware Matching

```bash
#!/bin/bash
# .cursor/hooks/context-aware.sh

input=$(cat)
command=$(echo "$input" | jq -r '.command')
cwd=$(echo "$input" | jq -r '.cwd')

# Different rules for different directories
if [[ "$cwd" == *"/production"* ]]; then
  # Strict rules for production
  if [[ "$command" =~ ^(rm|delete|drop) ]]; then
    echo '{"permission": "deny"}'
    exit 2
  fi
elif [[ "$cwd" == *"/test"* ]]; then
  # Relaxed rules for test
  echo '{"permission": "allow"}'
  exit 0
fi

echo '{"permission": "allow"}'
exit 0
```

## Performance Optimization

### Best Practices

✅ **DO**:
- Use matchers to reduce invocations
- Keep regex simple and fast
- Test matcher performance
- Log matcher hits/misses

❌ **DON'T**:
- Use complex regex patterns
- Run hooks without matchers in hot paths
- Skip performance testing

### Example: Optimized Configuration

```json
{
  "hooks": {
    "beforeShellExecution": [
      {
        "command": "./hooks/security-critical.sh",
        "matcher": "curl|wget|rm|sudo",  // Only high-risk commands
        "failClosed": true
      },
      {
        "command": "./hooks/audit.sh"  // Runs for all (no matcher)
      }
    ]
  }
}
```

## Commands

`/hooks-matcher-tool`: Create tool-based matcher  
`/hooks-matcher-command`: Create command text matcher  
`/hooks-matcher-subagent`: Create subagent matcher  

## Workflows

### Configuring Matchers

1. **Identify Target**: What to match?
2. **Choose Type**: Tool, command, subagent, file access, or agent lifecycle
3. **Write Pattern**: Regex, tool name, or event identifier
4. **Test**: Verify matcher triggers correctly
5. **Optimize**: Reduce unnecessary invocations

### Performance Tuning

1. **Measure**: Count hook invocations
2. **Identify Hot Paths**: Most frequent triggers
3. **Add Matchers**: Filter unnecessary calls
4. **Re-measure**: Verify improvement

## References

- Official Docs: https://cursor.com/docs/agent/hooks#matcher-configuration

## Related Skills

- See `.cursor/skills/cursor-hooks-core/SKILL.md` for fundamentals
- See `.cursor/skills/cursor-hooks-formatting/SKILL.md` for formatting use cases
