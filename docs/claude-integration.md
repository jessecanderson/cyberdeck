# Claude local runtime research

Research date: 2026-09-11. This is an integration proposal, not a claim that
Cyberdeck 0.3.7 includes or has live-validated Claude support. Tracks
[issue #26](https://github.com/jessecanderson/cyberdeck/issues/26).

## Recommended route

Reuse the existing ACP v1 stdio adapter with a built-in `claude` runtime preset.
The maintained adapter moved from Zed's namespace to
[`@agentclientprotocol/claude-agent-acp`](https://github.com/agentclientprotocol/claude-agent-acp).
The npm stable release observed during research was 0.76.0; its executable is
`claude-agent-acp`, and it requires Node 22 or newer. It uses Anthropic's Claude
Agent SDK. Pin and test a released adapter version before declaring compatibility;
do not use its preview channel for a supported Cyberdeck preset.
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

A possible manual test configuration after installing the pinned adapter is:

```toml
[[runtimes]]
id = "claude"
label = "Claude Agent (ACP candidate)"
command = ["claude-agent-acp"]
```

This uses Cyberdeck's existing custom-runtime facility; it is not yet a supported
built-in preset. Candidate installation: `npm install -g @agentclientprotocol/claude-agent-acp@0.76.0`.
No installation or authenticated Claude session was performed during this research.

## Proposed implementation and acceptance

1. Add a built-in runtime definition, executable/Node/version preflight, and clear
   provider-owned authentication guidance. Resolve any collision with an existing
   custom runtime named `claude` explicitly.
2. Keep provider-specific exceptions in `providers/`; reuse manager lifecycle and
   the standard ACP reducer. Add no Claude-specific manager or UI state.
3. Add fake-server coverage for initialization, streaming/tool events, permission
   approval and denial, cancellation, session restore, missing auth, late replies,
   long turns, and mixed-provider dispatch.
4. Add an opt-in real compatibility smoke procedure in a scratch workspace. Test
   create, prompt, permission, interrupt, follow-up, disconnect/retry, and session
   identity with the actual work authentication route.
5. Publish the tested adapter version and limitations. Treat richer steering,
   native-agent discovery, compaction, and session-list UI as separate follow-ups.
