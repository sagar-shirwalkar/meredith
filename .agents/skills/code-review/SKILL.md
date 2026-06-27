---
name: code-review
description: Review a diff, pull request, or code change for correctness, security, performance, and maintainability. Use when asked to review code, check a PR, audit a change, or vet a contribution.
disable-model-invocation: false
---

# Code Review

## Tenets

- **Review the code, not the author.** Feedback addresses the change, not the person. No "you" — "This path lacks error handling."
- **Automate what you can.** Style, formatting, and lint are tools' jobs, not reviewers'. If it can be a CI check, don't review it by hand.
- **Every comment earns its place.** A vague concern ("this could be better") wastes the author's attention more than a clear blocking issue ("this SQL is injectable"). Say nothing, say it clearly, or say "approve".
- **Bias toward action.** A review that blocks for a week is worse than a review that approves with follow-up. Block only what would ship a bug; suggest everything else.

## Leading words

- **Triage** — The first pass: assess scope, decide what to probe deeply, identify what needs immediate attention vs what can wait.
- **Gate** — A condition the change must meet before shipping. Gating issues block merge; everything else is a suggestion.

## Phases

### PHASE 1: Scout

**Completion criterion:** the PR's purpose, scope, and risk level are understood.

1. Read the PR description and linked issue. What is the change meant to do?
2. Scan the file list. How many files changed? (>400 lines across >10 files → suggest splitting.)
3. Check CI status. If tests fail or lint is red, flag it immediately — no point reviewing code that doesn't pass its own bar.
4. Identify the risk zone: does the change touch auth, data persistence, public API surfaces, or concurrency? Those files get a deeper probe.

### PHASE 2: Triage

**Completion criterion:** every file has been read once; issues are captured by category, not yet classified by severity.

One pass through every changed file, top to bottom. For each file, check against the categories below. Capture every observation as a note — don't classify yet, don't skip anything because it seems minor.

- **Correctness** — Off-by-one, unhandled None/null, wrong branch taken, boundary condition missed, assumption violated.
- **Security** — Unvalidated input, injection surface, hardcoded secret, missing auth gate, data leak in error message. See [SECURITY.md](references/SECURITY.md) for deeper reference.
- **Performance** — Loop over a query, N+1, blocking call in async path, allocation in hot loop, unbounded growth.
- **Maintainability** — Magic number, duplicated logic, function doing too much, name that obscures intent, dead code.
- **Test quality** — Missing test for the change, test that mocks everything and asserts nothing, test that depends on another test's state.

### PHASE 3: Gate

**Completion criterion:** every observation from Triage is classified as gate (blocks merge) or suggestion (nice to have), and every gate has an actionable fix.

1. Classify each observation:
   - **Gate** — The change is wrong, unsafe, or untested. Must fix before merge.
   - **Suggestion** — Improvement that would help but is not required. The author can defer or decline.
   - **Praise** — A notable positive — well-named abstraction, thorough test, clever simplification.
2. For every gate, articulate the specific fix. Vague gates ("this should be better" without "here's how") force round-trips.
3. Verify each gate independently — don't pile conditions. A single change asked to fix three unrelated issues is three separate gates.

### PHASE 4: Summarise

**Completion criterion:** the review comment is posted with clear gates, ordered suggestions, and an unambiguous verdict.

Structure:

```markdown
## Summary
One paragraph: what the change does and whether the approach is sound.

## Gates (must fix)
- [file:line] Description of the issue and the specific fix.

## Suggestions (consider)
- [file:line] Description of the improvement opportunity.

## Praise
- [file:line] What was done well.

## Verdict
✅ Approve | 💬 Comment | 🔄 Request changes
```

The verdict is unambiguous. "Request changes" means at least one gate exists. "Comment" means suggestions only. "Approve" means clean.

## Failure modes

- **Scope creep** — "While you're at it, also fix X" that is unrelated to the change. Each PR fixes one thing. File a new issue.
- **Rubber stamp** — Approving without reading, because the change looks small or the author is trusted. Every change gets the full triage pass.
- **Bike shedding** — Debating trivial style or naming while real gates go unmentioned. Curate your attention toward what matters.
- **Ghosting** — Requesting changes then disappearing. If you gate, stay available to re-review within the same day.
