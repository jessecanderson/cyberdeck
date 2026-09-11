import asyncio
from pathlib import Path

import pytest

from cyberdeck.domain import AgentCapabilities, AgentStatus, HistoryPage
from cyberdeck.manager import AgentManager
from cyberdeck.providers import AgentEvent
from cyberdeck.providers.base import SteeringNotSent


class ConversationAdapter:
    thread_id = "same-session"
    model = "fake"
    model_provider = "fake"
    capabilities = AgentCapabilities(interrupt=True, load_session=True)

    def __init__(self):
        self.incoming = asyncio.Queue()
        self.sent = asyncio.Queue()
        self.release = asyncio.Event()
        self.cancel_called = asyncio.Event()
        self.stopped = False
        self.steered = []
        self.steer_error = None

    async def start(self, *_args):
        pass

    async def resume_thread(self, thread_id, _cwd):
        assert thread_id == self.thread_id
        return HistoryPage()

    async def events(self):
        while True:
            yield await self.incoming.get()

    async def send(self, prompt):
        await self.sent.put((self.thread_id, prompt))
        await self.release.wait()
        self.release.clear()
        await self.incoming.put(AgentEvent("status", "ready"))

    async def steer(self, prompt):
        if self.steer_error:
            raise self.steer_error
        self.steered.append(prompt)

    async def interrupt_turn(self):
        self.cancel_called.set()

    async def stop(self):
        self.stopped = True


async def connected(**kwargs):
    adapter = ConversationAdapter()
    deck = AgentManager(lambda *_: None, adapter_factory=lambda: adapter, **kwargs)
    state = await deck.spawn("ghost", Path("/tmp"))
    return deck, state, adapter


async def settled():
    # Let provider, event pump, and queued send each take their scheduled step.
    for _ in range(8):
        await asyncio.sleep(0)


async def test_fifo_continuation_uses_same_session_and_exact_text():
    deck, state, adapter = await connected()
    first = asyncio.create_task(deck.submit_prompt(state, "first"))
    assert await adapter.sent.get() == ("same-session", "first")
    for prompt in ("  second\n", "third"):
        assert await deck.submit_prompt(state, prompt) == "queued"
    adapter.release.set()
    assert await asyncio.wait_for(adapter.sent.get(), 1) == ("same-session", "  second\n")
    adapter.release.set()
    assert await asyncio.wait_for(adapter.sent.get(), 1) == ("same-session", "third")
    adapter.release.set()
    await first
    await settled()
    assert [entry.text for entry in state.transcript] == ["first", "  second\n", "third"]
    await deck.shutdown()


@pytest.mark.parametrize("status", [AgentStatus.PROCESSING, AgentStatus.FIREWALL_HOLD])
async def test_multiple_steers_do_not_start_turns_or_resolve_approval(status):
    deck, state, adapter = await connected()
    state.status = status
    state.capabilities = AgentCapabilities(steering=True)
    assert await deck.submit_prompt(state, "one") == "steered"
    assert await deck.submit_prompt(state, "two") == "steered"
    assert adapter.steered == ["one", "two"]
    assert adapter.sent.empty()
    assert state.status is status
    await deck.shutdown()


async def test_proven_unsent_steering_waits_for_completion_before_fallback():
    deck, state, adapter = await connected()
    state.status = AgentStatus.PROCESSING
    state.capabilities = AgentCapabilities(steering=True)
    adapter.steer_error = SteeringNotSent("local turn ended before write")
    assert await deck.submit_prompt(state, "follow up") == "queued"
    assert adapter.sent.empty()
    await adapter.incoming.put(AgentEvent("status", "ready"))
    assert await asyncio.wait_for(adapter.sent.get(), 1) == ("same-session", "follow up")
    assert [entry.text for entry in state.transcript] == ["follow up"]
    await deck.shutdown()


async def test_error_text_is_not_proof_of_rejection_and_never_replays():
    deck, state, adapter = await connected()
    state.status = AgentStatus.PROCESSING
    state.capabilities = AgentCapabilities(steering=True)
    adapter.steer_error = RuntimeError("no active turn; request timed out")
    with pytest.raises(RuntimeError):
        await deck.submit_prompt(state, "uncertain")
    await adapter.incoming.put(AgentEvent("status", "ready"))
    await settled()
    assert state.status is AgentStatus.ERROR
    assert state.uncertain_prompts == ["uncertain"]
    assert await deck.submit_prompt(state, "unsent") == "queued"
    with pytest.raises(ValueError, match="READY"):
        deck.resume_queue(state)
    # Simulate successful restore, which permits only the confirmed-unsent queue.
    state.status = AgentStatus.READY
    deck.resume_queue(state)
    assert await asyncio.wait_for(adapter.sent.get(), 1) == ("same-session", "unsent")
    assert state.uncertain_prompts == ["uncertain"]
    await deck.shutdown()


async def test_interrupt_waits_for_completion_and_pauses_followups():
    deck, state, adapter = await connected()
    first = asyncio.create_task(deck.submit_prompt(state, "first"))
    await adapter.sent.get()
    await deck.submit_prompt(state, "second")
    cancel = asyncio.create_task(deck.interrupt(state))
    await adapter.cancel_called.wait()
    assert state.cancellation_pending
    assert state.status is AgentStatus.PROCESSING
    await deck.interrupt(state)  # Repeated interruption is idempotent.
    await deck.submit_prompt(state, "third")
    adapter.release.set()
    await first
    await cancel
    assert state.status is AgentStatus.READY
    assert state.queue_paused and not state.cancellation_pending
    assert state.queued_prompts == ["second", "third"]
    assert adapter.sent.empty()
    deck.resume_queue(state)
    assert await adapter.sent.get() == ("same-session", "second")
    deck.clear_queue(state)
    assert state.queued_prompts == []
    await deck.shutdown()


async def test_cancellation_deadline_stops_transport_and_retains_input():
    deck, state, adapter = await connected(cancellation_timeout=0.01)
    first = asyncio.create_task(deck.submit_prompt(state, "first"))
    await adapter.sent.get()
    await deck.submit_prompt(state, "second")
    with pytest.raises(TimeoutError):
        await deck.interrupt(state)
    assert adapter.stopped
    assert first.cancelled()
    assert state.status is AgentStatus.ERROR
    assert state.queue_paused and not state.cancellation_pending
    assert state.queued_prompts == ["second"]
    assert state.uncertain_prompts == ["first"]
    await deck.shutdown()


async def test_retry_cancels_owned_sends_and_preserves_native_identity_and_queue():
    adapters = []
    identities = []

    class Registry:
        def create(self, provider, native_agent):
            identities.append((provider, native_agent))
            adapter = ConversationAdapter()
            adapters.append(adapter)
            return adapter

        ids = ("kiro",)

    deck = AgentManager(lambda *_: None, runtime_registry=Registry())
    state = await deck.spawn("ghost", Path("/tmp"), provider="kiro", native_agent="reviewer")
    first = asyncio.create_task(deck.submit_prompt(state, "first"))
    await adapters[0].sent.get()
    await deck.submit_prompt(state, "second")
    await deck.retry(state)
    assert first.cancelled()
    assert identities == [("kiro", "reviewer"), ("kiro", "reviewer")]
    assert state.queue_paused
    assert state.queued_prompts == ["second"]
    assert state.uncertain_prompts == ["first"]
    await adapters[0].incoming.put(AgentEvent("error", "stale transport"))
    await settled()
    assert state.status is AgentStatus.READY
    assert adapters[1].sent.empty()
    await deck.shutdown()


async def test_cancel_reserved_queue_before_worker_starts_retains_unsent_text():
    deck, state, _adapter = await connected()
    state.queue_paused = True
    state.queued_prompts.append("reserved")
    deck.resume_queue(state)
    await deck.retry(state)
    assert state.queued_prompts == ["reserved"]
    assert state.uncertain_prompts == []
    await deck.shutdown()


def test_recovery_requires_both_session_loading_and_thread():
    deck = AgentManager(lambda *_: None, adapter_factory=ConversationAdapter)
    state = deck.register("ghost", Path("/tmp"))
    assert "/retry" not in deck.recovery_guidance(state)
    state.capabilities = AgentCapabilities(load_session=True)
    assert "/retry" not in deck.recovery_guidance(state)
    state.thread_id = "thread"
    assert "/retry" in deck.recovery_guidance(state)


async def test_interrupt_before_reserved_send_runs_does_not_contact_provider():
    deck, state, adapter = await connected()
    state.queued_prompts.append("unsent")
    deck.resume_queue(state)
    await deck.interrupt(state)
    assert state.status is AgentStatus.READY
    assert state.queue_paused
    assert state.queued_prompts == ["unsent"]
    assert adapter.sent.empty()
    assert not adapter.cancel_called.is_set()
    await deck.shutdown()


async def test_disconnect_cancels_startup_before_it_can_resurrect_agent():
    started = asyncio.Event()

    class StartingAdapter(ConversationAdapter):
        async def start(self, *_args):
            started.set()
            await asyncio.Event().wait()

    adapter = StartingAdapter()
    deck = AgentManager(lambda *_: None, adapter_factory=lambda: adapter)
    state = deck.register("ghost", Path("/tmp"))
    connecting = asyncio.create_task(deck.connect(state))
    await started.wait()
    await deck.disconnect(state)
    assert connecting.cancelled()
    assert state.status is AgentStatus.STOPPED
    assert adapter.stopped
    assert state not in deck.agents


async def test_targeted_send_requires_ready_and_does_not_unpause_queue():
    deck, state, adapter = await connected()
    state.queue_paused = True
    state.queued_prompts.append("paused")
    sending = asyncio.create_task(deck.send(state, "explicit"))
    assert await adapter.sent.get() == ("same-session", "explicit")
    with pytest.raises(ValueError, match="READY"):
        await deck.send(state, "duplicate")
    adapter.release.set()
    await sending
    await settled()
    assert state.queue_paused
    assert state.queued_prompts == ["paused"]
    assert adapter.sent.empty()
    await deck.shutdown()


async def test_queued_connection_ready_cannot_complete_first_turn_or_drain_queue():
    release_readiness = asyncio.Event()

    class StartupEventAdapter(ConversationAdapter):
        async def events(self):
            await release_readiness.wait()
            async for event in super().events():
                yield event

        async def start(self, *_args):
            await self.incoming.put(
                AgentEvent("status", "ready", params={"connection_ready": True})
            )

    adapter = StartupEventAdapter()
    deck = AgentManager(lambda *_: None, adapter_factory=lambda: adapter)
    state = await deck.spawn("ghost", Path("/tmp"))
    # Delay the pump until a first turn and a follow-up have both been submitted.
    first = asyncio.create_task(deck.submit_prompt(state, "first"))
    await adapter.sent.get()
    await deck.submit_prompt(state, "second")
    release_readiness.set()
    await settled()
    assert state.status is AgentStatus.PROCESSING
    assert adapter.sent.empty()
    assert state.queued_prompts == ["second"]
    adapter.release.set()
    assert await asyncio.wait_for(adapter.sent.get(), 1) == ("same-session", "second")
    await first
    await deck.shutdown()


async def test_retry_cancels_compaction_so_old_completion_cannot_reset_context():
    compacting = asyncio.Event()

    class CompactAdapter(ConversationAdapter):
        capabilities = AgentCapabilities(load_session=True, context_compaction=True)

        async def compact_context(self):
            compacting.set()
            await asyncio.Event().wait()

    deck = AgentManager(lambda *_: None, adapter_factory=CompactAdapter)
    state = await deck.spawn("ghost", Path("/tmp"))
    task = asyncio.create_task(deck.compact_context(state))
    await compacting.wait()
    await deck.retry(state)
    assert task.cancelled()
    assert state.status is AgentStatus.READY
    assert state.queue_paused
    await deck.shutdown()
