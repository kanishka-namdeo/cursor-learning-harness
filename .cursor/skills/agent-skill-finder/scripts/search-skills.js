#!/usr/bin/env node

/**
 * search-skills.js - Search and discover agent skills from skills.sh and GitHub repositories
 *
 * Usage:
 *   node scripts/search-skills.js <query>
 *   node scripts/search-skills.js --list-all
 *   node scripts/search-skills.js --top 10
 *   node scripts/search-skills.js --category frontend
 *   node scripts/search-skills.js --repo anthropics/skills
 */

const https = require("https");
const http = require("http");

// Known skill repositories with metadata
const KNOWN_REPOS = [
  {
    repo: "anthropics/skills",
    skills: [
      "frontend-design",
      "pdf",
      "canvas-design",
      "brand-guidelines",
      "slack-gif-creator",
      "algorithmic-art",
      "doc-coauthoring",
      "theme-factory",
      "internal-comms",
      "web-artifacts-builder",
      "template-skill",
      "skill-creator",
      "xlsx",
      "docx",
      "pptx",
    ],
  },
  {
    repo: "vercel-labs/agent-skills",
    skills: [
      "vercel-react-best-practices",
      "web-design-guidelines",
      "vercel-composition-patterns",
      "vercel-react-native-skills",
      "deploy-to-vercel",
      "find-skills",
    ],
  },
  {
    repo: "microsoft/azure-skills",
    skills: [
      "microsoft-foundry",
      "azure-quotas",
      "azure-upgrade",
      "azure-cost-optimization",
      "azure-cost",
      "azure-enterprise-infra-planner",
      "azure-kubernetes",
      "azure-messaging",
      "azure-compute",
    ],
  },
  {
    repo: "obra/superpowers",
    skills: [
      "brainstorming",
      "systematic-debugging",
      "writing-plans",
      "executing-plans",
      "using-superpowers",
      "test-driven-development",
      "requesting-code-review",
      "receiving-code-review",
      "verification-before-completion",
      "dispatching-parallel-agents",
      "using-git-worktrees",
      "finishing-a-development-branch",
      "writing-skills",
      "subagent-driven-development",
    ],
  },
  {
    repo: "pbakaus/impeccable",
    skills: [
      "polish",
      "critique",
      "delight",
      "distill",
      "quieter",
      "normalize",
      "overdrive",
      "typeset",
      "frontend-design",
      "arrange",
      "layout",
      "shape",
      "teach-impeccable",
      "impeccable",
      "harden",
      "onboard",
      "extract",
    ],
  },
  {
    repo: "coreyhaines31/marketingskills",
    skills: [
      "seo-audit",
      "copywriting",
      "social-content",
      "content-strategy",
      "programmatic-seo",
      "marketing-psychology",
      "analytics-tracking",
      "page-cro",
      "onboarding-cro",
      "form-cro",
      "referral-program",
      "free-tool-strategy",
      "launch-strategy",
      "paid-ads",
      "competitor-alternatives",
      "email-sequence",
      "schema-markup",
      "ai-seo",
      "cold-email",
      "ad-creative",
      "churn-prevention",
      "sales-enablement",
      "revops",
      "lead-magnets",
      "pricing-strategy",
      "marketing-ideas",
      "product-marketing-context",
      "copy-editing",
      "site-architecture",
    ],
  },
  {
    repo: "google-labs-code/stitch-skills",
    skills: [
      "react:components",
      "design-md",
      "stitch-loop",
      "enhance-prompt",
      "shadcn-ui",
      "remotion",
    ],
  },
  {
    repo: "firebase/agent-skills",
    skills: [
      "firebase-basics",
      "firebase-auth-basics",
      "firebase-hosting-basics",
      "firebase-ai-logic",
      "firebase-app-hosting-basics",
      "firebase-data-connect",
      "firebase-firestore-standard",
      "firebase-firestore-enterprise-native-mode",
      "developing-genkit-js",
      "developing-genkit-dart",
    ],
  },
  {
    repo: "supabase/agent-skills",
    skills: [
      "supabase-postgres-best-practices",
      "supabase",
    ],
  },
  {
    repo: "expo/skills",
    skills: [
      "native-data-fetching",
      "expo-tailwind-setup",
      "upgrading-expo",
      "expo-api-routes",
      "expo-cicd-workflows",
    ],
  },
  {
    repo: "larksuite/cli",
    skills: [
      "lark-doc",
      "lark-event",
      "lark-approval",
      "lark-slides",
      "lark-attendance",
    ],
  },
  {
    repo: "xixu-me/skills",
    skills: [
      "github-actions-docs",
      "readme-i18n",
    ],
  },
  {
    repo: "juliusbrussee/caveman",
    skills: [
      "caveman",
      "caveman-commit",
      "caveman-review",
      "caveman-compress",
      "caveman-help",
    ],
  },
  {
    repo: "wshobson/agents",
    skills: [
      "tailwind-design-system",
      "typescript-advanced-types",
      "nodejs-backend-patterns",
    ],
  },
  {
    repo: "skillssh/skills",
    skills: [
      "ai-image-generations",
    ],
  },
  {
    repo: "better-auth/skills",
    skills: [
      "better-auth-best-practices",
    ],
  },
  {
    repo: "neondatabase/agent-skills",
    skills: [
      "neon-postgres",
    ],
  },
  {
    repo: "get-convex/agent-skills",
    skills: [
      "convex-quickstart",
      "convex-setup-auth",
    ],
  },
  {
    repo: "firecrawl/cli",
    skills: [
      "firecrawl",
      "firecrawl-scrape",
      "firecrawl-search",
      "firecrawl-agent",
    ],
  },
  {
    repo: "leonxlnx/taste-skill",
    skills: [
      "design-taste-frontend",
      "high-end-visual-design",
      "minimalist-ui",
      "full-output-enforcement",
      "redesign-existing-projects",
    ],
  },
  {
    repo: "github/awesome-copilot",
    skills: [
      "git-commit",
    ],
  },
  {
    repo: "matt-pocock/skills",
    skills: [
      "grill-me",
    ],
  },
  {
    repo: "mouse/skills",
    skills: [
      "valuehug",
    ],
  },
  {
    repo: "anthropics/claude-code",
    skills: [
      "frontend-design",
    ],
  },
  {
    repo: "browser-use/browser-use",
    skills: [
      "browser-use",
    ],
  },
  {
    repo: "currents-dev/playwright-best-practices-skill",
    skills: [
      "playwright-best-practices",
    ],
  },
  {
    repo: "kepano/obsidian-skills",
    skills: [
      "obsidian-markdown",
      "obsidian-bases",
    ],
  },
  {
    repo: "hyf0/vue-skills",
    skills: [
      "vue-best-practices",
    ],
  },
  {
    repo: "nextlevelbuilder/ui-ux-pro-max-skill",
    skills: [
      "ui-ux-pro-max",
    ],
  },
];

// Skill categories for filtering
const CATEGORIES = {
  frontend: ["anthropics/skills", "vercel-labs/agent-skills", "google-labs-code/stitch-skills", "leonxlnx/taste-skill"],
  backend: ["microsoft/azure-skills", "firebase/agent-skills", "supabase/agent-skills", "neondatabase/agent-skills", "get-convex/agent-skills"],
  productivity: ["larksuite/cli", "obra/superpowers", "xixu-me/skills"],
  marketing: ["coreyhaines31/marketingskills"],
  quality: ["pbakaus/impeccable", "juliusbrussee/caveman"],
  testing: ["browser-use/browser-use", "currents-dev/playwright-best-practices-skill"],
  scraping: ["firecrawl/cli"],
  design: ["anthropics/skills", "pbakaus/impeccable", "leonxlnx/taste-skill", "google-labs-code/stitch-skills"],
  auth: ["better-auth/skills", "firebase/agent-skills", "get-convex/agent-skills"],
  database: ["supabase/agent-skills", "firebase/agent-skills", "neondatabase/agent-skills", "get-convex/agent-skills"],
  image: ["skillssh/skills"],
  video: ["google-labs-code/stitch-skills"],
  native: ["expo/skills"],
  git: ["github/awesome-copilot", "obra/superpowers"],
  typescript: ["wshobson/agents", "matt-pocock/skills"],
};

/**
 * Fetch URL content (HTTP/HTTPS)
 */
function fetchURL(url) {
  return new Promise((resolve, reject) => {
    const client = url.startsWith("https") ? https : http;
    client
      .get(url, (res) => {
        if (res.statusCode === 301 || res.statusCode === 302) {
          fetchURL(res.headers.location).then(resolve, reject);
          return;
        }
        let data = "";
        res.on("data", (chunk) => (data += chunk));
        res.on("end", () => resolve(data));
      })
      .on("error", reject);
  });
}

/**
 * Search skills by query across all known repositories
 */
function searchSkills(query) {
  const q = query.toLowerCase();
  const results = [];

  for (const repoEntry of KNOWN_REPOS) {
    for (const skill of repoEntry.skills) {
      const skillLower = skill.toLowerCase();
      if (skillLower.includes(q) || repoEntry.repo.toLowerCase().includes(q)) {
        results.push({
          skill,
          repo: repoEntry.repo,
          installPath: `https://github.com/${repoEntry.repo}`,
        });
      }
    }
  }

  return results;
}

/**
 * List skills by category
 */
function listCategory(category) {
  const cat = category.toLowerCase();
  if (!CATEGORIES[cat]) {
    console.error(`Unknown category: ${category}`);
    console.log(`Available: ${Object.keys(CATEGORIES).join(", ")}`);
    process.exit(1);
  }

  const repos = CATEGORIES[cat];
  const results = [];

  for (const repoEntry of KNOWN_REPOS) {
    if (repos.includes(repoEntry.repo)) {
      for (const skill of repoEntry.skills) {
        results.push({
          skill,
          repo: repoEntry.repo,
          installPath: `https://github.com/${repoEntry.repo}`,
        });
      }
    }
  }

  return results;
}

/**
 * List all skills with optional limit
 */
function listAll(limit) {
  const results = [];
  for (const repoEntry of KNOWN_REPOS) {
    for (const skill of repoEntry.skills) {
      results.push({
        skill,
        repo: repoEntry.repo,
        installPath: `https://github.com/${repoEntry.repo}`,
      });
      if (limit && results.length >= limit) return results;
    }
  }
  return results;
}

/**
 * List skills from a specific repository
 */
function listRepo(repoName) {
  const entry = KNOWN_REPOS.find(
    (r) => r.repo.toLowerCase() === repoName.toLowerCase()
  );
  if (!entry) {
    console.error(`Repository not found: ${repoName}`);
    console.log(
      `Available: ${KNOWN_REPOS.map((r) => r.repo).join(", ")}`
    );
    process.exit(1);
  }

  return entry.skills.map((skill) => ({
    skill,
    repo: entry.repo,
    installPath: `https://github.com/${entry.repo}`,
  }));
}

/**
 * Format results for display
 */
function formatResults(results, title) {
  if (results.length === 0) {
    console.log("No skills found.");
    return;
  }

  console.log(`\n${title}\n`);
  console.log("─".repeat(70));

  for (let i = 0; i < results.length; i++) {
    const r = results[i];
    console.log(`${i + 1}. ${r.skill}`);
    console.log(`   Repo: ${r.repo}`);
    console.log(`   Install: npx skills add ${r.repo}`);
    console.log("");
  }

  console.log("─".repeat(70));
  console.log(`Found ${results.length} skill(s)`);
}

// CLI argument parsing
const args = process.argv.slice(2);

if (args.length === 0) {
  console.log(`
Agent Skill Finder - Search and discover skills

Usage:
  node scripts/search-skills.js <query>     Search skills by keyword
  node scripts/search-skills.js --list-all  List all known skills
  node scripts/search-skills.js --top N     List top N skills
  node scripts/search-skills.js --category <name>  List skills by category
  node scripts/search-skills.js --repo <name>      List skills from a repo

Categories:
  ${Object.keys(CATEGORIES).join(", ")}

Examples:
  node scripts/search-skills.js react
  node scripts/search-skills.js --top 10
  node scripts/search-skills.js --category frontend
  node scripts/search-skills.js --repo anthropics/skills
  `);
  process.exit(0);
}

if (args[0] === "--list-all") {
  const results = listAll();
  formatResults(results, "All Known Skills");
} else if (args[0] === "--top") {
  const limit = parseInt(args[1], 10) || 10;
  const results = listAll(limit);
  formatResults(results, `Top ${limit} Skills`);
} else if (args[0] === "--category") {
  const results = listCategory(args[1] || "");
  formatResults(results, `Skills in "${args[1]}" category`);
} else if (args[0] === "--repo") {
  const results = listRepo(args[1] || "");
  formatResults(results, `Skills from "${args[1]}"`);
} else {
  const query = args.join(" ");
  const results = searchSkills(query);
  formatResults(results, `Search results for "${query}"`);
}
