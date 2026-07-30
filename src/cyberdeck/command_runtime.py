"""Execution boundary for built-in and module-provided deck commands."""

from __future__ import annotations

import inspect
import shlex
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .commands import COMMANDS_BY_NAME
from .ui.screens import AboutScreen, ConfirmScreen, HelpScreen

if TYPE_CHECKING:
    from .app import CyberdeckApp

CommandHandler = Callable[["CyberdeckApp", list[str], str], Any]


async def run_local_command(app: CyberdeckApp, command_line: str) -> None:
    """Parse and route one local command through the authoritative catalog."""
    try:
        parts = shlex.split(command_line)
    except ValueError as exc:
        app._write_local(f"command parse error: {exc}")
        return
    if not parts:
        return

    requested = parts[0].casefold()
    spec = COMMANDS_BY_NAME.get(requested)
    command = spec.name if spec else requested
    if spec is None:
        await _run_module_command(app, command, parts[1:])
        return
    handler = HANDLERS_BY_KEY[spec.handler_key]

    result = handler(app, parts[1:], command)
    if inspect.isawaitable(result):
        await result


def _help(app: CyberdeckApp, _args: list[str], _command: str) -> None:
    app.push_screen(HelpScreen(app._all_local_commands()))


def _about(app: CyberdeckApp, _args: list[str], _command: str) -> None:
    app.push_screen(AboutScreen(app._system_manifest()))


def _restore(app: CyberdeckApp, _args: list[str], _command: str) -> None:
    app.action_restore()


def _new(app: CyberdeckApp, args: list[str], _command: str) -> None:
    if not args:
        app.action_spawn_agent()
        return
    if len(args) > 3:
        app._write_local("usage: /new CALLSIGN [RUNTIME] [PATH]")
        return

    provider = app.deck_config.default_runtime
    path_arg: str | None = None
    if len(args) == 2:
        if args[1].casefold() in app.manager.available_providers:
            provider = args[1].casefold()
        else:
            path_arg = args[1]
    elif len(args) == 3:
        if args[1].casefold() in app.manager.available_providers:
            provider, path_arg = args[1].casefold(), args[2]
        elif args[2].casefold() in app.manager.available_providers:
            path_arg, provider = args[1], args[2].casefold()
        else:
            app._write_local("usage: /new CALLSIGN [RUNTIME] [PATH]")
            return

    default_path = app.deck_config.workspace_root or Path.cwd()
    path = Path(path_arg).expanduser().resolve() if path_arg else default_path
    if provider not in app.manager.available_providers:
        app._write_local(
            f"unknown runtime: {provider} // choose " + ", ".join(app.manager.available_providers)
        )
    elif path.is_dir():
        app._spawn(args[0], path, provider)
    else:
        app._write_local(f"path not found: {path}")


def _agents(app: CyberdeckApp, _args: list[str], _command: str) -> None:
    rows = (
        f"{index}. {agent.config.name} "
        f"[{agent.config.provider.upper()} / {agent.status.value}] "
        f"{agent.config.working_directory}"
        for index, agent in enumerate(app.manager.agents, start=1)
    )
    app._write_local("\n".join(rows) or "no uplinks connected")


def _switch(app: CyberdeckApp, args: list[str], _command: str) -> None:
    if len(args) != 1:
        app._write_local("usage: /switch CALLSIGN")
        return
    target = next(
        (
            agent
            for agent in app.manager.agents
            if agent.config.name.casefold() == args[0].casefold()
        ),
        None,
    )
    if target is None:
        app._write_local(f"unknown uplink: {args[0]}")
    else:
        app._switch_result(target)


def _runtimes(app: CyberdeckApp, _args: list[str], _command: str) -> None:
    rows = []
    for runtime in app.manager.runtime_preflights(refresh=True):
        marker = "READY" if runtime.available else "OFFLINE"
        version = f" // {runtime.version}" if runtime.version else ""
        rows.append(
            f"{runtime.runtime_id:<12} [{marker}] {runtime.label}{version}\n  {runtime.detail}"
        )
    app._write_local("RUNTIME MATRIX\n" + "\n".join(rows))


def _modules(app: CyberdeckApp, _args: list[str], _command: str) -> None:
    rows = [
        f"{'●' if module_id == app.active_module_id else '○'} "
        f"{module_id:<12} {app._module_state(module_id):<14} "
        f"{app._module_description(module_id)}"
        for module_id in app._ordered_module_ids()
    ]
    app.notify("\n".join(rows), title="DECK MODULES")


def _module(app: CyberdeckApp, args: list[str], _command: str) -> None:
    if not args:
        app.notify(f"Active module: {app.active_module_id}", title="DECK MODULE")
        return
    action = args[0].casefold()
    if action in {"install", "link"}:
        _install_module(app, args, editable=action == "link")
    elif action in {"enable", "disable", "remove", "info", "update"}:
        if len(args) != 2:
            app._write_local(f"usage: /module {action} MODULE_ID")
        else:
            app._module_management_command(action, args[1].casefold())
    elif action not in app.deck_modules:
        app.notify(f"Unknown module: {args[0]}", severity="error")
    else:
        app._activate_module(action)


def _install_module(app: CyberdeckApp, args: list[str], *, editable: bool) -> None:
    if len(args) < 2:
        app._write_local(f"usage: /module {args[0]} SPEC")
        return
    specification = args[1]
    app.push_screen(
        ConfirmScreen(
            "TRUST EXTERNAL MODULE",
            f"Install and execute trusted Python code from:\n{specification}\n\n"
            "Modules run inside Cyberdeck and may access your user account.",
        ),
        lambda confirmed: (
            app._install_external_module(specification, editable=editable) if confirmed else None
        ),
    )


def _next_module(app: CyberdeckApp, args: list[str], _command: str) -> None:
    if args:
        app._write_local("usage: /next-module")
    else:
        app.action_next_module()


def _theme(app: CyberdeckApp, args: list[str], _command: str) -> None:
    app._theme_command(args)


def _density(app: CyberdeckApp, args: list[str], _command: str) -> None:
    if not args:
        app._write_local(f"WORKSPACE DENSITY // {app.deck_config.density.upper()}")
    elif len(args) != 1 or args[0].casefold() not in {"standard", "compact"}:
        app._write_local("usage: /density [standard|compact]")
    else:
        app._apply_density(args[0].casefold())


async def _deck_module(app: CyberdeckApp, args: list[str], command: str) -> None:
    handlers = {
        deck_command.name: deck_command.handler
        for deck_command in app.deck_modules["journal"].commands()
    }
    result = handlers[command](args)
    if inspect.isawaitable(result):
        await result


def _older(app: CyberdeckApp, _args: list[str], _command: str) -> None:
    state = app._active_agent()
    if state:
        app._load_older(state)


def _context(app: CyberdeckApp, args: list[str], _command: str) -> None:
    state = app._active_agent()
    if not state:
        app._write_local("No active uplink.")
        return
    if args:
        app._write_local("usage: /context")
        return

    if state.context_percentage is not None:
        usage = f"{state.context_percentage:.1f}%"
    elif state.context_window:
        percent = state.context_tokens / state.context_window * 100
        usage = f"{state.context_tokens:,}/{state.context_window:,} tokens ({percent:.1f}%)"
    else:
        usage = "not reported"
    support = "READY" if state.capabilities.context_compaction else "UNAVAILABLE"
    app._write_local(
        f"CONTEXT MATRIX // {state.config.name}\n"
        f"RUNTIME {state.config.provider} // "
        f"{state.model_provider}/{state.model or 'default'}\n"
        f"USAGE   {usage}\n"
        f"COMPACT {support} // /compact\n"
        "CLEAR   display only; provider context and identity remain // /clear"
    )


def _compact(app: CyberdeckApp, args: list[str], _command: str) -> None:
    state = app._active_agent()
    if not state:
        app._write_local("No active uplink.")
    elif args:
        app._write_local("usage: /compact")
    elif not state.capabilities.context_compaction:
        app._write_local(f"{state.config.provider} does not expose context compaction")
    else:
        app._compact_context(state)


def _clear(app: CyberdeckApp, args: list[str], _command: str) -> None:
    if args:
        app._write_local("usage: /clear // clears display only; use /compact for context")
        return
    state = app._active_agent()
    target = state.transcript if state else app._system_transcript
    target.clear()
    app._render_active()


def _path(app: CyberdeckApp, _args: list[str], _command: str) -> None:
    state = app._active_agent()
    app._write_local(str(state.config.working_directory if state else Path.cwd()))


def _agent(app: CyberdeckApp, _args: list[str], _command: str) -> None:
    app.action_agent_control()


def _dispatch(app: CyberdeckApp, _args: list[str], _command: str) -> None:
    app.action_dispatch()


def _copy(app: CyberdeckApp, args: list[str], _command: str) -> None:
    app._copy_command(args)


def _select(app: CyberdeckApp, args: list[str], _command: str) -> None:
    if args:
        app._write_local("usage: /select")
    else:
        app.action_select_transcript()


def _route(app: CyberdeckApp, args: list[str], command: str) -> None:
    app._route_command(command, args)


def _kill(app: CyberdeckApp, args: list[str], _command: str) -> None:
    app._request_kill(args)


def _approval(app: CyberdeckApp, args: list[str], command: str) -> None:
    state = app._active_agent()
    if not state or not state.pending_approvals:
        app._write_local("no pending ICE requests")
    elif command == "/approve" and args == ["all"]:
        app._confirm_approve_all(state)
    elif args:
        usage = "usage: /approve [all]" if command == "/approve" else f"usage: {command}"
        app._write_local(usage)
    else:
        decision = {
            "/approve": "accept",
            "/trust": "acceptForSession",
            "/deny": "decline",
        }[command]
        app._approval_decided(state, state.pending_approvals[-1], decision)


def _control(app: CyberdeckApp, args: list[str], command: str) -> None:
    state = app._active_agent()
    if not state:
        app._write_local("No active uplink.")
    elif command == "/rename" and not args:
        app._write_local("usage: /rename CALLSIGN")
    else:
        app._control_result(state, (command[1:], args[0] if args else None))


def _quit(app: CyberdeckApp, _args: list[str], _command: str) -> None:
    app.exit()


async def _run_module_command(app: CyberdeckApp, command: str, args: list[str]) -> None:
    handlers = {
        deck_command.name: deck_command.handler
        for module in app.deck_modules.values()
        for deck_command in module.commands()
    }
    handler = handlers.get(command)
    if handler is None:
        app._write_local(f"unknown local command: {command} (try /help)")
        return
    result = handler(args)
    if inspect.isawaitable(result):
        await result


HANDLERS_BY_KEY: dict[str, CommandHandler] = {
    handler.__name__.removeprefix("_"): handler
    for handler in (
        _help,
        _about,
        _restore,
        _new,
        _agents,
        _switch,
        _runtimes,
        _modules,
        _module,
        _next_module,
        _theme,
        _density,
        _deck_module,
        _older,
        _context,
        _compact,
        _clear,
        _path,
        _agent,
        _dispatch,
        _copy,
        _select,
        _route,
        _kill,
        _approval,
        _control,
        _quit,
    )
}
