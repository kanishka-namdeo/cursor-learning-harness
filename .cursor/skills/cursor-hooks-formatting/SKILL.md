# SKILL.md: Cursor Hooks Formatting

## Description
Expertise in building auto-formatting Cursor hooks for code quality enforcement, covering Prettier, ESLint, Black, gofmt, and language-specific formatters with afterFileEdit automation.

## When to Use
- User wants automatic code formatting after AI edits
- Enforcing code style standards
- Integrating linters and formatters
- Handling multiple languages
- Differentiating Tab vs Agent formatting policies

## Capabilities
- Auto-format edited files
- Run linters post-edit
- Handle multiple languages
- Configure formatter chains
- Manage Tab vs Agent policies

## Patterns

### Pattern 1: Multi-Language Formatter

```bash
#!/bin/bash
# .cursor/hooks/auto-format.sh

input=$(cat)
file_path=$(echo "$input" | jq -r '.file_path')

# TypeScript/JavaScript
if [[ "$file_path" == *.ts ]] || [[ "$file_path" == *.tsx ]] || [[ "$file_path" == *.js ]]; then
  if command -v npx &> /dev/null; then
    npx prettier --write "$file_path" --log-level silent 2>/dev/null
  fi

# Python
elif [[ "$file_path" == *.py ]]; then
  if command -v black &> /dev/null; then
    black "$file_path" --quiet 2>/dev/null
  elif command -v autopep8 &> /dev/null; then
    autopep8 --in-place "$file_path" 2>/dev/null
  fi

# Go
elif [[ "$file_path" == *.go ]]; then
  if command -v gofmt &> /dev/null; then
    gofmt -w "$file_path" 2>/dev/null
  fi

# Rust
elif [[ "$file_path" == *.rs ]]; then
  if command -v rustfmt &> /dev/null; then
    rustfmt "$file_path" 2>/dev/null
  fi

# JSON
elif [[ "$file_path" == *.json ]]; then
  if command -v jq &> /dev/null; then
    jq '.' "$file_path" > "$file_path.tmp" && mv "$file_path.tmp" "$file_path"
  fi
fi

echo '{}'
exit 0
```

**Configuration**:
```json
{
  "hooks": {
    "afterFileEdit": [
      {
        "command": ".cursor/hooks/auto-format.sh"
      }
    ]
  }
}
```

### Pattern 2: Linter Integration

```bash
#!/bin/bash
# .cursor/hooks/run-linter.sh

input=$(cat)
file_path=$(echo "$input" | jq -r '.file_path')

# ESLint for TypeScript/JavaScript
if [[ "$file_path" == *.ts ]] || [[ "$file_path" == *.tsx ]] || [[ "$file_path" == *.js ]]; then
  if command -v npx &> /dev/null; then
    npx eslint "$file_path" --quiet 2>&1
    exit_code=$?
    
    if [ $exit_code -ne 0 ]; then
      echo "Linter issues found" >&2
    fi
  fi

# Ruff for Python
elif [[ "$file_path" == *.py ]]; then
  if command -v ruff &> /dev/null; then
    ruff check "$file_path" --quiet 2>&1
  fi
fi

echo '{}'
exit 0
```

### Pattern 3: Tab vs Agent Policies

```json
{
  "hooks": {
    "afterFileEdit": [
      {
        "command": ".cursor/hooks/format-agent.sh",
        "matcher": "Write"
      }
    ],
    "afterTabFileEdit": [
      {
        "command": ".cursor/hooks/format-tab.sh"
      }
    ]
  }
}
```

**Different Policies**:
- Agent: Full formatting + linting
- Tab: Lightweight formatting only

### Pattern 4: Formatter Chain

```bash
#!/bin/bash
# .cursor/hooks/format-chain.sh

input=$(cat)
file_path=$(echo "$input" | jq -r '.file_path')

# Run formatters in sequence
formatters=(
  "prettier --write"
  "eslint --fix"
  "stylelint --fix"
)

for formatter in "${formatters[@]}"; do
  if command -v $(echo $formatter | cut -d' ' -f1) &> /dev/null; then
    $formatter "$file_path" --silent 2>/dev/null
  fi
done

echo '{}'
exit 0
```

## Commands

`/hooks-format-setup`: Set up auto-formatting hooks  
`/hooks-format-lang`: Create language-specific formatter  
`/hooks-format-lint`: Create linting hook  

## Workflows

### Setting Up Formatting

1. **Choose Formatters**: Prettier, Black, etc.
2. **Install Dependencies**: npm install, pip install
3. **Create Hook Script**: Multi-language support
4. **Configure hooks.json**: Add afterFileEdit hook
5. **Test**: Edit file, verify formatting

### Language-Specific Setup

**TypeScript**:
```bash
npm install -D prettier eslint
```

**Python**:
```bash
pip install black autopep8 ruff
```

**Go**:
```bash
# gofmt comes with Go installation
```

## References

- Prettier: https://prettier.io/
- ESLint: https://eslint.org/
- Black: https://black.readthedocs.io/

## Related Skills

- See `.cursor/skills/cursor-hooks-core/SKILL.md` for fundamentals
- See `.cursor/skills/cursor-hooks-matcher/SKILL.md` for conditional execution
