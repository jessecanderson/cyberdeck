import asyncio
import json
from datetime import date, timedelta

import pytest
from textual.widgets import Input, Static, TextArea

from cyberdeck.app import CyberdeckApp
from cyberdeck.config import ConfigStore, DeckConfig
from cyberdeck.domain import (
    AgentCapabilities,
    AgentConfig,
    AgentState,
    AgentStatus,
    DispatchRun,
    DispatchTarget,
    HistoryPage,
    OperationEntry,
    OperationState,
    TranscriptEntry,
)
from cyberdeck.journal import JournalConflictError, JournalStore
from cyberdeck.manager import AgentManager
from cyberdeck.providers import AgentEvent
from cyberdeck.runtimes import capability_summary
from cyberdeck.session_store import SessionStore
from cyberdeck.ui.conversation import ConversationView, OperationsView
from cyberdeck.ui.workflows import QueueScreen, ResultsScreen, SearchPicker


class Adapter:
    thread_id = "test-session"
    model = "test"
    model_provider = "test"
    capabilities = AgentCapabilities(load_session=True)

    def __init__(self, failure=False):
        self.incoming = asyncio.Queue()
        self.sent = []
        self.failure = failure

    async def start(self, *_args):
        pass

    async def events(self):
        while True:
            yield await self.incoming.get()

    async def send(self, text):
        self.sent.append(text)
        if self.failure:
            raise RuntimeError("fake send failure")

    async def stop(self):
        pass

    async def resume_thread(self, thread_id, _path):
        self.thread_id = thread_id
        return HistoryPage()


async def settle():
    for _ in range(10):
        await asyncio.sleep(0)


def test_journal_conflict_preserves_external_file(tmp_path):
    store = JournalStore(tmp_path)
    day = date(2026, 10, 7)
    store.write(day, "original")
    expected = store.read(day)
    store.write(day, "external edit")
    with pytest.raises(JournalConflictError):
        store.write(day, "editor text", expected=expected)
    assert store.read(day) == "external edit"
    assert list(tmp_path.iterdir()) == [store.path_for(day)]


@pytest.mark.asyncio
async def test_failed_save_blocks_navigation_module_switch_and_quit(tmp_path):
    store = JournalStore(tmp_path / "journal")
    app = CyberdeckApp(skip_boot=True, journal_store=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._switch_module("journal")
        editor = app.query_one("#journal-editor", TextArea)
        original_day = app._journal_day
        store.write(original_day, "external change")
        editor.load_text("unsaved local edit")
        await pilot.pause()
        assert not app._load_journal_day(original_day - timedelta(days=1))
        await app._switch_module("agents")
        app.action_quit()
        assert app.active_module_id == "journal"
        assert app._journal_day == original_day
        assert editor.text == "unsaved local edit"
        assert app._journal_dirty
        assert "UNSAVED" in str(app.query_one("#journal-status", Static).render())
        assert store.read(original_day) == "external change"


@pytest.mark.asyncio
async def test_dated_command_saves_previous_day_and_quick_entry_preserves_editor(tmp_path):
    store = JournalStore(tmp_path / "journal")
    app = CyberdeckApp(skip_boot=True, journal_store=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._switch_module("journal")
        previous = app._journal_day
        app.query_one("#journal-editor", TextArea).load_text("local draft")
        await pilot.pause()
        await app.execute_command("/journal 2026-01-01")
        await pilot.pause()
        assert store.read(previous) == "local draft"
        assert app._journal_day == date(2026, 1, 1)
        app.query_one("#journal-editor", TextArea).load_text("editor draft")
        await pilot.pause()
        await app._handle_journal_prompt("quick entry")
        assert "editor draft" in store.read(app._journal_day)
        assert "quick entry" in store.read(app._journal_day)


def test_metadata_excludes_private_payloads_and_handles_corruption(tmp_path):
    store = SessionStore(tmp_path / "state.json")
    state = AgentState(AgentConfig("ghost", tmp_path), thread_id="thread")
    state.capabilities = AgentCapabilities(load_session=True)
    state.prompt_draft = "SECRET DRAFT"
    state.queued_prompts = ["SECRET QUEUE"]
    state.transcript = [TranscriptEntry("assistant", "SECRET TRANSCRIPT")]
    store.remember(state, sessions=False)
    assert not store.sessions
    store.remember(state, sessions=True)
    target = DispatchTarget(str(state.config.id), "ghost", "codex", error="SECRET ERROR")
    store.dispatches = [DispatchRun("SECRET PROMPT", [target])]
    store.save()
    assert "SECRET" not in store.path.read_text()
    loaded = SessionStore(store.path)
    assert loaded.sessions == store.sessions
    assert loaded.dispatches[0].prompt == ""
    assert loaded.dispatches[0].targets[0].status == "unknown"
    assert loaded.dispatches[0].targets[0].error is None
    store.path.write_text('{"schema_version": 99}')
    invalid = SessionStore(store.path)
    assert invalid.errors and not invalid.sessions
    invalid.reset()
    assert not SessionStore(store.path).errors


def test_metadata_is_bounded_and_forgets_archived_reference(tmp_path):
    store = SessionStore(tmp_path / "state.json")
    for i in range(60):
        state = AgentState(
            AgentConfig(f"agent-{i}", tmp_path / str(i)),
            thread_id=str(i),
            capabilities=AgentCapabilities(load_session=True),
        )
        store.remember(state, sessions=True)
    assert len(store.workspaces) == 20
    assert len(store.sessions) == 50
    store.forget(state)
    assert all(row.thread_id != "59" for row in store.sessions)
    store.save()
    assert json.loads(store.path.read_text())["schema_version"] == 1


def test_remember_sessions_configuration_round_trip(tmp_path):
    store = ConfigStore(tmp_path / "config.toml")
    store.save(DeckConfig(remember_sessions=True))
    assert store.load().remember_sessions


@pytest.mark.asyncio
async def test_dispatch_records_independent_completions_and_partial_failure(tmp_path):
    adapters = [Adapter(), Adapter(failure=True)]
    deck = AgentManager(lambda *_: None, adapter_factory=lambda: adapters.pop(0))
    one = await deck.spawn("one", tmp_path)
    two = await deck.spawn("two", tmp_path)
    a = deck.adapter_for(one)
    result = await deck.dispatch([one, two], "task")
    run = deck.dispatch_runs[0]
    assert result == {"one": None, "two": "fake send failure"}
    assert [target.status for target in run.targets] == ["running", "failed"]
    assert not run.complete
    await a.incoming.put(AgentEvent("status", "ready"))
    await settle()
    assert run.complete
    assert run.targets[0].status == "completed"
    assert run.targets[1].error == "fake send failure"
    with pytest.raises(ValueError, match="uncertain"):
        await deck.retry_dispatch(run, run.targets[1])
    await deck.shutdown()


@pytest.mark.asyncio
async def test_dispatch_completion_before_send_returns_and_retry_is_target_only(tmp_path):
    deck = AgentManager(lambda *_: None)
    one = deck.register("one", tmp_path, status=AgentStatus.READY)
    two = deck.register("two", tmp_path, status=AgentStatus.READY)

    class Immediate(Adapter):
        async def send(self, text):
            self.sent.append(text)
            deck.update_dispatch(one, AgentEvent("status", "ready"))

    a, b = Immediate(), Adapter()
    deck.attach_adapter(one, a)
    deck.attach_adapter(two, b)
    await deck.dispatch([one, two], "task")
    run = deck.dispatch_runs[0]
    assert run.targets[0].status == "completed"
    deck.update_dispatch(two, AgentEvent("error", "failed turn"))
    two.status = AgentStatus.READY
    await deck.retry_dispatch(run, run.targets[1])
    assert a.sent == ["task"]
    assert b.sent == ["task", "task"]
    assert len(deck.dispatch_runs[-1].targets) == 1


@pytest.mark.asyncio
async def test_queue_editor_pauses_reserved_input_without_duplication(tmp_path):
    deck = AgentManager(lambda *_: None)
    state = deck.register("one", tmp_path, status=AgentStatus.READY)
    adapter = Adapter()
    deck.attach_adapter(state, adapter)
    state.queue_paused = True
    state.queued_prompts = ["first", "second"]
    deck.resume_queue(state)
    deck.pause_queue(state)
    await settle()
    assert state.queued_prompts == ["first", "second"]
    assert adapter.sent == []
    deck.edit_queue(state, 0, "edited\ninput")
    assert deck.move_queued(state, 0, 1) == 1
    assert state.queued_prompts == ["second", "edited\ninput"]
    deck.remove_queued(state, 0)
    state.uncertain_prompts = ["uncertain"]
    deck.resume_queue(state)
    await settle()
    assert adapter.sent == ["edited\ninput"]
    assert state.uncertain_prompts == ["uncertain"]
    await deck.shutdown()


@pytest.mark.asyncio
async def test_follow_off_keeps_scroll_and_refresh_reuses_widgets(tmp_path):
    app = CyberdeckApp(skip_boot=True)
    async with app.run_test(size=(100, 30)) as pilot:
        state = app.manager.register("one", tmp_path, status=AgentStatus.READY)
        state.transcript = [TranscriptEntry("assistant", f"message {i}\n" * 6) for i in range(30)]
        await app.present_agent(state)
        await pilot.pause()
        await app.execute_command("/follow off")
        view = app.query_one(ConversationView)
        view.scroll_to(y=10, animate=False)
        await pilot.pause()
        first = next(iter(view.query("TerminalMessage")))
        before = view.scroll_y
        state.transcript[-1].text += "streamed text"
        app.receive_agent_event(state, AgentEvent("assistant_delta", "streamed text"))
        await pilot.pause()
        assert view.scroll_y == before
        assert next(iter(view.query("TerminalMessage"))) is first
        await app.execute_command("/follow on")
        await pilot.pause()
        assert view.scroll_y == view.max_scroll_y


@pytest.mark.asyncio
async def test_search_arrow_navigation_and_jump_holds_position(tmp_path):
    app = CyberdeckApp(skip_boot=True)
    async with app.run_test(size=(100, 30)) as pilot:
        state = app.manager.register("one", tmp_path, status=AgentStatus.READY)
        state.transcript = [
            TranscriptEntry("assistant", f"entry {i}\nneedle\n" * 4) for i in range(25)
        ]
        await app.present_agent(state)
        await pilot.pause()
        await app.execute_command("/search needle")
        await pilot.pause()
        assert app.screen.query_one(Input).has_focus
        await pilot.press("down")
        assert app.screen.query_one("#workflow-list").index == 1
        await pilot.press("enter")
        await pilot.pause()
        assert not state.follow_output
        assert (
            app.query_one(ConversationView).scroll_y < app.query_one(ConversationView).max_scroll_y
        )


@pytest.mark.asyncio
async def test_operation_filter_selection_maps_to_filtered_row(tmp_path):
    app = CyberdeckApp(skip_boot=True)
    async with app.run_test() as pilot:
        state = app.manager.register("one", tmp_path, status=AgentStatus.READY)
        state.operations = [
            OperationEntry("commandExecution", "success", OperationState.SUCCEEDED),
            OperationEntry("fileChange", "failed file", OperationState.FAILED),
        ]
        await app.present_agent(state)
        await app.execute_command("/operations failed")
        await pilot.pause()
        view = app.query_one(OperationsView)
        assert view.shown_operations == [state.operations[1]]
        view.focus()
        view.index = 0
        await pilot.press("enter")
        assert app.screen.operation is state.operations[1]


@pytest.mark.asyncio
async def test_queue_modal_edits_only_pending_and_keeps_uncertain_read_only(tmp_path):
    app = CyberdeckApp(skip_boot=True)
    async with app.run_test() as pilot:
        state = app.manager.register("one", tmp_path, status=AgentStatus.READY)
        state.queued_prompts = ["pending"]
        state.uncertain_prompts = ["uncertain"]
        await app.present_agent(state)
        await app.execute_command("/queue edit")
        await pilot.pause()
        assert isinstance(app.screen, QueueScreen) and state.queue_paused
        await pilot.press("enter")
        app.screen.query_one(TextArea).load_text("updated")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert state.queued_prompts == ["updated"]
        assert state.uncertain_prompts == ["uncertain"]
        await pilot.press("escape")
        assert state.queue_paused


@pytest.mark.asyncio
async def test_recent_and_sessions_opt_in_are_restart_safe(tmp_path):
    config = ConfigStore(tmp_path / "config.toml")
    app = CyberdeckApp(skip_boot=True, config_store=config)
    async with app.run_test() as pilot:
        state = app.manager.register("one", tmp_path, status=AgentStatus.READY)
        state.thread_id = "session-ref"
        state.capabilities = AgentCapabilities(load_session=True)
        await app.present_agent(state)
        await app.execute_command("/sessions on")
        assert config.load().remember_sessions
        await app.execute_command("/recent")
        await pilot.pause()
        assert isinstance(app.screen, SearchPicker)
        await pilot.press("enter")
        assert config.load().workspace_root == tmp_path
    loaded = SessionStore(config.path.with_suffix(".state.json"))
    assert loaded.sessions[0].thread_id == "session-ref"
    second = CyberdeckApp(skip_boot=True, config_store=config)
    async with second.run_test() as pilot:
        assert not second.manager.agents
        await second.execute_command("/sessions off")
        assert not SessionStore(loaded.path).sessions


@pytest.mark.asyncio
async def test_results_inspection_preserves_active_agent(tmp_path):
    app = CyberdeckApp(skip_boot=True)
    async with app.run_test() as pilot:
        state = app.manager.register("one", tmp_path, status=AgentStatus.READY)
        await app.present_agent(state)
        target = DispatchTarget(str(state.config.id), "one", "codex", "running")
        app.manager.dispatch_runs.append(DispatchRun("task", [target]))
        await app.execute_command("/results")
        await pilot.pause()
        assert isinstance(app.screen, ResultsScreen)
        target.status = "completed"
        app.screen._refresh()
        await pilot.pause()
        assert app.active_agent() is state
        await pilot.press("enter")
        assert app.active_agent() is state


def test_capabilities_are_actual_negotiated_values():
    assert "steering" not in capability_summary(AgentCapabilities(steering=False))
    assert "steering" in capability_summary(AgentCapabilities(steering=True))


@pytest.mark.asyncio
async def test_permission_failure_preserves_editor_until_retry(tmp_path):
    class FailingStore(JournalStore):
        fail = True

        def write(self, day, text, *, expected=None):
            if self.fail:
                raise PermissionError("test write denied")
            super().write(day, text, expected=expected)

    store = FailingStore(tmp_path / "journal")
    app = CyberdeckApp(skip_boot=True, journal_store=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._switch_module("journal")
        day = app._journal_day
        editor = app.query_one("#journal-editor", TextArea)
        editor.load_text("recoverable edits")
        await pilot.pause()
        await app.execute_command("/journal 2026-01-01")
        assert app._journal_day == day
        assert editor.text == "recoverable edits"
        store.fail = False
        await app.execute_command("/journal 2026-01-01")
        await pilot.pause()
        assert store.read(day) == "recoverable edits"
        assert app._journal_day == date(2026, 1, 1)


@pytest.mark.asyncio
async def test_queue_modal_reorder_uses_modal_binding_instead_of_switching_agents(tmp_path):
    app = CyberdeckApp(skip_boot=True)
    async with app.run_test() as pilot:
        state = app.manager.register("one", tmp_path, status=AgentStatus.READY)
        state.queued_prompts = ["first", "second"]
        await app.present_agent(state)
        await app.execute_command("/queue edit")
        await pilot.pause()
        await pilot.press("ctrl+down")
        await pilot.pause()
        assert state.queued_prompts == ["second", "first"]
        assert app.active_agent() is state
        await pilot.press("ctrl+d")
        assert state.queued_prompts == ["second"]
        await pilot.press("escape")


@pytest.mark.asyncio
async def test_search_normalizes_unicode_and_does_not_match_other_agent(tmp_path):
    app = CyberdeckApp(skip_boot=True)
    async with app.run_test() as pilot:
        state = app.manager.register("one", tmp_path, status=AgentStatus.READY)
        state.transcript = [
            TranscriptEntry("assistant", "caf\u0065\u0301"),
            TranscriptEntry("assistant", "unrelated"),
        ]
        other = app.manager.register("two", tmp_path, status=AgentStatus.READY)
        other.transcript = [TranscriptEntry("assistant", "café")]
        await app.present_agent(state)
        await app.execute_command("/search CAFÉ")
        await pilot.pause()
        assert app.screen.matches == [0]
        await pilot.press("escape")


@pytest.mark.asyncio
async def test_saved_session_restores_native_identity_without_auto_connect(tmp_path):
    config = ConfigStore(tmp_path / "config.toml")
    config.save(DeckConfig(remember_sessions=True))
    saved = SessionStore(config.path.with_suffix(".state.json"))
    state = AgentState(
        AgentConfig("ghost", tmp_path, provider="kiro", native_agent="reviewer"),
        thread_id="saved-id",
        capabilities=AgentCapabilities(load_session=True),
    )
    saved.remember(state, sessions=True)
    saved.save()
    adapter = Adapter()
    manager = AgentManager(lambda *_: None, adapter_factories={"kiro": lambda: adapter})
    app = CyberdeckApp(skip_boot=True, config_store=config, manager=manager)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert not manager.agents
        await app.execute_command("/sessions")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        restored = app.active_agent()
        assert restored.thread_id == "saved-id"
        assert restored.config.provider == "kiro"
        assert restored.config.native_agent == "reviewer"
        assert restored.status is AgentStatus.READY


@pytest.mark.asyncio
async def test_results_retry_is_confirmed_and_rejects_uncertainty(tmp_path):
    app = CyberdeckApp(skip_boot=True)
    async with app.run_test() as pilot:
        state = app.manager.register("one", tmp_path, status=AgentStatus.READY)
        state.uncertain_prompts = ["maybe accepted"]
        await app.present_agent(state)
        target = DispatchTarget(str(state.config.id), "one", "codex", "failed")
        app.manager.dispatch_runs.append(DispatchRun("task", [target]))
        await app.execute_command("/results")
        await pilot.pause()
        await pilot.press("ctrl+r")
        assert app.screen.title_text == "RETRY FAILED TARGET"
        await pilot.press("y")
        await pilot.pause()
        assert len(app.manager.dispatch_runs) == 1
        assert state.uncertain_prompts == ["maybe accepted"]


@pytest.mark.asyncio
async def test_disconnected_dispatch_finishes_only_affected_target(tmp_path):
    deck = AgentManager(lambda *_: None)
    one = deck.register("one", tmp_path, status=AgentStatus.READY)
    two = deck.register("two", tmp_path, status=AgentStatus.READY)
    deck.attach_adapter(one, Adapter())
    deck.attach_adapter(two, Adapter())
    await deck.dispatch([one, two], "task")
    await deck.disconnect(one)
    assert [target.status for target in deck.dispatch_runs[0].targets] == ["failed", "running"]
    await deck.shutdown()


@pytest.mark.asyncio
async def test_reading_position_restores_after_switching_agents(tmp_path):
    app = CyberdeckApp(skip_boot=True)
    async with app.run_test(size=(100, 30)) as pilot:
        one = app.manager.register("one", tmp_path, status=AgentStatus.READY)
        two = app.manager.register("two", tmp_path, status=AgentStatus.READY)
        for state in (one, two):
            state.transcript = [TranscriptEntry("assistant", "line\n" * 6) for _ in range(30)]
        await app.present_agent(one)
        await app.present_agent(two, select=False)
        await pilot.pause()
        await app.execute_command("/follow off")
        view = app.query_one(ConversationView)
        view.scroll_to(y=10, animate=False)
        await pilot.pause()
        app._switch_result(two)
        await pilot.pause()
        app._switch_result(one)
        await pilot.pause()
        assert view.scroll_y == 10


@pytest.mark.asyncio
async def test_workflow_modals_fit_small_terminal(tmp_path):
    app = CyberdeckApp(skip_boot=True)
    async with app.run_test(size=(80, 24)) as pilot:
        state = app.manager.register("one", tmp_path, status=AgentStatus.READY)
        state.queued_prompts = ["pending"]
        state.transcript = [TranscriptEntry("assistant", "searchable")]
        await app.present_agent(state)
        for command in ("/queue edit", "/results", "/search", "/recent", "/sessions"):
            await app.execute_command(command)
            await pilot.pause()
            dialog = app.screen.query_one(".workflow-dialog")
            help_widget = app.screen.query_one(".modal-help")
            assert dialog.region.width <= 80
            assert dialog.region.height <= 24
            assert help_widget.region.bottom <= 24
            await pilot.press("escape")


@pytest.mark.asyncio
async def test_metadata_reset_stays_empty_after_quit_without_new_activity(tmp_path):
    config = ConfigStore(tmp_path / "config.toml")
    config.save(DeckConfig(remember_sessions=True))
    app = CyberdeckApp(skip_boot=True, config_store=config)
    async with app.run_test() as pilot:
        state = app.manager.register("one", tmp_path, status=AgentStatus.READY)
        state.thread_id = "old-reference"
        state.capabilities = AgentCapabilities(load_session=True)
        await app.present_agent(state)
        await app.execute_command("/sessions on")
        await app.execute_command("/sessions reset")
        await pilot.press("y")
    saved = SessionStore(config.path.with_suffix(".state.json"))
    assert not saved.workspaces and not saved.sessions and not saved.dispatches


@pytest.mark.asyncio
async def test_journal_reload_requires_confirmation_after_conflict(tmp_path):
    store = JournalStore(tmp_path / "journal")
    app = CyberdeckApp(skip_boot=True, journal_store=store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._switch_module("journal")
        day = app._journal_day
        store.write(day, "external version")
        editor = app.query_one("#journal-editor", TextArea)
        editor.load_text("unsaved buffer")
        await pilot.pause()
        await app.execute_command("/journal reload")
        await pilot.press("n")
        assert editor.text == "unsaved buffer" and app._journal_dirty
        await app.execute_command("/journal reload")
        await pilot.press("y")
        await pilot.pause()
        assert editor.text == "external version" and not app._journal_dirty
        await app._switch_module("agents")
        assert app.active_module_id == "agents"
