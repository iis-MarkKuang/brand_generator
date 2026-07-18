---
name: code-review
description: Audit a Python + FastAPI codebase with fastapi-doctor (Rust-native static analyzer) for security, architecture, correctness, Pydantic, and performance issues.
license: MIT
---

# Code Review Skill (fastapi-doctor)

Wraps the open-source **fastapi-doctor** tool
(https://github.com/s-smits/fastapi-doctor) — a Rust-native static analyzer
purpose-built for FastAPI applications. It scores the codebase 0–100 and
reports findings across 68 rules in 8 categories:

- **Security** — hardcoded secrets, CORS wildcard, missing auth, subprocess shell, unsafe yaml
- **Architecture** — god modules, giant functions, fat route handlers, deep nesting, print in prod
- **Correctness** — sync-io-in-async, duplicate routes, missing HTTP timeout, unreachable code
- **Pydantic** — mutable defaults, deprecated validators, sensitive field types
- **Performance** — n+1 hints, regex in loops, sequential awaits
- **Resilience** — bare except/pass, swallowed exceptions, reraise without context
- **API Surface** — missing docstrings, tags, pagination
- **Configuration** — direct env access, env mutation

## Prerequisites

```bash
uv tool install --index https://s-smits.github.io/fastapi-doctor/simple/ fastapi-doctor
# binary lands in ~/.local/bin/fastapi-doctor
```

## Usage

Run a balanced audit (default profile) from the project root:

```bash
fastapi-doctor --repo-root . --profile balanced
```

Strict profile (all rules, no leniency):

```bash
fastapi-doctor --repo-root . --profile strict
```

Security-only sweep:

```bash
fastapi-doctor --repo-root . --only-rules "security/*"
```

Machine-readable JSON for triage:

```bash
fastapi-doctor --repo-root . --json > review.json
```

Doctor score only (0–100, use as a gate):

```bash
fastapi-doctor --repo-root . --score
```

## Output

The tool prints a categorized findings table with file:line, severity
(error/warning), rule id, and a human-readable message plus a final
**Doctor Score** (0–100). Treat `error` severity findings as must-fix.

## Rules

List every rule with `fastapi-doctor --list-rules`.
