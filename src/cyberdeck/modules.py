from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum

from textual.widget import Widget

CommandHandler = Callable[[list[str]], Awaitable[None] | None]


class ModuleInputMode(str, Enum):
    DECK_PROMPT = "deck_prompt"
    WORKSPACE_EDITOR = "workspace_editor"
    VIEW_ONLY = "view_only"


@dataclass(frozen=True, slots=True)
class ModuleManifest:
    id: str
    title: str
    description: str
    order: int = 100


@dataclass(frozen=True, slots=True)
class DeckCommand:
    name: str
    description: str
    handler: CommandHandler


class DeckModule(ABC):
    """Provisional contract exercised by Cyberdeck's built-in workspaces."""

    manifest: ModuleManifest
    input_mode: ModuleInputMode = ModuleInputMode.DECK_PROMPT
    focus_target: str | None = None

    @abstractmethod
    def build(self) -> Widget:
        """Return the retained root widget for this module."""

    def commands(self) -> tuple[DeckCommand, ...]:
        return ()

    async def activate(self) -> None:
        return None

    async def deactivate(self) -> None:
        return None

    async def save(self) -> bool:
        """Persist module state when supported; return whether save was handled."""
        return False

    @abstractmethod
    async def handle_prompt(self, text: str) -> None:
        """Handle ordinary deck-prompt input while this module is active."""
