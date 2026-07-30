---
inclusion: always
---

# Technology stack

- Python 3.11–3.14
- Textual 8.x for the TUI and Rich rendering
- `asyncio` subprocess transports over JSON lines
- Codex App Server for Codex
- ACP v1 for Kiro and configured ACP-compatible runtimes
- `pytest` and `pytest-asyncio` for tests
- Ruff for formatting, linting, and complexity gates
- Hatchling, Build, and Twine for distributions
- GitHub Actions for the supported-Python, minimum-Textual, and packaging matrix

Prefer the standard library and existing dependencies. Adding a runtime dependency
requires a concrete product need, compatibility review, and explicit scope. Provider
tests use fake subprocesses and must remain credential-free and network-free.

Use the exact commands and Python practices in the root `AGENTS.md`. See
`pyproject.toml` for authoritative version constraints and `docs/runtimes.md` for the
runtime contract.
