from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from .domain import (
    AgentCapabilities,
    AgentConfig,
    AgentState,
    AgentStatus,
    HistoryPage,
    PendingApproval,
    ThreadSummary,
    TranscriptEntry,
)
from .event_reducer import apply_agent_event
from .providers import AgentAdapter, AgentEvent
from .runtimes import RuntimePreflight, RuntimeRegistry


class AgentManager:
    def __init__(
        self,
        on_event: Callable[[AgentState, AgentEvent], None],
        adapter_factory: Callable[[], AgentAdapter] | None = None,
        adapter_factories: dict[str, Callable[[], AgentAdapter]] | None = None,
        runtime_registry: RuntimeRegistry | None = None,
    ) -> None:
        self.agents: list[AgentState] = []
        self._adapters: dict[str, AgentAdapter] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._on_event = on_event
        self.runtime_registry = runtime_registry or RuntimeRegistry()
        self._adapter_factories: dict[str, Callable[[], AgentAdapter]] = {}
        if adapter_factory:
            self._adapter_factories["codex"] = adapter_factory
        if adapter_factories:
            self._adapter_factories.update(adapter_factories)

    def set_event_handler(self, handler: Callable[[AgentState, AgentEvent], None]) -> None:
        """Attach the UI event sink without exposing manager internals."""
        self._on_event = handler

    def attach_adapter(self, state: AgentState, adapter: AgentAdapter) -> None:
        """Bind an externally constructed adapter to a registered agent.

        Runtime connections normally do this automatically. The explicit seam is
        useful for embedders and deterministic tests without mutating private maps.
        """
        if state not in self.agents:
            raise ValueError("Cannot attach an adapter to an unregistered agent")
        self._adapters[str(state.config.id)] = adapter

    def adapter_for(self, state: AgentState) -> AgentAdapter:
        """Return the adapter bound to a registered agent."""
        try:
            return self._adapters[str(state.config.id)]
        except KeyError as exc:
            raise LookupError(f"No adapter attached to {state.config.name}") from exc

    @property
    def available_providers(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.runtime_registry.ids, *self._adapter_factories)))

    def runtime_preflights(self, *, refresh: bool = False) -> tuple[RuntimePreflight, ...]:
        rows = {row.runtime_id: row for row in self.runtime_registry.preflights(refresh=refresh)}
        for runtime_id in self._adapter_factories:
            rows.setdefault(
                runtime_id,
                RuntimePreflight(runtime_id, runtime_id.title(), True, "injected runtime"),
            )
        return tuple(rows[runtime_id] for runtime_id in self.available_providers)

    def _new_adapter(self, provider: str) -> AgentAdapter:
        provider = provider.casefold()
        factory = self._adapter_factories.get(provider)
        return factory() if factory else self.runtime_registry.create(provider)

    def register(
        self,
        name: str,
        working_directory: Path,
        *,
        provider: str = "codex",
        status: AgentStatus = AgentStatus.STARTING,
    ) -> AgentState:
        if any(agent.config.name.casefold() == name.strip().casefold() for agent in self.agents):
            raise ValueError(f"Callsign already in use: {name.strip()}")
        provider = provider.casefold()
        if provider not in self.available_providers:
            raise ValueError(f"Unknown agent runtime: {provider}")
        state = AgentState(
            AgentConfig(
                name=name,
                working_directory=working_directory.resolve(),
                provider=provider,
            ),
            status=status,
            model_provider=provider,
        )
        self.agents.append(state)
        return state

    async def discover_threads(self, working_directory: Path) -> list[ThreadSummary]:
        adapter = self._new_adapter("codex")
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
        adapter = self._new_adapter(state.config.provider)
        self.attach_adapter(state, adapter)
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
        state = self.register(
            callsign,
            summary.cwd,
            provider=summary.provider,
            status=AgentStatus.RESTORING,
        )
        state.thread_id = summary.id
        state.restored = True
        state.current_activity = "hydrating archived turns"
        adapter = self._new_adapter(summary.provider)
        self.attach_adapter(state, adapter)
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

    def _finish_connect(self, state: AgentState, adapter: AgentAdapter) -> None:
        state.thread_id = adapter.thread_id
        state.model = adapter.model
        state.model_provider = adapter.model_provider
        state.capabilities = getattr(adapter, "capabilities", AgentCapabilities())
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

    async def _failed_connect(self, state: AgentState, adapter: AgentAdapter) -> None:
        state.status = AgentStatus.ERROR
        state.current_activity = "uplink failed"
        self._adapters.pop(str(state.config.id), None)
        await adapter.stop()

    async def spawn(
        self, name: str, working_directory: Path, *, provider: str = "codex"
    ) -> AgentState:
        state = self.register(name, working_directory, provider=provider)
        await self.connect(state)
        return state

    async def load_older(self, state: AgentState) -> HistoryPage:
        if not state.capabilities.history:
            raise ValueError(f"{state.config.provider} does not expose paged history")
        if not state.history_cursor:
            return HistoryPage()
        page = await self.adapter_for(state).list_turns(cursor=state.history_cursor)
        state.transcript[0:0] = page.transcript
        state.operations[0:0] = page.operations
        state.history_cursor = page.next_cursor
        return page

    async def send(self, state: AgentState, prompt: str) -> None:
        entry = TranscriptEntry("user", prompt)
        state.transcript.append(entry)
        state.status = AgentStatus.PROCESSING
        state.current_activity = "generating response"
        # ACP prompt requests remain open until the turn completes. Notify the UI
        # before awaiting provider acceptance so the operator's message is visible
        # immediately for every transport.
        self._on_event(state, AgentEvent("user_submitted", prompt))
        try:
            await self.adapter_for(state).send(prompt)
        except Exception as exc:
            if entry in state.transcript:
                state.transcript.remove(entry)
            state.status = AgentStatus.ERROR
            state.current_activity = "transmission failed"
            state.error_message = str(exc)
            raise

    async def rename(self, state: AgentState, name: str) -> None:
        if not state.capabilities.rename:
            raise ValueError(f"{state.config.provider} does not support persistent rename")
        name = name.strip()
        if not name:
            raise ValueError("Callsign cannot be empty")
        if any(a is not state and a.config.name.casefold() == name.casefold() for a in self.agents):
            raise ValueError(f"Callsign already in use: {name}")
        if not state.thread_id:
            raise ValueError("Agent has no thread")
        await self.adapter_for(state).set_thread_name(state.thread_id, name)
        state.config.name = name

    async def interrupt(self, state: AgentState) -> None:
        if not state.capabilities.interrupt:
            raise ValueError(f"{state.config.provider} does not support interruption")
        await self.adapter_for(state).interrupt_turn()
        state.status = AgentStatus.READY
        state.current_activity = "turn interrupted"

    async def compact_context(self, state: AgentState) -> None:
        if not state.capabilities.context_compaction:
            raise ValueError(f"{state.config.provider} does not support context compaction")
        if state.status is not AgentStatus.READY:
            raise ValueError(f"{state.config.name} is {state.status.value}; wait for READY")
        state.status = AgentStatus.PROCESSING
        state.current_activity = "compacting context"
        try:
            await self.adapter_for(state).compact_context()
        except Exception as exc:
            state.status = AgentStatus.ERROR
            state.current_activity = "context compaction failed"
            state.error_message = str(exc)
            raise
        state.status = AgentStatus.READY
        state.current_activity = "context compacted"
        state.context_tokens = 0
        state.context_percentage = None

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
        if not state.capabilities.archive:
            raise ValueError(f"{state.config.provider} does not support archiving")
        await self.adapter_for(state).archive_thread()
        await self._remove(state)

    async def retry(self, state: AgentState) -> None:
        if not state.capabilities.load_session:
            raise ValueError(f"{state.config.provider} does not support session restore")
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
        adapter = self._new_adapter(state.config.provider)
        self.attach_adapter(state, adapter)
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
        blocked = [
            f"{a.config.name} ({a.status.value.upper()})"
            for a in targets
            if a.status is not AgentStatus.READY
        ]
        if blocked:
            raise ValueError("Unavailable targets: " + ", ".join(blocked))
        results = await asyncio.gather(
            *(self.send(state, prompt) for state in targets), return_exceptions=True
        )
        summary: dict[str, str | None] = {}
        for state, result in zip(targets, results, strict=True):
            if isinstance(result, BaseException):
                # Dispatch is an explicit fan-out record: retain the attempted prompt on
                # every target even though ordinary rejected sends are rolled back.
                state.transcript.append(TranscriptEntry("user", prompt))
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
        await self.adapter_for(state).respond_approval(request_id, decision)
        state.pending_approvals[:] = [
            approval for approval in state.pending_approvals if approval.request_id != request_id
        ]
        if not state.pending_approvals:
            state.status = AgentStatus.PROCESSING
            state.current_activity = "resuming authorized turn"

    async def respond_all_approvals(
        self, state: AgentState, decision: str = "accept"
    ) -> list[tuple[PendingApproval, Exception | None]]:
        """Resolve the current approval batch without conflating request identities."""
        pending = list(state.pending_approvals)

        async def respond(approval: PendingApproval) -> tuple[PendingApproval, Exception | None]:
            try:
                await self.respond_approval(state, approval.request_id, decision)
            except Exception as exc:  # noqa: BLE001
                return approval, exc
            return approval, None

        return list(await asyncio.gather(*(respond(approval) for approval in pending)))

    async def shutdown(self) -> None:
        await asyncio.gather(*(adapter.stop() for adapter in self._adapters.values()))
        for task in self._tasks.values():
            task.cancel()

    async def _pump(self, state: AgentState, adapter: AgentAdapter) -> None:
        try:
            async for event in adapter.events():
                apply_agent_event(state, event)
                self._on_event(state, event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            state.status = AgentStatus.ERROR
            state.current_activity = "event pump failed"
            state.error_message = str(exc)
            self._on_event(state, AgentEvent("error", f"event pump failed: {exc}"))
