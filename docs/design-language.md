# ODS interface language

Cyberdeck should feel like a personal machine connecting its operator to a
larger, dangerous information landscape. The interface is atmospheric, but its
language must still communicate real application state.

This vocabulary is original to Cyberdeck. Avoid names, corporations, devices,
or character references borrowed from existing cyberpunk fiction.

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
