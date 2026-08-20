from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Static

from ..domain import AgentState, AgentStatus, ThreadSummary
from ..native_agents import NativeAgent, NativeAgentCatalog, discover_native_agents
from ..runtimes import RuntimePreflight


@dataclass(frozen=True, slots=True)
class SpawnRequest:
    callsign: str
    workspace: Path
    runtime: str
    native_agent: str | None = None


class SpawnAgent(ModalScreen[SpawnRequest | None]):
    BINDINGS: ClassVar = [
        ("escape", "cancel", "Cancel"),
        Binding("down", "next_native", "Next agent", show=False, priority=True),
        Binding("up", "previous_native", "Previous agent", show=False, priority=True),
        Binding("enter", "confirm", "Select / launch", show=False, priority=True),
    ]

    def __init__(
        self,
        runtimes: tuple[RuntimePreflight, ...] = (),
        default_runtime: str = "codex",
        *,
        catalog_loader: Callable[[Path], NativeAgentCatalog] = discover_native_agents,
    ) -> None:
        super().__init__()
        self.runtimes = runtimes or (
            RuntimePreflight("codex", "Codex", True, "built-in"),
            RuntimePreflight("kiro", "Kiro", True, "built-in"),
        )
        self.default_runtime = default_runtime
        self.catalog_loader = catalog_loader
        self.catalog = NativeAgentCatalog()
        self._catalog_workspace: Path | None = None
        self.filtered: list[NativeAgent | None] = [None]
        self.selected_native: str | None = None
        self._prefilled_callsign: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="spawn-dialog"):
            yield Label("ODS // INITIALIZE UPLINK", id="spawn-title")
            yield Input(placeholder="Callsign", id="spawn-agent-name")
            yield Input(
                value=str(Path.cwd()), placeholder="Working directory", id="spawn-agent-path"
            )
            yield Input(
                value=self.default_runtime,
                placeholder="Runtime ID",
                id="spawn-provider",
            )
            yield Input(placeholder="Search harness-native agents", id="spawn-native-search")
            yield ListView(id="spawn-native-list")
            yield Static(
                f"ENTER  JACK IN   •   DEFAULT {self.default_runtime.upper()}   •   ESC  ABORT",
                classes="modal-help",
                id="spawn-help",
            )

    def on_mount(self) -> None:
        self._refresh_catalog()

    @on(Input.Changed, "#spawn-agent-path, #spawn-provider, #spawn-native-search")
    def refresh_native_agents(self, event: Input.Changed) -> None:
        self._refresh_catalog(refresh_discovery=event.input.id == "spawn-agent-path")

    def _refresh_catalog(self, *, refresh_discovery: bool = True) -> None:
        workspace = Path(self.query_one("#spawn-agent-path", Input).value).expanduser()
        if refresh_discovery and workspace != self._catalog_workspace:
            self.catalog = (
                self.catalog_loader(workspace) if workspace.is_dir() else NativeAgentCatalog()
            )
            self._catalog_workspace = workspace
        runtime = self.query_one("#spawn-provider", Input).value.strip().casefold()
        term = self.query_one("#spawn-native-search", Input).value.casefold()
        rows = [
            row
            for row in self.catalog.agents
            if row.runtime_id == runtime
            and term in f"{row.native_id} {row.display_name} {row.description}".casefold()
        ]
        self.filtered = [None, *rows]
        view = self.query_one("#spawn-native-list", ListView)
        view.clear()
        runtime_row = next((row for row in self.runtimes if row.runtime_id == runtime), None)
        default_marker = "●" if runtime_row and runtime_row.available else "×"
        if runtime_row is None:
            default_detail = "UNKNOWN RUNTIME"
        elif runtime_row.available:
            default_detail = "provider-owned defaults"
        else:
            default_detail = f"RUNTIME UNAVAILABLE // {runtime_row.detail}"
        view.append(ListItem(Label(f"{default_marker} DEFAULT HARNESS  // {default_detail}")))
        for row in rows:
            marker = "VIEW ONLY" if not row.launch_supported else row.scope.upper()
            view.append(
                ListItem(
                    Label(
                        f"○ {row.display_name}  [{marker}]\n   {row.native_id} // {row.description}"
                    )
                )
            )
        view.index = 0
        self.selected_native = None
        self.query_one("#spawn-help", Static).update(
            f"ENTER  JACK IN   •   DEFAULT {self.default_runtime.upper()}   •   ESC  ABORT"
        )
        diagnostics = [row for row in self.catalog.diagnostics if row.runtime_id == runtime]
        if diagnostics:
            self.query_one("#spawn-help", Static).update(
                f"CATALOG // {len(diagnostics)} INVALID DEFINITION(S) SKIPPED"
            )

    def action_next_native(self) -> None:
        view = self.query_one("#spawn-native-list", ListView)
        view.index = min((view.index or 0) + 1, len(self.filtered) - 1)

    def action_previous_native(self) -> None:
        view = self.query_one("#spawn-native-list", ListView)
        view.index = max((view.index or 0) - 1, 0)

    @on(ListView.Selected, "#spawn-native-list")
    def select_native(self, event: ListView.Selected) -> None:
        index = event.list_view.index
        self._select_native(index)

    def _select_native(self, index: int | None) -> None:
        row = self.filtered[index] if index is not None else None
        if row is not None and not row.launch_supported:
            self.query_one("#spawn-help", Static).update(f"VIEW ONLY // {row.unavailable_reason}")
            return
        self.selected_native = row.native_id if row else None
        name = self.query_one("#spawn-agent-name", Input)
        if row is not None and (not name.value or name.value == self._prefilled_callsign):
            name.value = row.display_name
            self._prefilled_callsign = row.display_name
        name.focus()

    def action_confirm(self) -> None:
        if self.focused in {
            self.query_one("#spawn-native-search", Input),
            self.query_one("#spawn-native-list", ListView),
        }:
            self._select_native(self.query_one("#spawn-native-list", ListView).index)
        else:
            self.submit()

    @on(Input.Submitted)
    def submit(self) -> None:
        name = self.query_one("#spawn-agent-name", Input).value.strip()
        path = Path(self.query_one("#spawn-agent-path", Input).value).expanduser().resolve()
        provider = self.query_one("#spawn-provider", Input).value.strip().casefold()
        if not name:
            self.query_one("#spawn-agent-name", Input).focus()
            return
        if not path.is_dir():
            self.query_one("#spawn-help", Static).update("PATH NOT FOUND // RETRY")
            return
        runtime = next((row for row in self.runtimes if row.runtime_id == provider), None)
        if runtime is None:
            self.query_one("#spawn-help", Static).update("UNKNOWN RUNTIME // SELECT LISTED ID")
            self.query_one("#spawn-provider", Input).focus()
            return
        if not runtime.available:
            self.query_one("#spawn-help", Static).update(f"RUNTIME UNAVAILABLE // {runtime.detail}")
            return
        self.dismiss(SpawnRequest(name, path, provider, self.selected_native))

    def action_cancel(self) -> None:
        self.dismiss(None)


class ToggleSearchInput(Input):
    """Filter input whose Space key toggles the highlighted result."""

    BINDINGS: ClassVar = [Binding("space", "toggle_result", "Select", show=False, priority=True)]

    def action_toggle_result(self) -> None:
        toggle = getattr(self.screen, "action_toggle", None)
        if callable(toggle):
            toggle()


class RestoreScreen(ModalScreen[list[tuple[ThreadSummary, str]]]):
    """Searchable, multi-select archive picker. Space toggles; Enter restores."""

    BINDINGS: ClassVar = [
        ("escape", "cancel", "Cancel"),
        Binding("enter", "restore", "Restore", priority=True),
    ]

    def __init__(self, threads: list[ThreadSummary]) -> None:
        super().__init__()
        self.threads = threads
        self.filtered = threads
        self.selected: set[str] = set()

    def compose(self) -> ComposeResult:
        with Vertical(id="restore-dialog"):
            yield Label("ARCHIVE UPLINK // NON-ARCHIVED INTERACTIVE THREADS", id="restore-title")
            yield ToggleSearchInput(
                placeholder="SEARCH callsign / project / transcript",
                id="restore-search",
            )
            yield ListView(id="restore-list")
            yield Input(placeholder="Callsign for selected unnamed thread", id="restore-name")
            yield Static("SPACE  SELECT   ENTER  RESTORE   ESC  ABORT", id="restore-help")

    def on_mount(self) -> None:
        self._rebuild()
        self.query_one("#restore-search", Input).focus()

    @on(Input.Changed, "#restore-search")
    def search(self, event: Input.Changed) -> None:
        term = event.value.casefold()
        self.filtered = [
            t
            for t in self.threads
            if term in " ".join((t.name or "", t.source, str(t.cwd), t.preview)).casefold()
        ]
        self._rebuild()

    def _rebuild(self) -> None:
        view = self.query_one("#restore-list", ListView)
        view.clear()
        for thread in self.filtered:
            mark = "×" if thread.is_open else ("◆" if thread.id in self.selected else "◇")
            age = thread.updated_at.strftime("%Y-%m-%d %H:%M")
            name = thread.name or "<CALLSIGN REQUIRED>"
            lock = "  [ALREADY OPEN]" if thread.is_open else ""
            text = f"{mark} {name}  [{thread.source}]  {thread.cwd.name}{lock}\n   {age}  {thread.preview}"
            view.append(ListItem(Label(text)))
        if self.filtered:
            view.index = 0

    def action_toggle(self) -> None:
        view = self.query_one("#restore-list", ListView)
        if view.index is None or view.index >= len(self.filtered):
            return
        thread = self.filtered[view.index]
        if thread.is_open:
            self.query_one("#restore-help", Static).update("THREAD ALREADY OPEN // SELECT ANOTHER")
            return
        self.selected.symmetric_difference_update({thread.id})
        index = view.index
        self._rebuild()
        view.index = index

    def _move_result(self, direction: int) -> None:
        if not self.filtered or not self.query_one("#restore-search", Input).has_focus:
            return
        view = self.query_one("#restore-list", ListView)
        current = view.index if view.index is not None else 0
        view.index = max(0, min(len(self.filtered) - 1, current + direction))

    def action_previous_result(self) -> None:
        self._move_result(-1)

    def action_next_result(self) -> None:
        self._move_result(1)

    def action_restore(self) -> None:
        # Enter in the search field first selects the highlighted row.
        chosen = [thread for thread in self.threads if thread.id in self.selected]
        if not chosen:
            self.action_toggle()
            return
        unnamed = [thread for thread in chosen if not thread.name]
        supplied = self.query_one("#restore-name", Input).value.strip()
        if unnamed and (len(unnamed) > 1 or not supplied):
            self.query_one("#restore-help", Static).update(
                "SELECT ONE UNNAMED THREAD AND ENTER A CALLSIGN"
            )
            self.query_one("#restore-name", Input).focus()
            return
        self.dismiss([(thread, thread.name or supplied) for thread in chosen])

    def action_cancel(self) -> None:
        self.dismiss([])


class OperativeControl(ModalScreen[tuple[str, str | None] | None]):
    BINDINGS: ClassVar = [("escape", "cancel", "Close")]
    ACTIONS = ("rename", "interrupt", "retry", "disconnect", "archive")

    def __init__(self, agent: AgentState) -> None:
        super().__init__()
        self.agent = agent

    def compose(self) -> ComposeResult:
        with Vertical(id="control-dialog"):
            yield Label(
                f"OPERATIVE CONTROL // SYN::{self.agent.config.name.upper()}",
                id="control-title",
            )
            yield Input(value=self.agent.config.name, placeholder="New callsign", id="control-name")
            yield ListView(
                *(
                    ListItem(
                        Label(
                            action.upper()
                            + (
                                ""
                                if self.agent.capabilities.supports(action)
                                else "  [UNAVAILABLE]"
                            )
                        )
                    )
                    for action in self.ACTIONS
                ),
                id="control-list",
            )
            yield Static("ENTER  EXECUTE   ESC  RETURN", classes="modal-help", id="control-help")

    def on_mount(self) -> None:
        self.query_one("#control-list", ListView).index = 0

    def _move_result(self, direction: int) -> None:
        view = self.query_one("#control-list", ListView)
        current = view.index if view.index is not None else 0
        view.index = max(0, min(len(self.ACTIONS) - 1, current + direction))

    def action_previous_result(self) -> None:
        self._move_result(-1)

    def action_next_result(self) -> None:
        self._move_result(1)

    @on(Input.Submitted, "#control-name")
    def name_submitted(self) -> None:
        self.query_one("#control-list", ListView).action_select_cursor()

    @on(ListView.Selected, "#control-list")
    def selected(self, event: ListView.Selected) -> None:
        index = event.list_view.index
        if index is not None:
            action = self.ACTIONS[index]
            if not self.agent.capabilities.supports(action):
                self.query_one("#control-help", Static).update(
                    f"{self.agent.config.provider.upper()} DOES NOT SUPPORT {action.upper()}"
                )
                return
            name = (
                self.query_one("#control-name", Input).value.strip() if action == "rename" else None
            )
            self.dismiss((action, name))

    def action_cancel(self) -> None:
        self.dismiss(None)


class AgentSwitcher(ModalScreen[AgentState | None]):
    BINDINGS: ClassVar = [
        ("escape", "cancel", "Close"),
        ("enter", "choose", "Switch"),
    ]

    def __init__(self, agents: list[AgentState], active: AgentState | None) -> None:
        super().__init__()
        self.agents, self.filtered, self.active = agents, agents, active

    def compose(self) -> ComposeResult:
        with Vertical(id="switch-dialog"):
            yield Label("UPLINK MATRIX // AGENT SWITCHER", id="switch-title")
            yield Input(placeholder="SEARCH callsign / project / cwd / status", id="switch-search")
            yield ListView(id="switch-list")
            yield Static("ENTER  SWITCH   ESC  RETURN", classes="modal-help")

    def on_mount(self) -> None:
        self._rebuild()
        self.query_one("#switch-search", Input).focus()

    @on(Input.Changed, "#switch-search")
    def search(self, event: Input.Changed) -> None:
        term = event.value.casefold()
        self.filtered = [
            a
            for a in self.agents
            if term
            in " ".join(
                (
                    a.config.name,
                    a.model_provider,
                    a.config.working_directory.name,
                    str(a.config.working_directory),
                    a.status.value,
                )
            ).casefold()
        ]
        self._rebuild()

    def _rebuild(self) -> None:
        view = self.query_one("#switch-list", ListView)
        view.clear()
        for agent in self.filtered:
            active = " [ACTIVE]" if agent is self.active else ""
            provider = (agent.model_provider or agent.config.provider).upper()
            view.append(
                ListItem(
                    Label(
                        f"SYN::{agent.config.name.upper()}  {agent.status.value.upper()}{active}\n"
                        f"  {provider} / LOCAL  ─  {agent.config.working_directory}"
                    )
                )
            )
        if self.filtered:
            view.index = 0

    def action_choose(self) -> None:
        index = self.query_one("#switch-list", ListView).index
        if index is not None and index < len(self.filtered):
            self.dismiss(self.filtered[index])

    @on(Input.Submitted, "#switch-search")
    def search_submitted(self) -> None:
        self.action_choose()

    def _move_result(self, direction: int) -> None:
        if not self.filtered:
            return
        view = self.query_one("#switch-list", ListView)
        current = view.index if view.index is not None else 0
        view.index = max(0, min(len(self.filtered) - 1, current + direction))

    def action_previous_result(self) -> None:
        self._move_result(-1)

    def action_next_result(self) -> None:
        self._move_result(1)

    def action_cancel(self) -> None:
        self.dismiss(None)


class DispatchScreen(ModalScreen[tuple[list[AgentState], str] | None]):
    BINDINGS: ClassVar = [
        ("escape", "cancel", "Close"),
        ("ctrl+enter", "transmit", "Transmit"),
    ]

    def __init__(self, agents: list[AgentState]) -> None:
        super().__init__()
        self.agents, self.filtered, self.selected = agents, agents, set()

    def compose(self) -> ComposeResult:
        with Vertical(id="dispatch-dialog"):
            yield Label("SIGNAL MULTIPLEXER // GUARDED DISPATCH", id="dispatch-title")
            yield ToggleSearchInput(placeholder="SEARCH targets", id="dispatch-search")
            yield ListView(id="dispatch-list")
            yield Input(placeholder="Signal payload", id="dispatch-prompt")
            yield Static("SPACE  SELECT   CTRL+ENTER  TRANSMIT   ESC  ABORT", id="dispatch-help")

    def on_mount(self) -> None:
        self._rebuild()
        self.query_one("#dispatch-search", Input).focus()

    @on(Input.Changed, "#dispatch-search")
    def search(self, event: Input.Changed) -> None:
        term = event.value.casefold()
        self.filtered = [
            a
            for a in self.agents
            if term
            in " ".join((a.config.name, str(a.config.working_directory), a.status.value)).casefold()
        ]
        self._rebuild()

    def _rebuild(self) -> None:
        view = self.query_one("#dispatch-list", ListView)
        view.clear()
        for agent in self.filtered:
            mark = "◆" if agent.config.id in self.selected else "◇"
            view.append(
                ListItem(
                    Label(
                        f"{mark} SYN::{agent.config.name.upper()}  "
                        f"[{agent.status.value.upper()}]  {agent.config.working_directory.name}"
                    )
                )
            )
        if self.filtered:
            view.index = 0

    def action_toggle(self) -> None:
        view = self.query_one("#dispatch-list", ListView)
        index = view.index
        if index is None or index >= len(self.filtered):
            return
        self.selected.symmetric_difference_update({self.filtered[index].config.id})
        self._rebuild()
        view.index = index

    def _move_result(self, direction: int) -> None:
        if not self.filtered or not self.query_one("#dispatch-search", Input).has_focus:
            return
        view = self.query_one("#dispatch-list", ListView)
        current = view.index if view.index is not None else 0
        view.index = max(0, min(len(self.filtered) - 1, current + direction))

    def action_previous_result(self) -> None:
        self._move_result(-1)

    def action_next_result(self) -> None:
        self._move_result(1)

    @on(Input.Submitted, "#dispatch-search")
    def search_submitted(self) -> None:
        self.action_toggle()

    def action_transmit(self) -> None:
        targets = [a for a in self.agents if a.config.id in self.selected]
        prompt = self.query_one("#dispatch-prompt", Input).value.strip()
        if len(targets) < 2 or not prompt:
            self.query_one("#dispatch-help", Static).update("SELECT 2+ TARGETS AND ENTER A SIGNAL")
            return
        blocked = [
            f"{a.config.name}:{a.status.value.upper()}"
            for a in targets
            if a.status is not AgentStatus.READY
        ]
        if blocked:
            self.query_one("#dispatch-help", Static).update("BLOCKED // " + ", ".join(blocked))
            return
        self.dismiss((targets, prompt))

    def action_cancel(self) -> None:
        self.dismiss(None)
