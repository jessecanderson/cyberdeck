from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Static

from ..domain import AgentState, AgentStatus, ThreadSummary
from ..runtimes import RuntimePreflight


class SpawnAgent(ModalScreen[tuple[str, Path, str] | None]):
    BINDINGS: ClassVar = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        runtimes: tuple[RuntimePreflight, ...] = (),
        default_runtime: str = "codex",
    ) -> None:
        super().__init__()
        self.runtimes = runtimes or (
            RuntimePreflight("codex", "Codex", True, "built-in"),
            RuntimePreflight("kiro", "Kiro", True, "built-in"),
        )
        self.default_runtime = default_runtime

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
            yield Static(
                "\n".join(
                    f"{'●' if row.available else '×'} {row.runtime_id:<12} "
                    f"{row.label} // {row.version or row.detail}"
                    for row in self.runtimes
                ),
                id="spawn-runtimes",
            )
            yield Static(
                f"ENTER  JACK IN   •   DEFAULT {self.default_runtime.upper()}   •   ESC  ABORT",
                classes="modal-help",
                id="spawn-help",
            )

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
        self.dismiss((name, path, provider))

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
