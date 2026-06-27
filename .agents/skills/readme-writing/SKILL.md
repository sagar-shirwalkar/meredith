---
name: readme-writing
description: Create, rewrite, or audit a project README. Use when the user asks for a README, documentation overhaul, project description, or getting-started guide. Also use when another skill ships a feature that needs documenting for external readers.
disable-model-invocation: false
---

# README Writing

A README is the project's front door. Every reader arrives with a question: *what is this, should I use it, how do I start?* Answer those in order without making them dig. Then curate everything else.

## Tenets

Three tenets anchor every decision:

- **Portal** — The README answers the reader's first question before they scroll. Identity, value proposition, and quick start come first. Everything else follows.
- **Tier** — READMEs serve readers at different depths. Match the tier to the project's maturity and audience. See [TIERS.md](references/TIERS.md).
- **Relentless** — Every word earns its place. Cut anything that doesn't answer a reader's question. A sharply curated short README beats a long one that hedges.

## Leading word: Curate

Every line, section, badge, and link passes the test: *does this serve a reader, or is it here because it exists?* Cut what fails. Curate the install section to the fastest path. Curate the feature list to what matters. Curate badges to the ones a reader actually clicks. When in doubt, leave it out.

## Phases

### PHASE 1: Scout

**Completion criterion:** every planned section named and its primary audience noted.

Before a word of prose, understand the project and its readers.

1. **Know the project.** What does it do, who does it serve, what distinguishes it from alternatives? Read source files, check the pyproject.toml / package.json, scan recent commits.
2. **Know the reader.** A README has at least three audiences — *evaluator* (should I use this?), *new user* (how do I start?), *contributor* (how do I help?). Each section serves one primary audience.
3. **Pick the tier.** Consult [TIERS.md](references/TIERS.md). Default to *solid* for developer tools; upgrade to *curated* for public-facing projects; use *lean* for experiments or personal packages.
4. **Audit if rewriting.** Read the existing README. Note what works, what's stale, what readers are likely bouncing on. Preserve what works; reconsider everything else.
5. **List sections.** Name every section the README needs. For each, note the primary audience.

### PHASE 2: Draft

**Completion criterion:** every section drafted with real content — no TODOs, no placeholders, no "TODO: add examples". Every claim backed by something real.

Write each section. Follow the structure in [TEMPLATES.md](references/TEMPLATES.md). Write for the audience identified in Scout.

Drafting rules:

- **Start fast.** The first paragraph is a complete answer to *what is this?* The second answers *why should I care?* The reader decides whether to stay inside three seconds.
- **Show, don't list.** Instead of "Fast and reliable", show a benchmark. Instead of "Many features", link to a feature table. A README that proves its claims is a README readers trust.
- **One code block per section.** A single, runnable example in Quick Start beats five snippets that each do half the job.
- **Badges signal health.** Only badge what a reader would check before adopting — build status, Python version, license. Not your social media follower count.

### PHASE 3: Relentless review

**Completion criterion:** every item in [CHECKLIST.md](references/CHECKLIST.md) passed with zero flags.

This is the review loop — the phase that separates curated from written.

1. Run every item in CHECKLIST.md against the draft.
2. Every flag gets fixed immediately. No deferrals, no "will address later".
3. After fixing, re-check only the flagged items.
4. Loop until the checklist passes clean.

Treat CHECKLIST.md as the binding completion criterion for this phase. The loop does not exit until every item is clean.

### PHASE 4: Polish

**Completion criterion:** rendered README verified — every badge resolves, every internal link works, every HTML element renders correctly on GitHub.

The README must be as good in rendering as it is in source.

1. Verify every badge URL resolves. Badges that return 404s signal an abandoned project.
2. Verify `<picture>`, `<p align="center">`, `<h1 align="center">`, `<details>`, and any HTML blocks render as intended on GitHub.
3. Confirm the directory tree reflects the actual project layout. Stale trees erode trust.
4. Navigate every internal anchor link (`#section-name`). Fix broken anchors.
5. Read the rendered version top-to-bottom as a first-time visitor. Does the story hold?

## Failure modes

- **Identity-first failure** — The README describes features before identity. The reader doesn't know what the project *is* until paragraph three. Cure: lead with the portal tenet — identity, then value, then details.
- **Tier mismatch** — A *curated*-tier README for an experimental project wastes effort readers won't reward. A *lean* README for a public tool undersells it. Cure: pick the tier in Scout and commit to it.
- **Thin checklist** — The review loop passes but the README still feels incomplete. Cure: add the missing items to CHECKLIST.md. The checklist is a living document, not a static artifact.
