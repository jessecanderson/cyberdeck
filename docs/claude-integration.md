# Claude local runtime integration

Research date: 2026-09-11; implementation updated 2026-09-14. Cyberdeck 0.4.0 has
built-in Anthropic, Amazon Bedrock, and Google Vertex AI runtime definitions. Tracks
[issue #26](https://github.com/jessecanderson/cyberdeck/issues/26).

## Recommended route

Reuse the existing ACP v1 stdio adapter with three built-in runtime presets:
`claude`, `claude-bedrock`, and `claude-vertex`.
The maintained adapter moved from Zed's namespace to
[`@agentclientprotocol/claude-agent-acp`](https://github.com/agentclientprotocol/claude-agent-acp).
The npm stable release observed during implementation was 0.76.0; its executable is
`claude-agent-acp`, and it requires Node 22 or newer. It uses Anthropic's Claude
Agent SDK. Cyberdeck accepts the tested `0.76.x` release line and rejects other
versions in preflight until they are validated. Do not use the adapter's preview
channel for a supported Cyberdeck preset.
[Package metadata](https://github.com/agentclientprotocol/claude-agent-acp/blob/v0.76.0/package.json).

Here, local means Cyberdeck owns a local agent process. Claude inference still uses
the configured Anthropic or cloud service; this is not an offline model runtime.

## Protocol fit and gaps

The adapter advertises ACP protocol 1 and session loading, supports permission
requests and cancellation, and replays history through session updates. Its current
implementation also advertises an optional steering extension. These are a good
match for Cyberdeck's existing transport, reducer, queue, and recovery boundaries.
[Adapter implementation](https://github.com/agentclientprotocol/claude-agent-acp/blob/v0.76.0/src/acp-agent.ts).

For the initial integration, use standard ACP prompt/cancel/load and Cyberdeck's
FIFO follow-ups. Evaluate steering separately against the pinned extension contract.
Keep compaction and other extensions disabled until explicitly implemented and
negotiated. Do not infer feature support from another provider.

Cyberdeck currently advertises no client filesystem or terminal services and has
no ACP terminal-auth UI. Compatibility testing must confirm the adapter's own tool
execution works with those capabilities disabled, and that interactive question
requests fail clearly rather than leaving the session stuck. Authentication should
be completed in the owning Claude tooling before connection.

## Authentication and work-machine setup

Claude Code supports Claude account, Console, and cloud-provider authentication.
Organization policy can constrain allowed login methods. Do not assume an existing
interactive Claude subscription has identical SDK access or billing. Verify the
work account's permitted SDK route before the first real prompt.
[Anthropic authentication documentation](https://code.claude.com/docs/en/authentication).

The adapter has terminal login integration and cloud-provider routing, but Cyberdeck
should not copy credentials, initiate browser login implicitly, or save credential
values. Preserve the configured environment and provider-owned policy. Confirm the
specific Anthropic, Bedrock, or Vertex setup used at work through an opt-in live test.

A custom-runtime configuration is no longer needed. After installing the pinned
adapter, select a built-in runtime:

```text
/new case claude ~/src/project
/new molly claude-bedrock ~/src/project
/new wintermute claude-vertex ~/src/project
```

Installation: `npm install -g @agentclientprotocol/claude-agent-acp@0.76.0`.
ACP initialization and session creation have been validated locally with Node.js
22.23.2 for all three routes. No authenticated model prompt was sent during that
transport validation.

## Implementation and validation

1. Built-in runtime definitions, executable/Node/version preflight, deterministic
   cloud selection in the process environment and adapter settings tier, and
   provider-owned authentication guidance are implemented. Claude runtime IDs are
   reserved from custom configuration collisions.
2. Provider-specific environment selection lives in `providers/claude.py`; manager
   lifecycle and the standard ACP reducer remain shared with no Claude-specific UI state.
3. Existing ACP fake-server coverage exercises initialization, streaming/tool events,
   permission approval and denial, cancellation, session restore, late replies,
   long turns, and mixed-provider dispatch.
4. An authenticated compatibility smoke remains opt-in. Test
   create, prompt, permission, interrupt, follow-up, disconnect/retry, and session
   identity with the actual work authentication route.
5. Cyberdeck 0.4.0 publishes the tested adapter version and limitations. Richer
   steering, native-agent discovery, compaction, and session-list UI remain separate
   follow-ups.
