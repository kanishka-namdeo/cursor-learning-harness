# Agent Skill Finder - Usage Examples

## Example 1: Search for React Skills

```bash
node scripts/search-skills.js react
```

Output:
```
Search results for "react"

──────────────────────────────────────────────────────────────────────
1. vercel-react-best-practices
   Repo: vercel-labs/agent-skills
   Install: npx skills add vercel-labs/agent-skills

2. vercel-react-native-skills
   Repo: vercel-labs/agent-skills
   Install: npx skills add vercel-labs/agent-skills

3. react:components
   Repo: google-labs-code/stitch-skills
   Install: npx skills add google-labs-code/stitch-skills
──────────────────────────────────────────────────────────────────────
Found 3 skill(s)
```

Install command:
```bash
npx skills add vercel-labs/agent-skills google-labs-code/stitch-skills
```

## Example 2: Find Debugging Skills

```bash
node scripts/search-skills.js debug
```

## Example 3: List Top Skills

```bash
node scripts/search-skills.js --top 10
```

## Example 4: Browse by Category

```bash
# Frontend skills
node scripts/search-skills.js --category frontend

# Database skills
node scripts/search-skills.js --category database

# Marketing skills
node scripts/search-skills.js --category marketing
```

## Example 5: List All Skills from a Repo

```bash
node scripts/search-skills.js --repo anthropics/skills
```

## Example 6: Real-World Workflow

**Goal:** Add React and testing skills to a new project

1. Search for relevant skills:
```bash
node scripts/search-skills.js react
node scripts/search-skills.js testing
node scripts/search-skills.js playwright
```

2. Install the skills:
```bash
npx skills add vercel-labs/agent-skills
npx skills add browser-use/browser-use
```

3. Verify installation:
```bash
ls .cursor/skills/
# Should see skill directories
```

## Example 7: Using with WebFetch

When the local script doesn't have what you need:

1. Fetch skills.sh directly:
```javascript
// Use WebFetch to get the latest skills directory
const html = await fetchURL("https://skills.sh/");
// Parse for skills matching your criteria
```

2. Search GitHub for specific patterns:
```javascript
// Use WebFetch to check a repo's skill directory
const tree = await fetchURL(
  "https://api.github.com/repos/anthropics/skills/git/trees/main?recursive=1"
);
// Filter for SKILL.md files
```

## Example 8: Creating a Custom Skill After Finding Patterns

After browsing existing skills, create your own:

```bash
# 1. Find inspiration
node scripts/search-skills.js --category quality

# 2. Review the pattern
# Browse anthropics/skills and pbakaus/impeccable

# 3. Create your own skill following the pattern
mkdir -p .cursor/skills/my-custom-skill
# Create SKILL.md with proper frontmatter
```

## Example 9: Batch Install for New Project

```bash
# Install comprehensive skill set
npx skills add \
  anthropics/skills \
  vercel-labs/agent-skills \
  obra/superpowers \
  pbakaus/impeccable \
  wshobson/agents
```

## Example 10: Skill Discovery via Agent

When using an agent, simply ask:
- "What skills exist for React development?"
- "Find me debugging skills"
- "What are the top 10 most installed skills?"
- "Show me all skills from Microsoft"

The agent will use this skill to search and recommend.
