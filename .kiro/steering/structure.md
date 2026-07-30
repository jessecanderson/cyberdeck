---
inclusion: always
---

# Project structure

Cyberdeck uses a `src/` layout:

- `src/cyberdeck/app.py` — Textual composition root and application coordination
- `src/cyberdeck/ui/` — focused screens and widgets
- `src/cyberdeck/domain.py` — provider-neutral models and state invariants
- `src/cyberdeck/event_reducer.py` — normalized provider-event transitions
- `src/cyberdeck/manager.py` — agent lifecycle and transport task coordination
- `src/cyberdeck/providers/` — provider contracts, Codex, ACP, and shared framing only
- `src/cyberdeck/runtimes.py` — executable discovery, preflight, and adapter creation
- `src/cyberdeck/commands.py` — authoritative built-in command metadata
- `src/cyberdeck/command_runtime.py` — command execution
- `src/cyberdeck/completion.py` — ordered completion rules
- `src/cyberdeck/modules.py` — public Module API v1 contracts
- `tests/` — unit, manager/provider, Textual pilot, and packaging coverage
- `docs/` — architecture, public API, runtime, design, and release decisions
- `scripts/` — explicit maintenance and measurement entry points

Follow dependencies inward: UI coordinates workflows; workflows mutate provider-neutral
domain state; providers do not depend on Textual. Avoid circular imports, provider-name
conditionals in shared code, generic utility modules, and new large dispatch functions.

The root `AGENTS.md` is authoritative for boundaries, verification, security, and
delivery behavior. Review `docs/architecture.md` and `docs/public-api.md` before moving
code or changing imports.
