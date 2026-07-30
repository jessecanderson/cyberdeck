# Agent runtimes

Cyberdeck owns agent lifecycle through a runtime-neutral manager. Codex uses
its native App Server adapter; Kiro and compatible local agents use the shared
ACP v1 stdio adapter. ACP is not required for Codex, and a future Codex ACP
migration is not part of the 0.3.0 contract.

## Built-in runtimes

| Runtime | Transport | New | Resume | Rename | Archive | Interrupt | ICE | Compact |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `codex` | App Server stdio | yes | yes | yes | yes | yes | yes | yes |
| `kiro` | ACP v1 stdio | yes | negotiated | no | no | yes | yes | extension |

Kiro resume is available only when its initialize response advertises
`agentCapabilities.loadSession`. ACP v1 session loading restores provider
context but does not return a structured history page; Cyberdeck rebuilds the
visible transcript from replayed session updates. Disconnected Kiro sessions
are not currently discoverable through the Codex-only Archive Uplink.

Use `/runtimes` to refresh executable preflight and show detected versions.
Cyberdeck 0.3.4 is exercised against the installed Codex CLI at test/run time
rather than promising compatibility with an unbounded App Server version.
App Server requests have a 30-second response timeout; a stalled or closed
transport becomes an actionable per-agent error and can be restored with
`/retry` when the runtime advertises session loading.
Authentication remains owned by each CLI and is verified when an uplink
connects; Cyberdeck does not read, copy, or store provider credentials.

## Selecting a runtime

The create dialog and `/new` accept any registered runtime ID:

```text
/new ghost
/new wintermute kiro ~/src/project
/new molly work-agent ~/src/project
```

Set the default and register another local ACP command in Cyberdeck's
`config.toml`:

```toml
[agents]
default_runtime = "work-agent"
workspace_root = "/path/to/projects"
approval_policy = "on-request"
sandbox = "workspace-write"

[deck]
show_boot = true
density = "standard"

[[runtimes]]
id = "work-agent"
label = "Work ACP"
command = ["work-agent", "acp"]
environment_allowlist = ["WORK_AGENT_PROFILE"]
```

Runtime IDs use lowercase letters, numbers, hyphens, or underscores. `codex`
and `kiro` are reserved built-in IDs. `command` is executed directly without a
shell. When `environment_allowlist` is present, the child receives the basic
process environment (`PATH`, `HOME`, locale variables) plus only those named
variables. Values are never written back to the configuration file.

`workspace_root` must be an existing directory. Supported approval policies
are `untrusted`, `on-failure`, `on-request`, and `never`; supported sandbox
values are `read-only`, `workspace-write`, and `danger-full-access`. Invalid
values fall back safely and are reported at startup. Configuration never stores
provider credentials. File configuration supplies defaults; an explicit
`/new` path or runtime always wins for that uplink.

Workspace density is a presentation-only preference. `/density compact` or
`F7` reduces post-boot workspace chrome and spacing; `/density standard`
restores the full presentation. It does not change the boot animation, themes,
commands, transcript data, approvals, navigation, or provider behavior.

Configured ACP agents must implement ACP protocol version 1 over newline-
delimited JSON-RPC on stdin/stdout. Cyberdeck negotiates session loading and
model metadata during initialize/session creation, rejects incompatible
protocol versions, and surfaces unknown vendor extensions as debug telemetry
rather than treating them as user messages.

## Capability behavior

Capabilities belong to each live agent, not to the UI globally. Operative
Control keeps its stable action layout but labels unsupported actions
`UNAVAILABLE`. Equivalent slash commands are guarded by the manager before a
transport call. Disconnect remains universally available because it only stops
the Cyberdeck-owned process and removes the local sidebar entry.

Context compaction is capability-gated as well. Codex uses
`thread/compact/start`; Kiro uses its `_kiro.dev/commands/execute` extension
with the `/compact` command. Generic ACP v1 runtimes are marked unavailable
because ACP does not standardize context compaction. `/clear` remains a
Cyberdeck display operation and never implies provider-side context deletion.
Cyberdeck 0.3.4 intentionally does not offer a destructive provider-context
reset command: starting a fresh provider session remains an explicit new-uplink
operation. Successful compaction preserves the active agent identity and local
transcript; failures leave the agent visibly recoverable instead of guessing a
provider-specific reset request.

Dispatch can mix ready Codex, Kiro, and configured ACP agents. Each send is an
independent turn; partial failures remain isolated and are never rolled back on
successful targets.
