# Agent runtimes

Cyberdeck owns agent lifecycle through a runtime-neutral manager. Codex uses
its native App Server adapter; Kiro and compatible local agents use the shared
ACP v1 stdio adapter. ACP is not required for Codex, and a future Codex ACP
migration is not part of the 0.3.0 contract.

## Built-in runtimes

| Runtime | Transport | New | Resume | Rename | Archive | Interrupt | ICE |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `codex` | App Server stdio | yes | yes | yes | yes | yes | yes |
| `kiro` | ACP v1 stdio | yes | negotiated | no | no | yes | yes |

Kiro resume is available only when its initialize response advertises
`agentCapabilities.loadSession`. ACP v1 session loading restores provider
context but does not return a structured history page; Cyberdeck rebuilds the
visible transcript from replayed session updates. Disconnected Kiro sessions
are not currently discoverable through the Codex-only Archive Uplink.

Use `/runtimes` to refresh executable preflight and show detected versions.
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

Dispatch can mix ready Codex, Kiro, and configured ACP agents. Each send is an
independent turn; partial failures remain isolated and are never rolled back on
successful targets.
