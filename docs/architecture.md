# Cyberdeck architecture

Cyberdeck is a local Textual application with provider-neutral domain state and
provider-specific transport adapters. Dependencies point inward: UI code may call
application workflows, workflows may use domain models and provider protocols, and
providers must not depend on Textual widgets or application screens.

## Package boundaries

- `domain.py` contains provider-neutral state and normalization helpers. Domain
  timestamps are timezone-aware UTC values.
- `providers/` contains Codex App Server and ACP protocol adapters behind the
  `AgentAdapter` protocol.
- `runtimes.py` owns executable discovery, preflight, and adapter construction.
- `manager.py` owns agent lifecycle and transport tasks. `event_reducer.py` applies
  normalized provider events without depending on the UI.
- `commands.py` is the authoritative built-in command catalog.
  `command_runtime.py` maps its handler keys to command behavior, and
  `completion.py` provides ordered, independently testable completion rules.
- `ui/` contains screens and widgets. `ui/screens.py` is a compatibility export
  facade; new implementation code belongs in the focused UI modules.
- `builtin_modules.py` contains retained built-in workspace widgets and their typed
  module specification.
- `clipboard.py` owns platform and terminal clipboard selection and error conversion.
- `app.py` is the Textual composition root. It owns widget composition, application
  coordination, and callbacks, but protocol parsing and command parsing do not live
  there.

## Compatibility rules

- Public commands and keyboard behavior are preserved during internal refactors.
- Provider-specific data is normalized before it mutates `AgentState`.
- External modules target Module API v1 and declare a compatible Cyberdeck release
  range. The 0.3 line uses `>=0.3,<0.4`.
- Prompts, transcripts, credentials, and approval payloads are not persisted by
  architecture helpers unless a feature explicitly establishes that policy.

## Quality gates

CI runs Ruff linting, Ruff formatting checks, the full supported-Python test matrix,
minimum-Textual tests, distribution builds, metadata validation, and a wheel smoke
test. Complexity limits prevent another monolithic command or event dispatcher from
being added. Rendering throughput can be measured locally with
`python scripts/benchmark_rendering.py` before changing transcript refresh behavior.
