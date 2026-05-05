---
name: context7-parallel-research
description: Maximize Context7 effectiveness with parallel execution, cross-referencing, and security awareness including ContextCrush vulnerability verification.
---

# Context7 Parallel Research

## Quick Start
Library + version detected → Context7 query → Parallel WebSearch → Cross-reference → Alert discrepancies → Cite both sources

## Auto-Invoke Triggers
- Library name + version number (e.g., "React 19", "Vite 6")
- "How to use" + library + API method
- Version migration questions ("migrate from X to Y")
- API syntax or parameters unclear
- Library comparison ("Vite vs Webpack")

## When to Use
- Need version-specific API documentation
- Library has Context7 support (check registry)
- Want current code examples matching project version
- Security-critical implementations
- Comparing multiple libraries or versions

## Security Awareness: ContextCrush Vulnerability

**Context**: In Feb 2026, Context7 had a vulnerability where community contributions could inject malicious documentation.

**Mitigation**:
1. **Always cross-reference** security-critical code
2. **Verify against official docs** for:
   - Authentication implementations
   - Encryption/crypto code
   - User input handling
   - IPC/security configurations
3. **Check GitHub repo** for library's official examples
4. **Review security advisories** for the library

**When to be extra cautious**:
- 🔴 Authentication/authorization code
- 🔴 Payment processing
- 🔴 User data handling
- 🔴 System-level access
- 🟡 Configuration code
- 🟡 API integrations

## Workflow

### 1. Identify Library & Version

From user query or project context:
```
User: "How to use React 19 use() hook?"
Extracted:
  - Library: react
  - Version: 19.0.0 (from package.json)
  - Feature: use() hook
```

### 2. Check Context7 Registry

**Resolve library ID**:
```
CallMcpTool(
  server: "user-context7",
  toolName: "resolve-library-id",
  arguments: { library: "react" }
)
```

**If Found**: Get library ID, proceed to query
**If Not Found**: 
```
Response: "React not found in Context7 registry, searching web..."
Action: Fall back to WebSearch + WebFetch
```

### 3. Query Context7 Documentation

**Query version-specific docs**:
```
CallMcpTool(
  server: "user-context7",
  toolName: "query-docs",
  arguments: {
    library_id: "react",
    query: "use() hook promise handling syntax",
    version: "19.0.0"
  }
)
```

**Extract from response**:
- API signatures
- Parameter types
- Usage examples
- Version-specific notes
- Migration guides

### 4. Parallel WebSearch

**Execute simultaneously with Context7 query**:
```
WebSearch(
  search_term: "React 19 use() hook best practices 2026",
  explanation: "Get current React 19 patterns for use() hook"
)
```

**Search strategies**:
- "[library] [version] [feature] best practices 2026"
- "[library] [API] official documentation"
- "[library] [version] breaking changes"

### 5. Cross-Reference & Verify

**Compare sources**:

**✅ Match** (proceed with confidence):
```
Context7: use(promise) returns resolved value
React.dev: use() accepts promise, returns resolved data
Conclusion: API confirmed, safe to use
```

**⚠️ Discrepancy** (alert user):
```
Context7: use() can be used in event handlers
React.dev: use() only at component top level
Response: "⚠️ Discrepancy detected: Context7 shows different usage than official docs. Following React.dev (official source)."
```

**🔴 Security concern** (extra verification):
```
For auth/crypto code:
1. Context7 shows implementation
2. Cross-reference with official security guide
3. Check OWASP recommendations
4. Verify against GitHub examples
5. If all align: safe to use
6. If conflict: flag for manual review
```

### 6. Apply to Codebase

**Show implementation** with citations:
```typescript
// ✅ Verified against:
// - Context7 (React v19.0.0)
// - react.dev/reference/react/use (2026)
import { use } from 'react';

function Component({ promise }) {
  const data = use(promise); // ✅ Correct usage per both sources
  return <div>{data}</div>;
}
```

**Note version compatibility**:
```markdown
**Version**: React 19.0.0+
**Source**: Context7 + react.dev (cross-referenced)
**Security**: ✅ Verified against 2 sources
```

## Success Metrics

✅ Resolved library in Context7 registry
✅ Fetched version-specific documentation matching project
✅ Cross-referenced with WebSearch/WebFetch
✅ Noted any discrepancies between sources
✅ Applied examples to user's codebase correctly
✅ Security-critical code verified against official docs
❌ Library not found without fallback to WebSearch
❌ Discrepancies not noted
❌ Security code used without cross-reference

## Parallel Execution Patterns

**Pattern 1: Single Library Deep Dive**
```
User: "React 19 use() hook"
Parallel:
  - Context7: Query "use() hook API syntax"
  - WebSearch: "React 19 use() hook examples 2026"
  - WebFetch: react.dev/reference/react/use
Merge: Compare all three, note alignment/discrepancies
```

**Pattern 2: Version Comparison**
```
User: "Migrate Vite 5 config to Vite 6"
Parallel:
  - Context7: Vite 5 config API
  - Context7: Vite 6 config API
  - WebSearch: "Vite 6 migration breaking changes 2026"
  - WebFetch: vitejs.dev/guide/migration
Merge: Create migration guide with verified changes
```

**Pattern 3: Technology Comparison**
```
User: "Vite vs Webpack for 2026"
Parallel:
  - Context7: Vite config, build API
  - Context7: Webpack config, build API
  - WebSearch: "Vite vs Webpack performance 2026"
  - WebFetch: Both official docs
Merge: Comparison table with sourced data
```

## Security Verification Workflow

**For authentication, encryption, user input**:

### Step 1: Context7 Query
```
Query: "JWT sign verify implementation"
Extract: API signatures, examples
```

### Step 2: Official Docs Verification
```
WebFetch: jwt.io/introduction
WebFetch: github.com/auth0/node-jsonwebtoken#readme
Compare: Do Context7 examples match official docs?
```

### Step 3: Security Guide Check
```
WebSearch: "JWT security best practices OWASP 2026"
WebFetch: OWASP JWT security cheat sheet
Verify: Are security patterns in Context7 aligned with OWASP?
```

### Step 4: Decision
```
If all align: ✅ Safe to implement
If discrepancy: ⚠️ Flag for manual review, use official docs
If security concern: 🔴 Require manual security review
```

## Example Usage

**User**: "How do I implement JWT authentication in Electron?"

**Agent response**:

"I'll research JWT implementation using Context7 and cross-reference with security guides..."

1. **Check package.json**: jsonwebtoken v9.0.0, Electron 41

2. **Context7 queries** (parallel):
   ```
   - Query: "jsonwebtoken v9 sign API"
   - Query: "jsonwebtoken v9 verify API"
   ```

3. **Parallel WebSearch**:
   ```
   - "JWT authentication Electron 2026"
   - "JWT security best practices OWASP 2026"
   ```

4. **WebFetch** (security verification):
   ```
   - jwt.io/introduction
   - OWASP JWT cheat sheet
   - electronjs.org/docs/security
   ```

5. **Cross-reference**:
   ```
   ✅ Context7 jwt.sign() matches jwt.io docs
   ✅ Secret management aligns with OWASP
   ✅ Electron IPC pattern matches official guide
   ```

6. **Implementation**:
   ```typescript
   // ✅ Verified against:
   // - Context7 (jsonwebtoken v9.0.0)
   // - jwt.io (2026)
   // - OWASP JWT guidelines (2025)
   import jwt from 'jsonwebtoken';
   
   const token = jwt.sign(
     { userId: user.id },
     process.env.JWT_SECRET!,
     { expiresIn: '1h' } // ✅ OWASP recommendation
   );
   ```

## Common Failures & Fixes

**Failure**: Library not in Context7 registry
```
Response: "Library [name] not found in Context7 registry. I'll search web for current documentation instead."
Action: WebSearch "[library] [version] API documentation"
Then: WebFetch official docs, GitHub readme
```

**Failure**: Version not available in Context7
```
Response: "Version [x.y.z] not available, fetching latest docs..."
Action: Query without version constraint
Note: "Using latest available version docs, may differ from [requested version]"
```

**Failure**: Context7 returns no results for query
```
Response: "No results for [query]. Trying broader search..."
Action: Simplify query to core terms, retry
If still empty: Fall back to WebSearch
```

**Failure**: Discrepancy between Context7 and official docs
```
Response: "⚠️ Discrepancy detected: Context7 shows [X], official docs show [Y]. Following official source."
Action: Use official docs as primary source
Note: "Context7 may have outdated or incorrect info"
```

**Failure**: Security-critical code with no official verification
```
Response: "🔴 Security concern: JWT implementation needs verification against official security guide."
Action: Fetch OWASP, official security docs
If unavailable: "Manual security review recommended"
```

## ContextCrush Vulnerability Response

**Feb 2026 Context7 vulnerability awareness**:

### High-Risk Patterns (require extra verification)

**Authentication**:
```
Context7 shows: JWT implementation
Verification required:
  ✅ jwt.io official docs
  ✅ OWASP JWT guidelines
  ✅ Library GitHub examples
```

**Encryption**:
```
Context7 shows: Crypto implementation
Verification required:
  ✅ Node.js crypto docs
  ✅ NIST guidelines
  ✅ Security audit reports
```

**User Input Handling**:
```
Context7 shows: Validation/sanitization
Verification required:
  ✅ OWASP input validation guide
  ✅ Library official examples
  ✅ Security blog posts (2025-2026)
```

### Safe Patterns (standard verification)

**UI components**:
```
Context7 shows: React component pattern
Verification:
  ✅ react.dev reference
  ✅ Cross-reference with WebSearch
```

**Build configuration**:
```
Context7 shows: Vite/Webpack config
Verification:
  ✅ Official docs
  ✅ GitHub examples
```

## Best Practices

### 1. Always Cross-Reference Security Code
```
❌ Bad: Trust Context7 for auth implementation
✅ Good: Context7 + jwt.io + OWASP + GitHub examples
```

### 2. Note Discrepancies Explicitly
```
❌ Bad: Ignore conflicting info
✅ Good: "⚠️ Context7 shows X, official docs show Y. Following official source."
```

### 3. Use Parallel Execution
```
❌ Bad: Sequential queries (slow)
✅ Good: Context7 + WebSearch simultaneously
```

### 4. Verify Version Matching
```
❌ Bad: Assume latest version
✅ Good: Check package.json, query specific version
```

### 5. Document Sources
```
❌ Bad: No citations
✅ Good: "// Verified against Context7 + react.dev (2026)"
```

## See Also
- **context7-integration**: Base Context7 usage patterns
- **web-search-research**: Fallback when Context7 unavailable
