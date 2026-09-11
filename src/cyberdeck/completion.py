"""Composable prompt completion rules for local deck commands."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from shlex import quote
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import CyberdeckApp

Completion = tuple[str, str]
CompletionResult = list[Completion] | None
CompletionRule = Callable[["CyberdeckApp", str, list[str]], CompletionResult]


def complete_prompt(app: CyberdeckApp, value: str) -> list[Completion]:
    if not value:
        return []
    words = value.rstrip().split()
    for rule in COMPLETION_RULES:
        result = rule(app, value, words)
        if result is not None:
            return result
    return []


def _command_names(app: CyberdeckApp, value: str, _words: list[str]) -> CompletionResult:
    if not value.startswith("/") or " " in value:
        return None
    return [
        (command, description)
        for command, description in app._all_local_commands().items()
        if command.startswith(value) and command != value
    ]


def _queue(_app: CyberdeckApp, value: str, words: list[str]) -> CompletionResult:
    if not words or words[0] != "/queue" or len(words) > 2:
        return None
    prefix = "" if value.endswith(" ") else (words[1] if len(words) == 2 else "")
    return [
        (action, description)
        for action, description in (
            ("resume", "resume confirmed-unsent input when READY"),
            ("clear", "discard pending and uncertain input"),
        )
        if action.startswith(prefix) and action != prefix
    ]


def _density(_app: CyberdeckApp, value: str, words: list[str]) -> CompletionResult:
    if not words or words[0] != "/density" or len(words) > 2:
        return None
    prefix = "" if value.endswith(" ") else (words[1].casefold() if len(words) == 2 else "")
    return [
        (density, f"use {density} workspace presentation")
        for density in ("standard", "compact")
        if density.startswith(prefix) and density != prefix
    ]


def _module_action(app: CyberdeckApp, value: str, words: list[str]) -> CompletionResult:
    if not words or words[0] != "/module" or len(words) != 2 or value.endswith(" "):
        return None
    prefix = words[1].casefold()
    actions = [
        (action, description)
        for action, description in app.MODULE_ACTIONS.items()
        if action.startswith(prefix)
    ]
    modules = [
        (module_id, module.manifest.description)
        for module_id, module in app.deck_modules.items()
        if module_id.startswith(prefix)
    ]
    return actions + modules


def _module_record(app: CyberdeckApp, value: str, words: list[str]) -> CompletionResult:
    if not (
        words
        and words[0] == "/module"
        and len(words) == 3
        and words[1] in {"info", "update", "enable", "disable", "remove"}
        and not value.endswith(" ")
    ):
        return None
    prefix = words[2].casefold()
    return [
        (module_id, f"{record.status} external module")
        for module_id, record in app.module_registry.records.items()
        if module_id.startswith(prefix)
    ]


def _theme(app: CyberdeckApp, value: str, words: list[str]) -> CompletionResult:
    if not words or words[0] != "/theme" or len(words) != 2 or value.endswith(" "):
        return None
    prefix = words[1].casefold()
    return [
        (theme_id, theme.name)
        for theme_id, theme in app.deck_themes.items()
        if theme_id.startswith(prefix)
    ]


def _agent(app: CyberdeckApp, value: str, words: list[str]) -> CompletionResult:
    if not words or words[0] not in {"/send", "/pipe", "/kill", "/switch"} or len(words) != 2:
        return None
    if value.endswith(" "):
        return []
    prefix = words[1].casefold()
    candidates = [
        (agent.config.name, f"{agent.status.value} agent") for agent in app.manager.agents
    ]
    if words[0] == "/kill":
        candidates.append(("all", "all connected agents"))
    if any(name.casefold() == prefix for name, _description in candidates):
        return []
    return [
        (name, description)
        for name, description in candidates
        if name.casefold().startswith(prefix)
    ]


def _approval(_app: CyberdeckApp, value: str, words: list[str]) -> CompletionResult:
    if not words or words[0] != "/approve" or len(words) != 2:
        return None
    prefix = "" if value.endswith(" ") else words[1].casefold()
    return [("all", "approve every pending ICE request once")] if "all".startswith(prefix) else []


def _runtime(app: CyberdeckApp, value: str, words: list[str]) -> CompletionResult:
    if not words or words[0] != "/new":
        return None
    if "--agent" in words:
        marker = words.index("--agent")
        if len(words) == marker + 1 and value.endswith(" "):
            prefix = ""
        elif len(words) == marker + 2 and not value.endswith(" "):
            prefix = words[-1].casefold()
        else:
            return []
        before = words[1:marker]
        provider = next(
            (
                part.casefold()
                for part in before
                if part.casefold() in app.manager.available_providers
            ),
            app.deck_config.default_runtime,
        )
        path_token = next(
            (part for part in before[1:] if part.casefold() not in app.manager.available_providers),
            None,
        )
        workspace = (
            Path(path_token).expanduser().resolve()
            if path_token
            else (app.deck_config.workspace_root or Path.cwd())
        )
        return [
            (
                quote(row.native_id),
                row.description if row.launch_supported else f"VIEW ONLY: {row.unavailable_reason}",
            )
            for row in app.manager.native_agents(workspace).agents
            if row.runtime_id == provider and row.native_id.casefold().startswith(prefix)
        ]
    prefix: str | None = None
    if len(words) == 2 and value.endswith(" "):
        prefix = ""
    elif (
        len(words) == 3
        and not value.endswith(" ")
        and not words[2].startswith(("/", "./", "../", "~"))
    ):
        prefix = words[2].casefold()
    elif (
        len(words) == 3
        and value.endswith(" ")
        and words[2].casefold() not in app.manager.available_providers
    ):
        prefix = ""
    elif (
        len(words) == 4
        and not value.endswith(" ")
        and words[2].casefold() not in app.manager.available_providers
    ):
        prefix = words[3].casefold()
    if prefix is None:
        return None
    return [
        (provider, "agent runtime")
        for provider in app.manager.available_providers
        if provider.startswith(prefix)
    ]


def _path(_app: CyberdeckApp, value: str, _words: list[str]) -> CompletionResult:
    token = value.rsplit(" ", 1)[-1]
    is_new_path = value.startswith("/new ") and value.count(" ") >= 2
    if not (is_new_path or token.startswith(("/", "./", "../", "~"))):
        return None
    try:
        expanded = Path(token or ".").expanduser()
        directory = expanded if not token or token.endswith("/") else expanded.parent
        prefix = "" if not token or token.endswith("/") else expanded.name
        matches = sorted(
            (
                path
                for path in directory.iterdir()
                if (path.is_dir() or not is_new_path) and path.name.startswith(prefix)
            ),
            key=lambda path: path.name.casefold(),
        )
    except (OSError, RuntimeError, ValueError):
        return []
    results: list[Completion] = []
    if is_new_path and token.endswith("/") and expanded.is_dir():
        results.append((token, "use this directory"))
    for path in matches[:12]:
        completed = str(path) + ("/" if path.is_dir() and not is_new_path else "")
        if token.startswith("~"):
            try:
                completed = f"~/{path.relative_to(Path.home())}"
                if path.is_dir() and not is_new_path:
                    completed += "/"
            except ValueError:
                pass
        if completed != token:
            results.append((completed, "directory" if path.is_dir() else "file"))
    return results


COMPLETION_RULES: tuple[CompletionRule, ...] = (
    _command_names,
    _queue,
    _density,
    _module_action,
    _module_record,
    _theme,
    _agent,
    _approval,
    _runtime,
    _path,
)
