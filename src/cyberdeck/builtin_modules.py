from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Input, ListView, Static, TextArea

from .modules import DeckCommand, DeckModule, ModuleInputMode, ModuleManifest


class AgentsWorkspace(Vertical):
    def compose(self) -> ComposeResult:
        with Vertical(id="agent-header"):
            with Horizontal(id="agent-primary"):
                yield Static("NO ACTIVE UPLINK", id="agent-name")
                yield Static(id="agent-model")
                yield Static("│ STATE OFFLINE", id="agent-state")
                yield Static("│ awaiting uplink", id="agent-activity")
                yield Static("GRID [····]", id="agent-network")
                yield Static("MEM [······] --", id="agent-mnem")
                yield Static(id="agent-cwd")
            yield Static("CARRIER // 通信 ··· OFFLINE", id="signal-trace")
        yield Static(id="state-transition")
        yield VerticalScroll(id="conversation")
        with Vertical(id="operations-console"):
            yield Static("GRID TRACE // LIVE OPERATIONS", id="operations-title")
            yield ListView(id="operations-list")


class JournalWorkspace(Vertical):
    def compose(self) -> ComposeResult:
        with Horizontal(id="journal-header"):
            yield Static("JOURNAL // 日誌", id="journal-title")
            yield Static("LOCAL MARKDOWN // USER OWNED", id="journal-status")
        with Horizontal(id="journal-body"):
            with Vertical(id="journal-index"):
                yield Input(placeholder="search entries...", id="journal-search")
                yield ListView(id="journal-days")
            with Vertical(id="journal-document"):
                yield Static("TODAY", id="journal-date")
                yield TextArea(
                    "",
                    language="markdown",
                    soft_wrap=True,
                    tab_behavior="indent",
                    id="journal-editor",
                )
        yield Static(
            "^L COMMAND   ESC RETURN TO EDITOR   ^S SAVE   UTF-8 // 日本語対応",
            id="journal-help",
        )


@dataclass(frozen=True, slots=True)
class BuiltinModuleSpec:
    manifest: ModuleManifest
    factory: Callable[[], Widget]
    prompt_handler: Callable[[str], Awaitable[None]]
    commands: tuple[DeckCommand, ...] = ()
    activate_handler: Callable[[], Awaitable[None]] | None = None
    deactivate_handler: Callable[[], Awaitable[None]] | None = None
    input_mode: ModuleInputMode = ModuleInputMode.DECK_PROMPT
    focus_target: str | None = None
    save_handler: Callable[[], Awaitable[bool] | bool] | None = None


class BuiltinModule(DeckModule):
    def __init__(self, spec: BuiltinModuleSpec) -> None:
        self.manifest = spec.manifest
        self._factory = spec.factory
        self._prompt_handler = spec.prompt_handler
        self._commands = spec.commands
        self._activate_handler = spec.activate_handler
        self._deactivate_handler = spec.deactivate_handler
        self.input_mode = spec.input_mode
        self.focus_target = spec.focus_target
        self._save_handler = spec.save_handler

    def build(self) -> Widget:
        return self._factory()

    def commands(self) -> tuple[DeckCommand, ...]:
        return self._commands

    async def activate(self) -> None:
        if self._activate_handler:
            await self._activate_handler()

    async def deactivate(self) -> None:
        if self._deactivate_handler:
            await self._deactivate_handler()

    async def save(self) -> bool:
        if not self._save_handler:
            return False
        result = self._save_handler()
        return await result if asyncio.iscoroutine(result) else result

    async def handle_prompt(self, text: str) -> None:
        await self._prompt_handler(text)
