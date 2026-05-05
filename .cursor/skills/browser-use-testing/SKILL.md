---
name: browser-use-testing
description: Frontend testing and visual verification using cursor-ide-browser MCP. Use when building web features, verifying UI changes, testing user interactions, or visual debugging.
---

# Browser Use Testing

## Quick Start
Lock browser → Navigate → Snapshot → Interact with refs → Verify → Unlock

## Auto-Invoke Triggers
- "Test the UI" or "visual verification"
- "Click" + element name
- "Screenshot" + page/feature
- "Does this button work"

## Critical Rules
✅ **ALWAYS**: Fresh snapshot after EVERY interaction
✅ **ALWAYS**: Use refs from snapshot (never coordinates)
✅ **ALWAYS**: Lock before interactions, unlock when done
❌ **NEVER**: Use stale snapshots
❌ **NEVER**: Use browser_mouse_click_xy (except with fresh screenshot)

## Core Workflow
1. `browser_tabs(action: "list")` - Check state
2. `browser_lock(action: "lock")` - Lock tab
3. `browser_navigate(url)` - Navigate if needed
4. `browser_snapshot()` - Get page structure with refs
5. Interact using refs: `browser_click(ref)`, `browser_fill(ref, text)`
6. `browser_snapshot()` - **FRESH!** Verify changes
7. `browser_lock(action: "unlock")` - Release lock

## Success Metrics
✅ Locked browser before interactions
✅ Fresh snapshot after each action
✅ Used refs (not coordinates)
✅ Verified outcome
✅ Unlocked when complete

## Common Failures & Fixes
**Ref fails**: Take fresh browser_snapshot()
**Element not found**: Verify page, scroll into view, retry
**Page stuck**: Wait 3s, snapshot, check URL, report if stuck
**Captcha/manual**: Stop, report "Manual interaction required", ask user

## See Also
- **playwright-testing**: For automated E2E (CI/CD)
