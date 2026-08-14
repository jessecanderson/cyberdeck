"""Searchable command selection for the deck prompt."""

from __future__ import annotations

from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Static


class CommandPalette(ModalScreen[str | None]):
    """Filter commands and return one for insertion into the prompt."""

    BINDINGS: ClassVar = [
        Binding("up", "previous_result", "Previous", show=False, priority=True),
        Binding("down", "next_result", "Next", show=False, priority=True),
        Binding("enter", "choose", "Use command", priority=True),
        Binding("escape", "cancel", "Close"),
    ]

    def __init__(self, commands: dict[str, str]) -> None:
        super().__init__()
        self.commands = tuple(commands.items())
        self.filtered = self.commands

    def compose(self) -> ComposeResult:
        with Vertical(id="command-palette-dialog"):
            yield Label("DECK COMMAND PALETTE // LOCAL CONTROL", id="command-palette-title")
            yield Input(
                placeholder="SEARCH command or description",
                id="command-palette-search",
            )
            yield ListView(id="command-palette-list")
            yield Static("↑/↓  SELECT   ENTER  INSERT   ESC  RETURN", classes="modal-help")

    async def on_mount(self) -> None:
        await self._rebuild()
        self.query_one("#command-palette-search", Input).focus()

    @on(Input.Changed, "#command-palette-search")
    async def search(self, event: Input.Changed) -> None:
        term = event.value.casefold().lstrip("/")
        self.filtered = tuple(
            (name, description)
            for name, description in self.commands
            if term in f"{name.lstrip('/')} {description}".casefold()
        )
        await self._rebuild()

    async def _rebuild(self) -> None:
        view = self.query_one("#command-palette-list", ListView)
        await view.clear()
        for name, description in self.filtered:
            await view.append(ListItem(Label(f"{name}\n  {description}")))
        view.index = 0 if self.filtered else None

    def _move_result(self, direction: int) -> None:
        if not self.filtered:
            return
        view = self.query_one("#command-palette-list", ListView)
        current = view.index if view.index is not None else 0
        view.index = max(0, min(len(self.filtered) - 1, current + direction))

    def action_previous_result(self) -> None:
        self._move_result(-1)

    def action_next_result(self) -> None:
        self._move_result(1)

    def action_choose(self) -> None:
        index = self.query_one("#command-palette-list", ListView).index
        if index is not None and index < len(self.filtered):
            self.dismiss(self.filtered[index][0])

    @on(Input.Submitted, "#command-palette-search")
    def search_submitted(self) -> None:
        self.action_choose()

    def action_cancel(self) -> None:
        self.dismiss(None)
