"""Application coordination for workflow inspection and safe continuity."""

from __future__ import annotations

from pathlib import Path

from textual import work

from ..domain import (
    AgentState,
    DispatchRun,
    DispatchTarget,
    ThreadSummary,
    TranscriptEntry,
    current_time,
)
from ..session_store import SessionReference
from .common import ConfirmScreen
from .conversation import ConversationView
from .workflows import QueueScreen, ResultsScreen, SearchPicker, TranscriptSearch


class WorkflowActions:
    def _save_metadata(self) -> None:
        if not self._persist_preferences:
            return
        self.session_store.dispatches = self.manager.dispatch_runs
        try:
            self.session_store.save()
        except OSError:
            if self.screen_stack:
                self.notify("Could not save workspace/session metadata", severity="warning")

    def _remember_agent(self, state: AgentState) -> None:
        self._metadata_reset = False
        self.session_store.remember(state, sessions=self.deck_config.remember_sessions)
        self._save_metadata()

    def action_follow_output(self) -> None:
        state = self.active_agent()
        if state:
            state.follow_output = not state.follow_output
            self.notify("Following output" if state.follow_output else "Reading position held")
            self._render_active()

    def action_search_transcript(self) -> None:
        self.search_transcript("")

    def search_transcript(self, query: str) -> None:
        state = self.active_agent()
        entries = list(state.transcript if state else self._system_transcript)
        self.push_screen(
            TranscriptSearch(entries, query),
            lambda index: self._search_result(state, entries, index),
        )

    def _search_result(
        self, state: AgentState | None, entries: list[TranscriptEntry], index: int | None
    ) -> None:
        if index is None:
            return
        if state and state not in self.manager.agents:
            self.notify("This agent is disconnected", severity="warning")
            return
        if state:
            self._switch_result(state)
            state.follow_output = False
        self.run_worker(
            self._show_search_result(state, entries[index]), group="search-reveal", exclusive=True
        )

    async def _show_search_result(self, state: AgentState | None, entry: TranscriptEntry) -> None:
        await self._switch_module("agents")
        self.call_after_refresh(lambda: self._reveal_entry(state, entry))

    def _reveal_entry(self, state: AgentState | None, entry: TranscriptEntry) -> None:
        if self.active_agent() is not state:
            return
        view = self.screen_stack[0].query_one("#conversation", ConversationView)
        for message in view.query("TerminalMessage"):
            if message.entry is entry:
                view.scroll_to_widget(message, animate=False)
                break

    def action_queue_editor(self) -> None:
        if self.active_agent():
            self.push_screen(
                QueueScreen(self.manager, self.active_agent()), lambda _: self._refresh_all()
            )
        else:
            self.notify("No active uplink", severity="warning")

    def action_dispatch_results(self) -> None:
        self.push_screen(ResultsScreen(lambda: self.manager.dispatch_runs), self._result_action)

    def _result_action(self, result: tuple[str, DispatchRun, DispatchTarget] | None) -> None:
        if not result:
            return
        action, run, target = result
        if action == "retry":
            self.push_screen(
                ConfirmScreen(
                    "RETRY FAILED TARGET",
                    f"Resubmit dispatch {run.id[:8]} to {target.callsign}?\n"
                    "Other targets will not be repeated. Uncertain deliveries must be reviewed first.",
                ),
                lambda confirmed: self._retry_result(run, target) if confirmed else None,
            )
            return
        state = next(
            (agent for agent in self.manager.agents if str(agent.config.id) == target.agent_id),
            None,
        )
        if state:
            self._switch_result(state)
        else:
            self.notify("Target is no longer open; use /sessions or /restore", severity="warning")

    @work(exclusive=False)
    async def _retry_result(self, run: DispatchRun, target: DispatchTarget) -> None:
        try:
            await self.manager.retry_dispatch(run, target)
        except (ValueError, LookupError) as exc:
            self.notify(str(exc), severity="error")
        self._save_metadata()
        self._refresh_all()

    def show_recent_workspaces(self) -> None:
        paths = list(self.session_store.workspaces)
        self.push_screen(
            SearchPicker(
                "RECENT WORKSPACES // ENTER SETS NEW UPLINK DEFAULT", [str(path) for path in paths]
            ),
            lambda index: self._recent_result(paths[index]) if index is not None else None,
        )

    def _recent_result(self, path: Path) -> None:
        if not path.is_dir():
            self.notify("Workspace no longer exists", severity="error")
            return
        self.deck_config.workspace_root = path
        self._save_preferences()
        self.notify(f"New uplink workspace: {path}")

    def _save_preferences(self) -> None:
        if self._persist_preferences:
            try:
                self.config_store.save(self.deck_config)
            except OSError:
                self.notify("Could not save preferences", severity="warning")

    def session_command(self, args: list[str]) -> None:
        if args == ["on"] or args == ["off"]:
            self._metadata_reset = False
            self.deck_config.remember_sessions = args == ["on"]
            if not self.deck_config.remember_sessions:
                self.session_store.sessions.clear()
            for state in self.manager.agents:
                self.session_store.remember(state, sessions=self.deck_config.remember_sessions)
            self._save_preferences()
            self._save_metadata()
            self.notify(
                "Session references " + ("enabled" if args == ["on"] else "disabled and cleared")
            )
        elif args == ["reset"]:
            self.push_screen(
                ConfirmScreen(
                    "RESET SAVED METADATA",
                    "Clear recent workspaces, session references and dispatch metadata?\n"
                    "Open agents and conversations remain available.",
                ),
                self._reset_metadata,
            )
        elif args:
            self._write_local("usage: /sessions [on|off|reset]")
        else:
            references = list(self.session_store.sessions)
            self.push_screen(
                SearchPicker(
                    "SAVED SESSIONS // "
                    + ("ENABLED" if self.deck_config.remember_sessions else "DISABLED"),
                    [f"{row.callsign} [{row.provider}]\n{row.workspace}" for row in references],
                ),
                lambda index: (
                    self._resume_reference(references[index]) if index is not None else None
                ),
            )

    def _reset_metadata(self, confirmed: bool) -> None:
        if confirmed:
            self._metadata_reset = True
            self.session_store.workspaces.clear()
            self.session_store.sessions.clear()
            self.manager.dispatch_runs.clear()
            self._save_metadata()

    @work(exclusive=False)
    async def _resume_reference(self, reference: SessionReference) -> None:
        existing = next(
            (
                state
                for state in self.manager.agents
                if state.thread_id == reference.thread_id
                and state.config.provider == reference.provider
            ),
            None,
        )
        if existing:
            self._switch_result(existing)
            return
        if not reference.workspace.is_dir():
            self.notify("Workspace no longer exists", severity="error")
            return
        summary = ThreadSummary(
            reference.thread_id,
            reference.callsign,
            "saved",
            reference.workspace,
            "",
            current_time(),
            provider=reference.provider,
        )
        try:
            state = await self.manager.restore(summary, native_agent=reference.native_agent)
        except Exception as exc:  # noqa: BLE001 - show a per-session recovery failure
            self.notify(
                f"{reference.provider}: session restore failed ({type(exc).__name__})",
                severity="error",
            )
            failed = next(
                (a for a in self.manager.agents if a.thread_id == reference.thread_id), None
            )
            if failed:
                await self.present_agent(failed)
        else:
            await self.present_agent(state)
            self._remember_agent(state)

    def preferences_command(self, args: list[str]) -> None:
        if not args:
            config = self.deck_config
            self._write_local(
                f"PREFERENCES\nRuntime: {config.default_runtime}\nWorkspace: {config.workspace_root or Path.cwd()}\n"
                f"Boot: {config.show_boot}\nDensity: {config.density}\n"
                f"Remember sessions: {config.remember_sessions}\n"
                "Use /recent to select a workspace; /sessions on|off to change retention."
            )
        elif args == ["reset"]:
            self.push_screen(
                ConfirmScreen(
                    "RESET PREFERENCES",
                    "Reset boot, density, runtime, workspace and session retention?\n"
                    "Custom runtimes, journal files, modules, and themes remain installed.",
                ),
                self._reset_preferences,
            )
        else:
            self._write_local("usage: /preferences [reset]")

    def _reset_preferences(self, confirmed: bool) -> None:
        if confirmed:
            self.deck_config.workspace_root = None
            self.deck_config.default_runtime = "codex"
            self.deck_config.show_boot = True
            self.deck_config.remember_sessions = False
            self.session_store.sessions.clear()
            self._apply_density("standard")
            self._save_preferences()
            self._save_metadata()
