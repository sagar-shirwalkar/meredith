# README Review Checklist

The binding completion criterion for PHASE 3 (Relentless review). Every item must pass with zero flags before the README ships.

## Identity

- [ ] The very first paragraph answers *what is this?* in plain language.
- [ ] The second paragraph (or first section) answers *why should I care?* — the project's differentiating value.
- [ ] A reader unfamiliar with the domain can understand the elevator pitch.
- [ ] No jargon goes unexplained on first use.

## Quick Start

- [ ] A complete, copy-pasteable example runs from scratch to visible result.
- [ ] The example uses the fastest possible path (default config, minimal setup).
- [ ] Prerequisites are stated before the example, not after.
- [ ] The example output is shown, so the reader knows they succeeded.

## Installation

- [ ] Every supported installation method is listed (package manager, source, Docker, etc.).
- [ ] The recommended method is clearly marked.
- [ ] Version requirements (Python, Node, OS) are explicit.
- [ ] Credential setup (API keys, tokens) links to where to get them, not just `export KEY=...`.

## Structure

- [ ] Sections are ordered by reader need: identity → quick start → usage → advanced → contributing.
- [ ] Every heading is a clear signpost, not a puzzle ("Configuration" not "Settings and Options Context").
- [ ] The README is scannable — short paragraphs, bullet lists where appropriate, code blocks for examples.
- [ ] No section is empty or contains "TODO" or "coming soon".

## Badges

- [ ] Every badge URL resolves to a real page (not a 404).
- [ ] Badges are grouped in a single `<p align="center">` block at the top of the README.
- [ ] Only badges a reader would check before adopting the project are present (build status, version, license, coverage).
- [ ] Social/vanity badges (Twitter followers, stars) are absent unless the project is a social product.

## Visual

- [ ] Images and SVG assets exist at the referenced paths — no broken image placeholders.
- [ ] `<picture>`, `<p align="center">`, and HTML blocks render correctly on GitHub.
- [ ] The project tree diagram matches the actual repository layout.
- [ ] Animations/GIFs (if present) have a paused fallback or are small enough to load quickly.

## Links

- [ ] Every internal anchor link navigates to the correct section.
- [ ] Every external link resolves (docs, registry, CI badges).
- [ ] License badge links to the LICENSE file.
- [ ] No dead links from renamed sections or removed pages.

## Depth

- [ ] Feature descriptions prove claims with examples, benchmarks, or screenshots — not adjectives.
- [ ] Configuration options are documented with defaults and explanations.
- [ ] API/CLI reference is present or linked to dedicated docs.
- [ ] Advanced usage sections exist for readers who need them (customisation, plugins, internals).

## Contribution

- [ ] Contribution guidelines are present or linked (CONTRIBUTING.md).
- [ ] Development setup instructions exist (how to install from source, run tests).
- [ ] The license is stated, not just badged.
- [ ] Code of conduct is linked if the project is public.
