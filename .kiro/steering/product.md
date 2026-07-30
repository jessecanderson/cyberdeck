---
inclusion: always
---

# Product overview

Cyberdeck is a local, keyboard-first terminal interface for running and monitoring
multiple coding agents without hiding provider identity or permission boundaries.

Its current users are developers operating Codex and Kiro sessions from one terminal.
The interface should make agent state, activity, approvals, failures, recovery, context,
and dispatch ownership understandable at a glance.

Core product principles:

- local-first and credential-safe;
- keyboard-complete, with predictable focus and cancellation;
- provider-aware without leaking provider-specific details into shared UX code;
- recoverable rather than silently failing;
- visually distinctive but readable, including the presentation-only compact density;
- incremental: release work should not become speculative orchestration or provider
  expansion unless that scope is explicitly approved.

The root `AGENTS.md` contains the authoritative repository-wide engineering and delivery
rules. `README.md`, `docs/design-language.md`, and `CHANGELOG.md` describe current user
behavior and release history.
