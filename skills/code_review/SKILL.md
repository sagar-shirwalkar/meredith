---
name: code-review
description: Perform a thorough code review on changes, checking for bugs, style issues, security vulnerabilities, and performance problems.
---

# Code Review Skill

## When to Use This Skill

Use this skill when the user:

- Asks to review code, a PR, or a diff
- Says "review this change" or "check my code"
- Wants feedback on code quality or correctness
- Mentions code review, PR review, or pull request

## Review Checklist

### 1. Correctness

- Does the code do what it is supposed to do?
- Are there off-by-one errors or boundary condition bugs?
- Are return values checked and handled properly?
- Are there potential null/None/undefined access issues?

### 2. Security

- Are user inputs validated and sanitized?
- Are there SQL injection, XSS, or command injection risks?
- Are secrets or credentials hardcoded?
- Are authentication and authorization checks in place?

### 3. Performance

- Are there N+1 query patterns?
- Are expensive operations inside loops?
- Can any operations be parallelized or cached?
- Are data structures chosen appropriately?

### 4. Style and Readability

- Does the code follow the project's style conventions?
- Are variables and functions named clearly?
- Are complex sections commented?
- Is the code DRY (Don't Repeat Yourself)?

### 5. Error Handling

- Are errors caught and handled gracefully?
- Are error messages informative but not leaking sensitive data?
- Are resources (files, connections) properly cleaned up?

### 6. Testing

- Are there tests for the new/changed functionality?
- Do tests cover edge cases and error conditions?
- Are tests isolated and independent?

## Steps

### Step 1 - Gather Context

- Read the changed files using read_file or git_diff
- Understand what the code is intended to do

### Step 2 - Run Static Analysis

- Run get_diagnostics on changed files
- Note any lint errors or type errors

### Step 3 - Review Systematically

- Go through each section of the checklist above
- Note issues with file path, line number, and explanation

### Step 4 - Summarise Findings

- Categorise issues as: critical / warning / suggestion
- Prioritise security and correctness issues
- Provide specific fix suggestions for each issue

## Output Format

Structure your review as:

**Critical** (must fix):

- [file:line] Description of the issue

**Warnings** (should fix):

- [file:line] Description of the issue

**Suggestions** (nice to have):

- [file:line] Description of the suggestion
