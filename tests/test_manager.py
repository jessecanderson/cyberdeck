from pathlib import Path

import pytest

from cyberdeck.domain import AgentStatus, HistoryPage
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

    async def events(self):
        while self.queue:
            yield self.queue.pop(0)

    async def send(self, prompt):
        if self.fail_send:
            raise RuntimeError("radio failure")

    async def set_thread_name(self, thread_id, name): self.names.append((thread_id, name))
    async def interrupt_turn(self): pass
    async def archive_thread(self): pass
    async def respond_approval(self, request_id, decision):
        self.approvals.append((request_id, decision))
    async def stop(self): self.stopped = True
    async def resume_thread(self, thread_id, cwd):
        self.thread_id = thread_id
        return HistoryPage()


def manager() -> AgentManager:
    return AgentManager(lambda state, event: None, adapter_factory=FakeAdapter)


def attach(manager, name):
    state = manager.register(name, Path("/tmp"), status=AgentStatus.READY)
    state.thread_id = f"thread-{name}"
    adapter = FakeAdapter()
    adapter.thread_id = state.thread_id
    manager._adapters[str(state.config.id)] = adapter
    return state, adapter


@pytest.mark.asyncio
async def test_rename_is_case_insensitively_unique_and_rolls_back() -> None:
    deck = manager(); ghost, adapter = attach(deck, "Ghost"); attach(deck, "Cipher")
    with pytest.raises(ValueError, match="already in use"):
        await deck.rename(ghost, "cipher")
    assert ghost.config.name == "Ghost"
    assert adapter.names == []


@pytest.mark.asyncio
async def test_disconnect_stops_and_removes_without_archiving() -> None:
    deck = manager(); state, adapter = attach(deck, "ghost")
    await deck.disconnect(state)
    assert state not in deck.agents
    assert state.status is AgentStatus.STOPPED
    assert adapter.stopped


@pytest.mark.asyncio
async def test_retry_resumes_same_thread_and_becomes_ready() -> None:
    deck = manager(); state, old = attach(deck, "ghost")
    state.status = AgentStatus.ERROR
    await deck.retry(state)
    assert old.stopped
    assert state.thread_id == "thread-ghost"
    assert state.status is AgentStatus.READY
    assert state.recovery_attempts == 1


@pytest.mark.asyncio
async def test_dispatch_partial_failure_marks_only_failed_target() -> None:
    deck = manager(); first, _ = attach(deck, "one"); second, failed = attach(deck, "two")
    failed.fail_send = True
    result = await deck.dispatch([first, second], "scan")
    assert result == {"one": None, "two": "radio failure"}
    assert first.status is AgentStatus.PROCESSING
    assert second.status is AgentStatus.ERROR
    assert [entry.text for entry in first.transcript] == ["scan"]
    assert [entry.text for entry in second.transcript] == ["scan"]


@pytest.mark.asyncio
async def test_dispatch_rejects_busy_target_before_any_send() -> None:
    deck = manager(); first, _ = attach(deck, "one"); second, _ = attach(deck, "two")
    second.status = AgentStatus.EXECUTING
    with pytest.raises(ValueError, match=r"two \(EXECUTING\)"):
        await deck.dispatch([first, second], "scan")
    assert first.transcript == []


@pytest.mark.asyncio
async def test_approval_is_owned_by_agent_until_answered() -> None:
    deck = manager(); state, adapter = attach(deck, "ghost")
    adapter.queue.append(AgentEvent(
        "approval",
        request_id=42,
        method="item/fileChange/requestApproval",
        params={"grantRoot": "/tmp"},
    ))
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
    deck = manager(); state, adapter = attach(deck, "ghost")
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
