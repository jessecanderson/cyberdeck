from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal

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
from .native_agents import NativeAgentCatalog, discover_native_agents
from .providers import AgentAdapter, AgentEvent, SteeringNotSent
from .runtimes import RuntimePreflight, RuntimeRegistry

PromptDisposition = Literal["sent", "steered", "queued"]


class AgentManager:
    def __init__(
        self,
        on_event: Callable[[AgentState, AgentEvent], None],
        adapter_factory: Callable[[], AgentAdapter] | None = None,
        adapter_factories: dict[str, Callable[[], AgentAdapter]] | None = None,
        runtime_registry: RuntimeRegistry | None = None,
        cancellation_timeout: float = 30.0,
    ) -> None:
        if cancellation_timeout <= 0:
            raise ValueError("Cancellation timeout must be positive")
        self.cancellation_timeout = cancellation_timeout
        self._owned: dict[str, set[asyncio.Task]] = {}
        self._completion: dict[str, asyncio.Event] = {}
        self._reserved: dict[str, tuple[asyncio.Task[None], str]] = {}
        self.agents: list[AgentState] = []
        self._adapters: dict[str, AgentAdapter] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._send_tasks: dict[str, asyncio.Task[None]] = {}
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

    def native_agents(self, working_directory: Path) -> NativeAgentCatalog:
        return discover_native_agents(working_directory)

    def _new_adapter(self, provider: str, native_agent: str | None = None) -> AgentAdapter:
        provider = provider.casefold()
        factory = self._adapter_factories.get(provider)
        if factory:
            return factory()
        return self.runtime_registry.create(provider, native_agent)

    def register(
        self,
        name: str,
        working_directory: Path,
        *,
        provider: str = "codex",
        native_agent: str | None = None,
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
                native_agent=native_agent,
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

    @asynccontextmanager
    async def _own_task(self, state: AgentState) -> AsyncIterator[None]:
        task = asyncio.current_task()
        assert task is not None
        owned = self._owned.setdefault(str(state.config.id), set())
        owned.add(task)
        try:
            yield
        finally:
            owned.discard(task)

    async def connect(self, state: AgentState) -> None:
        adapter = self._new_adapter(state.config.provider, state.config.native_agent)
        self.attach_adapter(state, adapter)
        async with self._own_task(state):
            try:
                await adapter.start(state.config.working_directory, state.config.name)
                if self._current(state, adapter):
                    self._finish_connect(state, adapter)
            except (Exception, asyncio.CancelledError):
                if self._current(state, adapter):
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
        async with self._own_task(state):
            try:
                page = await adapter.resume_thread(summary.id, summary.cwd)
                if not summary.name:
                    await adapter.set_thread_name(summary.id, callsign)
                state.transcript = page.transcript
                state.operations = page.operations
                state.history_cursor = page.next_cursor
                self._finish_connect(state, adapter)
            except (Exception, asyncio.CancelledError):
                state.status = AgentStatus.ERROR
                state.current_activity = "restore failed"
                self._on_event(state, AgentEvent("error", "restore failed"))
                await adapter.stop()
                raise
        return state

    def _finish_connect(self, state: AgentState, adapter: AgentAdapter) -> None:
        if not self._current(state, adapter):
            return
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
        self,
        name: str,
        working_directory: Path,
        *,
        provider: str = "codex",
        native_agent: str | None = None,
    ) -> AgentState:
        state = self.register(name, working_directory, provider=provider, native_agent=native_agent)
        await self.connect(state)
        return state

    async def load_older(self, state: AgentState) -> HistoryPage:
        if not state.capabilities.history:
            raise ValueError(f"{state.config.provider} does not expose paged history")
        if not state.history_cursor:
            return HistoryPage()
        adapter = self.adapter_for(state)
        async with self._own_task(state):
            page = await adapter.list_turns(cursor=state.history_cursor)
        if not self._current(state, adapter):
            return HistoryPage()
        state.transcript[0:0] = page.transcript
        state.operations[0:0] = page.operations
        state.history_cursor = page.next_cursor
        return page

    def recovery_guidance(self, state: AgentState) -> str:
        if state.capabilities.load_session and state.thread_id:
            return "run /retry"
        return "disconnect this uplink and use /new"

    def _current(self, state: AgentState, adapter: AgentAdapter) -> bool:
        return self._adapters.get(str(state.config.id)) is adapter

    def _retain_uncertain(self, state: AgentState, prompt: str) -> None:
        state.uncertain_prompts.append(prompt)
        state.queue_paused = True
        state.current_activity = "delivery uncertain; review /queue and transcript"
        self._on_event(state, AgentEvent("delivery_uncertain", prompt))

    async def send(self, state: AgentState, prompt: str) -> None:
        if state.status is not AgentStatus.READY or state.cancellation_pending:
            raise ValueError(f"{state.config.name} requires READY")
        await self._deliver(state, prompt, steering=False)

    async def _deliver(self, state: AgentState, prompt: str, *, steering: bool) -> None:
        adapter = self.adapter_for(state)
        key = str(state.config.id)
        task = asyncio.current_task()
        owned = self._owned.setdefault(key, set())
        owned.add(task)
        entry = TranscriptEntry("user", prompt)
        state.transcript.append(entry)
        if not steering:
            state.status = AgentStatus.PROCESSING
            state.current_activity = "generating response"
        self._on_event(
            state, AgentEvent("user_submitted", prompt, method="turn/steer" if steering else "")
        )
        try:
            if steering:
                await adapter.steer(prompt)
            else:
                await adapter.send(prompt)
        except SteeringNotSent:
            if self._current(state, adapter) and entry in state.transcript:
                state.transcript.remove(entry)
            raise
        except (Exception, asyncio.CancelledError) as exc:
            if self._current(state, adapter):
                if entry in state.transcript:
                    state.transcript.remove(entry)
                self._retain_uncertain(state, prompt)
                state.status = AgentStatus.ERROR
                state.error_message = str(exc) or "submission cancelled during delivery"
            raise
        finally:
            owned.discard(task)

    def _queue(self, state: AgentState, prompt: str) -> PromptDisposition:
        state.queued_prompts.append(prompt)
        self._on_event(state, AgentEvent("prompt_queued", prompt))
        return "queued"

    async def submit_prompt(self, state: AgentState, prompt: str) -> PromptDisposition:
        """Continue the selected conversation without replaying uncertain input."""
        if state.queue_paused or state.cancellation_pending:
            return self._queue(state, prompt)
        if state.status is AgentStatus.READY:
            await self.send(state, prompt)
            return "sent"
        if state.status not in {
            AgentStatus.PROCESSING,
            AgentStatus.EXECUTING,
            AgentStatus.EDITING,
            AgentStatus.FIREWALL_HOLD,
        }:
            raise ValueError(f"{state.config.name} is {state.status.value}; cannot accept input")
        if not state.capabilities.steering:
            return self._queue(state, prompt)
        try:
            await self.steer(state, prompt)
        except SteeringNotSent:
            # The adapter proves no write occurred. READY is still required before
            # starting a new turn; a completion event may still be in flight.
            self._queue(state, prompt)
            self._schedule_queue(state)
            return "queued"
        return "steered"

    async def steer(self, state: AgentState, prompt: str) -> None:
        if not state.capabilities.steering:
            raise ValueError(f"{state.config.provider} does not support active-turn steering")
        await self._deliver(state, prompt, steering=True)

    def resume_queue(self, state: AgentState) -> None:
        if state.status is not AgentStatus.READY or state.cancellation_pending:
            raise ValueError("Queue resume requires READY")
        state.queue_paused = False
        self._schedule_queue(state)

    def clear_queue(self, state: AgentState) -> None:
        reservation = self._reserved.pop(str(state.config.id), None)
        if reservation:
            reservation[0].cancel()
            state.status = AgentStatus.READY
        state.queued_prompts.clear()
        state.uncertain_prompts.clear()

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
        adapter = self.adapter_for(state)
        async with self._own_task(state):
            await adapter.set_thread_name(state.thread_id, name)
        if self._current(state, adapter):
            state.config.name = name

    async def interrupt(self, state: AgentState) -> None:
        if not state.capabilities.interrupt:
            raise ValueError(f"{state.config.provider} does not support interruption")
        state.queue_paused = True
        if state.cancellation_pending or state.status is AgentStatus.READY:
            return
        adapter = self.adapter_for(state)
        key = str(state.config.id)
        reservation = self._reserved.get(key)
        if reservation:
            reservation[0].cancel()
            with suppress(asyncio.CancelledError):
                await reservation[0]
            state.status = AgentStatus.READY
            return
        completed = self._completion.setdefault(key, asyncio.Event())
        completed.clear()
        state.cancellation_pending = True
        state.current_activity = "cancellation pending; queue paused"
        task = asyncio.current_task()
        owned = self._owned.setdefault(key, set())
        owned.add(task)
        try:
            async with asyncio.timeout(self.cancellation_timeout):
                await adapter.interrupt_turn()
                await completed.wait()
                if state.status is AgentStatus.ERROR:
                    raise RuntimeError(
                        state.error_message or "transport failed during cancellation"
                    )
        except Exception as exc:
            if self._current(state, adapter):
                await self._cancel_owned(key)
                await self._cancel_pump(key)
                await adapter.stop()
                apply_agent_event(
                    state,
                    AgentEvent("error", f"Cancellation failed: {str(exc) or type(exc).__name__}"),
                )
                self._on_event(
                    state, AgentEvent("error", state.error_message or "Cancellation failed")
                )
            raise
        finally:
            owned.discard(task)
            if self._current(state, adapter):
                state.cancellation_pending = False

    async def _cancel_owned(self, key: str) -> None:
        tasks = set(self._owned.get(key, ()))
        queued = self._send_tasks.pop(key, None)
        if queued:
            tasks.add(queued)
        tasks.discard(asyncio.current_task())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def compact_context(self, state: AgentState) -> None:
        if not state.capabilities.context_compaction:
            raise ValueError(f"{state.config.provider} does not support context compaction")
        if state.status is not AgentStatus.READY:
            raise ValueError(f"{state.config.name} is {state.status.value}; wait for READY")
        state.status = AgentStatus.PROCESSING
        state.current_activity = "compacting context"
        adapter = self.adapter_for(state)
        async with self._own_task(state):
            try:
                await adapter.compact_context()
            except Exception as exc:
                if self._current(state, adapter):
                    state.queue_paused = True
                    state.status = AgentStatus.ERROR
                    state.current_activity = "context compaction failed"
                    state.error_message = str(exc)
                raise
        if not self._current(state, adapter):
            return
        state.status = AgentStatus.READY
        state.current_activity = "context compacted"
        state.context_tokens = 0
        state.context_percentage = None

    async def _remove(self, state: AgentState) -> None:
        key = str(state.config.id)
        await self._cancel_owned(key)
        await self._cancel_pump(key)
        adapter = self._adapters.pop(key, None)
        try:
            if adapter:
                await adapter.stop()
        finally:
            if state in self.agents:
                self.agents.remove(state)
            state.status = AgentStatus.STOPPED

    async def _cancel_pump(self, key: str) -> None:
        task = self._tasks.pop(key, None)
        if not task:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def disconnect(self, state: AgentState) -> None:
        await self._remove(state)

    async def archive(self, state: AgentState) -> None:
        if not state.capabilities.archive:
            raise ValueError(f"{state.config.provider} does not support archiving")
        adapter = self.adapter_for(state)
        async with self._own_task(state):
            await adapter.archive_thread()
        if self._current(state, adapter):
            await self._remove(state)

    async def retry(self, state: AgentState) -> None:
        if not state.capabilities.load_session:
            raise ValueError(f"{state.config.provider} does not support session restore")
        if not state.thread_id:
            raise ValueError("Agent has no thread to restore")
        key = str(state.config.id)
        state.queue_paused = True
        await self._cancel_owned(key)
        state.cancellation_pending = False
        old_adapter = self._adapters.pop(key, None)
        await self._cancel_pump(key)
        if old_adapter:
            await old_adapter.stop()
        state.status = AgentStatus.RESTORING
        state.current_activity = "re-establishing uplink"
        state.recovery_attempts += 1
        adapter = self._new_adapter(state.config.provider, state.config.native_agent)
        self.attach_adapter(state, adapter)
        async with self._own_task(state):
            try:
                page = await adapter.resume_thread(state.thread_id, state.config.working_directory)
                state.transcript[:] = page.transcript
                state.operations[:] = page.operations
                state.history_cursor = page.next_cursor
                self._finish_connect(state, adapter)
            except (Exception, asyncio.CancelledError) as exc:
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
        adapter = self.adapter_for(state)
        async with self._own_task(state):
            await adapter.respond_approval(request_id, decision)
        if not self._current(state, adapter):
            return
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
        for key in tuple(self._adapters):
            await self._cancel_owned(key)
        tasks = (*self._tasks.values(), *self._send_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(
            *(adapter.stop() for adapter in self._adapters.values()), return_exceptions=True
        )

    async def _pump(self, state: AgentState, adapter: AgentAdapter) -> None:
        try:
            async for event in adapter.events():
                if not self._current(state, adapter):
                    return
                # Startup readiness was already applied by _finish_connect. It
                # may still be queued when the operator begins the first turn.
                if (event.params or {}).get("connection_ready"):
                    continue
                # ERROR is terminal for a connection. Late completion cannot make
                # an uncertain transport safe to use again.
                if state.status is AgentStatus.ERROR:
                    continue
                apply_agent_event(state, event)
                if (
                    event.kind == "status" and event.text == "ready"
                ) or state.status is AgentStatus.ERROR:
                    self._completion.setdefault(str(state.config.id), asyncio.Event()).set()
                self._on_event(state, event)
                self._schedule_queue(state)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            if not self._current(state, adapter):
                return
            state.queue_paused = True
            state.status = AgentStatus.ERROR
            state.current_activity = "event pump failed"
            state.error_message = str(exc)
            self._on_event(state, AgentEvent("error", f"event pump failed: {exc}"))

    def _schedule_queue(self, state: AgentState) -> None:
        if (
            state.status is not AgentStatus.READY
            or not state.queued_prompts
            or state.queue_paused
            or state.cancellation_pending
        ):
            return
        prompt = state.queued_prompts.pop(0)
        state.status = AgentStatus.PROCESSING
        state.current_activity = "dispatching queued input"
        key = str(state.config.id)

        async def deliver() -> None:
            self._reserved.pop(key, None)
            await self._send_queued(state, prompt)

        def finished(done: asyncio.Task[None]) -> None:
            if self._reserved.get(key) == (done, prompt):
                self._reserved.pop(key)
                state.queued_prompts.insert(0, prompt)
            self._send_task_done(key, done)

        task = asyncio.create_task(deliver())
        self._send_tasks[key] = task
        self._reserved[key] = (task, prompt)
        task.add_done_callback(finished)

    async def _send_queued(self, state: AgentState, prompt: str) -> None:
        adapter = self.adapter_for(state)
        try:
            await self._deliver(state, prompt, steering=False)
        except Exception as exc:  # noqa: BLE001 - queued sends become per-agent errors
            if not self._current(state, adapter):
                return
            state.status = AgentStatus.ERROR
            state.current_activity = "queued transmission failed"
            state.error_message = str(exc)
            self._on_event(state, AgentEvent("error", f"queued transmission failed: {exc}"))

    def _send_task_done(self, key: str, task: asyncio.Task[None]) -> None:
        if self._send_tasks.get(key) is task:
            self._send_tasks.pop(key, None)
