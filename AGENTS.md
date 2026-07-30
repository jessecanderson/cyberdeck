# Cyberdeck agent guidance

This file is the durable project guidance for coding agents, including Codex and
Kiro. Apply it to the entire repository. Human instructions in the current task take
priority when they conflict with this file.

## Product intent

Cyberdeck is a keyboard-first Textual TUI for operating multiple local coding agents.
It currently supports Codex through App Server and Kiro through ACP over local stdio.
Preserve the restrained ODS visual language, but prefer legibility, deterministic
behavior, and recoverability over decorative effects.

Do not silently expand a release into new providers, remote orchestration, or protocol
experiments. Treat release scope in the issue, milestone, or user request as a boundary.

## Start by orienting

Before editing:

1. Read the relevant implementation, tests, and nearby documentation.
2. Check `git status`; preserve unrelated and user-authored changes.
3. Consult `docs/architecture.md` for dependency boundaries and
   `docs/public-api.md` before changing public imports or extension contracts.
4. Prefer the smallest behavior-preserving change that fully resolves the task.

Use `./scripts/dev` to launch the current source tree during local verification. It
deliberately bypasses any older wheel installed in `.venv`.

Do not guess provider protocol messages. Use documented capabilities and existing
adapter contracts. Never send an unsupported request merely because another runtime
accepts something similar.

## Architecture rules

- Keep provider-neutral state and transitions in `domain.py` and `event_reducer.py`.
- Keep transport and protocol parsing in `providers/`. Codex and ACP may share framing
  and lifecycle mechanics, but their protocol semantics remain separate.
- Keep runtime discovery and preflight in `runtimes.py` and lifecycle coordination in
  `manager.py`.
- Keep the built-in command catalog authoritative in `commands.py`; route behavior
  through `command_runtime.py` and completion through `completion.py`.
- Keep focused Textual widgets and screens in `ui/`. `app.py` is the composition root,
  not the default home for new domain logic, protocol parsing, or large dispatchers.
- Keep external Module API v1 code dependent on public contracts from `modules.py`, not
  application or manager internals.
- Prefer explicit typed boundaries, small functions, and dependency injection over
  tests that mutate private dictionaries or callbacks.
- Preserve compatibility exports during the 0.3 release line unless a task explicitly
  authorizes a breaking change.

When adding a cross-cutting feature, first decide which existing owner should contain
it. Create a new module only when it establishes a real responsibility boundary; do
not create pass-through abstractions or generic `utils.py` collections.

## Python practices

- Support Python 3.11 through 3.14 and Textual 8.2 through the declared upper bound.
- Use modern type hints, `pathlib.Path`, dataclasses for value/state objects, and
  protocols for structural service contracts where they clarify a boundary.
- Keep imports at module scope unless a lazy import is required to break a documented
  cycle or defer an optional dependency.
- Use timezone-aware UTC timestamps for persisted or cross-provider state.
- Catch narrow exceptions when recovery differs. At process and event-pump boundaries,
  convert broad failures into concise, actionable per-agent errors.
- Keep credentials, raw private transcripts, approval payloads, and unsanitized
  provider logs out of configuration, fixtures, documentation, and commits.
- Respect Ruff's complexity limits. Split behavior by responsibility rather than
  suppressing complexity rules.

## Behavior and UX invariants

- Maintain keyboard-first operation and preserve prompt drafts when switching agents.
- Modal navigation must remain predictable: arrows move, Space selects where relevant,
  Enter confirms or accepts, Escape cancels, and Tab accepts completion where offered.
- `/clear` is display-only. `/compact` is provider-owned, capability-gated, and requires
  a ready agent.
- Presentation density changes styling only; they must not change capabilities,
  commands, data, or boot behavior.
- Transport failures must identify the runtime, give a concise reason and recovery
  guidance, and offer `/retry` only when supported.
- Preserve successful dispatch targets when another target fails.
- Never recommend bypassing Gatekeeper or other platform security controls.

## Testing

Use fake local transports and injected services. Tests must not require credentials,
network access, a real provider process, or the user's clipboard and config files.

For a focused change, run the nearest tests while iterating. Before handing off a
completed code change, run:

```bash
ruff format --check src tests scripts
ruff check src tests scripts
pytest -q
python -m build --no-isolation
python -m twine check dist/cyberdeck_tui-*.whl dist/cyberdeck_tui-*.tar.gz
```

If the environment is not installed editable, prefix source tests with `PYTHONPATH=src`
so an older installed wheel is not tested accidentally. Run
`scripts/benchmark_rendering.py` when transcript rendering or operation display changes;
record measurements for comparison, but do not add flaky wall-clock CI thresholds.

Add regression coverage at the lowest useful layer:

- pure parsing, validation, and state transitions before UI tests;
- manager/provider tests for lifecycle and transport behavior;
- Textual pilot tests for focus, key routing, rendering, and modal behavior;
- packaging smoke tests for version, artifact, or entry-point changes.

## Documentation and delivery

- Update `CHANGELOG.md` for release-visible changes.
- Update the relevant file under `docs/` when behavior, architecture, supported API,
  runtime requirements, or release procedure changes.
- Keep comments focused on constraints and rationale, not line-by-line narration.
- Do not commit, push, open or merge a pull request, tag a release, or mutate GitHub
  issues unless the user requests that delivery action.
- When asked to publish changes, report the commit, PR, verification performed, and any
  remaining risk. Never merge a draft or unreviewed PR unless explicitly instructed.
