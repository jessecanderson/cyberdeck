from __future__ import annotations

import argparse
import asyncio
import getpass
import platform
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from datetime import date, datetime
from importlib.metadata import version as package_version
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Input, Label, ListItem, ListView, Static, TextArea

from . import __version__
from .builtin_modules import (
    AgentsWorkspace,
    BuiltinModule,
    BuiltinModuleSpec,
    JournalWorkspace,
)
from .clipboard import ClipboardService
from .command_runtime import run_local_command
from .commands import COMMANDS_BY_NAME, command_descriptions
from .completion import complete_prompt
from .config import ConfigStore, DeckConfig, user_theme_directory
from .domain import (
    AgentState,
    AgentStatus,
    OperationEntry,
    PendingApproval,
    ThreadSummary,
    TranscriptEntry,
)
from .journal import JournalStore
from .manager import AgentManager
from .module_registry import ModuleRegistry
from .modules import (
    DeckCommand,
    DeckModule,
    ModuleContext,
    ModuleInputMode,
    ModuleManifest,
    ModuleStatus,
    validate_manifest,
)
from .providers import AgentEvent
from .runtimes import RuntimeRegistry
from .themes import DeckTheme, discover_themes, import_theme
from .ui.boot import BootScreen
from .ui.screens import (
    AboutScreen,
    AgentSwitcher,
    ApprovalMessage,
    ConfirmScreen,
    DispatchScreen,
    EmptyGrid,
    OperationDetail,
    OperativeControl,
    RestoreScreen,
    SpawnAgent,
    TerminalMessage,
    ThemeScreen,
    TranscriptSelection,
    ice_level,
)

__all__ = [
    "AboutScreen",
    "AgentSwitcher",
    "ApprovalMessage",
    "BootScreen",
    "ConfirmScreen",
    "CyberdeckApp",
    "DispatchScreen",
    "EmptyGrid",
    "OperativeControl",
    "RestoreScreen",
    "SpawnAgent",
    "ice_level",
    "main",
]


class CyberdeckApp(App[None]):
    CSS_PATH = "cyberdeck.tcss"
    TITLE = "CYBERDECK"
    BINDINGS: ClassVar = [
        ("ctrl+n", "spawn_agent", "New"),
        ("ctrl+r", "restore", "Restore"),
        ("ctrl+o", "operations", "Ops"),
        Binding("ctrl+j", "next_agent", "Next", priority=True),
        Binding("ctrl+k", "previous_agent", "Previous", priority=True),
        ("ctrl+q", "quit", "Quit"),
        Binding("ctrl+g", "agent_control", "Control", priority=True),
        Binding("ctrl+p", "agent_switcher", "Switch", priority=True),
        Binding("ctrl+b", "dispatch", "Dispatch", priority=True),
        Binding("ctrl+e", "select_transcript", "Select", priority=True),
        Binding("f6", "next_module", "Module", priority=True),
        Binding("f7", "toggle_density", "Density", priority=True),
        Binding("ctrl+l", "focus_command", "Command", priority=True),
        Binding("ctrl+s", "save_module", "Save", priority=True),
        Binding("escape", "workspace_focus", "Workspace", show=False),
        Binding("up", "prompt_previous", "History", show=False, priority=True),
        Binding("down", "prompt_next", "History", show=False, priority=True),
        Binding("tab", "complete_prompt", "Complete", show=False, priority=True),
    ]
    LOCAL_COMMANDS: ClassVar = command_descriptions()
    MODULE_ACTIONS: ClassVar = {
        "install": "install a trusted package, Git URL, wheel, or path",
        "link": "link an editable local module project",
        "info": "show external module metadata",
        "update": "stage an external module update",
        "enable": "enable an external module",
        "disable": "disable an external module",
        "remove": "remove an external module and its environment",
    }

    def __init__(
        self,
        *,
        skip_boot: bool = False,
        manager: AgentManager | None = None,
        config_store: ConfigStore | None = None,
        journal_store: JournalStore | None = None,
        module_registry: ModuleRegistry | None = None,
        clipboard_writer: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self.skip_boot = skip_boot
        config_store_supplied = config_store is not None
        self._ephemeral_root: tempfile.TemporaryDirectory[str] | None = None
        if skip_boot and any(
            dependency is None for dependency in (config_store, journal_store, module_registry)
        ):
            self._ephemeral_root = tempfile.TemporaryDirectory(prefix="cyberdeck-test-")
            ephemeral = Path(self._ephemeral_root.name)
            config_store = config_store or ConfigStore(ephemeral / "config.toml")
            journal_store = journal_store or JournalStore(ephemeral / "journal")
            module_registry = module_registry or ModuleRegistry(
                ephemeral / "modules", ephemeral / "module-config"
            )
        self._persist_preferences = not skip_boot or config_store_supplied
        self.config_store = config_store or ConfigStore()
        self.deck_config: DeckConfig = self.config_store.load()
        self.manager = manager or AgentManager(
            self.receive_agent_event,
            runtime_registry=RuntimeRegistry(
                self.deck_config.runtimes,
                approval_policy=self.deck_config.approval_policy,
                sandbox=self.deck_config.sandbox_mode,
            ),
        )
        self.manager.set_event_handler(self.receive_agent_event)
        if self.deck_config.default_runtime not in self.manager.available_providers:
            self.config_store.errors.append(
                f"Unknown default_runtime '{self.deck_config.default_runtime}'; using codex"
            )
            self.deck_config.default_runtime = "codex"
        self.journal_store = journal_store or JournalStore(self.deck_config.journal_path)
        self.module_registry = module_registry or ModuleRegistry()
        self.clipboard_service = ClipboardService(clipboard_writer)
        self.module_registry.apply_pending_updates()
        self._initialize_themes()
        self._initialize_application_state()
        self._initialize_modules()

    def _initialize_themes(self) -> None:
        self.deck_themes, self._theme_errors = discover_themes()
        for deck_theme in self.deck_themes.values():
            self.register_theme(deck_theme.textual_theme())
        selected_theme = self.deck_config.active_theme
        if selected_theme not in self.deck_themes:
            self._theme_errors.append(
                f"Configured theme '{selected_theme}' is unavailable; using ODS Nightwave"
            )
            selected_theme = "ods"
            self.deck_config.active_theme = selected_theme
        self.theme = selected_theme

    def _initialize_application_state(self) -> None:
        self._system_transcript: list[TranscriptEntry] = []
        self._prompt_completions: list[tuple[str, str]] = []
        self._completion_index = 0
        self._network_phase = 0
        self._prompt_history: list[str] = []
        self._history_index: int | None = None
        self._history_draft = ""
        self._draft_agent_id: str | None = None
        self._transition_serial = 0
        self.active_module_id = "agents"
        self._journal_day = datetime.now().astimezone().date()
        self._journal_loading = False
        self._journal_dirty = False
        self._journal_loaded_text = ""
        self._journal_initialized = False
        self._journal_save_timer = None

    def _initialize_modules(self) -> None:
        self.deck_modules: dict[str, DeckModule] = {
            "agents": BuiltinModule(
                BuiltinModuleSpec(
                    ModuleManifest("agents", "AGENT COMMAND", "Multi-agent operations", 10),
                    lambda: AgentsWorkspace(id="agent-module"),
                    self._handle_agent_prompt,
                )
            ),
            "journal": BuiltinModule(
                BuiltinModuleSpec(
                    ModuleManifest("journal", "JOURNAL", "Daily Markdown log", 20),
                    lambda: JournalWorkspace(id="journal-module"),
                    self._handle_journal_prompt,
                    commands=(
                        DeckCommand(
                            "/journal", "open a dated journal entry", self._command_journal
                        ),
                        DeckCommand("/today", "open today's journal entry", self._command_today),
                        DeckCommand("/save", "save the active journal entry", self._command_save),
                    ),
                    activate_handler=self._activate_journal,
                    deactivate_handler=self._deactivate_journal,
                    input_mode=ModuleInputMode.WORKSPACE_EDITOR,
                    focus_target="#journal-editor",
                    save_handler=self._save_journal_module,
                )
            ),
        }
        for module in self.deck_modules.values():
            validate_manifest(module.manifest)
        external_modules, self._module_errors = self.module_registry.discover_enabled(
            self._module_context
        )
        for module_id, module in external_modules.items():
            if module_id in self.deck_modules:
                self._module_errors[module_id] = "Module id collides with a bundled module"
                continue
            self.deck_modules[module_id] = module
        self.module_widgets: dict[str, Widget] = {}

    def compose(self) -> ComposeResult:
        with Horizontal(id="top-rail"):
            yield Static("ODS // CYBERDECK // 電脳端末", id="deck-brand")
            yield Static(id="uplink-count")
            yield Static(id="deck-clock")
        with Horizontal(id="workspace"):
            with Vertical(id="sidebar"):
                yield Label("── LOCAL GRID // 接続 ──", id="sidebar-title")
                yield ListView(id="agents")
                yield Label("── MODULE BAY // 機能 ──", id="modules-title")
                yield ListView(
                    *(
                        ListItem(Label(self._module_label_id(module_id)))
                        for module_id in self._ordered_module_ids()
                    ),
                    id="modules",
                )
                yield Static("^N NEW\n^P MATRIX", id="spawn-hint")
            with Vertical(id="main-panel"):
                for module_id in self._ordered_enabled_module_ids():
                    widget = self.deck_modules[module_id].build()
                    expected_id = self._module_widget_id(module_id)
                    if widget.id != expected_id:
                        widget.id = expected_id
                    widget.add_class("deck-module")
                    self.module_widgets[module_id] = widget
                    yield widget
                yield Static(id="autocomplete")
                with Vertical(id="prompt-zone"):
                    yield Static("▶ DECK:// 端末", id="prompt-label")
                    with Horizontal(id="prompt-bar"):
                        yield Static("local@deck:~ $", id="prompt-prefix")
                        yield Input(
                            placeholder="jack in... type a command or message",
                            id="prompt",
                        )
        yield Static(
            "^N NEW  ^R RESTORE  ^G CONTROL  ^P SWITCH  ^B DISPATCH  ^L CMD  ^S SAVE  ^O OPS  ^Q QUIT",
            id="shortcut-rail",
        )

    def on_mount(self) -> None:
        self.query_one("#operations-console").display = False
        # Keep the transition rail in layout so transient alerts never resize the
        # conversation viewport; visibility hides only its paint.
        self.query_one("#state-transition").visible = False
        self._apply_density(self.deck_config.density, persist=False)
        for module_id, widget in self.module_widgets.items():
            widget.display = module_id == "agents"
        self._update_rails()
        self.set_interval(1, self._update_rails)
        self.set_interval(0.28, self._update_network)
        self.query_one("#prompt", Input).focus()
        requested = self.deck_config.active_module if self._persist_preferences else "agents"
        self.call_after_refresh(
            lambda: self._activate_module(requested if requested in self.deck_modules else "agents")
        )
        for error in self._theme_errors:
            self.notify(error, title="THEME REJECTED", severity="warning")
        for error in self.config_store.errors:
            self.notify(error, title="CONFIGURATION FALLBACK", severity="warning")
        for module_id, error in self._module_errors.items():
            self.notify(error, title=f"MODULE FAULT // {module_id.upper()}", severity="error")
        if not self.skip_boot and self.deck_config.show_boot:
            self.push_screen(BootScreen())

    async def on_unmount(self) -> None:
        if self._journal_dirty:
            self._save_journal()
        await self.manager.shutdown()
        if self._ephemeral_root:
            self._ephemeral_root.cleanup()
            self._ephemeral_root = None

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if not self.screen_stack:
            return super().check_action(action, parameters)
        main = self.screen_stack[0]
        if self.screen is main and action in {
            "prompt_previous",
            "prompt_next",
            "complete_prompt",
        }:
            return main.query_one("#prompt", Input).has_focus
        if action == "focus_command":
            return self.screen is main
        if action == "workspace_focus":
            return (
                self.screen is main
                and self.deck_modules[self.active_module_id].input_mode
                is ModuleInputMode.WORKSPACE_EDITOR
                and main.query_one("#prompt", Input).has_focus
            )
        if action == "save_module":
            return self.screen is main
        return super().check_action(action, parameters)

    def _update_rails(self) -> None:
        active = sum(
            a.status not in {AgentStatus.ERROR, AgentStatus.STOPPED, AgentStatus.STARTING}
            for a in self.manager.agents
        )
        now = datetime.now().astimezone().strftime("%H:%M:%S")
        try:
            self.query_one("#uplink-count", Static).update(
                f"LOCAL GRID {active:02d}/{len(self.manager.agents):02d}"
            )
            self.query_one("#deck-clock", Static).update(now)
        except NoMatches:
            # Modal screens (including POST) temporarily own the app query root.
            return
        state = self._active_agent()
        if state:
            self.query_one("#agent-name", Static).update(f"UPLINK {state.config.name.upper()}")
            self.query_one("#agent-model", Static).update(
                f"│ {state.model_provider}/{state.model or 'default'}"
            )
            self.query_one("#agent-cwd", Static).update(f"│ {state.config.working_directory}")
            self.query_one("#agent-state", Static).update(f"│ STATE {state.status.value.upper()}")
            self.query_one("#agent-activity", Static).update(f"│ {state.current_activity}")
            self._update_network()
            self._update_mnem(state)
        else:
            self.query_one("#agent-name", Static).update("NO ACTIVE CONSTRUCT")
            self.query_one("#agent-model", Static).update("│ PROVIDER --")
            self.query_one("#agent-state", Static).update("│ STATE OFFLINE")
            self.query_one("#agent-activity", Static).update("│ awaiting operator")
            self.query_one("#agent-cwd", Static).update("")
            self._update_network()

    def _update_mnem(self, state: AgentState) -> None:
        meter = self.screen_stack[0].query_one("#agent-mnem", Static)
        if state.context_percentage is not None:
            percent = min(100, max(0, round(state.context_percentage)))
        elif state.context_window:
            percent = min(100, round(state.context_tokens / state.context_window * 100))
        else:
            meter.update(Text("MEM [······] --", style="#607087"))
            return
        filled = min(6, round(percent / 100 * 6))
        bar = "█" * filled + "░" * (6 - filled)
        color = "#52e891" if percent < 70 else "#e9b949" if percent < 90 else "#ff3b4f"
        meter.update(Text(f"MEM [{bar}] {percent:02d}%", style=f"bold {color}"))

    def _update_network(self) -> None:
        state = self._active_agent()
        try:
            indicator = self.screen_stack[0].query_one("#agent-network", Static)
        except (IndexError, NoMatches):
            return
        self._network_phase = (self._network_phase + 1) % 4
        self._update_signal_trace(state)
        self._refresh_agent_labels()
        if not state:
            indicator.update(Text("GRID [····]", style="#607087"))
            return
        patterns = ("▁▃▅▇", "▃▅▇▅", "▅▇▅▃", "▇▅▃▁")
        if state.status is AgentStatus.ERROR:
            label, color = "GRID [LOST]", "#ff3b4f"
        elif state.status is AgentStatus.FIREWALL_HOLD:
            label, color = "GRID [ICE]", "#ff3b4f"
        elif state.status in {
            AgentStatus.PROCESSING,
            AgentStatus.EXECUTING,
            AgentStatus.EDITING,
            AgentStatus.RESTORING,
        }:
            label, color = f"GRID [{patterns[self._network_phase]}]", "#e9b949"
        else:
            label, color = f"GRID [{patterns[self._network_phase]}]", "#52e891"
        indicator.update(Text(label, style=f"bold {color}"))

    def _update_signal_trace(self, state: AgentState | None) -> None:
        try:
            trace = self.screen_stack[0].query_one("#signal-trace", Static)
        except (IndexError, NoMatches):
            return
        if not state:
            trace.update(Text("CARRIER // 通信  ······················  OFFLINE", style="#283748"))
            return
        calm = (
            "───────╴──────────────",
            "───────────╴──────────",
            "───────────────╴──────",
            "───╴──────────────────",
        )
        active = ("▁▃▅▇▅▃▁──▁▃▅▇▅▃▁", "▃▅▇▅▃▁──▃▅▇▅▃▁", "▅▇▅▃▁──▁▃▅▇▅▃", "▇▅▃▁──▁▃▅▇▅▃▁")
        if state.status is AgentStatus.ERROR:
            body, label, color = "──────×────────×──────", "SIGNAL LOST // 通信断", "#ff3b4f"
        elif state.status is AgentStatus.FIREWALL_HOLD:
            body, label, color = "!─!─!─!─!─!─!─!─!─!─!", "ICE HOLD // 認証待機", "#ff3b4f"
        elif state.status in {
            AgentStatus.PROCESSING,
            AgentStatus.EXECUTING,
            AgentStatus.EDITING,
            AgentStatus.RESTORING,
        }:
            body, label, color = active[self._network_phase], "ACTIVE CARRIER // 稼働", "#e9b949"
        else:
            body, label, color = calm[self._network_phase], "CARRIER LOCK // 通信安定", "#1a8793"
        trace.update(Text(f"{body}  {label}", style=f"bold {color}"))

    def _show_transition(self, state: AgentState, message: str, color: str) -> None:
        if state is not self._active_agent():
            return
        banner = self.screen_stack[0].query_one("#state-transition", Static)
        self._transition_serial += 1
        serial = self._transition_serial
        banner.update(Text(f"▶ {message} // {state.config.name.upper()}", style=f"bold {color}"))
        banner.visible = True
        self.set_timer(2.4, lambda: self._hide_transition(serial))

    def _hide_transition(self, serial: int) -> None:
        if serial == self._transition_serial:
            try:
                self.screen_stack[0].query_one("#state-transition", Static).visible = False
            except (IndexError, NoMatches):
                return

    def action_spawn_agent(self) -> None:
        self.push_screen(
            SpawnAgent(
                self.manager.runtime_preflights(),
                self.deck_config.default_runtime,
            ),
            self._spawn_result,
        )

    def _spawn_result(self, result):
        if result:
            self._spawn(*result)

    @work(exclusive=False)
    async def _spawn(self, name: str, path: Path, provider: str = "codex") -> None:
        preflight = next(
            (row for row in self.manager.runtime_preflights() if row.runtime_id == provider),
            None,
        )
        if preflight and not preflight.available:
            self._write_local(f"runtime unavailable: {provider} // {preflight.detail}")
            return
        try:
            state = self.manager.register(name, path, provider=provider)
        except ValueError as exc:
            self._write_local(str(exc))
            return
        await self._add_agent_item(state, select=True)
        try:
            await self.manager.connect(state)
        except Exception as exc:  # noqa: BLE001
            self._write_local(f"uplink failed for {name}: {exc}")
        self._refresh_all()

    def action_restore(self) -> None:
        self._discover_restore()

    @work(exclusive=True)
    async def _discover_restore(self) -> None:
        try:
            threads = await self.manager.discover_threads(Path.cwd())
        except Exception as exc:  # noqa: BLE001
            self._write_local(f"archive uplink unavailable: {exc}")
            return
        self.push_screen(RestoreScreen(threads), self._restore_result)

    def _restore_result(self, selections):
        for summary, name in selections:
            self._restore_one(summary, name)

    @work(exclusive=False)
    async def _restore_one(self, summary: ThreadSummary, name: str) -> None:
        try:
            state = self.manager.register(name, summary.cwd, status=AgentStatus.RESTORING)
        except ValueError as exc:
            self._write_local(str(exc))
            return
        state.thread_id, state.restored = summary.id, True
        await self._add_agent_item(state, select=True)
        self._refresh_all()
        # Manager.restore owns registration, so remove the UI placeholder before invoking it.
        self.manager.agents.remove(state)
        try:
            await self.manager.restore(summary, name)
            index = self.query_one("#agents", ListView).index or 0
            self.manager.agents.insert(index, self.manager.agents.pop())
        except Exception as exc:  # noqa: BLE001
            state.status = AgentStatus.ERROR
            state.current_activity = str(exc)
            failed = next(
                (agent for agent in self.manager.agents if agent.thread_id == summary.id), None
            )
            if failed:
                self.manager.agents.remove(failed)
            self.manager.agents.insert(self.query_one("#agents", ListView).index or 0, state)
        self._refresh_all()

    async def _add_agent_item(self, state: AgentState, *, select: bool) -> None:
        view = self.query_one("#agents", ListView)
        await view.append(
            ListItem(
                Label(self._agent_label(state)),
                id=self._agent_row_id(state),
            )
        )
        if select:
            view.index = len(view.children) - 1

    async def present_agent(self, state: AgentState, *, select: bool = True) -> None:
        """Mount a registered agent for embedders and deterministic tests."""
        if state not in self.manager.agents:
            raise ValueError("Cannot present an unregistered agent")
        await self._add_agent_item(state, select=select)

    @on(Input.Submitted, "#prompt")
    async def send_prompt(self, event: Input.Submitted) -> None:
        if self._prompt_completions:
            self.action_complete_prompt()
            return
        prompt = event.value.strip()
        if not prompt:
            return
        self._prompt_history.append(prompt)
        self._history_index = None
        self._history_draft = ""
        event.input.value = ""
        state_for_draft = self._active_agent()
        if state_for_draft:
            state_for_draft.prompt_draft = ""
        if prompt.startswith("/"):
            await self._run_local_command(prompt)
            return
        # Provider sends may remain open for the entire turn (ACP session/prompt).
        # Return control to Textual's input pump immediately so operators can keep
        # drafting while the active agent is processing.
        self.run_worker(
            self.deck_modules[self.active_module_id].handle_prompt(prompt),
            group="deck-prompt",
            exclusive=False,
        )

    async def _handle_agent_prompt(self, prompt: str) -> None:
        state = self._active_agent()
        if not state:
            self._write_local("No active uplink. Use /new or /restore.")
            return
        if state.status is not AgentStatus.READY:
            self._write_local(
                f"{state.config.name} is {state.status.value.upper()}; wait for READY"
            )
            return
        try:
            await self.manager.send(state, prompt)
        except Exception as exc:  # noqa: BLE001
            self._write_local(f"TRANSMISSION FAILED // {exc}\nRECOVERY AVAILABLE // run /retry")
        self._refresh_all()

    async def _handle_journal_prompt(self, prompt: str) -> None:
        try:
            updated = self.journal_store.append_quick_entry(self._journal_day, prompt)
        except OSError as exc:
            self.notify(str(exc), title="JOURNAL WRITE FAILED", severity="error")
            return
        self._journal_loading = True
        self.screen_stack[0].query_one("#journal-editor", TextArea).load_text(updated)
        self._journal_loading = False
        self._journal_dirty = False
        self._journal_loaded_text = updated
        query = self.screen_stack[0].query_one("#journal-search", Input).value
        self._refresh_journal_days(query)
        self.notify("Quick entry recorded", title="JOURNAL")

    @on(Input.Changed, "#prompt")
    def prompt_changed(self, event: Input.Changed) -> None:
        self._prompt_completions = self._complete(event.value)
        self._completion_index = 0
        self._render_prompt_completions()

    def _render_prompt_completions(self) -> None:
        panel = self.screen_stack[0].query_one("#autocomplete", Static)
        if not self._prompt_completions:
            panel.display = False
            return
        rows = Text()
        for index, (value, description) in enumerate(self._prompt_completions[:6]):
            selected = index == self._completion_index
            rows.append(
                "TAB  " if selected else "     ",
                style="bold #e62acb" if selected else "",
            )
            rows.append(value, style="bold #00e8f2" if selected else "#8ba2b3")
            rows.append(f"  {description}", style="#607087")
            rows.append("\n")
        panel.update(rows)
        panel.display = True

    def action_complete_prompt(self) -> None:
        if self.screen is not self.screen_stack[0]:
            self.screen.focus_next()
            return
        prompt = self.screen_stack[0].query_one("#prompt", Input)
        if not prompt.has_focus or not self._prompt_completions:
            return
        visible = self._prompt_completions[:6]
        completion = visible[self._completion_index][0]
        raw = prompt.value
        if raw.startswith("/") and " " not in raw:
            spec = COMMANDS_BY_NAME.get(completion)
            prompt.value = completion + (" " if spec and spec.append_space else "")
        else:
            head, separator, _ = raw.rpartition(" ")
            prompt.value = f"{head}{separator}{completion}"
            if head == "/module" and completion in self.MODULE_ACTIONS:
                prompt.value += " "
        prompt.cursor_position = len(prompt.value)

    def _complete(self, value: str) -> list[tuple[str, str]]:
        return complete_prompt(self, value)

    @on(ListView.Highlighted, "#agents")
    def selected_agent_changed(self) -> None:
        if self.is_mounted and self.active_module_id != "agents":
            self._activate_module("agents")
        state = self._active_agent()
        if state:
            state.unread_count = 0
            state.unread_message_index = None
        prompt = self.screen_stack[0].query_one("#prompt", Input)
        if self._draft_agent_id:
            previous = next(
                (a for a in self.manager.agents if str(a.config.id) == self._draft_agent_id), None
            )
            if previous:
                previous.prompt_draft = prompt.value
        prompt.value = state.prompt_draft if state else ""
        self._draft_agent_id = str(state.config.id) if state else None
        self._history_index = None
        self._render_active()

    @on(ListView.Selected, "#modules")
    def module_selected(self, event: ListView.Selected) -> None:
        if event.list_view.index is None:
            return
        module_id = self._ordered_module_ids()[event.list_view.index]
        record = self.module_registry.records.get(module_id)
        if record and not record.enabled:
            self.notify(
                f"{module_id} is disabled; use /module enable {module_id}", severity="warning"
            )
            return
        if record and record.status == ModuleStatus.FAULTED.value:
            self.notify(record.error or "Module failed to load", severity="error")
            return
        self._activate_module(module_id)

    @on(ListView.Selected, "#operations-list")
    def operation_selected(self, event: ListView.Selected) -> None:
        state = self._active_agent()
        if (
            state
            and event.list_view.index is not None
            and event.list_view.index < len(state.operations)
        ):
            self.push_screen(OperationDetail(state.operations[event.list_view.index]))

    def action_operations(self) -> None:
        if self.active_module_id != "agents":
            self.notify("Operations are available in AGENT COMMAND", severity="warning")
            return
        console = self.query_one("#operations-console")
        console.display = not console.display
        if console.display:
            operations = self.query_one("#operations-list", ListView)
            if operations.children and operations.index is None:
                operations.index = 0
            operations.focus()
        else:
            self.query_one("#prompt", Input).focus()

    def action_next_agent(self) -> None:
        self._move_agent(1)

    def action_previous_agent(self) -> None:
        self._move_agent(-1)

    def action_next_module(self) -> None:
        ordered = self._ordered_enabled_module_ids()
        index = ordered.index(self.active_module_id)
        self._activate_module(ordered[(index + 1) % len(ordered)])

    def action_toggle_density(self) -> None:
        density = "compact" if self.deck_config.density == "standard" else "standard"
        self._apply_density(density)

    def action_focus_command(self) -> None:
        self.screen_stack[0].query_one("#prompt", Input).focus()

    def action_workspace_focus(self) -> None:
        self.call_after_refresh(self._focus_active_workspace)

    def _latest_ice(self) -> tuple[AgentState, PendingApproval] | None:
        state = self._active_agent()
        if not state or not state.pending_approvals:
            return None
        return state, state.pending_approvals[-1]

    def action_save_module(self) -> None:
        self.run_worker(self._save_active_module(), group="module-save", exclusive=True)

    async def _save_active_module(self) -> None:
        handled = await self.deck_modules[self.active_module_id].save()
        if not handled:
            self.notify(f"{self.active_module_id} has nothing to save", severity="warning")

    def _focus_active_workspace(self) -> None:
        module = self.deck_modules[self.active_module_id]
        if module.input_mode is ModuleInputMode.DECK_PROMPT:
            self.screen_stack[0].query_one("#prompt", Input).focus()
        elif module.focus_target:
            self.screen_stack[0].query_one(module.focus_target).focus()

    def _activate_module(self, module_id: str) -> None:
        if module_id not in self.deck_modules:
            self.notify(f"Unknown module: {module_id}", severity="error")
            return
        self.run_worker(self._switch_module(module_id), group="module-switch", exclusive=True)

    async def _switch_module(self, module_id: str) -> None:
        main = self.screen_stack[0]
        previous = self.active_module_id
        if previous != module_id:
            await self.deck_modules[previous].deactivate()
        self.active_module_id = module_id
        for candidate, widget in self.module_widgets.items():
            widget.display = candidate == module_id
        ordered = self._ordered_module_ids()
        main.query_one("#modules", ListView).index = next(
            index for index, candidate in enumerate(ordered) if candidate == module_id
        )
        self._refresh_module_labels()
        prompt = main.query_one("#prompt", Input)
        if module_id == "agents":
            prompt.placeholder = "jack in... type a command or message"
            self._render_active()
        elif module_id == "journal":
            prompt.placeholder = "quick journal entry... or /command"
            main.query_one("#prompt-prefix", Static).update("local@journal:today $")
        else:
            prompt.placeholder = "module input... or /command"
            main.query_one("#prompt-prefix", Static).update(f"local@{module_id}:~ $")
        await self.deck_modules[module_id].activate()
        self.deck_config.active_module = module_id
        if self._persist_preferences:
            try:
                self.config_store.save(self.deck_config)
            except OSError as exc:
                self.notify(str(exc), title="CONFIG WRITE FAILED", severity="warning")
        self._focus_active_workspace()

    def _refresh_module_labels(self) -> None:
        view = self.screen_stack[0].query_one("#modules", ListView)
        ordered = self._ordered_module_ids()
        for item, module_id in zip(view.children, ordered, strict=False):
            labels = list(item.query(Label))
            if labels:
                labels[0].update(self._module_label_id(module_id))

    def _module_label(self, module: DeckModule) -> Text:
        return self._module_label_id(module.manifest.id)

    def _module_label_id(self, module_id: str) -> Text:
        module = self.deck_modules.get(module_id)
        record = self.module_registry.records.get(module_id)
        active = module_id == self.active_module_id
        title = module.manifest.title if module else module_id.upper()
        description = module.manifest.description if module else (record.error or record.package)
        status = (
            "ACTIVE"
            if active
            else "FAULT"
            if record and record.status == ModuleStatus.FAULTED.value
            else "UPDATE"
            if record and record.pending_environment
            else "DISABLED"
            if record and not record.enabled
            else "STANDBY"
        )
        label = Text()
        label.append("● " if active else "◇ ", style="bold #52e891" if active else "#607087")
        label.append(title, style="bold #00e8f2" if active else "#8ba2b3")
        label.append(f"  {status}", style="bold #52e891" if active else "#607087")
        label.append(f"\n  {description}", style="#46566c")
        return label

    @staticmethod
    def _module_widget_id(module_id: str) -> str:
        return "agent-module" if module_id == "agents" else f"{module_id}-module"

    def _ordered_enabled_module_ids(self) -> list[str]:
        return sorted(
            self.deck_modules,
            key=lambda key: (self.deck_modules[key].manifest.order, key),
        )

    def _ordered_module_ids(self) -> list[str]:
        ids = set(self.deck_modules) | set(self.module_registry.records)
        return sorted(
            ids,
            key=lambda key: (
                self.deck_modules[key].manifest.order if key in self.deck_modules else 100,
                key,
            ),
        )

    def _module_context(self, module_id: str) -> ModuleContext:
        return ModuleContext(
            module_id=module_id,
            data_directory=self.module_registry.root / "data" / module_id,
            config_directory=self.module_registry.config_root / module_id,
            notify=lambda message, title="MODULE", severity="information": self.notify(
                message, title=title, severity=severity
            ),
            copy_to_clipboard=self._copy_text,
            services={},
        )

    async def _activate_journal(self) -> None:
        main = self.screen_stack[0]
        query = main.query_one("#journal-search", Input).value
        self._refresh_journal_days(query)
        if not self._journal_initialized:
            self._load_journal_day(self._journal_day)

    async def _deactivate_journal(self) -> None:
        if self._journal_dirty:
            self._save_journal()

    def _refresh_journal_days(self, query: str = "") -> None:
        days = self.journal_store.days(query)
        today = datetime.now().astimezone().date()
        if not query and today not in days:
            days.insert(0, today)
        self._journal_dates = days
        view = self.screen_stack[0].query_one("#journal-days", ListView)
        view.clear()
        for day in days:
            marker = "●" if day == self._journal_day else "○"
            view.append(ListItem(Label(f"{marker} {day.isoformat()}\n  {day:%A}")))
        if days:
            try:
                view.index = days.index(self._journal_day)
            except ValueError:
                view.index = 0

    def _load_journal_day(self, day: date) -> None:
        if self._journal_dirty:
            self._save_journal()
        self._journal_day = day
        try:
            content = self.journal_store.read(day)
        except OSError as exc:
            self.notify(str(exc), title="JOURNAL READ FAILED", severity="error")
            return
        self._journal_loading = True
        main = self.screen_stack[0]
        main.query_one("#journal-editor", TextArea).load_text(content)
        self._journal_loading = False
        self._journal_dirty = False
        self._journal_loaded_text = content
        self._journal_initialized = True
        main.query_one("#journal-date", Static).update(
            f"{day:%A, %B} {day.day}, {day.year} // {day.isoformat()}"
        )
        if self.active_module_id == "journal":
            main.query_one("#prompt-prefix", Static).update(f"local@journal:{day.isoformat()} $")

    def _save_journal(self) -> bool:
        if not self._journal_dirty:
            return True
        main = self.screen_stack[0]
        text = main.query_one("#journal-editor", TextArea).text
        try:
            self.journal_store.write(self._journal_day, text)
        except OSError as exc:
            self.notify(str(exc), title="JOURNAL WRITE FAILED", severity="error")
            return False
        self._journal_dirty = False
        self._journal_loaded_text = text
        main.query_one("#journal-status", Static).update("SAVED // USER OWNED MARKDOWN")
        query = main.query_one("#journal-search", Input).value
        self._refresh_journal_days(query)
        return True

    async def _save_journal_module(self) -> bool:
        saved = self._save_journal()
        if saved:
            self.notify("Entry saved", title="JOURNAL")
        return saved

    @on(TextArea.Changed, "#journal-editor")
    def journal_changed(self) -> None:
        editor = self.screen_stack[0].query_one("#journal-editor", TextArea)
        if self._journal_loading or editor.text == self._journal_loaded_text:
            return
        self._journal_dirty = True
        self.screen_stack[0].query_one("#journal-status", Static).update(
            "MODIFIED // AUTOSAVE ARMED"
        )
        if self._journal_save_timer is not None:
            self._journal_save_timer.stop()
        self._journal_save_timer = self.set_timer(0.7, self._save_journal)

    @on(Input.Changed, "#journal-search")
    def journal_search_changed(self, event: Input.Changed) -> None:
        self._refresh_journal_days(event.value)

    @on(ListView.Highlighted, "#journal-days")
    def journal_day_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.index is not None and event.list_view.index < len(self._journal_dates):
            day = self._journal_dates[event.list_view.index]
            if day != self._journal_day:
                self._load_journal_day(day)

    @on(ListView.Selected, "#journal-days")
    def journal_day_selected(self) -> None:
        self.screen_stack[0].query_one("#journal-editor", TextArea).focus()

    def action_prompt_previous(self) -> None:
        if self._navigate_non_prompt(-1):
            return
        prompt = self.query_one("#prompt", Input)
        if prompt.has_focus and self._prompt_completions:
            visible_count = min(6, len(self._prompt_completions))
            self._completion_index = (self._completion_index - 1) % visible_count
            self._render_prompt_completions()
            return
        if not prompt.has_focus or not self._prompt_history:
            return
        if self._history_index is None:
            self._history_draft = prompt.value
            self._history_index = len(self._prompt_history) - 1
        elif self._history_index > 0:
            self._history_index -= 1
        prompt.value = self._prompt_history[self._history_index]
        prompt.cursor_position = len(prompt.value)

    def action_prompt_next(self) -> None:
        if self._navigate_non_prompt(1):
            return
        prompt = self.query_one("#prompt", Input)
        if prompt.has_focus and self._prompt_completions:
            visible_count = min(6, len(self._prompt_completions))
            self._completion_index = (self._completion_index + 1) % visible_count
            self._render_prompt_completions()
            return
        if not prompt.has_focus or self._history_index is None:
            return
        if self._history_index < len(self._prompt_history) - 1:
            self._history_index += 1
            prompt.value = self._prompt_history[self._history_index]
        else:
            self._history_index = None
            prompt.value = self._history_draft
        prompt.cursor_position = len(prompt.value)

    def _navigate_non_prompt(self, direction: int) -> bool:
        result_screens = (AgentSwitcher, RestoreScreen, OperativeControl, DispatchScreen)
        if isinstance(self.screen, result_screens):
            action = (
                self.screen.action_previous_result
                if direction < 0
                else self.screen.action_next_result
            )
            action()
            return True
        if isinstance(self.focused, ListView):
            self._move_focused_list(self.focused, direction)
            return True
        if isinstance(self.focused, VerticalScroll):
            action = self.focused.scroll_up if direction < 0 else self.focused.scroll_down
            action(animate=False, force=True)
            return True
        if self.screen is not self.screen_stack[0]:
            return True
        state = self._active_agent()
        if state and state.pending_approvals:
            conversation = self.query_one("#conversation", VerticalScroll)
            action = conversation.scroll_up if direction < 0 else conversation.scroll_down
            action(animate=False, force=True)
            return True
        return False

    @staticmethod
    def _move_focused_list(view: ListView, direction: int) -> None:
        count = len(view.children)
        if not count:
            return
        current = view.index if view.index is not None else 0
        view.index = max(0, min(count - 1, current + direction))

    def action_agent_control(self) -> None:
        state = self._active_agent()
        if not state:
            self._write_local("No active uplink.")
            return
        self.push_screen(
            OperativeControl(state), lambda result: self._control_result(state, result)
        )

    def action_agent_switcher(self) -> None:
        self.push_screen(
            AgentSwitcher(self.manager.agents, self._active_agent()), self._switch_result
        )

    def _switch_result(self, state: AgentState | None) -> None:
        if state and state in self.manager.agents:
            self.query_one("#agents", ListView).index = self.manager.agents.index(state)

    def action_dispatch(self) -> None:
        self.push_screen(DispatchScreen(self.manager.agents), self._dispatch_result)

    def action_select_transcript(self) -> None:
        state = self._active_agent()
        entries = state.transcript if state else self._system_transcript
        if not entries:
            self._write_local("No transcript messages to select.")
            return
        self.push_screen(TranscriptSelection(list(entries)), self._selection_result)

    def _selection_result(self, entries: list[TranscriptEntry] | None) -> None:
        if not entries:
            return
        # Preserve each selected message verbatim; separators are plain text only.
        text = "\n\n".join(entry.text for entry in entries)
        try:
            self._copy_text(text)
        except RuntimeError as exc:
            self._write_local(f"CLIPBOARD FAULT // {exc}")

    def _dispatch_result(self, result) -> None:
        if result:
            self._dispatch(*result)

    @work(exclusive=False)
    async def _dispatch(self, targets: list[AgentState], prompt: str) -> None:
        try:
            results = await self.manager.dispatch(targets, prompt)
            rows = [
                f"{name}: {'FAILED // ' + error if error else 'TRANSMITTED'}"
                for name, error in results.items()
            ]
            self._write_local("DISPATCH SUMMARY\n" + "\n".join(rows))
        except Exception as exc:  # noqa: BLE001
            self._write_local(f"dispatch blocked: {exc}")
        self._refresh_all()

    def _control_result(self, state: AgentState, result) -> None:
        if not result:
            return
        action, argument = result
        if action == "disconnect" and state.status not in {AgentStatus.READY, AgentStatus.ERROR}:
            self.push_screen(
                ConfirmScreen(
                    "DISCONNECT BUSY OPERATIVE", f"Interrupt and disconnect {state.config.name}?"
                ),
                lambda yes: self._lifecycle(state, action, argument) if yes else None,
            )
        elif action == "archive":
            self.push_screen(
                ConfirmScreen(
                    "ARCHIVE OPERATIVE",
                    f"Archive {state.config.name}? This removes it from Archive Uplink.",
                ),
                lambda yes: self._lifecycle(state, action, argument) if yes else None,
            )
        else:
            self._lifecycle(state, action, argument)

    @work(exclusive=False)
    async def _lifecycle(self, state: AgentState, action: str, argument: str | None = None) -> None:
        try:
            operation = getattr(self.manager, action)
            await operation(state, argument) if action == "rename" else await operation(state)
            if action in {"disconnect", "archive"}:
                self._sync_agent_list()
            signal = {
                "rename": "CALLSIGN UPDATED",
                "interrupt": "ABORT SIGNAL CONFIRMED",
                "retry": "CARRIER REACQUIRED",
                "disconnect": "CARRIER RELEASED",
                "archive": "CONSTRUCT ARCHIVED",
            }.get(action, f"{action.upper()} COMPLETE")
            self._write_local(f"{signal} // {argument or state.config.name}")
        except Exception as exc:  # noqa: BLE001
            self._write_local(f"{action} failed: {exc}")
        self._refresh_all()

    def _sync_agent_list(self) -> None:
        view = self.query_one("#agents", ListView)
        view.clear()
        for state in self.manager.agents:
            view.append(
                ListItem(
                    Label(self._agent_label(state)),
                    id=self._agent_row_id(state),
                )
            )
        if self.manager.agents:
            view.index = min(view.index or 0, len(self.manager.agents) - 1)

    def _move_agent(self, direction: int) -> None:
        view = self.query_one("#agents", ListView)
        if self.manager.agents:
            view.index = ((view.index or 0) + direction) % len(self.manager.agents)

    def _active_agent(self) -> AgentState | None:
        try:
            index = self.screen_stack[0].query_one("#agents", ListView).index
        except (IndexError, NoMatches):
            return None
        return (
            self.manager.agents[index]
            if index is not None and index < len(self.manager.agents)
            else None
        )

    def active_agent(self) -> AgentState | None:
        """Return the agent selected in the primary workspace."""
        return self._active_agent()

    def _render_active(self, *, follow_end: bool = True) -> None:
        main = self.screen_stack[0]
        state = self._active_agent()
        conversation = main.query_one("#conversation", VerticalScroll)
        conversation.remove_children()
        entries = state.transcript if state else self._system_transcript
        if not state and not entries:
            conversation.mount(EmptyGrid())
        if state and state.history_cursor:
            conversation.mount(Static("↑ LOAD OLDER TURNS  //  /older", classes="load-older"))
        for entry in entries:
            conversation.mount(TerminalMessage(entry, state))
        if state:
            for approval in state.pending_approvals:
                conversation.mount(ApprovalMessage(state, approval))
        prefix = main.query_one("#prompt-prefix", Static)
        prefix.update(
            f"{getpass.getuser()}@{state.config.name}:{self.display_path(state.config.working_directory)} $"
            if state
            else "local@deck:~ $"
        )
        self._render_operations()
        self._update_rails()
        if follow_end:
            self.call_after_refresh(lambda: conversation.scroll_end(animate=False))

    def _render_operations(self) -> None:
        view = self.screen_stack[0].query_one("#operations-list", ListView)
        view.clear()
        state = self._active_agent()
        if not state:
            return
        for op in state.operations:
            glyph = {
                "succeeded": "✓",
                "failed": "!",
                "approval": "?",
                "running": "◐",
                "pending": "○",
            }[op.state.value]
            trace = self._trace_class(op)
            phase = {
                "succeeded": "CLEAR",
                "failed": "FAULT",
                "approval": "INTERLOCK",
                "running": "ACTIVE",
                "pending": "QUEUED",
            }[op.state.value]
            view.append(
                ListItem(
                    Label(
                        f"{op.created_at:%H:%M:%S}  {trace:<7} {phase:<9} {glyph} "
                        f"{op.kind:<16} {op.summary}"
                    )
                )
            )

    @staticmethod
    def _trace_class(operation: OperationEntry) -> str:
        if operation.state.value == "approval":
            return "ICE"
        if operation.state.value == "failed":
            return "FAULT"
        return {
            "commandExecution": "TRACE",
            "fileChange": "PATCH",
            "mcpToolCall": "PROBE",
            "dynamicToolCall": "PROBE",
            "webSearch": "SCAN",
        }.get(operation.kind, "SIGNAL")

    def _write_local(self, text: str) -> None:
        state = self._active_agent()
        (state.transcript if state else self._system_transcript).append(
            TranscriptEntry("system", text)
        )
        self._render_active()

    async def _run_local_command(self, command_line: str) -> None:
        await self.execute_command(command_line)

    async def execute_command(self, command_line: str) -> None:
        """Execute one local deck command through the supported command boundary."""
        await run_local_command(self, command_line)

    def _all_local_commands(self) -> dict[str, str]:
        commands = dict(self.LOCAL_COMMANDS)
        for module in self.deck_modules.values():
            for command in module.commands():
                commands[command.name] = command.description
        return commands

    def _module_state(self, module_id: str) -> str:
        if module_id == self.active_module_id:
            return "active"
        record = self.module_registry.records.get(module_id)
        if record:
            return record.status
        return "bundled"

    def _module_description(self, module_id: str) -> str:
        module = self.deck_modules.get(module_id)
        if module:
            return module.manifest.description
        record = self.module_registry.records[module_id]
        return record.error or record.package

    def _module_management_command(self, action: str, module_id: str) -> None:
        if module_id not in self.module_registry.records:
            self.notify(f"External module not found: {module_id}", severity="error")
            return
        if action == "info":
            record = self.module_registry.records[module_id]
            self.notify(
                f"PACKAGE  {record.package}\nVERSION  {record.version}\n"
                f"SOURCE   {record.source}\nSTATE    {record.status}\n"
                f"ERROR    {record.error or '--'}",
                title=f"MODULE // {module_id.upper()}",
            )
        elif action == "enable":
            self.run_worker(self._enable_external_module(module_id), exclusive=False)
        elif action == "disable":
            self.run_worker(self._disable_external_module(module_id), exclusive=False)
        elif action == "remove":
            self.push_screen(
                ConfirmScreen("REMOVE MODULE", f"Remove {module_id} and its environment?"),
                lambda confirmed: (
                    self.run_worker(self._remove_external_module(module_id), exclusive=False)
                    if confirmed
                    else None
                ),
            )
        elif action == "update":
            record = self.module_registry.records[module_id]
            self._install_external_module(record.source)

    @work(exclusive=False)
    async def _install_external_module(self, specification: str, *, editable: bool = False) -> None:
        self.notify("Resolving package and dependencies", title="MODULE INSTALL")
        record = None
        try:
            record, module = await asyncio.to_thread(
                self.module_registry.install,
                specification,
                self._module_context,
                editable=editable,
                trusted=True,
            )
            if module:
                await self._mount_external_module(module)
                self.notify(
                    f"{record.id} {record.version} mounted and ready",
                    title="MODULE INSTALLED",
                )
            else:
                self.notify(
                    f"{record.id} update staged for next launch",
                    title="UPDATE PENDING",
                )
            await self._sync_module_list()
        except Exception as exc:  # noqa: BLE001
            if (
                record
                and record.id in self.module_registry.records
                and not record.pending_environment
            ):
                record.enabled = False
                record.status = ModuleStatus.FAULTED.value
                record.error = str(exc)
                self.module_registry.save()
                await self._sync_module_list()
            self.notify(str(exc), title="MODULE INSTALL FAILED", severity="error")

    async def _mount_external_module(self, module: DeckModule) -> None:
        module_id = module.manifest.id
        if module_id in self.deck_modules:
            raise ValueError(f"Module id already loaded: {module_id}")
        registered = {
            name
            for item in self.deck_modules.values()
            for name in (c.name for c in item.commands())
        }
        registered.update(self.LOCAL_COMMANDS)
        conflicts = sorted(
            command.name for command in module.commands() if command.name in registered
        )
        if conflicts:
            raise ValueError(f"Module command collision: {', '.join(conflicts)}")
        widget = module.build()
        widget.id = self._module_widget_id(module_id)
        widget.add_class("deck-module")
        widget.display = False
        await (
            self.screen_stack[0]
            .query_one("#main-panel")
            .mount(widget, before=self.screen_stack[0].query_one("#autocomplete"))
        )
        self.deck_modules[module_id] = module
        self.module_widgets[module_id] = widget
        await self._sync_module_list()
        await self._switch_module(module_id)

    async def _enable_external_module(self, module_id: str) -> None:
        if module_id in self.deck_modules:
            self.notify(f"{module_id} is already enabled")
            return
        try:
            module = await asyncio.to_thread(
                self.module_registry.load_record, module_id, self._module_context
            )
            await self._mount_external_module(module)
            self.notify(f"{module_id} enabled", title="MODULE ONLINE")
        except Exception as exc:  # noqa: BLE001
            record = self.module_registry.records[module_id]
            record.status = ModuleStatus.FAULTED.value
            record.error = str(exc)
            self.module_registry.save()
            await self._sync_module_list()
            self.notify(str(exc), title="MODULE FAULT", severity="error")

    async def _disable_external_module(self, module_id: str) -> None:
        if self.active_module_id == module_id:
            await self._switch_module("agents")
        module = self.deck_modules.pop(module_id, None)
        widget = self.module_widgets.pop(module_id, None)
        if module:
            try:
                await asyncio.wait_for(module.deactivate(), timeout=2)
            except Exception as exc:  # noqa: BLE001
                self.notify(str(exc), title="MODULE DEACTIVATION FAULT", severity="warning")
        if widget:
            await widget.remove()
        self.module_registry.set_enabled(module_id, False)
        await self._sync_module_list()
        self.notify(f"{module_id} disabled", title="MODULE OFFLINE")

    async def _remove_external_module(self, module_id: str) -> None:
        if module_id in self.deck_modules:
            await self._disable_external_module(module_id)
        await asyncio.to_thread(self.module_registry.remove, module_id)
        await self._sync_module_list()
        self.notify(f"{module_id} removed", title="MODULE REMOVED")

    async def _sync_module_list(self) -> None:
        view = self.screen_stack[0].query_one("#modules", ListView)
        selected = self.active_module_id
        view.clear()
        ordered = self._ordered_module_ids()
        for module_id in ordered:
            await view.append(ListItem(Label(self._module_label_id(module_id))))
        if selected in ordered:
            view.index = ordered.index(selected)

    def _system_manifest(self) -> str:
        codex_version = self._executable_version("codex")
        external_records = list(self.module_registry.records.values())
        faulted_modules = sum(
            record.status == ModuleStatus.FAULTED.value for record in external_records
        )
        rows = [
            "OPEN DECK SYSTEMS // SAFE DIAGNOSTIC EXPORT",
            "",
            f"Cyberdeck...... {__version__}",
            f"Python......... {platform.python_version()}",
            f"Textual........ {package_version('textual')}",
            f"Platform....... {platform.system()} {platform.release()}",
            f"Architecture... {platform.machine()}",
            "",
            f"Active module.. {self.active_module_id}",
            f"Active theme... {self.deck_config.active_theme}",
            f"Open agents.... {len(self.manager.agents)}",
            f"Ext. modules... {len(external_records)} installed / {faulted_modules} faulted",
            f"Codex CLI...... {codex_version}",
            "",
            f"Config......... {self.display_path(self.config_store.path)}",
            f"Journal........ {self.display_path(self.journal_store.directory)}",
            f"Themes......... {self.display_path(user_theme_directory())}",
            f"Modules........ {self.display_path(self.module_registry.root)}",
            "",
            "Repository..... https://github.com/jessecanderson/cyberdeck",
            "Issues......... https://github.com/jessecanderson/cyberdeck/issues",
            "",
            "No prompts, transcripts, environment variables, or credentials included.",
        ]
        return "\n".join(rows)

    @staticmethod
    def _executable_version(name: str) -> str:
        executable = shutil.which(name)
        if not executable:
            return "NOT DETECTED"
        try:
            result = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                check=False,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            return "DETECTED // VERSION UNAVAILABLE"
        output = (result.stdout or result.stderr).strip().splitlines()
        return output[0] if output else "DETECTED // VERSION UNAVAILABLE"

    async def _command_journal(self, args: list[str]) -> None:
        day = datetime.now().astimezone().date()
        if args:
            try:
                day = date.fromisoformat(args[0])
            except ValueError:
                self.notify("usage: /journal [YYYY-MM-DD]", severity="error")
                return
        self._journal_day = day
        self._activate_module("journal")
        self._load_journal_day(day)

    async def _command_today(self, _args: list[str]) -> None:
        await self._command_journal([])

    async def _command_save(self, _args: list[str]) -> None:
        if self.active_module_id != "journal":
            self.notify("Journal is not active", severity="warning")
            return
        await self._save_journal_module()

    def _theme_command(self, args: list[str]) -> None:
        if not args:
            self.push_screen(
                ThemeScreen(list(self.deck_themes.values()), self.deck_config.active_theme),
                self._theme_selected,
            )
            return
        if args[0].casefold() == "import":
            if len(args) != 2:
                self.notify("usage: /theme import PATH", severity="error")
                return
            try:
                source = Path(args[1]).expanduser().resolve()
            except (RuntimeError, OSError, ValueError) as exc:
                self.notify(str(exc), title="THEME IMPORT FAILED", severity="error")
                return
            try:
                deck_theme = import_theme(source)
            except FileExistsError:
                self.push_screen(
                    ConfirmScreen("REPLACE THEME", f"Replace imported theme {source.name}?"),
                    lambda yes: self._replace_theme(source) if yes else None,
                )
                return
            except ValueError as exc:
                self.notify(str(exc), title="THEME REJECTED", severity="error")
                return
            self._register_imported_theme(deck_theme)
            return
        self._apply_theme(args[0].casefold())

    def _replace_theme(self, source: Path) -> None:
        try:
            deck_theme = import_theme(source, replace=True)
        except (OSError, ValueError) as exc:
            self.notify(str(exc), title="THEME IMPORT FAILED", severity="error")
            return
        self._register_imported_theme(deck_theme)

    def _register_imported_theme(self, deck_theme: DeckTheme) -> None:
        self.deck_themes[deck_theme.id] = deck_theme
        self.register_theme(deck_theme.textual_theme())
        self._apply_theme(deck_theme.id)
        self.notify(f"Imported {deck_theme.name}", title="CHROMA MATRIX")

    def _theme_selected(self, theme_id: str | None) -> None:
        if theme_id:
            self._apply_theme(theme_id)

    def _apply_theme(self, theme_id: str) -> None:
        if theme_id not in self.deck_themes:
            self.notify(f"Unknown theme: {theme_id}", severity="error")
            return
        self.theme = theme_id
        self.deck_config.active_theme = theme_id
        if not self._persist_preferences:
            return
        try:
            self.config_store.save(self.deck_config)
        except OSError as exc:
            self.notify(str(exc), title="CONFIG WRITE FAILED", severity="warning")

    def _apply_density(self, density: str, *, persist: bool = True) -> None:
        """Apply workspace-only presentation density without changing behavior."""
        main = self.screen_stack[0]
        main.set_class(density == "compact", "compact")
        self.deck_config.density = density
        self._refresh_agent_labels()
        self._render_active(follow_end=False)
        if not persist or not self._persist_preferences:
            return
        try:
            self.config_store.save(self.deck_config)
        except OSError as exc:
            self.notify(str(exc), title="CONFIG WRITE FAILED", severity="warning")

    def _copy_command(self, args: list[str]) -> None:
        state = self._active_agent()
        if args and args[0].casefold() == "all":
            if len(args) != 1:
                self._write_local("usage: /copy [N|all|TEXT]")
                return
            entries = state.transcript if state else self._system_transcript
            text = "\n\n".join(f"{entry.role.upper()}: {entry.text}" for entry in entries)
        elif len(args) == 1 and args[0].isdigit():
            count = int(args[0])
            if count < 1:
                self._write_local("copy count must be at least 1")
                return
            entries = state.transcript if state else self._system_transcript
            responses = [entry.text for entry in entries if entry.role == "assistant"]
            if not responses:
                self._write_local("nothing to copy: no assistant response")
                return
            text = "\n\n".join(responses[-count:])
        elif args:
            text = " ".join(args)
        else:
            entries = state.transcript if state else self._system_transcript
            latest = next((entry for entry in reversed(entries) if entry.role == "assistant"), None)
            if not latest:
                self._write_local("nothing to copy: no assistant response")
                return
            text = latest.text
        if not text:
            self._write_local("nothing to copy")
            return
        try:
            target = self._copy_text(text)
        except RuntimeError as exc:
            self._write_local(f"CLIPBOARD FAULT // {exc}")
            return
        self._write_local(f"CLIPBOARD WRITE CONFIRMED // {len(text)} characters via {target}")

    def _copy_text(self, text: str) -> str:
        return self.clipboard_service.write(text, self.copy_to_clipboard)

    def _find_agent(self, callsign: str) -> AgentState | None:
        name = callsign.casefold()
        return next(
            (agent for agent in self.manager.agents if agent.config.name.casefold() == name), None
        )

    def _route_command(self, command: str, args: list[str]) -> None:
        usage = f"usage: {command} CALLSIGN" + (" MESSAGE" if command == "/send" else "")
        if not args:
            self._write_local(usage)
            return
        target = self._find_agent(args[0])
        if not target:
            self._write_local(f"unknown callsign: {args[0]}")
            return
        if target.status is not AgentStatus.READY:
            self._write_local(
                f"{target.config.name} is {target.status.value.upper()}; requires READY"
            )
            return
        if command == "/send":
            payload = " ".join(args[1:]).strip()
            if not payload:
                self._write_local(usage)
                return
        else:
            source = self._active_agent()
            latest = (
                next(
                    (entry for entry in reversed(source.transcript) if entry.role == "assistant"),
                    None,
                )
                if source
                else None
            )
            if not latest:
                self._write_local("nothing to pipe: no assistant response")
                return
            payload = latest.text
        self._send_to_agent(target, payload, command[1:])

    @work(exclusive=False)
    async def _send_to_agent(self, target: AgentState, payload: str, verb: str) -> None:
        try:
            await self.manager.send(target, payload)
            self._write_local(f"{verb} transmitted to {target.config.name}")
        except Exception as exc:  # noqa: BLE001
            target.status = AgentStatus.ERROR
            target.current_activity = f"{verb} failed"
            target.error_message = str(exc)
            self._write_local(f"{verb} failed for {target.config.name}: {exc}")
        self._refresh_all()

    def _request_kill(self, args: list[str]) -> None:
        if args and args[0].casefold() == "all":
            targets = list(self.manager.agents)
        elif args:
            target = self._find_agent(args[0])
            if not target:
                self._write_local(f"unknown callsign: {args[0]}")
                return
            targets = [target]
        else:
            active = self._active_agent()
            targets = [active] if active else []
        if not targets:
            self._write_local("no agents to kill")
            return
        names = ", ".join(
            f"{agent.config.name} [{agent.config.provider.upper()}]" for agent in targets
        )
        self.push_screen(
            ConfirmScreen(
                "KILL UPLINK" if len(targets) == 1 else "KILL ALL UPLINKS",
                f"Disconnect {names}? Threads remain restorable through Archive Uplink.",
            ),
            lambda yes: self._kill_agents(targets) if yes else None,
        )

    def _confirm_approve_all(self, state: AgentState) -> None:
        count = len(state.pending_approvals)
        if not count:
            self._write_local("no pending ICE requests")
            return
        self.push_screen(
            ConfirmScreen(
                "OPEN ALL ICE GATES",
                f"Approve {count} pending request{'s' if count != 1 else ''} once "
                f"for {state.config.name}?",
            ),
            lambda yes: self._approve_all(state) if yes else None,
        )

    @work(exclusive=False)
    async def _approve_all(self, state: AgentState) -> None:
        results = await self.manager.respond_all_approvals(state, "accept")
        approved = sum(error is None for _, error in results)
        failures = [
            f"{approval.request_id}: {error}" for approval, error in results if error is not None
        ]
        message = f"ICE BATCH // {approved}/{len(results)} GATES OPENED ONCE"
        if failures:
            message += "\nFAILED // " + "\n".join(failures)
        state.transcript.append(TranscriptEntry("system", message))
        self._refresh_all()
        self.call_after_refresh(lambda: self._restore_ice_input(state))

    @work(exclusive=False)
    async def _kill_agents(self, targets: list[AgentState]) -> None:
        results: list[str] = []
        for target in targets:
            try:
                await self.manager.disconnect(target)
                results.append(f"{target.config.name} [{target.config.provider.upper()}]: KILLED")
            except Exception as exc:  # noqa: BLE001
                results.append(
                    f"{target.config.name} [{target.config.provider.upper()}]: FAILED // {exc}"
                )
        self._sync_agent_list()
        self._write_local("KILL SUMMARY\n" + "\n".join(results))
        self._refresh_all()

    @work(exclusive=False)
    async def _load_older(self, state: AgentState) -> None:
        try:
            await self.manager.load_older(state)
        except Exception as exc:  # noqa: BLE001
            self._write_local(f"history load failed: {exc}")
        self._render_active(follow_end=False)

    @work(exclusive=False)
    async def _compact_context(self, state: AgentState) -> None:
        state.transcript.append(
            TranscriptEntry("system", "MNEMONIC COMPRESSION // CONTEXT COMPACTION STARTED")
        )
        self._refresh_all()
        try:
            await self.manager.compact_context(state)
        except Exception as exc:  # noqa: BLE001
            state.transcript.append(
                TranscriptEntry(
                    "system",
                    f"CONTEXT COMPACTION FAILED // {exc}\n"
                    "RECOVERY AVAILABLE // run /retry if the uplink was lost",
                )
            )
        else:
            state.transcript.append(
                TranscriptEntry("system", "MNEMONIC COMPRESSION COMPLETE // CONTEXT FREED")
            )
        self._refresh_all()

    def _agent_event(self, state: AgentState, event: AgentEvent) -> None:
        self._track_unread(state, event)
        self._show_event_transition(state, event)
        if self._render_priority_event(state, event):
            return
        if state is not self._active_agent():
            self._refresh_agent_label(state)
            self._update_rails()
            return
        self._refresh_all()

    def receive_agent_event(self, state: AgentState, event: AgentEvent) -> None:
        """Render an event after the manager applies its domain transition."""
        self._agent_event(state, event)

    def _track_unread(self, state: AgentState, event: AgentEvent) -> None:
        if state is not self._active_agent() and event.kind == "assistant_delta":
            message_index = len(state.transcript) - 1
            if message_index >= 0 and state.unread_message_index != message_index:
                state.unread_count += 1
                state.unread_message_index = message_index

    def _show_event_transition(self, state: AgentState, event: AgentEvent) -> None:
        if event.kind == "status":
            if event.text == "ready":
                message = (
                    "CONSTRUCT RESTORED // 記憶復元"
                    if state.restored
                    else "GRID MAPPED // CARRIER STABLE"
                )
                self._show_transition(state, message, "#52e891")
                state.restored = False
            elif event.text in {"processing", "working"}:
                self._show_transition(state, "CONSTRUCT ACTIVE // SIGNAL ENGAGED", "#00e8f2")
        elif event.kind == "approval":
            approval = state.pending_approvals[-1] if state.pending_approvals else None
            level, color = ice_level(state, approval) if approval else ("ICE", "#ff3b4f")
            self._show_transition(state, f"{level} INTERLOCK // 認証待機", color)
        elif event.kind in {"error", "transport_closed"}:
            self._show_transition(state, "GRID FRACTURE // SIGNAL LOST", "#ff3b4f")
            state.transcript.append(
                TranscriptEntry(
                    "system",
                    f"GRID FRACTURE // SIGNAL LOST\n{event.text}\nRECOVERY AVAILABLE // run /retry",
                )
            )

    def _render_priority_event(self, state: AgentState, event: AgentEvent) -> bool:
        if event.kind == "approval" and state is self._active_agent():
            # The approval reveal owns the final scroll position. Avoid racing it
            # against the transcript's ordinary follow-end callback.
            self._refresh_agent_label(state)
            self._render_active(follow_end=False)
            self.call_after_refresh(lambda: self._restore_ice_input(state))
            return True
        if event.kind == "assistant_delta" and state is self._active_agent():
            conversation = self.screen_stack[0].query_one("#conversation", VerticalScroll)
            messages = list(conversation.query(TerminalMessage))
            expected = len(state.transcript)
            if len(messages) < expected:
                conversation.mount(TerminalMessage(state.transcript[-1], state))
            elif messages:
                messages[-1].refresh(layout=True)
            self._refresh_agent_label(state)
            self._update_rails()
            self.call_after_refresh(lambda: conversation.scroll_end(animate=False))
            return True
        return False

    def _reveal_latest_approval(self) -> None:
        approvals = list(self.screen_stack[0].query(ApprovalMessage))
        if approvals:
            approval = approvals[-1]
            approval.scroll_visible(
                animate=False,
                top=True,
                force=True,
                immediate=True,
            )

    def _restore_ice_input(self, state: AgentState) -> None:
        if state is not self._active_agent():
            return
        self._reveal_latest_approval()
        self.screen_stack[0].query_one("#prompt", Input).focus()

    def _approval_decided(
        self, state: AgentState, approval: PendingApproval, decision: str
    ) -> None:
        self._respond_to_approval(state, approval, decision)

    @work(exclusive=False)
    async def _respond_to_approval(
        self, state: AgentState, approval: PendingApproval, decision: str
    ) -> None:
        try:
            await self.manager.respond_approval(state, approval.request_id, decision)
            level, _ = ice_level(state, approval)
            result = {
                "accept": "ICE GATE OPEN // APPROVED ONCE",
                "acceptForSession": "ICE GATE OPEN // SESSION TRUSTED",
                "decline": "ICE SEALED // ACCESS DENIED",
            }[decision]
            state.transcript.append(TranscriptEntry("system", f"{level} // {result}"))
        except Exception as exc:  # noqa: BLE001
            state.transcript.append(TranscriptEntry("system", f"ICE RESPONSE FAILED // {exc}"))
        self._refresh_all()
        self.call_after_refresh(lambda: self._restore_ice_input(state))

    def _refresh_all(self) -> None:
        self._refresh_agent_labels()
        self._render_active()

    def _refresh_agent_labels(self) -> None:
        try:
            view = self.screen_stack[0].query_one("#agents", ListView)
        except (IndexError, NoMatches):
            return
        for state in self.manager.agents:
            try:
                item = view.query_one(f"#{self._agent_row_id(state)}", ListItem)
                item.query_one(Label).update(self._agent_label(state))
            except NoMatches:
                continue

    def _refresh_agent_label(self, state: AgentState) -> None:
        try:
            view = self.screen_stack[0].query_one("#agents", ListView)
            item = view.query_one(f"#{self._agent_row_id(state)}", ListItem)
        except (IndexError, NoMatches):
            return
        item.query_one(Label).update(self._agent_label(state))

    @staticmethod
    def _agent_row_id(state: AgentState) -> str:
        return f"agent-{state.config.id.hex}"

    def _agent_label(self, state: AgentState) -> Text:
        color = {
            AgentStatus.READY: "#52e891",
            AgentStatus.ERROR: "#ff3b4f",
            AgentStatus.FIREWALL_HOLD: "#ff3b4f",
            AgentStatus.RESTORING: "#e9b949",
        }.get(state.status, "#e62acb")
        glyphs = {
            AgentStatus.READY: ("●", "∙", "∙", "∙"),
            AgentStatus.RESTORING: ("↻", "↺", "↻", "↺"),
            AgentStatus.PROCESSING: ("◐", "◓", "◑", "◒"),
            AgentStatus.EXECUTING: ("▰", "▱", "▰", "▱"),
            AgentStatus.EDITING: ("◆", "◇", "◆", "◇"),
            AgentStatus.ERROR: ("×", "×", "×", "×"),
            AgentStatus.FIREWALL_HOLD: ("!", "·", "!", "·"),
        }
        glyph = glyphs.get(state.status, ("◐", "◓", "◑", "◒"))[self._network_phase]
        label = Text()
        label.append(f"{glyph} ", style=f"bold {color}")
        label.append(f"SYN::{state.config.name.upper()}", style=f"bold {color}")
        if state.status is AgentStatus.FIREWALL_HOLD:
            label.append("  ATTN::ICE", style="bold #ff3b4f")
        elif state.status is AgentStatus.ERROR:
            label.append("  ATTN::FAULT", style="bold #ff3b4f")
        elif state.unread_count:
            label.append(f"  ECHO +{state.unread_count}", style="bold #e9b949")
        label.append(f"  {state.status.value}", style="#7a879a")
        if self.deck_config.density == "compact":
            return label
        provider = (state.model_provider or state.config.provider).upper()
        label.append(f"\n  ├─ {provider} / LOCAL", style="#607087")
        label.append(f"\n  └─ {state.config.working_directory.name}", style="#46566c")
        return label

    @staticmethod
    def display_path(path: Path) -> str:
        try:
            return f"~/{path.relative_to(Path.home())}"
        except ValueError:
            return str(path)


def main() -> None:
    from .module_cli import configure_module_parser, run_module_command

    parser = argparse.ArgumentParser(
        prog="cyberdeck",
        description="Open Deck Systems terminal workspace for local AI agents",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")
    configure_module_parser(subparsers)
    args = parser.parse_args()
    if args.command == "module":
        raise SystemExit(run_module_command(args))
    CyberdeckApp().run()


if __name__ == "__main__":
    main()
