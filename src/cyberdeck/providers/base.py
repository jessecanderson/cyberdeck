from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class AgentEvent:
    kind: str
    text: str = ""
    request_id: int | str | None = None
    method: str = ""
    params: dict[str, Any] | None = None
    message_id: str | None = None


class AgentAdapter(Protocol):
    async def start(self, working_directory: Path) -> None: ...

    async def send(self, prompt: str) -> None: ...

    async def stop(self) -> None: ...

    async def respond_approval(self, request_id: int | str, decision: str) -> None: ...

    async def events(self) -> AsyncIterator[AgentEvent]: ...
