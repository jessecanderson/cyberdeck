# Changelog

All notable changes to Cyberdeck are documented here. The project follows
[Semantic Versioning](https://semver.org/).

## [0.3.4] - 2026-07-28

### Added

- Keyboard-driven whole-message transcript selection with exact plain-text
  clipboard output and non-mutating cancellation.
- Numeric `/copy N` selection for copying the latest N assistant outputs in
  chronological order without leaving the command line.
- Explicit runtime, usage, compaction capability, and display-only clearing
  semantics in `/context`.

### Changed

- Identify sidebar agent rows by durable agent UUIDs so asynchronous refreshes
  do not depend on transient child ordering or widget shape.
- Make Homebrew tap publishing safe to rerun for an existing release branch or
  open pull request while retaining checksum validation and protected auto-merge.
- Add bounded startup defaults for workspace root, Codex approval policy,
  sandbox mode, and boot visibility with safe validation fallbacks.
- Add contributor, security, conduct, issue, and pull-request guidance.

### Fixed

- Give transcript-selection movement, toggle, confirmation, and cancellation
  bindings priority over the focused list widget.
- Time out stalled Codex App Server requests and context compaction with
  actionable recovery guidance.
- Preserve clipboard failure reporting in transcript selection mode.

## [0.3.3] - 2026-07-27

### Fixed

- Resolve Homebrew's cask symlink before launching the standalone runtime, so
  `cyberdeck` works after installation rather than only from an extracted
  release directory.

## [0.3.2] - 2026-07-27

### Added

- Publish a tested standalone Apple Silicon macOS bundle containing a
  relocatable CPython runtime and Cyberdeck's application dependencies.
- Dispatch the standalone artifact URL and verified checksum to the Homebrew
  tap so tagged releases automatically update the cask through a protected PR.

### Changed

- Recommend `brew install --cask` on macOS so Cyberdeck no longer depends on a
  Homebrew Python bottle or the host's system Expat library.

### Fixed

- Avoid `pyexpat` loader failures on managed macOS versions whose system Expat
  symbols are incompatible with Homebrew's precompiled Python bottles.

## [0.3.1] - 2026-07-26

### Added

- Provider-aware `/context` diagnostics and `/compact` context compaction for
  Codex App Server and Kiro's documented ACP command extension.
- Direct `/switch CALLSIGN` navigation with callsign autocomplete.
- `/next-module` and `F6` as reliable module-cycling controls.

### Changed

- Generate the scrollable command reference from the live command registry so
  built-in and module commands cannot silently disappear from `/help`.
- Give `Ctrl+J` and `Ctrl+K` priority over the focused prompt and preserve
  wraparound navigation with large agent lists.
- Navigate the `Ctrl+P` Uplink Matrix with Up/Down directly from its search
  field, and use Up/Down plus Tab to select prompt autocomplete suggestions.
- Route arrow keys consistently through hotkey-opened overlays: searchable
  Restore and Dispatch lists retain typing focus, Operative Control navigates
  its actions, and scrollable Help and operation details retain keyboard scroll.
- Refresh only the affected agent row for streamed background events rather
  than rebuilding the active transcript and every sidebar label.
- Clarify that `/clear` clears Cyberdeck's local display while provider context
  remains intact; use `/compact` to reduce provider context.

## [0.3.0] - 2026-07-26

### Added

- ACP v1 runtime with initialize negotiation, local stdio sessions, streaming
  transcript boundaries, normalized tool telemetry, interruption, and explicit
  transport-failure recovery.
- Kiro CLI runtime with new-session and session-load lifecycle support,
  provider-owned context restoration, model metadata, and process-tree cleanup.
- Inline Kiro ICE gates, independent batched permission requests, and concurrent
  approve-all handling.
- Runtime registry with Codex and Kiro built-ins plus configurable ACP commands,
  executable/version preflight, runtime selection, and `/runtimes` diagnostics.
- Negotiated per-agent capability metadata used by lifecycle controls and
  slash commands.

### Changed

- Generalized `/new` to `/new CALLSIGN [RUNTIME] [PATH]` while preserving the
  earlier path-first spelling.
- Made agent creation, retry, interruption, disconnect, kill, and dispatch
  preserve the owning runtime in mixed Codex/Kiro sessions.
- Keep ordinary prompt submission responsive while ACP turns and permission
  requests remain open.
- Render distinct ACP assistant segments as separate transcript messages,
  including boundaries around tool calls and permission gates.

### Fixed

- Prevent inline permission cards and long-running ACP prompts from stealing or
  blocking terminal input focus.
- Reconstruct Kiro replayed transcript rows during session restoration without
  collapsing assistant messages onto one line.
- Stop the complete adapter-owned ACP process group so retries do not race a
  provider session lock left behind by child processes.
- Report malformed ACP messages and unexpected stdout closure as recoverable
  transport failures.

## [0.2.1] - 2026-07-25

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
- Keep transient grid alerts in a reserved rail so the conversation viewport
  does not jump when agent state changes.

### Fixed

- Write `/copy` through the native macOS clipboard utility and report failures
  instead of claiming success after an unsupported terminal clipboard request.
- Preserve Codex agent-message item identity so separate streamed messages no
  longer collapse into one transcript line.
- Add visual spacing between distinct transcript messages.
- Reset the active-agent header after the final operative disconnects instead
  of leaving stale agent information visible.
- Accept large newline-delimited Codex protocol messages produced by repository
  reviews and other tool-heavy turns.
- Surface transport failure details with explicit `/retry` recovery guidance.
- Roll back prompts rejected before `turn/start` is accepted and leave the
  affected agent in a recoverable error state.
- Count unread background assistant messages instead of individual streaming
  and status events.
- Show restoration messaging only for the initial restored-agent ready event.
- Validate every managed module environment path before recursive cleanup.
- Preserve the positional `AgentEvent` constructor contract for external
  providers after adding streamed-message identity.
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

[0.3.0]: https://github.com/jessecanderson/cyberdeck/compare/v0.2.1...v0.3.0
[0.3.4]: https://github.com/jessecanderson/cyberdeck/compare/v0.3.3...v0.3.4
[0.2.1]: https://github.com/jessecanderson/cyberdeck/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/jessecanderson/cyberdeck/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/jessecanderson/cyberdeck/releases/tag/v0.1.0
