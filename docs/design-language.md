# ODS interface language

Cyberdeck should feel like a personal machine connecting its operator to a
larger, dangerous information landscape. The interface is atmospheric, but its
language must still communicate real application state.

This vocabulary is original to Cyberdeck. Avoid names, corporations, devices,
or character references borrowed from existing cyberpunk fiction.

## The ODS mythos

Open Deck Systems began with a simple belief: cognition infrastructure should
belong to its operator. A deck is not a portal into somebody else's product;
it is a personal machine that brings foreign intelligences onto territory the
operator can inspect, interrupt, reconfigure, and shut down.

In the ODS setting, the public network has become an endless collection of
sealed intelligence grids. Each grid speaks its own dialect, maintains its own
memory, and enforces its own boundaries. Commercial terminals hide those
differences behind polished assistants. An open deck exposes them. It shows the
carrier, records the trace, identifies the provider gate, and stops at the ICE
instead of silently deciding for its operator.

ODS hardware is assembled, repaired, and extended rather than replaced. Its
operating culture values local ownership, explicit authority, reversible
actions, and visible system state. The aesthetic is improvised and severe
because the machine is built to remain useful when a provider disappears.

The fiction should remain suggestive rather than canonical. ODS can plausibly
exist in a corporate dystopia, a street-level hacker setting, a distant orbital
network, or the user's real terminal today.

## Operator doctrine

Every ODS deck follows five rules:

1. **The operator owns the deck.** Providers are guests behind explicit gates.
2. **Every signal has a source.** Provider, process, tool, and session identity
   remain inspectable.
3. **ICE never opens silently.** Authority is requested in concrete language.
4. **A severed uplink must not kill the grid.** Failures stay isolated and
   recovery is deliberate.
5. **Modules remain replaceable.** The deck is a platform, not a sealed product.

These are product principles as much as lore. New features that violate them
should be reconsidered even if their fictional presentation sounds compelling.

## People and identities

| ODS term | Meaning |
| --- | --- |
| Operator | The human controlling the deck and granting authority. |
| Operative | A connected agent instance with a callsign and independent state. |
| Callsign | The operator-assigned identity used throughout the deck. |
| Construct | The durable conversation, instructions, and accumulated working context behind an operative. |
| Echo | Unread output or residual activity from a background operative. |
| Ghost | An operative whose transport vanished unexpectedly; use sparingly because the real state is `ERROR`. |

An agent provider is never described as the operator, and an operative is
never presented as a human teammate. The fiction creates presence without
misrepresenting agency or responsibility.

## System map

| ODS term | Product meaning | Usage rule |
| --- | --- | --- |
| Deck | The permanent Cyberdeck shell | Use for the application and global command surface. |
| Local Grid | Open agent processes on this machine | Use as the agent rail heading until remote topology exists. |
| Uplink | One live connection to an agent | Use for connect, disconnect, carrier, and failure language. |
| Operative | An open agent identified by a callsign | Use in lifecycle controls, never to conceal the provider. |
| Construct | Durable agent conversation and restored context | Use for restoration and active-memory language. |
| Provider Gate | The provider-specific connection boundary | Use in diagnostics and boot status, not ordinary prompts. |
| ICE | A permission or policy boundary | Always pair the fiction with the concrete requested action. |
| Grid Trace | Normalized tool and file activity | Use for the operations console. |
| Module Bay | Installed Cyberdeck workspaces | Use for the module rail and module management. |
| Memory | Context-window utilization | Display the actual percentage when available. |
| Signal | Live transport/activity feedback | Never imply real network strength when none is measured. |

## Grid geography

ODS treats connectivity as a small, legible topology:

| Region | Meaning |
| --- | --- |
| Local Grid | Processes and modules running under the current user account. |
| Provider Grid | A named external agent platform reached through a provider gate. |
| Dark Grid | A configured provider that is unavailable or unauthenticated. |
| Remote Grid | A future authenticated transport to another machine; never use for ordinary cloud API calls alone. |
| Module Bay | Local functional workspaces installed into the deck shell. |
| Archive | Durable provider-owned sessions that can be restored. |

“Dark” means unreachable, not malicious. “Remote” must correspond to a real
transport boundary. Geography should help the operator reason about ownership
and failure domains rather than merely decorating the screen.

## Machine anatomy

| Component | Role |
| --- | --- |
| Deck Core | Application lifecycle, configuration, and global command handling. |
| Provider Gate | Adapter and transport boundary for one agent platform. |
| Carrier | The live process or connection supporting an uplink. |
| Memory Bank | Provider context and durable session identity. |
| Trace Buffer | Normalized operation history shown by the Grid Trace. |
| ICE Table | Available permission choices and their scope. |
| Module Socket | Runtime contract through which a module occupies the main canvas. |
| Signal Multiplexer | Guarded dispatch from one operator prompt to multiple operatives. |

These names can appear in diagnostics, boot copy, and documentation. Ordinary
controls should continue to use familiar verbs such as Save, Copy, Retry, and
Disconnect.

## State language

Decorative language supplements the real state; it does not replace it.

| Real state | Primary signal |
| --- | --- |
| Starting | `ACQUIRING CARRIER` |
| Ready | `GRID MAPPED // CARRIER STABLE` |
| Processing | `CONSTRUCT ACTIVE // SIGNAL ENGAGED` |
| Executing a tool | `TRACE ACTIVE` or `PROBE ACTIVE` |
| Editing files | `PATCH ACTIVE` |
| Permission required | `<LEVEL> ICE INTERLOCK` |
| Restoring | `CONSTRUCT RESTORING` |
| Restored | `CONSTRUCT RESTORED` |
| Transport error | `GRID FRACTURE // SIGNAL LOST` |

The actual status (`READY`, `ERROR`, `ICE HOLD`, and so on) remains visible
nearby for accessibility and diagnosis.

## Grid Trace classes

| Class | Activity |
| --- | --- |
| `TRACE` | Shell or process execution |
| `PATCH` | File modification |
| `PROBE` | MCP or dynamic tool invocation |
| `SCAN` | Search and discovery |
| `ICE` | Activity awaiting permission |
| `FAULT` | Failed activity |
| `SIGNAL` | A normalized operation without a more specific class |

## ICE taxonomy

ICE describes the boundary, not the agent or the requested command. Its level
communicates potential impact while the permission panel communicates the real
action, path, command, host, and duration.

| Level | Meaning | Typical examples |
| --- | --- | --- |
| Gray ICE | Read-oriented or contained activity requiring confirmation | Reading outside the workspace, opening a local resource |
| Amber ICE | Mutation or external communication with bounded scope | Editing files, installing a dependency, contacting a service |
| Red ICE | Broad, persistent, destructive, or difficult-to-reverse authority | Recursive deletion, unrestricted execution, permanent trust |

Avoid escalating language merely for drama. A denied request is `ICE SEALED`;
an approved request is `ICE GATE OPEN`; an expired or orphaned request is
`INTERLOCK RELEASED`.

## Event vocabulary

| Event | ODS copy |
| --- | --- |
| Process launching | `ACQUIRING CARRIER` |
| Handshake accepted | `PROVIDER GATE OPEN` |
| Session created | `CONSTRUCT INITIALIZED` |
| Session loaded | `CONSTRUCT RESTORED` |
| Prompt submitted | `SIGNAL ENGAGED` |
| Agent producing output | `CONSTRUCT ACTIVE` |
| Tool started | `<TRACE CLASS> ACTIVE` |
| Tool completed | `<TRACE CLASS> CLEAR` |
| Permission needed | `<LEVEL> ICE INTERLOCK` |
| Permission approved | `ICE GATE OPEN` |
| Permission denied | `ICE SEALED` |
| Cancellation requested | `ABORT SIGNAL SENT` |
| Agent disconnected intentionally | `CARRIER RELEASED` |
| Transport failed | `GRID FRACTURE // SIGNAL LOST` |
| Retry underway | `REACQUIRING CARRIER` |

Short event copy belongs in transitions. Longer explanations belong in the
transcript or diagnostic view.

## Voice and writing style

ODS copy is terse, technical, and slightly ominous. It does not joke during a
failure or obscure responsibility.

- Prefer `CARRIER LOST // process exited unexpectedly`.
- Avoid `Uh oh! Your cyber connection got zapped!`
- Prefer `RED ICE // recursive deletion requires operator approval`.
- Avoid `Danger detected` without naming the action.
- Prefer one evocative term paired with one plain-language fact.
- Use uppercase for short signals, not paragraphs.
- Use `//` to separate atmosphere from clarification.
- Use Japanese as secondary texture or a concise equivalent, never as required
  knowledge for operating the deck.

Recommended pattern:

```text
<ODS SIGNAL> // <CONCRETE STATE OR ACTION>
```

Examples:

```text
GRID FRACTURE // app-server closed stdout
AMBER ICE // write access requested for pyproject.toml
CONSTRUCT RESTORED // 42 turns hydrated
CARRIER RELEASED // thread remains available in Archive Uplink
```

## Visual restraint

- Reserve cyan for identity and navigation, green for stable state, amber for
  active or uncertain state, red for intervention, and magenta for boundaries.
- Prefer dark space and short state transitions over persistent animation.
- Animate only live activity, carrier feedback, or a state change.
- Keep Japanese text short and secondary unless a region is explicitly
  decorative. It must not change layout width between animation frames.
- Do not invent telemetry. `LOCAL`, context percentage, process state, and
  provider identity must correspond to values Cyberdeck actually knows.
- A user must be able to understand every dangerous action without knowing the
  fictional vocabulary.

## Future provider topology

Version 0.2.1 labels the existing agent rail `LOCAL GRID`. Provider-specific
grids belong to the provider/profile work planned for 0.3.0. Until then, the
secondary agent line may identify the known provider and local connection:

```text
● SYN::GHOST       ready
  ├─ CODEX / LOCAL
  └─ cyberdeck
```

Do not display Kiro, Claude, remote, trust, or signal-quality metadata until
the corresponding integration provides real state.
