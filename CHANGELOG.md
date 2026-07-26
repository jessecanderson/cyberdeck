# Changelog

All notable changes to Cyberdeck are documented here. The project follows
[Semantic Versioning](https://semver.org/).

## [0.2.1] - Unreleased

### Added

- Original Open Deck Systems mythos and interface-language guide.
- Local Grid empty state with direct New Uplink and Archive guidance.
- Explicit operative attention markers for ICE holds, failures, and unread
  background echoes.
- Semantic Grid Trace classes and phases for commands, file changes, tools,
  searches, permission interlocks, and failures.

### Changed

- Reframed the agent rail as the Local Grid and the workspace rail as the
  Module Bay.
- Added real provider and project topology beneath each operative callsign.
- Refined connection, restoration, memory, and failure language around ODS
  carriers and constructs.
- Expanded the boot sequence with grid mapping, provider-gate, ICE-table, and
  construct checks.
- Updated lifecycle controls, agent switching, dispatch, and operation detail
  copy to use the shared ODS vocabulary.
- Report the installed Cyberdeck version during the Codex app-server handshake.

### Fixed

- Reset the active-agent header after the final operative disconnects instead
  of leaving stale agent information visible.
- Guard the POST renderer against its worker starting before boot widgets have
  finished mounting.

## [0.2.0] - 2026-07-25

### Added

- External module installation, editable linking, isolated environments,
  enable/disable controls, staged updates, removal, and module diagnostics.
- Public module API and project scaffolding command.
- Module-aware command autocomplete and bundled Journal workspace.
- Homebrew tap installation and automated release artifacts.

## [0.1.0] - 2026-07-24

### Added

- Multi-agent Codex command center with durable thread restoration.
- Lifecycle controls, guarded dispatch, clipboard and routing commands.
- Inline ICE permission gates and normalized operation telemetry.
- Agent switcher, prompt history, themes, system manifest, and package CI.

[0.2.1]: https://github.com/jessecanderson/cyberdeck/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/jessecanderson/cyberdeck/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/jessecanderson/cyberdeck/releases/tag/v0.1.0
