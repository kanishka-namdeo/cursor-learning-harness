# Known Skill Repositories

Comprehensive registry of agent skill repositories across the ecosystem.

## Primary Sources

### https://skills.sh/

The main skills directory and leaderboard. Tracks install counts and trending skills.

**Install command:** `npx skills add <owner/repo>`

**Key metrics tracked:**
- Total installs
- 24h trending
- Hot skills

## GitHub Repositories

### anthropics/skills (319.3K+ installs)
| Skill | Purpose |
|-------|---------|
| frontend-design | UI/UX design guidance |
| pdf | PDF processing and extraction |
| canvas-design | Data visualization and canvas work |
| brand-guidelines | Brand consistency rules |
| slack-gif-creator | Slack GIF generation |
| algorithmic-art | Generative art creation |
| doc-coauthoring | Document collaboration |
| theme-factory | Theme generation |
| internal-comms | Internal communication patterns |
| web-artifacts-builder | Web artifact building |
| template-skill | Template skill structure |
| skill-creator | Skill creation guidance |
| xlsx | Excel file processing |
| docx | Word document processing |
| pptx | PowerPoint processing |

### vercel-labs/agent-skills (335.1K+ installs)
| Skill | Purpose |
|-------|---------|
| find-skills | Skill discovery (1.1M installs) |
| vercel-react-best-practices | React patterns |
| web-design-guidelines | Web design standards |
| vercel-composition-patterns | Composition patterns |
| vercel-react-native-skills | React Native patterns |
| deploy-to-vercel | Vercel deployment |

### microsoft/azure-skills (224.4K+ installs)
| Skill | Purpose |
|-------|---------|
| microsoft-foundry | Azure Foundry agent management |
| azure-quotas | Quota management |
| azure-upgrade | Upgrade paths |
| azure-cost-optimization | Cost optimization |
| azure-kubernetes | Kubernetes deployment |
| azure-messaging | Azure messaging services |
| azure-compute | Compute resources |

### obra/superpowers (607.8K+ installs across all)
| Skill | Purpose |
|-------|---------|
| brainstorming | Idea generation |
| systematic-debugging | Debug methodology |
| writing-plans | Plan documentation |
| executing-plans | Plan execution |
| test-driven-development | TDD workflow |
| requesting-code-review | Code review requests |
| receiving-code-review | Code review response |
| verification-before-completion | Verification workflow |
| dispatching-parallel-agents | Parallel execution |
| using-git-worktrees | Git worktree patterns |
| writing-skills | Skill authoring |
| subagent-driven-development | Subagent patterns |

### pbakaus/impeccable (607.8K+ installs across all)
| Skill | Purpose |
|-------|---------|
| polish | Polish and refinement |
| critique | Code critique |
| delight | UX delight patterns |
| distill | Content distillation |
| quieter | Minimal UI patterns |
| normalize | Normalization patterns |
| overdrive | Performance patterns |
| typeset | Typography |
| frontend-design | Frontend design |
| arrange | Layout arrangement |
| layout | Layout patterns |
| shape | Shape manipulation |
| impeccable | Comprehensive quality |
| harden | Security hardening |
| onboard | Onboarding patterns |
| extract | Data extraction |
| teach-impeccable | Teaching impeccable patterns |

### coreyhaines31/marketingskills (193.6K+ installs across all)
| Skill | Purpose |
|-------|---------|
| seo-audit | SEO auditing |
| copywriting | Copy writing |
| social-content | Social media content |
| content-strategy | Content planning |
| programmatic-seo | Programmatic SEO |
| marketing-psychology | Marketing psychology |
| analytics-tracking | Analytics setup |
| page-cro | Conversion rate optimization |
| launch-strategy | Launch planning |
| pricing-strategy | Pricing strategy |

### google-labs-code/stitch-skills
| Skill | Purpose |
|-------|---------|
| react:components | React component patterns |
| design-md | Design markdown generation |
| stitch-loop | Stitch development loop |
| enhance-prompt | Prompt enhancement |
| shadcn-ui | shadcn/ui patterns |
| remotion | Remotion video patterns |

### firebase/agent-skills
| Skill | Purpose |
|-------|---------|
| firebase-basics | Firebase fundamentals |
| firebase-auth-basics | Authentication |
| firebase-hosting-basics | Hosting setup |
| firebase-ai-logic | AI integration |
| firebase-app-hosting-basics | App hosting |
| firebase-data-connect | Data Connect |
| firebase-firestore-standard | Firestore patterns |

### supabase/agent-skills
| Skill | Purpose |
|-------|---------|
| supabase-postgres-best-practices | Postgres patterns |
| supabase | Supabase setup |

### expo/skills
| Skill | Purpose |
|-------|---------|
| native-data-fetching | Native data patterns |
| expo-tailwind-setup | Tailwind integration |
| upgrading-expo | Expo upgrades |
| expo-api-routes | API routing |
| expo-cicd-workflows | CI/CD setup |

### larksuite/cli (866.8K+ installs across all)
| Skill | Purpose |
|-------|---------|
| lark-doc | Lark document creation |
| lark-event | Lark event handling |
| lark-approval | Lark approval workflows |
| lark-slides | Lark presentation creation |
| lark-attendance | Attendance tracking |

### firecrawl/cli (95.3K+ installs across all)
| Skill | Purpose |
|-------|---------|
| firecrawl | Web scraping |
| firecrawl-scrape | Page scraping |
| firecrawl-search | Search scraping |
| firecrawl-agent | Agent-based scraping |

### leonxlnx/taste-skill
| Skill | Purpose |
|-------|---------|
| design-taste-frontend | Frontend design taste |
| high-end-visual-design | Premium visual design |
| minimalist-ui | Minimal UI patterns |
| full-output-enforcement | Output enforcement |
| redesign-existing-projects | Redesign patterns |

### Other Notable Repositories
| Repository | Key Skills | Installs |
|------------|------------|----------|
| juliusbrussee/caveman | caveman, caveman-commit, caveman-review | 66K+ |
| wshobson/agents | tailwind-design-system, typescript-advanced-types | 35K+ |
| skillssh/skills | ai-image-generations | 105K+ |
| better-auth/skills | better-auth-best-practices | 39.9K |
| neondatabase/agent-skills | neon-postgres | 25.9K |
| get-convex/agent-skills | convex-quickstart, convex-setup-auth | 27.5K+ |
| kepano/obsidian-skills | obsidian-markdown, obsidian-bases | 19.8K+ |
| hyf0/vue-skills | vue-best-practices | 19.7K |
| firebase/agent-skills | firebase-basics, firebase-auth-basics | 28.5K+ |
| browser-use/browser-use | browser-use | 68.3K |
| currents-dev/playwright-best-practices-skill | playwright-best-practices | 30K |

## Installation Patterns

### Single Repository
```bash
npx skills add <owner/repo>
```

### Multiple Repositories
```bash
npx skills add anthropics/skills vercel-labs/agent-skills obra/superpowers
```

### Specific Skill from Repository
1. Clone repo with sparse checkout
2. Copy skill directory to target location
3. Verify SKILL.md format

## Verification Checklist

After installation, verify:
- [ ] SKILL.md exists with valid YAML frontmatter
- [ ] `name` field is lowercase, hyphenated, max 64 chars
- [ ] `description` is non-empty, under 1024 chars
- [ ] No Windows-style paths in file references
- [ ] File references are one level deep only
- [ ] No time-sensitive information that could become outdated
