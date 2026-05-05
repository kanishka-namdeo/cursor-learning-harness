---
name: agent-skill-finder
description: Search, discover, and install agent skills from skills.sh directory, GitHub repositories, and community sources. Use when the user wants to find skills, add skills, search for capabilities, install agent skills, or enhance agent capabilities.
---

# Agent Skill Finder

Search and fetch agent skills from the ecosystem.

## Quick Start

1. Use `search-skills` to find relevant skills
2. Review the skill details and installation options
3. Use `install-skill` to add to project or personal directory

## Core Commands

### Search Skills

Use the helper script to search:

```bash
node scripts/search-skills.js <query>
```

Or use WebFetch to search skills.sh directly:

```bash
# Search the skills directory
curl "https://skills.sh/" | grep -i "<query>"
```

### Install a Skill

From a GitHub repository:

```bash
npx skills add <owner/repo>
```

Or manually copy to:
- **Personal:** `~/.cursor/skills/skill-name/`
- **Project:** `.cursor/skills/skill-name/`

## Search Strategy

### 1. Search skills.sh Directory

- Visit https://skills.sh/ for the full leaderboard
- Search by skill name, category, or publisher
- Note install counts for popularity signals

### 2. Search GitHub Repositories

Known skill repositories:

| Repository | Skills Available |
|------------|-----------------|
| anthropics/skills | Frontend design, PDF, canvas, brand guidelines |
| vercel-labs/agent-skills | React best practices, composition patterns |
| microsoft/azure-skills | Azure deployment, cost optimization |
| obra/superpowers | Systematic debugging, planning, subagents |
| pbakaus/impeccable | Polish, critique, design patterns |
| coreyhaines31/marketingskills | SEO, copywriting, marketing |
| larksuite/cli | Lark document integration |
| xixu-me/skills | GitHub Actions, i18n |
| google-labs-code/stitch-skills | React components, design, remotion |
| firebase/agent-skills | Firebase hosting, auth, firestore |
| expo/skills | Expo native UI, data fetching |
| supabase/agent-skills | Supabase Postgres, setup |
| better-auth/skills | Better Auth best practices |
| juliusbrussee/caveman | Simple, minimal skill patterns |
| wshobson/agents | TypeScript, Node.js patterns |
| skillssh/skills | AI image generation |

### 3. Search by Category

| Category | Repositories to Check |
|----------|----------------------|
| Frontend/UI | anthropics/skills, vercel-labs/agent-skills, google-labs-code/stitch-skills |
| Backend/Cloud | microsoft/azure-skills, firebase/agent-skills |
| Productivity | larksuite/cli, obra/superpowers |
| Marketing | coreyhaines31/marketingskills |
| Quality/Polish | pbakaus/impeccable, juliusbrussee/caveman |
| Data | supabase/agent-skills, firebase/agent-skills |
| Testing | browser-use/browser-use, currents-dev/playwright-best-practices-skill |

## Installation Workflow

### Method 1: CLI Install (Recommended)

```bash
npx skills add <owner/repo>
```

This automatically detects your agent type (Cursor, Claude Code, VSCode, etc.) and installs to the correct location.

### Method 2: Manual Install

1. Clone or download the skill repository
2. Copy the desired skill directory to:
   - Personal: `~/.cursor/skills/<skill-name>/`
   - Project: `.cursor/skills/skills/<skill-name>/`
3. Verify the SKILL.md frontmatter is valid

### Method 3: Single Skill Fetch

For a specific skill from a repo:

```bash
# Download just one skill
git clone --depth 1 --sparse <repo-url>
cd <repo-name>
git sparse-checkout set <skill-directory>
```

Then copy to your skills directory.

## Skill Verification

After installation, verify:

1. **SKILL.md exists** with valid frontmatter
2. **Name field** is lowercase, hyphenated, max 64 chars
3. **Description** is non-empty and under 1024 chars
4. **File references** are one level deep only

## Related Resources

- Skills Directory: https://skills.sh/
- Skill Creator Guide: See create-skill skill
- Known Repositories: See [repositories.md](repositories.md)
- Usage Examples: See [examples.md](examples.md)
