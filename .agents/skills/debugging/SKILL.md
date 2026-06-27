---
name: debugging
description: Debug a failure — test failures, runtime errors, unexpected behaviour, or build breaks. Use when the user reports a bug, a test fails, an error trace appears, output is wrong, or behaviour is unexplained.
disable-model-invocation: false
---

# Debugging

## Tenets

- **Reproduce first** — A bug you can trigger on demand is a bug you can fix. A bug you cannot reproduce is a guess. Invest in reproduction before anything else.
- **One hypothesis at a time** — Change one thing, observe the result. Changing two things at once tells you nothing about which one mattered.
- **Bias toward evidence** — The stack trace tells you *where*, not *why*. The actual cause is rarely where the error is raised. Dig upstream.

## Leading words

- **Probe** — A targeted diagnostic (print, log, added assertion, narrowed input) placed at a known point to reveal state. Probes are cheap and disposable; place them aggressively, remove them on fix.
- **Bisect** — Binary search through the chain of cause and effect: half the commits, half the input, half the code path. Each bisect eliminates half the search space.
- **Monomorph** — Reduce variability. Pin every variable you can (seed, input, config, environment) so only the suspect remains free. A flaky test is a test you haven't monomorphed.
- **Rubber duck** — Explain the problem aloud, to an inanimate object or empty buffer. The gap between what you think the code does and what it actually does appears in the telling. Cheap, fast, often sufficient alone.

## Phases

### PHASE 1: Reproduce

**Completion criterion:** a reliable, documented reproduction case — the exact command or input, the exact output, and the exact conditions.

1. Capture the exact error: full traceback, exit code, unexpected output.
2. Check what changed — most bugs are recent. Run `git log --oneline -10` in the affected module. Note recent commits, dependency bumps, or config changes that bracket the first appearance of the bug.
3. Find or create the minimal reproducer — the shortest input and fewest steps that trigger the failure. A test is the ideal reproducer.
4. Reproduce at least twice to confirm consistency.
5. If the failure is intermittent (flaky), document the pass/fail rate first, then skip to [FLAPPING.md](references/FLAPPING.md).

### PHASE 2: Probe

**Completion criterion:** the fault is narrowed to a single function, module, or code path — a clear suspect zone.

1. Read the traceback from bottom to top. The *bottom* frame is where the error was raised; the *top* frames are where the fault was introduced. The gap between them is where you probe.
2. Add probes at decision points entering the suspect zone: log the inputs, the state, the branch taken.
3. Run the reproducer. Read the probes.
4. If the probes rule out the suspect zone, widen the search and repeat. If they confirm it, proceed to bisect.

### PHASE 3: Bisect

**Completion criterion:** the root cause is identified — the specific line, input, or condition that triggers the failure. Not a guess, not a zone — a line.

1. Within the suspect zone, isolate the exact condition: specific input value, state mutation, call order, boundary case.
2. Use [PATTERNS.md](references/PATTERNS.md) to match the symptom to a known cause class (null access, off-by-one, race, type mismatch, etc.).
3. **If one path stalls** — the suspect zone is clear but no single condition isolates. Generate 2-3 competing hypotheses from different failure categories (see [CATEGORIES.md](references/CATEGORIES.md)). Test them independently — one change at a time — and compare the evidence. The hypothesis whose predicted fix makes the reproducer pass is the root cause.
4. Confirm the root cause by: (a) predicting what change would fix it, (b) applying that change, (c) verifying the reproducer passes.
5. If the fix doesn't work, you haven't found the root cause. Revert and return to probing or competing hypotheses.

### PHASE 4: Fix

**Completion criterion:** the reproducer passes, existing tests pass, and no regression in related behaviour.

1. Apply the minimal fix — the smallest change that addresses the root cause without over-correction.
2. Run the reproducer. Run existing tests in the affected module. Run a broader test suite.
3. Check for sibling bugs: the same class of error elsewhere in the codebase.
4. Remove all probes added during debugging.

### PHASE 5: Reflect (optional)

**Completion criterion:** a commit message or note captures what was wrong, why, and what prevents recurrence.

Write a commit message that explains the root cause, not just what changed. Include:
- The symptom (what broke)
- The root cause (why it broke)
- The fix (what changed)
- The prevention (test added, type narrowed, invariant enforced)

## Failure modes

- **Probe starvation** — Debugging without enough evidence. You guess at the cause rather than reading the state. Cure: add more probes before forming hypotheses.
- **Premature fix** — Jumping to a fix before the root cause is confirmed. The reproducer still fails, but you've added complexity. Cure: don't fix until bisect completes.
- **Over-correction** — Fixing the symptom rather than the cause. The error disappears but the underlying bug remains. Cure: confirm root cause by predicting the fix outcome before applying it.
- **Environment drift** — The bug repros on one machine but not another. Monomorph the environment (OS, Python version, dependency versions, working directory state).
- **Stuck** — You've been probing for minutes with no narrowing. Cure: rubber duck the problem from the start, step away briefly, or start a fresh bisect from the reproducer — the path you're on may be wrong.
