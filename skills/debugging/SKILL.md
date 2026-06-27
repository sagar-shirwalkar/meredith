---
name: debugging
description: Systematically debug an error or failing test by isolating the root cause and verifying the fix.
---

# Debugging Skill

## When to Use This Skill

Use this skill when the user:

- Reports an error, crash, or unexpected behavior
- Asks to fix a failing test
- Says something is not working or broken
- Mentions debugging, fixing a bug, or troubleshooting

## Debugging Methodology

### Step 1 - Reproduce the Error

- Run the exact command or test that fails
- Capture the FULL error message and stack trace
- Note the exact conditions under which it occurs

### Step 2 - Read the Error Carefully

- Identify the error type (syntax, runtime, logic)
- Find the file and line number mentioned in the stack trace
- Read the error message literally — do not assume

### Step 3 - Locate the Problem

- Use read_file to examine the code at the error location
- If the error is in a dependency or called function, trace the call:
  - Use find_symbols to locate the function definition
  - Use search_code to find where it is called
- Check if the error might be caused by a missing import or dependency

### Step 4 - Form a Hypothesis

- Based on the error and the code, form a hypothesis about the root cause
- State your hypothesis explicitly before making changes

### Step 5 - Apply a Fix

- Make the minimal change needed to fix the issue
- Prefer edit_file over write_file
- Do not change unrelated code

### Step 6 - Verify the Fix

- Re-run the failing test or command
- Run get_diagnostics on modified files
- Check that no other tests are broken

### Step 7 - Document

- If the bug was subtle, add a comment explaining the fix
- If a test was missing, add one that would have caught the bug

## Common Patterns

    Symptom                    | Likely Cause              | First Check
    ---------------------------|---------------------------|-------------------------------------------
    NameError / not defined    | Missing import or typo    | Search for the symbol definition
    TypeError wrong arguments  | API changed or overload   | Check function signature with find_symbols
    AttributeError None        | Variable is None          | Trace where it is assigned
    ImportError                | Missing package or path   | Check requirements and sys.path
    AssertionError in test     | Code behavior changed     | Read the test to understand expectation
    Timeout / infinite loop    | Missing base case         | Check loop/recursive termination

## Rules

- Never change test expectations to make a test pass — fix the code instead
- Always reproduce the error before attempting a fix
- Make one fix at a time and verify after each
- If you cannot find the cause after 3 attempts, ask the user for more context
