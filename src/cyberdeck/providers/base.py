from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..domain import AgentCapabilities, HistoryPage, ThreadSummary


@dataclass(frozen=True, slots=True)
class AgentEvent:
    kind: str
    text: str = ""
    request_id: int | str | None = None
    method: str = ""
    params: dict[str, Any] | None = None
    message_id: str | None = None


class AgentAdapter(Protocol):
    thread_id: str | None
    model: str | None
    model_provider: str
    capabilities: AgentCapabilities

    async def start(self, working_directory: Path, name: str | None = None) -> None: ...

    async def send(self, prompt: str) -> None: ...

    async def stop(self) -> None: ...

    async def interrupt_turn(self) -> None: ...

    async def compact_context(self) -> None: ...

    async def respond_approval(self, request_id: int | str, decision: str) -> None: ...

    async def resume_thread(self, thread_id: str, cwd: Path) -> HistoryPage: ...

    async def list_threads(
        self, working_directory: Path, *, cursor: str | None = None
    ) -> tuple[list[ThreadSummary], str | None]: ...

    async def list_turns(self, *, cursor: str | None = None) -> HistoryPage: ...

    async def set_thread_name(self, thread_id: str, name: str) -> None: ...

    async def archive_thread(self) -> None: ...

    async def events(self) -> AsyncIterator[AgentEvent]: ...
