---
name: web-search-research
description: Real-time information gathering for libraries, frameworks, and tools using WebSearch. Use when user asks about current best practices, API documentation, or version-specific guidance.
---

# Web Search Research

## Quick Start
Search web for current best practices → Fetch top URLs → Synthesize findings → Apply to context

## Auto-Invoke Triggers
- User asks "best practices" + year (2025, 2026)
- "What's new in [version]" queries
- "Compare [A] vs [B]" questions
- Library/framework not in Context7 registry
- "Breaking changes" + library + version
- Plan mode research requests ("Plan: [feature]")
- Agent verification ("verify implementation", "check before commit")

## When to Use
- User asks about library/framework (React, Next.js, Vite, Electron, etc.)
- Need current best practices (2025-2026)
- API documentation or syntax needed
- Version migration or upgrade questions
- Library comparison or evaluation

## Workflow

### 1. Identify Information Need
Extract from user query:
- Library/framework name
- Specific version (if mentioned)
- Topic or feature area
- Use case or goal

### 2. Search Web
Use WebSearch tool with targeted queries:
```
"[library_name] best practices 2025 2026"
"[library_name] [feature] documentation"
"[library_name] vs [alternative] comparison"
```

### 3. Fetch Documentation
For top 3-5 results:
- Use WebFetch to retrieve content
- Prioritize official documentation URLs
- Check publication dates for recency

### 4. Synthesize Findings
- Extract key patterns and recommendations
- Note version-specific differences
- Identify code examples
- Cite sources with URLs

### 5. Provide Actionable Recommendations
- Apply findings to user's specific context
- Show code examples following current patterns
- Link to source documentation
- Note any breaking changes or migrations

## Example Usage

**User**: "How do I optimize Vite builds for production?"

**Agent Response**:
"I'll search for current Vite build optimization best practices..."

1. **Search**: "Vite build optimization best practices 2025 2026"
2. **Fetch**: vitejs.dev/guide/build, vitejs.dev/config/build-options
3. **Synthesize**: 
   - Code splitting strategies
   - Tree shaking configuration
   - Asset optimization
4. **Recommend**: Apply to your Vite config with specific examples

**User**: "What's the latest React Server Components pattern?"

**Agent Response**:
"Let me fetch the current React Server Components documentation..."

1. **Search**: "React Server Components pattern 2025 2026"
2. **Fetch**: react.dev/blog, nextjs.org/docs/app
3. **Synthesize**: Current patterns, best practices
4. **Recommend**: Show implementation for your use case

## Best Practices

### Search Queries
✅ **Good**:
- "Electron 35 security best practices 2026"
- "React 19 hooks optimization documentation"
- "TypeScript 5.7 strict mode configuration"

❌ **Avoid**:
- Generic queries without version/year
- Overly broad topics
- Outdated terminology

### Source Priority
1. Official documentation (react.dev, nextjs.org, etc.)
2. GitHub repositories and release notes
3. Reputable tech blogs (Vercel, Stripe, etc.)
4. Community tutorials (with date verification)

### Citation Format
Always include:
- Source URL
- Publication/update date
- Relevant excerpt or code sample

## Success Metrics
✅ Found 2+ authoritative sources with dates from 2025-2026
✅ Extracted working code examples
✅ Cited all sources with URLs and dates
✅ Applied findings to user's specific context
❌ Sources older than 2024 without disclaimer

## Parallel Execution

### Pattern 1: Library Research
**When**: Library research or version comparison
**Parallel**: WebSearch + Context7 (if library supported)
**Example**: "React 19 optimization"
  - Context7: React 19 APIs (version-specific)
  - WebSearch: Latest patterns 2025-2026 (current practices)

### Pattern 2: Plan Mode Research (NEW)
**When**: User requests plan mode
**Parallel**: WebSearch + Context7 + WebFetch (all three)
**Example**: "Plan: Add authentication"
  - WebSearch: "Electron 41 authentication 2026"
  - Context7: Electron IPC patterns, jsonwebtoken v9 API
  - WebFetch: electronjs.org/docs/security, jwt.io, OWASP
**Merge**: Synthesize into implementation plan with citations

### Pattern 3: Agent Verification (NEW)
**When**: Post-execution verification
**Parallel**: WebSearch (breaking changes) + verification commands
**Example**: After implementing feature
  - WebSearch: "[library] breaking changes 2026"
  - Commands: npm run typecheck, lint, build
**Goal**: Ensure implementation matches current best practices

### Pattern 4: Security-Critical Research (NEW)
**When**: Authentication, encryption, user input
**Parallel**: Multiple authoritative sources
**Example**: "Implement JWT auth"
  - WebSearch: "JWT security best practices OWASP 2026"
  - WebFetch: jwt.io, OWASP guidelines, GitHub security notes
**Requirement**: Triple verification before implementing

## Common Failures & Fixes
**No recent results (pre-2024)**: Refine query with specific year, check official blog
**Conflicting information**: Prioritize official docs, note discrepancies
**Low-quality sources only**: Fall back to WebFetch on official URLs
**Search timeout**: Retry with simpler query, focus on core terms

## See Also
- **web-fetch-docs**: Fetch specific URLs found via search
- **context7-integration**: Use first for version-specific library APIs
- **context7-parallel-research**: Parallel execution with security

## Related Skills

- **web-fetch-docs**: For fetching specific documentation URLs
- **context7-integration**: For version-specific library APIs via MCP
- **browser-use-testing**: For testing fetched patterns in browser
