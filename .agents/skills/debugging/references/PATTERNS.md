# Debugging Patterns by Symptom

Match your symptom to a known cause class. Each entry links the symptom to the most likely root cause and the probing strategy to confirm it.

## Null / None / undefined access

| Symptom | Likely cause | Probe |
|---|---|---|
| `AttributeError: 'NoneType' object has no attribute 'x'` | A function returned `None` on a code path the author didn't expect | Log the return value at every call site. Track which code path produced `None`. |
| `KeyError: 'x'` | Dict access without checking key existence | Check whether the key is guaranteed (schema validation) or optional (use `.get()`). |
| `IndexError: list index out of range` | Off-by-one or empty collection | Log `len()` before access. Check if the source list could be empty. |
| `TypeError: 'NoneType' object is not callable` | A variable expected to be a function is `None` | Trace the assignment of the variable. It was never set or was explicitly set to `None`. |

## Off-by-one / boundary

| Symptom | Likely cause | Probe |
|---|---|---|
| Fencepost — misses first or last element | Loop uses `<` instead of `<=`, or vice versa | Log the loop bounds and iteration count. Check inclusive vs exclusive semantics. |
| Crash on empty input | Code assumes at least one element | Check `if not items:` guard. Add a test with empty input. |
| Crash on single-element input | Code assumes a neighbour exists (`items[i+1]`) | Check `i < len(items) - 1` before accessing `[i+1]`. |
| Works for n=2 but not n=1 | Loop or recursion base case is wrong | Trace the first iteration specifically. |

## Type / shape mismatch

| Symptom | Likely cause | Probe |
|---|---|---|
| `TypeError: can only concatenate str (not "int") to str` | Mixed types in an operation | Log `type()` of both operands before the operation. |
| Wrong sort order | Items compared as strings instead of numbers | Log `type()` of elements being sorted. Check if they arrived as strings from JSON/CLI. |
| Format string renders wrong | Wrong type coercion in f-string or format call | Log each interpolated value's `type()` and `repr()`. |
| Pydantic validation errors on valid data | Schema field type doesn't match actual data shape | Check if the data has extra nesting, nullable fields, or union ambiguity. |

## State mutation

| Symptom | Likely cause | Probe |
|---|---|---|
| Output depends on call order | Shared mutable state between operations | Log `id()` of shared objects before and after each mutation. Check for mutable defaults in function signatures. |
| Same input, different output | Function modifies its argument in place | Log the argument before and after the call. Check for `list.append()`, `dict.update()`, `set.add()`. |
| Caching returns stale data | Cache key doesn't include all relevant parameters | Log the cache key and the stored value. Check if a parameter was added to the function but not to the cache key. |
| Global/config changes persist across tests | Test modifies global state without teardown | Check for `monkeypatch` / cleanup in test teardown. Check module-level state. |

## Concurrency / race

| Symptom | Likely cause | Probe |
|---|---|---|
| Flaky test that only fails under CI | Race condition exposed by parallel execution | Check for shared state between tests. Check `pytest-xdist` / `pytest-asyncio` mode. |
| `RuntimeError: asyncio.run() cannot be called from a running event loop` | Nested event loops | Use `asyncio.run()` only at the top-level entry point. Use `pytest-asyncio` for async tests. |
| Data corruption under load | Unsynchronized write to shared structure | Add thread-safe wrappers or use `asyncio.Lock` for async shared state. |

## Dependency / environment

| Symptom | Likely cause | Probe |
|---|---|---|
| Works locally, fails in CI | Different dependency version or OS | Pin exact versions in `pyproject.toml` or `requirements.txt`. Check OS-specific code paths. |
| Works on one Python version, not another | Syntax or stdlib change between versions | Check the minimum Python version. Grep for version-gated code (`sys.version_info`). |
| `ModuleNotFoundError: No module named 'x'` | Missing dependency or install | Check `pyproject.toml` dependencies. Check if the module is installed in the active environment. |
| Import works in REPL but not in script | Working directory not on `sys.path` | Use `python -m package.module` instead of `python path/to/script.py`. |

## Logic / semantic

| Symptom | Likely cause | Probe |
|---|---|---|
| Boolean condition always true/false | Operator precedence or short-circuit logic | Add parentheses. Log each term of the condition separately. |
| Wrong branch taken in if/else | Condition doesn't match the developer's intent | Log the condition's value and each term's value before the branch. |
| Loop runs 0 or infinite times | While condition or for range misconfigured | Log the loop variable and condition on each iteration. Check the initial state. |
| Try/except swallows an unrelated error | Catch is too broad (`except Exception`) | Narrow to specific exception types. Log the full traceback in the except block. |
