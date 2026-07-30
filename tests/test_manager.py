import asyncio
from pathlib import Path

import pytest

from cyberdeck.domain import AgentCapabilities, AgentStatus, HistoryPage, PendingApproval
from cyberdeck.manager import AgentManager
from cyberdeck.providers import AgentEvent


class FakeAdapter:
    def __init__(self, *, fail_send: bool = False) -> None:
        self.thread_id = "thread-1"
        self.model = "test"
        self.model_provider = "codex"
        self.fail_send = fail_send
        self.stopped = False
        self.names = []
        self.queue = []
        self.approvals = []
        self.compacted = False
        self.capabilities = AgentCapabilities(
            load_session=True,
            history=True,
            rename=True,
            archive=True,
            context_compaction=True,
        )

    async def events(self):
        while self.queue:
            yield self.queue.pop(0)

    async def start(self, working_directory, name=None):
        self.started = (working_directory, name)

    async def send(self, prompt):
        if self.fail_send:
            raise RuntimeError("radio failure")

    async def set_thread_name(self, thread_id, name):
        self.names.append((thread_id, name))

    async def interrupt_turn(self):
        pass

    async def compact_context(self):
        self.compacted = True

    async def archive_thread(self):
        pass

    async def respond_approval(self, request_id, decision):
        self.approvals.append((request_id, decision))

    async def stop(self):
        self.stopped = True

    async def resume_thread(self, thread_id, cwd):
        self.thread_id = thread_id
        return HistoryPage()


def manager() -> AgentManager:
    return AgentManager(lambda state, event: None, adapter_factory=FakeAdapter)


def test_adapter_binding_is_public_and_validates_registration() -> None:
    deck = manager()
    state = deck.register("ghost", Path("/tmp"), status=AgentStatus.READY)
    adapter = FakeAdapter()

    deck.attach_adapter(state, adapter)

    assert deck.adapter_for(state) is adapter
    foreign = manager().register("foreign", Path("/tmp"))
    with pytest.raises(ValueError, match="unregistered"):
        deck.attach_adapter(foreign, FakeAdapter())


@pytest.mark.asyncio
async def test_compact_context_uses_provider_and_returns_agent_ready() -> None:
    deck = manager()
    state = deck.register("ghost", Path("/tmp"), status=AgentStatus.READY)
    adapter = FakeAdapter()
    deck.attach_adapter(state, adapter)
    state.capabilities = adapter.capabilities
    state.context_tokens = 42_000
    state.thread_id = "durable-thread"
    original_transcript = list(state.transcript)

    await deck.compact_context(state)

    assert adapter.compacted is True
    assert state.status is AgentStatus.READY
    assert state.current_activity == "context compacted"
    assert state.context_tokens == 0
    assert state.thread_id == "durable-thread"
    assert state.transcript == original_transcript


@pytest.mark.asyncio
async def test_compact_context_failure_is_visible_and_recoverable() -> None:
    class FailingCompactAdapter(FakeAdapter):
        async def compact_context(self):
            raise RuntimeError("provider rejected compaction")

    deck = manager()
    state = deck.register("ghost", Path("/tmp"), status=AgentStatus.READY)
    adapter = FailingCompactAdapter()
    deck.attach_adapter(state, adapter)
    state.capabilities = adapter.capabilities

    with pytest.raises(RuntimeError, match="provider rejected"):
        await deck.compact_context(state)

    assert state.status is AgentStatus.ERROR
    assert state.current_activity == "context compaction failed"
    assert state.error_message == "provider rejected compaction"


@pytest.mark.asyncio
async def test_compact_context_rejects_busy_or_unsupported_agent() -> None:
    deck = manager()
    state = deck.register("ghost", Path("/tmp"), status=AgentStatus.PROCESSING)
    state.capabilities = AgentCapabilities(context_compaction=True)
    deck.attach_adapter(state, FakeAdapter())

    with pytest.raises(ValueError, match="wait for READY"):
        await deck.compact_context(state)

    state.status = AgentStatus.READY
    state.capabilities = AgentCapabilities(context_compaction=False)
    with pytest.raises(ValueError, match="does not support"):
        await deck.compact_context(state)


@pytest.mark.asyncio
async def test_send_announces_user_message_before_provider_finishes() -> None:
    release = asyncio.Event()
    observed: list[tuple[str, list[str]]] = []

    class DelayedAdapter(FakeAdapter):
        async def send(self, prompt):
            await release.wait()

    deck = AgentManager(
        lambda state, event: observed.append(
            (event.kind, [entry.text for entry in state.transcript])
        ),
        adapter_factory=DelayedAdapter,
    )
    state = deck.register("ghost", Path("/tmp"), status=AgentStatus.READY)
    adapter = DelayedAdapter()
    deck.attach_adapter(state, adapter)

    send_task = asyncio.create_task(deck.send(state, "scan grid"))
    await asyncio.sleep(0)

    assert observed == [("user_submitted", ["scan grid"])]
    assert not send_task.done()
    release.set()
    await send_task


@pytest.mark.asyncio
async def test_connect_uses_registered_provider_factory() -> None:
    kiro_adapter = FakeAdapter()
    kiro_adapter.model_provider = "kiro"
    deck = AgentManager(
        lambda state, event: None,
        adapter_factory=FakeAdapter,
        adapter_factories={"kiro": lambda: kiro_adapter},
    )
    state = deck.register("wintermute", Path("/tmp"), provider="kiro")

    assert state.model_provider == "kiro"

    await deck.connect(state)

    assert state.config.provider == "kiro"
    assert state.model_provider == "kiro"
    assert kiro_adapter.started == (state.config.working_directory, "wintermute")
    await deck.shutdown()


@pytest.mark.asyncio
async def test_respond_all_approvals_preserves_each_request_identity() -> None:
    deck = manager()
    state, adapter = attach(deck, "ghost")
    state.pending_approvals.extend(
        [
            PendingApproval("permission-7", "session/request_permission", {"options": []}),
            PendingApproval("permission-8", "session/request_permission", {"options": []}),
        ]
    )

    results = await deck.respond_all_approvals(state)

    assert adapter.approvals == [
        ("permission-7", "accept"),
        ("permission-8", "accept"),
    ]
    assert all(error is None for _, error in results)
    assert state.pending_approvals == []


def attach(manager, name):
    state = manager.register(name, Path("/tmp"), status=AgentStatus.READY)
    state.thread_id = f"thread-{name}"
    adapter = FakeAdapter()
    adapter.thread_id = state.thread_id
    state.capabilities = adapter.capabilities
    manager.attach_adapter(state, adapter)
    return state, adapter


@pytest.mark.asyncio
async def test_rename_is_case_insensitively_unique_and_rolls_back() -> None:
    deck = manager()
    ghost, adapter = attach(deck, "Ghost")
    attach(deck, "Cipher")
    with pytest.raises(ValueError, match="already in use"):
        await deck.rename(ghost, "cipher")
    assert ghost.config.name == "Ghost"
    assert adapter.names == []


@pytest.mark.asyncio
async def test_disconnect_stops_and_removes_without_archiving() -> None:
    deck = manager()
    state, adapter = attach(deck, "ghost")
    await deck.disconnect(state)
    assert state not in deck.agents
    assert state.status is AgentStatus.STOPPED
    assert adapter.stopped


@pytest.mark.asyncio
async def test_retry_resumes_same_thread_and_becomes_ready() -> None:
    deck = manager()
    state, old = attach(deck, "ghost")
    state.status = AgentStatus.ERROR
    await deck.retry(state)
    assert old.stopped
    assert state.thread_id == "thread-ghost"
    assert state.status is AgentStatus.READY
    assert state.recovery_attempts == 1


@pytest.mark.asyncio
async def test_retry_recreates_the_agents_original_provider_adapter() -> None:
    created: list[FakeAdapter] = []

    def new_kiro_adapter() -> FakeAdapter:
        adapter = FakeAdapter()
        adapter.model_provider = "kiro"
        created.append(adapter)
        return adapter

    deck = AgentManager(
        lambda state, event: None,
        adapter_factory=FakeAdapter,
        adapter_factories={"kiro": new_kiro_adapter},
    )
    state = deck.register("wintermute", Path("/tmp"), provider="kiro")
    state.thread_id = "kiro-session"
    state.status = AgentStatus.ERROR
    state.capabilities = AgentCapabilities(load_session=True)

    await deck.retry(state)

    assert len(created) == 1
    assert state.config.provider == "kiro"
    assert state.model_provider == "kiro"
    assert created[0].thread_id == "kiro-session"
    await deck.shutdown()


@pytest.mark.asyncio
async def test_unsupported_lifecycle_actions_fail_before_transport_calls() -> None:
    deck = manager()
    state, _ = attach(deck, "limited")
    state.capabilities = AgentCapabilities(interrupt=False, approvals=False)

    with pytest.raises(ValueError, match="persistent rename"):
        await deck.rename(state, "other")
    with pytest.raises(ValueError, match="session restore"):
        await deck.retry(state)
    with pytest.raises(ValueError, match="archiving"):
        await deck.archive(state)
    with pytest.raises(ValueError, match="interruption"):
        await deck.interrupt(state)


@pytest.mark.asyncio
async def test_dispatch_preserves_mixed_runtime_identity() -> None:
    deck = manager()
    codex, _ = attach(deck, "ghost")
    kiro, _ = attach(deck, "molly")
    kiro.config.provider = "kiro"
    kiro.model_provider = "kiro"

    result = await deck.dispatch([codex, kiro], "status")

    assert result == {"ghost": None, "molly": None}
    assert codex.config.provider == "codex"
    assert kiro.config.provider == "kiro"


@pytest.mark.asyncio
async def test_dispatch_partial_failure_marks_only_failed_target() -> None:
    deck = manager()
    first, _ = attach(deck, "one")
    second, failed = attach(deck, "two")
    failed.fail_send = True
    result = await deck.dispatch([first, second], "scan")
    assert result == {"one": None, "two": "radio failure"}
    assert first.status is AgentStatus.PROCESSING
    assert second.status is AgentStatus.ERROR
    assert [entry.text for entry in first.transcript] == ["scan"]
    assert [entry.text for entry in second.transcript] == ["scan"]


@pytest.mark.asyncio
async def test_dispatch_rejects_busy_target_before_any_send() -> None:
    deck = manager()
    first, _ = attach(deck, "one")
    second, _ = attach(deck, "two")
    second.status = AgentStatus.EXECUTING
    with pytest.raises(ValueError, match=r"two \(EXECUTING\)"):
        await deck.dispatch([first, second], "scan")
    assert first.transcript == []


@pytest.mark.asyncio
async def test_failed_send_rolls_back_prompt_and_enters_recoverable_error() -> None:
    deck = manager()
    state, adapter = attach(deck, "ghost")
    adapter.fail_send = True

    with pytest.raises(RuntimeError, match="radio failure"):
        await deck.send(state, "unaccepted prompt")

    assert state.transcript == []
    assert state.status is AgentStatus.ERROR
    assert state.current_activity == "transmission failed"
    assert state.error_message == "radio failure"


@pytest.mark.asyncio
async def test_approval_is_owned_by_agent_until_answered() -> None:
    deck = manager()
    state, adapter = attach(deck, "ghost")
    adapter.queue.append(
        AgentEvent(
            "approval",
            request_id=42,
            method="item/fileChange/requestApproval",
            params={"grantRoot": "/tmp"},
        )
    )
    await deck._pump(state, adapter)
    assert state.status is AgentStatus.FIREWALL_HOLD
    assert state.current_activity == "ICE authorization required"
    assert [approval.request_id for approval in state.pending_approvals] == [42]

    await deck.respond_approval(state, 42, "accept")
    assert adapter.approvals == [(42, "accept")]
    assert state.pending_approvals == []
    assert state.status is AgentStatus.PROCESSING


@pytest.mark.asyncio
async def test_distinct_agent_message_ids_create_distinct_transcript_entries() -> None:
    deck = manager()
    state, adapter = attach(deck, "ghost")
    adapter.queue.extend(
        [
            AgentEvent("assistant_delta", "I will review it.", message_id="message-1"),
            AgentEvent("assistant_delta", " More soon.", message_id="message-1"),
            AgentEvent("assistant_delta", "I reviewed it.", message_id="message-2"),
        ]
    )

    await deck._pump(state, adapter)

    assert [(entry.text, entry.source_id) for entry in state.transcript] == [
        ("I will review it. More soon.", "message-1"),
        ("I reviewed it.", "message-2"),
    ]


@pytest.mark.asyncio
async def test_acp_replay_roles_reconstruct_transcript_boundaries() -> None:
    deck = manager()
    state, adapter = attach(deck, "wintermute")
    adapter.queue.extend(
        [
            AgentEvent("user_replay", "First prompt"),
            AgentEvent("assistant_delta", "First response"),
            AgentEvent("user_replay", "Second prompt"),
            AgentEvent("assistant_delta", "Second response"),
        ]
    )

    await deck._pump(state, adapter)

    assert [(entry.role, entry.text) for entry in state.transcript] == [
        ("user", "First prompt"),
        ("assistant", "First response"),
        ("user", "Second prompt"),
        ("assistant", "Second response"),
    ]
