from __future__ import annotations

from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView, Static

from ..themes import DeckTheme


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS: ClassVar = [
        ("y", "yes", "Confirm"),
        ("n", "no", "Cancel"),
        ("escape", "no", "Cancel"),
    ]

    def __init__(self, title: str, message: str) -> None:
        super().__init__()
        self.title_text, self.message = title, message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label(self.title_text, id="confirm-title")
            yield Static(self.message, id="confirm-message")
            yield Static("Y  CONFIRM   N / ESC  ABORT", classes="modal-help")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


class ThemeScreen(ModalScreen[str | None]):
    BINDINGS: ClassVar = [("escape", "close", "Close")]

    def __init__(self, themes: list[DeckTheme], active: str) -> None:
        super().__init__()
        self.themes = themes
        self.active = active

    def compose(self) -> ComposeResult:
        with Vertical(id="theme-dialog"):
            yield Label("CHROMA MATRIX // 配色選択", id="theme-title")
            yield ListView(
                *(
                    ListItem(
                        Label(
                            f"{'●' if theme.id == self.active else '○'}  {theme.name}\n    {theme.id} // {theme.author}"
                        )
                    )
                    for theme in self.themes
                ),
                id="theme-list",
            )
            yield Static("ENTER  APPLY     ESC  RETURN", classes="modal-help")

    def on_mount(self) -> None:
        self.query_one("#theme-list", ListView).focus()

    @on(ListView.Selected, "#theme-list")
    def select_theme(self, event: ListView.Selected) -> None:
        if event.list_view.index is not None:
            self.dismiss(self.themes[event.list_view.index].id)

    def action_close(self) -> None:
        self.dismiss(None)


class HelpScreen(ModalScreen[None]):
    BINDINGS: ClassVar = [("escape", "close", "Close")]

    def __init__(self, commands: dict[str, str]) -> None:
        super().__init__()
        self.commands = commands

    def _help_text(self) -> str:
        width = max(map(len, self.commands), default=0)
        rows = ["DECK COMMAND INDEX // LOCAL CONTROL", ""]
        rows.extend(
            f"{name:<{width}}  {description}" for name, description in self.commands.items()
        )
        rows.extend(
            [
                "",
                "KEYBOARD",
                "",
                "Ctrl+N new   Ctrl+R restore   Ctrl+G control   Ctrl+P switch",
                "Ctrl+B dispatch   F6 next module   Ctrl+L command line",
                "Ctrl+S save editor   Ctrl+O operations",
                "Ctrl+J/K switch uplink   Esc close window   Ctrl+Q quit",
            ]
        )
        return "\n".join(rows)

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Label("ODS // COMMAND REFERENCE // 操作一覧", id="help-title")
            with VerticalScroll(id="help-scroll"):
                yield Static(self._help_text(), id="help-content")
            yield Static("ESC  RETURN", classes="modal-help")

    def on_mount(self) -> None:
        self.query_one("#help-scroll", VerticalScroll).focus()

    def action_close(self) -> None:
        self.dismiss(None)


class AboutScreen(ModalScreen[None]):
    BINDINGS: ClassVar = [("escape", "close", "Close"), ("c", "copy", "Copy")]

    def __init__(self, manifest: str) -> None:
        super().__init__()
        self.manifest = manifest

    def compose(self) -> ComposeResult:
        with Vertical(id="about-dialog"):
            yield Label("SYSTEM MANIFEST // システム情報", id="about-title")
            yield Static(self.manifest, id="about-content")
            yield Static("C  COPY DIAGNOSTICS     ESC  RETURN", classes="modal-help")

    def action_copy(self) -> None:
        try:
            self.app._copy_text(self.manifest)
        except RuntimeError as exc:
            self.notify(str(exc), title="CLIPBOARD FAULT", severity="error")
        else:
            self.notify("System manifest copied", title="DIAGNOSTICS")

    def action_close(self) -> None:
        self.dismiss(None)
