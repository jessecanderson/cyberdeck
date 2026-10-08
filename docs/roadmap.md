# Cyberdeck roadmap

## 0.4.3: local workflow usability

This release covers the nine improvements selected in the project review:

1. Journal save recovery and external-change detection.
2. Output-follow control and incremental conversation rendering.
3. Per-target dispatch inspection and explicit failure retries.
4. Recent workspaces and opt-in resumable session references.
5. Paused editing and reordering of confirmed-unsent queue input.
6. Loaded-transcript search and operation filters.
7. Cross-provider availability, version, and negotiated-capability diagnostics.
8. Focused journal, module lifecycle, rendering, and workflow UI owners.
9. Current project guidance and a bounded release roadmap.

These features retain independent local agent sessions, Module API v1, and the
existing Codex App Server, Kiro ACP, and Claude Agent SDK contracts.

## Reconcile existing issues during the next backlog review

- #3 remains relevant for protocol compatibility and fixture hardening.
- #4 overlaps shipped configuration and preflight; review remaining acceptance work.
- #5 now has local dispatch results. Persistent prompts and artifacts would require
  a separate explicit retention policy; this release stores metadata only.
- #6 now has safe continuity and inspect/reset controls. Prompt history and drafts
  remain process-local as requested by that issue.
- #11 has native-agent discovery and Kiro launch; portable profiles and import/export
  remain future work.
- #15 describes Homebrew update automation; reconcile it with the existing tag-driven
  dispatch and protected tap-PR workflow documented in releases.md.

Existing draft PR #48 contains an older handoff/results proposal. It is preserved
separately; this release does not merge its command compatibility changes or
structured handoff behavior. Review the remaining handoff scope against current main.

This document records scope; it does not close or change GitHub issues.

## Subsequent options, requiring their own release scope

- Portable profiles and harness background telemetry (#11, #40).
- Guarded sequential runbooks (#41), after profiles, telemetry, and explicit handoff
  contracts. Keep human approval gates and deterministic cancellation.
- Portable prompt editing (#51) and a file/diff viewer before a larger editor (#13).
- Ollama (#33), experimental remote ACP (#27), and mobile control (#36) are separate
  runtime/transport projects with their own lifecycle and permission requirements.
- Governed A2A/task graphs (#28) follow proven local workflows; they are not part of
  the 0.4.3 release.
