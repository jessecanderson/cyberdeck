# Agent runtimes

Cyberdeck owns agent lifecycle through a runtime-neutral manager. Codex uses
its native App Server adapter; Kiro, Claude, and compatible local agents use the
shared ACP v1 stdio adapter. ACP is not required for Codex.

## Built-in runtimes

| Runtime | Transport | New | Resume | Rename | Archive | Interrupt | ICE | Compact |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `codex` | App Server stdio | yes | yes | yes | yes | yes | yes | yes |
| `kiro` | ACP v1 stdio | yes | negotiated | no | no | yes | yes | extension |
| `claude` | ACP v1 stdio | yes | negotiated | no | no | yes | yes | no |
| `claude-bedrock` | ACP v1 stdio | yes | negotiated | no | no | yes | yes | no |
| `claude-vertex` | ACP v1 stdio | yes | negotiated | no | no | yes | yes | no |

Kiro resume is available only when its initialize response advertises
`agentCapabilities.loadSession`. ACP v1 session loading restores provider
context but does not return a structured history page; Cyberdeck rebuilds the
visible transcript from replayed session updates. Disconnected Kiro sessions
are not currently discoverable through the Codex-only Archive Uplink.

Use `/runtimes` to refresh executable preflight and show detected versions.
Cyberdeck is exercised against the installed Codex CLI at test/run time
rather than promising compatibility with an unbounded App Server version.
App Server requests have a 30-second response timeout; a stalled or closed
transport becomes an actionable per-agent error and can be restored with
`/retry` when the runtime advertises session loading.
Authentication remains owned by each CLI and is verified when an uplink connects or
sends its first provider request; Cyberdeck does not read, copy, or store provider
credentials.

### Claude

All three Claude runtimes use the maintained
[`@agentclientprotocol/claude-agent-acp`](https://github.com/agentclientprotocol/claude-agent-acp)
adapter and the official Claude Agent SDK. Cyberdeck accepts the tested `0.76.x`
adapter release line; its executable is `claude-agent-acp` and it requires Node.js 22
or newer:

```bash
npm install -g @agentclientprotocol/claude-agent-acp@0.76.0
claude-agent-acp --version
```

The runtime choice selects the inference route deterministically:

| Runtime | Inference route | Provider-owned setup |
| --- | --- | --- |
| `claude` | Anthropic | Claude Code login, Console/API credentials, or an Anthropic profile |
| `claude-bedrock` | Amazon Bedrock | AWS credentials, region, model access, and optional model pins |
| `claude-vertex` | Google Vertex AI | Google credentials, project, region, model access, and optional model pins |

Cyberdeck injects `CLAUDE_CODE_USE_BEDROCK=1` or `CLAUDE_CODE_USE_VERTEX=1` for
the corresponding cloud runtime and clears conflicting cloud selectors. The same
selection is passed through the pinned adapter's programmatic settings tier so a
stale user or project setting cannot redirect the session. Managed organization
policy remains authoritative. Cyberdeck inherits the launching process environment
so the Claude SDK can use existing provider-owned credentials and settings, but it
never reads or persists their values.

For direct Anthropic access, authenticate with Claude Code or provide one of its
documented credential sources, such as `ANTHROPIC_API_KEY`. For Bedrock, configure
the AWS default credential chain and optionally `AWS_PROFILE` and `AWS_REGION`; the
runtime sets the Bedrock selector itself. For Vertex, configure Application Default
Credentials, `ANTHROPIC_VERTEX_PROJECT_ID`, and `CLOUD_ML_REGION`; the runtime sets
the Vertex selector itself. Provider setup can also be completed with Claude Code's
`/setup-bedrock` or `/setup-vertex` flow before starting Cyberdeck.

Examples:

```text
/new case claude ~/src/project
/new molly claude-bedrock ~/src/project
/new wintermute claude-vertex ~/src/project
```

Claude advertises ACP session loading, permissions, cancellation, and tool events.
ACP v1 does not standardize compaction or active-turn steering, so follow-ups use
Cyberdeck's FIFO continuation queue and `/compact` remains unavailable.

## Selecting a runtime

The create dialog and `/new` accept any registered runtime ID:

```text
/new ghost
/new wintermute kiro ~/src/project
/new molly work-agent ~/src/project
/new wintermute kiro ~/src/project --agent security/reviewer
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

Runtime IDs use lowercase letters, numbers, hyphens, or underscores. `codex`,
`kiro`, `claude`, `claude-bedrock`, and `claude-vertex` are reserved built-in IDs.
`command` is executed directly without a shell. When `environment_allowlist` is
present, the child receives the basic
process environment (`PATH`, `HOME`, locale variables) plus only those named
variables. Values are never written back to the configuration file.

`workspace_root` must be an existing directory. Supported approval policies
are `untrusted`, `on-failure`, `on-request`, and `never`; supported sandbox
values are `read-only`, `workspace-write`, and `danger-full-access`. Invalid
values fall back safely and are reported at startup. Configuration never stores
provider credentials. File configuration supplies defaults; an explicit
`/new` path or runtime always wins for that uplink.

### Harness-native agents

New Uplink refreshes agent identity metadata whenever its workspace or runtime changes.
It reads Codex definitions from `~/.codex/agents/*.toml` and
`WORKSPACE/.codex/agents/*.toml`, and Kiro definitions recursively from
`~/.kiro/agents/**/*.{json,md}` and `WORKSPACE/.kiro/agents/**/*.{json,md}`.
Workspace Kiro definitions override personal definitions with the same relative ID.

Kiro entries can be launched with `--agent NATIVE`; Cyberdeck delegates validation and
all capabilities to `kiro-cli acp --agent NATIVE`. Codex entries are view-only because
App Server does not expose named primary-agent selection. The default-harness row keeps
the ordinary launch behavior. Cyberdeck reads only names and descriptions: plugins,
skills, MCP servers, hooks, permissions, and credentials remain harness-owned and are
not imported or persisted.

Harness-native agents and plugins are distinct from Cyberdeck Module API v1. Modules
extend Cyberdeck itself; native definitions configure the owning provider harness.

### Steering and queued input

Submitting more input while Codex is working steers its active turn through App
Server. ACP v1 has no equivalent steering request, so Cyberdeck queues additional
Kiro, Claude, or generic ACP prompts per uplink and sends them in order whenever
that agent returns to `READY`, in the same session. Each submission keeps its exact text and
is bound to the agent selected when Enter is pressed. Steering during an approval
hold does not approve or bypass the hold. A starting Codex turn waits for its ID
within the adapter's bounded startup wait.

`/interrupt` pauses pending input and waits for provider turn completion, with a
30-second cancellation deadline. A failed cancellation stops the affected transport
and leaves the uplink in `ERROR`. Input entered during cancellation or while paused
joins the pending queue.

- `/queue` shows confirmed-unsent and uncertain messages.
- `/queue resume` requires `READY` and resumes only confirmed-unsent messages.
- `/queue clear` discards pending and uncertain messages; it does not unpause input.

Ambiguous timeouts and transport errors retain the input for review and pause the
queue. Check the transcript and explicitly resubmit uncertain messages if needed;
they are never automatically replayed. Steering falls back to a subsequent turn
only when the adapter can prove it was not sent or accepted, never by matching
arbitrary error text. Codex currently proves this locally when its active turn ends
before the steering write; other RPC errors remain uncertain.

`/retry` is available only with session-loading support and an existing thread ID.
It preserves the runtime's native-agent selection and pending input, cancels old
connection tasks, and restores the session with the queue paused. Otherwise,
disconnect and create a new uplink. Explicit targeted sends and dispatch still
require `READY` and do not resume the queue. Queues are in-memory and are not
restored after application restart.

ACP initialization retains its 15-second deadline. Session creation, each session
load attempt, compaction, and transport writes have a 30-second deadline; bounded
session-lock retries remain in place. Normal ACP prompt responses have no turn
duration limit. Cancellation has its separate deadline. Timed-out or cancelled
requests are removed, and late responses are ignored.

When Codex reports per-turn token usage, Cyberdeck adds a concise usage line after
the turn completes. This includes only fields returned by App Server; Cyberdeck does
not estimate money or workspace credits from tokens. ACP runtimes show no turn usage
unless the protocol exposes an equivalent provider-owned event in the future.

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
Cyberdeck 0.4.0 intentionally does not offer a destructive provider-context
reset command: starting a fresh provider session remains an explicit new-uplink
operation. Successful compaction preserves the active agent identity and local
transcript; failures leave the agent visibly recoverable instead of guessing a
provider-specific reset request.

Dispatch can mix ready Codex, Kiro, Claude, and configured ACP agents. Each send is an
independent turn; partial failures remain isolated and are never rolled back on
successful targets.
