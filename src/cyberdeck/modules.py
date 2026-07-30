from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from textual.widget import Widget

CommandHandler = Callable[[list[str]], Awaitable[None] | None]
CYBERDECK_MODULE_API = 1
MODULE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")


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
    version: str = "0.0.0"
    api_version: int = CYBERDECK_MODULE_API
    requires_cyberdeck: str = ">=0.3,<0.4"
    author: str = "Unknown"
    source: str = "bundled"
    capabilities: tuple[str, ...] = ()


class ModuleStatus(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    FAULTED = "faulted"
    UPDATE_PENDING = "update_pending"


@dataclass(frozen=True, slots=True)
class ModuleContext:
    """Stable services available to a trusted in-process module."""

    module_id: str
    data_directory: Path
    config_directory: Path
    notify: Callable[[str, str, str], None]
    copy_to_clipboard: Callable[[str], None]
    services: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DeckCommand:
    name: str
    description: str
    handler: CommandHandler


class DeckModule(ABC):
    """Version 1 contract for bundled and trusted external workspaces."""

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


def validate_manifest(manifest: ModuleManifest) -> None:
    if not MODULE_ID_PATTERN.fullmatch(manifest.id):
        raise ValueError(
            "Module id must be 2-32 lowercase letters, digits, underscores, or hyphens"
        )
    if manifest.id == "agents" and manifest.source != "bundled":
        raise ValueError("The module id 'agents' is reserved")
    if manifest.api_version != CYBERDECK_MODULE_API:
        raise ValueError(
            f"Module API {manifest.api_version} is incompatible with API {CYBERDECK_MODULE_API}"
        )
    if not manifest.title.strip() or not manifest.description.strip():
        raise ValueError("Module title and description are required")
