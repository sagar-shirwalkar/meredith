# README Tiers

The *tier* frames what level of depth and polish a README needs. Pick the lowest tier that serves the project's actual audience — going higher than needed wastes effort; going lower undersells.

## Lean

**For:** Personal packages, experimental projects, internal tools, weekend prototypes.
**Audience:** The author and maybe 1–2 colleagues.
**Tone:** Direct, minimal, no marketing.

**Includes:**
- One-line identity + badge row
- Quick install (one command)
- Minimal usage example
- License

**Omits:** Feature lists, configuration reference, architecture docs, contributing guide, benchmarks.

**Polishing effort:** Minutes. A quick pass for clarity and one badge check.

---

## Solid

**For:** Developer tools, libraries, CLIs, open-source utilities — anything with external users.
**Audience:** Evaluators and new users who found the project on their own.
**Tone:** Professional, precise, confident.

**Includes everything in Lean, plus:**
- Identity paragraph + feature bullets
- Full Quick Start with copy-paste example and expected output
- Installation section with all supported methods
- Usage guide with 2–3 realistic scenarios
- API / CLI reference or link to dedicated docs
- Configuration reference with defaults
- Contributing section or link to CONTRIBUTING.md
- Badges: build, version, license, coverage

**Polishing effort:** 1–2 review loops. Most CHECKLIST.md items must pass.

---

## Curated

**For:** Public-facing products, startup projects, anything competing for adoption against polished alternatives.
**Audience:** Evaluators who compare against other projects; new users who need convincing.
**Tone:** Polished, trustworthy, opinionated.

**Includes everything in Solid, plus:**
- Centered logo + title + badge block at top
- "Why this project?" section with benchmarks, comparisons, or case studies
- Screenshots, diagrams, or terminal recordings
- Migration guide from common alternatives (if applicable)
- Architecture overview or link to dedicated docs
- Philosophy / design principles section
- Community / ecosystem section (plugins, extensions, integrations)

**Polishing effort:** 3+ review loops. Every CHECKLIST.md item must pass. Rendered verification is mandatory.

---

## Choosing a tier

| Project type | Recommended tier |
|---|---|
| Personal experiment, gist, dotfile | Lean |
| Internal library, team tool | Lean |
| CLI tool, library, framework | Solid |
| SaaS product, startup OSS | Curated |
| Project competing for adoption | Curated |

When in doubt, start at Solid. It is the default for a reason: it serves evaluators and new users without over-investing. Upgrade to Curated only when the project has users who are comparing rather than discovering.
