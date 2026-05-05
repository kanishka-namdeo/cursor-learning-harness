---
name: web-fetch-docs
description: Fast documentation retrieval from known URLs using WebFetch. Use when user provides documentation URL or when specific library docs need to be fetched quickly.
---

# Web Fetch Documentation

## Quick Start
Fetch URL with WebFetch → Extract relevant sections → Apply to task → Cite source

## Auto-Invoke Triggers
- User provides full URL (http/https)
- "Check this documentation" + URL
- "See [domain]/docs" references
- URLs found via WebSearch results

## Workflow
1. **Identify URL**: From user input or search results
2. **Fetch**: `WebFetch(url: "https://example.com/docs")`
3. **Extract**: API signatures, code examples, configuration options
4. **Apply**: Adapt to user's codebase, note version compatibility
5. **Cite**: Source URL with timestamp

## Priority Order
1. WebFetch (built-in, fastest)
2. Browser-use MCP (if blocked)
3. User assistance (if captcha)

## Success Metrics
✅ Fetched content within 10s
✅ Extracted relevant sections
✅ Applied to user's context
✅ Cited source URL
❌ Failed after 2 attempts without fallback

## Parallel Execution
**When**: Multiple URLs from search
**Example**: "Compare Vite 5 and 6 migration"
  - Fetch both URLs simultaneously
  - Compare and summarize

## Common Failures & Fixes
**Timeout (>30s)**: Retry once, then browser-use MCP
**Blocked access**: Use browser-use MCP headless
**Captcha**: Ask user assistance
**Dynamic content**: Switch to browser-use MCP

## See Also
- **web-search-research**: Find URLs when not provided
- **browser-use-testing**: Fallback when blocked
