# Debugging Flaky Tests

A flaky test passes and fails without code changes. The cause is always a missing invariant — something the test assumes but does not enforce.

## Monomorph the environment

Flaky tests are environment-sensitive. Pin every variable to eliminate drift:

- **Random seed** — Use `@pytest.mark.parametrize` with explicit seeds instead of `random`. Set `PYTHONHASHSEED=0` in CI.
- **Clock time** — Freeze time with `pytest-freezer` or `time_mock`. Tests that depend on `datetime.now()` or `time.time()` are flaky across midnight, DST, and leap seconds.
- **Filesystem state** — Use `tmp_path` fixture. Never assume a file exists or is absent.
- **Network** — Mock all external HTTP calls with `respX` or `pytest-httpx`. A test that hits a real server is flaky by definition.
- **Parallel execution** — Tests sharing state (database, filesystem, globals) will collide under `pytest-xdist -n auto`. Isolate per-test state or mark with `@pytest.mark.serial`.

## Capture the failure mode

Flaky tests fail in one of three patterns:

| Pattern | Signature | Cure |
|---|---|---|
| Order-dependent | Passes alone, fails in a suite | Test modifies shared state that a neighbour depends on. Use `pytest --random-order` to surface it, then isolate state per test. |
| Timing-dependent | Passes on fast machines, fails on slow (or vice versa) | Missing `await` or insufficient timeout. Add `async_timeout` or use `pytest-asyncio` with strict mode. |
| Resource-dependent | Passes with few tests, fails under full suite | Resource leak (file handles, connections, threads). Add teardown or use fixture `yield` + cleanup. |

## Loop until stable

1. Run the test 20 times in isolation: `pytest path/to/test.py::test_name --count=20`.
2. If it passes 20/20, the flake is order-dependent. Run with `--random-order` to surface the conflict.
3. If it fails intermittently in isolation, it is timing- or resource-dependent. Add probes (log timestamps, resource counts, thread counts).
4. Fix one suspect at a time. Run 20x again. Loop until 20/20 passes.
5. Add a regression comment above the test explaining what was flaky and why the fix resolves it.
