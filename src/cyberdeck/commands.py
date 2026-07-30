"""Built-in command metadata and lookup.

This module is deliberately UI-agnostic.  It is the authoritative catalog used by
routing, help, collision detection, and command-name completion.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    description: str
    handler: str | None = None
    aliases: tuple[str, ...] = ()
    append_space: bool = False

    @property
    def names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)

    @property
    def handler_key(self) -> str:
        return self.handler or self.name.removeprefix("/").replace("-", "_")


BUILTIN_COMMANDS = (
    CommandSpec("/new", "new uplink: /new CALLSIGN [RUNTIME] [PATH]", append_space=True),
    CommandSpec("/runtimes", "show runtime availability and versions"),
    CommandSpec("/restore", "open Archive Uplink"),
    CommandSpec("/agents", "list connected uplinks"),
    CommandSpec("/switch", "select an uplink: /switch CALLSIGN"),
    CommandSpec("/agent", "open Operative Control"),
    CommandSpec("/rename", "persist a new callsign", handler="control"),
    CommandSpec("/interrupt", "interrupt the active turn", handler="control"),
    CommandSpec("/retry", "restore an errored uplink", handler="control"),
    CommandSpec("/disconnect", "reversibly close the active uplink", handler="control"),
    CommandSpec("/archive", "archive and close the active uplink", handler="control"),
    CommandSpec("/dispatch", "transmit to multiple ready agents"),
    CommandSpec("/send", "send a prompt to one ready agent", handler="route"),
    CommandSpec(
        "/pipe",
        "forward latest response with optional instruction: /pipe CALLSIGN [INSTRUCTION]",
        handler="route",
    ),
    CommandSpec("/copy", "copy latest response, N responses, transcript, or text"),
    CommandSpec("/select", "select and copy whole transcript messages"),
    CommandSpec("/kill", "disconnect an agent after confirmation"),
    CommandSpec("/approve", "approve pending ICE requests", handler="approval"),
    CommandSpec("/trust", "trust the latest ICE request for this session", handler="approval"),
    CommandSpec("/deny", "deny the latest ICE request", handler="approval"),
    CommandSpec("/modules", "list installed deck modules"),
    CommandSpec("/module", "activate or manage a deck module"),
    CommandSpec("/next-module", "cycle to the next enabled deck module"),
    CommandSpec("/theme", "select or import a color theme"),
    CommandSpec(
        "/density",
        "show or set workspace density: standard|compact",
        append_space=True,
    ),
    CommandSpec("/journal", "open a dated journal entry", handler="deck_module"),
    CommandSpec("/today", "open today's journal entry", handler="deck_module"),
    CommandSpec("/save", "save the active journal entry", handler="deck_module"),
    CommandSpec("/about", "open system manifest"),
    CommandSpec("/older", "load 50 older turns"),
    CommandSpec("/context", "show active context usage and compaction support"),
    CommandSpec("/compact", "compact active provider context"),
    CommandSpec("/clear", "clear the local transcript display (provider context remains)"),
    CommandSpec("/path", "show the active working directory"),
    CommandSpec("/help", "open command reference", aliases=("/?",)),
    CommandSpec("/quit", "shut down Cyberdeck", aliases=("/exit",)),
)

COMMANDS_BY_NAME = {name: command for command in BUILTIN_COMMANDS for name in command.names}


def command_descriptions() -> dict[str, str]:
    """Return public canonical command descriptions in display order."""
    return {command.name: command.description for command in BUILTIN_COMMANDS}
