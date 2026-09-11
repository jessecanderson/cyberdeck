# Public Python API

Cyberdeck's command-line interface is the primary supported interface. Python
embedders and external modules may rely on these package boundaries during the 0.3
release line:

- `cyberdeck.__version__`
- domain types and timestamp normalization from `cyberdeck.domain`
- `AgentManager` plus its public registration, lifecycle, event-handler, adapter
  attachment, and adapter lookup methods
- provider contracts exported by `cyberdeck.providers`
- Module API v1 contracts from `cyberdeck.modules`
- runtime and configuration value types from `cyberdeck.runtimes` and
  `cyberdeck.config`
- `CyberdeckApp.execute_command`, `present_agent`, `active_agent`, and
  `receive_agent_event` for deterministic embedding and UI tests

Names beginning with an underscore remain implementation details. Classes re-exported
from `cyberdeck.app` for compatibility may move internally while their existing 0.3
imports remain available. The focused modules under `cyberdeck.ui` are implementation
boundaries, not a stable widget-extension API.

External modules should use only `DeckModule`, `ModuleManifest`, `ModuleContext`,
`ModuleService`, `DeckCommand`, and `ModuleInputMode`. Services are a mapping of named
objects implementing the `ModuleService` protocol; modules must not depend on the
application object or manager internals.

Conversation lifecycle additions are backward compatible: `AgentState` has defaulted
`queue_paused`, `cancellation_pending`, and `uncertain_prompts` fields alongside
`queued_prompts`. `AgentManager.submit_prompt` routes composer input;
`resume_queue` requires READY and sends only confirmed-unsent input, and
`clear_queue` discards retained input without unpausing. `recovery_guidance` reflects
session-loading capability and thread identity. `AgentManager` accepts an optional
positive `cancellation_timeout` (default 30 seconds). Zero-argument adapter factories
and Module API v1 remain unchanged.

`AcpAgentAdapter` accepts an optional positive `control_timeout` (default 30 seconds).
Its existing `initialize_timeout` remains 15 seconds; normal prompt responses remain
unbounded. Capability-gated steering adapters may raise
`cyberdeck.providers.SteeringNotSent` only when they can prove input was not sent
or accepted. Other failures are retained as uncertain and cannot be automatically
replayed. No additional provider request methods are required.
