# Claude local runtime integration

Cyberdeck 0.4.1 integrates Claude through Anthropic's official Python Agent SDK.
The SDK package includes a native Claude Code executable for each supported platform,
so Cyberdeck does not require Node.js, npm, a separate Claude Code installation, or
the `claude-agent-acp` bridge used by Cyberdeck 0.4.0.

Here, local means Cyberdeck owns the local agent process. Model inference still uses
Anthropic, Amazon Bedrock, or Google Vertex AI; this is not an offline model runtime.

## Runtime design

The built-in `claude`, `claude-bedrock`, and `claude-vertex` runtimes use
`claude-agent-sdk` 0.2.152 and its public `ClaudeSDKClient` API. The client supplies
the persistent conversation, streamed message objects, tool activity, permission
callbacks, session resume, and interruption. Provider messages are normalized inside
`providers/claude.py`; `AgentManager`, the reducer, and the UI remain provider-neutral.

The SDK is pinned because it is still a pre-1.0 package and embeds a specific Claude
Code build. A Cyberdeck release must validate a newer SDK before changing that pin.
[Python Agent SDK documentation](https://code.claude.com/docs/en/agent-sdk/python).

Cyberdeck keeps additional composer input in its existing FIFO continuation queue.
Although the SDK accepts bidirectional input, active-turn steering semantics remain
disabled until completion races and provider acceptance are tested explicitly.
Cyberdeck also leaves Claude compaction, session discovery, naming, and archiving
disabled in this release.

## Authentication and inference routes

The SDK reads the same provider-owned credentials and settings as Claude Code.
Cyberdeck never copies credential values into its configuration or transcript and
does not start an interactive browser-login flow.

- `claude` uses an existing Claude Code login or a documented Anthropic credential
  such as `ANTHROPIC_API_KEY`.
- `claude-bedrock` uses the AWS credential chain, region, model access, and optional
  model pins.
- `claude-vertex` uses Google Application Default Credentials, project, region, model
  access, and optional model pins.

Cyberdeck clears conflicting cloud selectors and sets the selected route in both the
SDK subprocess environment and its highest-priority command-line settings layer.
Managed organization policy remains authoritative. See
[Claude Code authentication](https://code.claude.com/docs/en/authentication).

Examples:

```text
/new case claude ~/src/project
/new molly claude-bedrock ~/src/project
/new wintermute claude-vertex ~/src/project
```

## Release validation

Deterministic tests use an injected SDK client and do not need credentials, network
access, user settings, or the real Claude process. They cover route isolation, session
create and resume, streamed and complete messages, tool start and completion, ICE
approval and denial, interruption, provider errors, usage, shutdown, and preflight.

Packaging validation must confirm that the platform-specific SDK wheel resolves for
every supported Python job and that the standalone macOS archive contains the bundled
Claude executable. An authenticated compatibility smoke remains opt-in and should
exercise one small prompt, a tool permission, interruption, a FIFO follow-up, and
session retry with the tester's permitted Anthropic, Bedrock, or Vertex route.
