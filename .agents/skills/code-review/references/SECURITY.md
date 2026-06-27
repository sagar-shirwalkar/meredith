# Security Review Reference

Disclosed reference for the Security category in code review. Consult during PHASE 2 (Triage) when reviewing files in the risk zone (auth, data, API, concurrency).

## Injection

- SQL queries use parameterization, not string interpolation.
- Shell commands use `shlex.quote()` or an equivalent safe API.
- `eval()`, `exec()`, `__import__()`, `pickle.loads()` on untrusted data — flag immediately. No exception.
- File paths constructed from user input are normalized and bounded to a safe directory.

## Authentication & authorisation

- Every state-changing endpoint checks auth before executing.
- Token validation checks signature, expiry, and issuer. Not just "is it present?"
- Rate limiting on auth endpoints (login, password reset, signup).
- Password hashing uses a modern algorithm (bcrypt, argon2). Not SHA-2 or MD5.

## Data exposure

- Error messages returned to the client do not contain stack traces, internal paths, or database details.
- Logs do not contain credentials, tokens, PII, or full request bodies.
- Secrets (API keys, connection strings, signing keys) are loaded from environment variables or secrets manager. Not hardcoded, not in config files committed to git.
- URLs returned in API responses use HTTPS, not HTTP.

## Common Python pitfalls

- `assert` statements are not a security boundary — they compile away under `-O`. Use real conditionals for auth gates.
- `yaml.load()` without `Loader=yaml.SafeLoader` is arbitrary code execution. Use `yaml.safe_load()`.
- `xml.etree.ElementTree` without entity resolution disabled is vulnerable to XML bomb / XXE. Use `defusedxml`.
- `pickle` on any data you do not control is arbitrary code execution.
