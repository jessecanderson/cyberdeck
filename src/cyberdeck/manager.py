from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from .domain import (
    AgentConfig,
    AgentState,
    AgentStatus,
    HistoryPage,
    OperationState,
    PendingApproval,
    ThreadSummary,
    TranscriptEntry,
    operation_from_item,
)
from .providers import AgentEvent, CodexAppServerAdapter


class AgentManager:
    def __init__(
        self,
        on_event: Callable[[AgentState, AgentEvent], None],
        adapter_factory: Callable[[], CodexAppServerAdapter] = CodexAppServerAdapter,
    ) -> None:
        self.agents: list[AgentState] = []
        self._adapters: dict[str, CodexAppServerAdapter] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._on_event = on_event
        self._adapter_factory = adapter_factory

    def register(
        self, name: str, working_directory: Path, *, status: AgentStatus = AgentStatus.STARTING
    ) -> AgentState:
        if any(agent.config.name.casefold() == name.strip().casefold() for agent in self.agents):
            raise ValueError(f"Callsign already in use: {name.strip()}")
        state = AgentState(
            AgentConfig(name=name, working_directory=working_directory.resolve()), status=status
        )
        self.agents.append(state)
        return state

    async def discover_threads(self, working_directory: Path) -> list[ThreadSummary]:
        adapter = self._adapter_factory()
        rows: list[ThreadSummary] = []
        cursor: str | None = None
        try:
            while True:
                page, cursor = await adapter.list_threads(working_directory, cursor=cursor)
                rows.extend(page)
                if not cursor:
                    break
        finally:
            await adapter.stop()
        open_ids = {agent.thread_id for agent in self.agents if agent.thread_id}
        for row in rows:
            row.is_open = row.id in open_ids
        return rows

    async def connect(self, state: AgentState) -> None:
        adapter = self._adapter_factory()
        self._adapters[str(state.config.id)] = adapter
        try:
            await adapter.start(state.config.working_directory, state.config.name)
            self._finish_connect(state, adapter)
        except Exception:
            await self._failed_connect(state, adapter)
            raise

    async def restore(self, summary: ThreadSummary, name: str | None = None) -> AgentState:
        callsign = (name or summary.name or "").strip()
        if not callsign:
            raise ValueError("A callsign is required for unnamed threads")
        if any(agent.thread_id == summary.id for agent in self.agents):
            raise ValueError("Thread is already open in Cyberdeck")
        state = self.register(callsign, summary.cwd, status=AgentStatus.RESTORING)
        state.thread_id = summary.id
        state.restored = True
        state.current_activity = "hydrating archived turns"
        adapter = self._adapter_factory()
        self._adapters[str(state.config.id)] = adapter
        try:
            page = await adapter.resume_thread(summary.id, summary.cwd)
            if not summary.name:
                await adapter.set_thread_name(summary.id, callsign)
            state.transcript = page.transcript
            state.operations = page.operations
            state.history_cursor = page.next_cursor
            self._finish_connect(state, adapter)
        except Exception:
            state.status = AgentStatus.ERROR
            state.current_activity = "restore failed"
            self._on_event(state, AgentEvent("error", "restore failed"))
            await adapter.stop()
            raise
        return state

    def _finish_connect(self, state: AgentState, adapter: CodexAppServerAdapter) -> None:
        state.thread_id = adapter.thread_id
        state.model = adapter.model
        state.model_provider = adapter.model_provider
        state.status = AgentStatus.READY
        state.current_activity = "awaiting input"
        state.error_message = None
        task = asyncio.create_task(self._pump(state, adapter))
        key = str(state.config.id)
        self._tasks[key] = task
        task.add_done_callback(lambda done, agent_key=key: self._task_done(agent_key, done))

    def _task_done(self, key: str, task: asyncio.Task[None]) -> None:
        if self._tasks.get(key) is task:
            self._tasks.pop(key, None)

    async def _failed_connect(
        self, state: AgentState, adapter: CodexAppServerAdapter
    ) -> None:
        state.status = AgentStatus.ERROR
        state.current_activity = "uplink failed"
        self._adapters.pop(str(state.config.id), None)
        await adapter.stop()

    async def spawn(self, name: str, working_directory: Path) -> AgentState:
        state = self.register(name, working_directory)
        await self.connect(state)
        return state

    async def load_older(self, state: AgentState) -> HistoryPage:
        if not state.history_cursor:
            return HistoryPage()
        page = await self._adapters[str(state.config.id)].list_turns(cursor=state.history_cursor)
        state.transcript[0:0] = page.transcript
        state.operations[0:0] = page.operations
        state.history_cursor = page.next_cursor
        return page

    async def send(self, state: AgentState, prompt: str) -> None:
        state.transcript.append(TranscriptEntry("user", prompt))
        state.status = AgentStatus.PROCESSING
        state.current_activity = "generating response"
        await self._adapters[str(state.config.id)].send(prompt)

    async def rename(self, state: AgentState, name: str) -> None:
        name = name.strip()
        if not name:
            raise ValueError("Callsign cannot be empty")
        if any(a is not state and a.config.name.casefold() == name.casefold() for a in self.agents):
            raise ValueError(f"Callsign already in use: {name}")
        if not state.thread_id:
            raise ValueError("Agent has no thread")
        await self._adapters[str(state.config.id)].set_thread_name(state.thread_id, name)
        state.config.name = name

    async def interrupt(self, state: AgentState) -> None:
        await self._adapters[str(state.config.id)].interrupt_turn()
        state.status = AgentStatus.READY
        state.current_activity = "turn interrupted"

    async def _remove(self, state: AgentState) -> None:
        key = str(state.config.id)
        task = self._tasks.pop(key, None)
        if task:
            task.cancel()
        adapter = self._adapters.pop(key, None)
        if adapter:
            await adapter.stop()
        if state in self.agents:
            self.agents.remove(state)
        state.status = AgentStatus.STOPPED

    async def disconnect(self, state: AgentState) -> None:
        await self._remove(state)

    async def archive(self, state: AgentState) -> None:
        await self._adapters[str(state.config.id)].archive_thread()
        await self._remove(state)

    async def retry(self, state: AgentState) -> None:
        if not state.thread_id:
            raise ValueError("Agent has no thread to restore")
        key = str(state.config.id)
        old_adapter = self._adapters.pop(key, None)
        old_task = self._tasks.pop(key, None)
        if old_task:
            old_task.cancel()
        if old_adapter:
            await old_adapter.stop()
        state.status = AgentStatus.RESTORING
        state.current_activity = "re-establishing uplink"
        state.recovery_attempts += 1
        adapter = self._adapter_factory()
        self._adapters[key] = adapter
        try:
            page = await adapter.resume_thread(state.thread_id, state.config.working_directory)
            state.transcript[:] = page.transcript
            state.operations[:] = page.operations
            state.history_cursor = page.next_cursor
            self._finish_connect(state, adapter)
        except Exception as exc:
            state.status = AgentStatus.ERROR
            state.current_activity = "recovery failed"
            state.error_message = str(exc)
            await adapter.stop()
            self._adapters.pop(key, None)
            self._on_event(state, AgentEvent("error", str(exc)))
            raise

    async def dispatch(self, targets: list[AgentState], prompt: str) -> dict[str, str | None]:
        if len(targets) < 2:
            raise ValueError("Dispatch requires at least two targets")
        blocked = [f"{a.config.name} ({a.status.value.upper()})" for a in targets if a.status is not AgentStatus.READY]
        if blocked:
            raise ValueError("Unavailable targets: " + ", ".join(blocked))
        results = await asyncio.gather(
            *(self.send(state, prompt) for state in targets), return_exceptions=True
        )
        summary: dict[str, str | None] = {}
        for state, result in zip(targets, results, strict=True):
            if isinstance(result, BaseException):
                state.status = AgentStatus.ERROR
                state.current_activity = "dispatch failed"
                state.error_message = str(result)
                summary[state.config.name] = str(result)
            else:
                summary[state.config.name] = None
        return summary

    async def respond_approval(
        self, state: AgentState, request_id: int | str, decision: str
    ) -> None:
        await self._adapters[str(state.config.id)].respond_approval(request_id, decision)
        state.pending_approvals[:] = [
            approval for approval in state.pending_approvals
            if approval.request_id != request_id
        ]
        if not state.pending_approvals:
            state.status = AgentStatus.PROCESSING
            state.current_activity = "resuming authorized turn"

    async def shutdown(self) -> None:
        await asyncio.gather(*(adapter.stop() for adapter in self._adapters.values()))
        for task in self._tasks.values():
            task.cancel()

    async def _pump(self, state: AgentState, adapter: CodexAppServerAdapter) -> None:
      try:
        async for event in adapter.events():
            if event.kind == "status":
                normalized = "processing" if event.text == "working" else event.text
                state.status = AgentStatus(normalized)
                state.current_activity = (
                    "generating response"
                    if state.status is AgentStatus.PROCESSING
                    else "awaiting input"
                )
            elif event.kind == "assistant_delta":
                if state.transcript and state.transcript[-1].role == "assistant":
                    state.transcript[-1].text += event.text
                else:
                    state.transcript.append(TranscriptEntry("assistant", event.text))
                state.status = AgentStatus.PROCESSING
                state.current_activity = "streaming response"
            elif event.kind == "operation":
                operation = operation_from_item(event.params or {})
                existing = next((op for op in state.operations if op.id == operation.id), None)
                if existing and operation.id:
                    index = state.operations.index(existing)
                    state.operations[index] = operation
                else:
                    state.operations.append(operation)
                is_edit = operation.kind == "fileChange"
                state.status = AgentStatus.EDITING if is_edit else AgentStatus.EXECUTING
                state.current_activity = operation.summary
                if event.method == "item/completed" and operation.state is OperationState.RUNNING:
                    operation.state = OperationState.SUCCEEDED
            elif event.kind == "approval":
                state.status = AgentStatus.FIREWALL_HOLD
                state.current_activity = "ICE authorization required"
                if event.request_id is not None:
                    state.pending_approvals.append(
                        PendingApproval(
                            request_id=event.request_id,
                            method=event.method,
                            params=event.params or {},
                        )
                    )
            elif event.kind == "token_usage":
                usage = (event.params or {}).get("tokenUsage") or {}
                last = usage.get("last") or {}
                state.context_tokens = int(last.get("totalTokens") or 0)
                window = usage.get("modelContextWindow")
                state.context_window = int(window) if window else None
            elif event.kind in {"error", "transport_closed"}:
                state.status = AgentStatus.ERROR
                state.current_activity = event.text
                state.error_message = event.text
                state.pending_approvals.clear()
            self._on_event(state, event)
      except asyncio.CancelledError:
        raise
      except Exception as exc:  # noqa: BLE001
        state.status = AgentStatus.ERROR
        state.current_activity = "event pump failed"
        state.error_message = str(exc)
        self._on_event(state, AgentEvent("error", f"event pump failed: {exc}"))
