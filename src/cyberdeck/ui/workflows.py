"""Keyboard-first inspection of pending input, search, and dispatch outcomes."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Static, TextArea

from ..domain import AgentState, DispatchRun, DispatchTarget, TranscriptEntry
from ..manager import AgentManager


def normalized(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


class SearchPicker(ModalScreen[int | None]):
    """A searchable selector that keeps arrow navigation in its search field."""

    BINDINGS: ClassVar = [
        ("escape", "close", "Close"),
        Binding("up", "previous", show=False, priority=True),
        Binding("down", "next", show=False, priority=True),
        Binding("enter", "accept", "Open", priority=True),
    ]

    def __init__(self, title: str, rows: list[str], query: str = "") -> None:
        super().__init__()
        self.title_text, self.rows, self.query_text = title, rows, query
        self.matches: list[int] = []

    def compose(self) -> ComposeResult:
        with Vertical(classes="workflow-dialog"):
            yield Label(self.title_text)
            yield Input(self.query_text, placeholder="Search…", id="workflow-search")
            yield ListView(id="workflow-list")
            yield Static("↑ ↓ MOVE   ENTER OPEN   ESC RETURN", classes="modal-help")

    def on_mount(self) -> None:
        self._filter(self.query_text)
        self.query_one(Input).focus()

    @on(Input.Changed)
    def search_changed(self, event: Input.Changed) -> None:
        self._filter(event.value)

    def _filter(self, query: str) -> None:
        needle = normalized(query.strip())
        self.matches = [i for i, row in enumerate(self.rows) if needle in normalized(row)]
        view = self.query_one(ListView)
        view.clear()
        view.extend(ListItem(Label(self.rows[i], markup=False)) for i in self.matches)
        view.index = 0 if self.matches else None

    def action_previous(self) -> None:
        self._move(-1)

    def action_next(self) -> None:
        self._move(1)

    def _move(self, offset: int) -> None:
        view = self.query_one(ListView)
        if self.matches:
            view.index = max(0, min(len(self.matches) - 1, (view.index or 0) + offset))

    def action_accept(self) -> None:
        index = self.query_one(ListView).index
        if index is not None and index < len(self.matches):
            self.dismiss(self.matches[index])

    def action_close(self) -> None:
        self.dismiss(None)


class TranscriptSearch(SearchPicker):
    def __init__(self, entries: list[TranscriptEntry], query: str = "") -> None:
        super().__init__(
            "SEARCH // LOADED TRANSCRIPT",
            [
                f"{index + 1}. {entry.role.upper()} {entry.created_at:%H:%M}\n{entry.text}"
                for index, entry in enumerate(entries)
            ],
            query,
        )


class QueueScreen(ModalScreen[None]):
    BINDINGS: ClassVar = [
        ("escape", "close", "Close"),
        Binding("ctrl+s", "save", "Save edit", priority=True),
        Binding("ctrl+d", "remove", "Remove", priority=True),
        Binding("ctrl+up", "earlier", "Earlier", priority=True),
        Binding("ctrl+down", "later", "Later", priority=True),
        Binding("ctrl+r", "resume", "Resume", priority=True),
    ]

    def __init__(self, manager: AgentManager, state: AgentState) -> None:
        super().__init__()
        self.manager, self.state = manager, state
        self.edit_index: int | None = None
        manager.pause_queue(state)

    def compose(self) -> ComposeResult:
        with Vertical(classes="workflow-dialog"):
            yield Label(f"QUEUE // {self.state.config.name} // PAUSED", markup=False)
            yield ListView(id="queue-list")
            yield TextArea("", soft_wrap=True, id="queue-editor")
            with VerticalScroll(id="queue-uncertain"):
                yield Static(
                    "UNCERTAIN // READ ONLY; NEVER REPLAYED\n"
                    + ("\n\n".join(self.state.uncertain_prompts) or "No uncertain deliveries."),
                    markup=False,
                )
            yield Static(
                "ENTER EDIT   ^S SAVE EDIT   ^D REMOVE   ^↑/↓ REORDER\n"
                "TAB CHANGE FOCUS   ^R RESUME   ESC CLOSE (QUEUE STAYS PAUSED)",
                classes="modal-help",
            )

    def on_mount(self) -> None:
        self._rebuild()
        self.query_one("#queue-list", ListView).focus()

    def _rebuild(self, index: int = 0) -> None:
        view = self.query_one("#queue-list", ListView)
        view.clear()
        view.extend(
            ListItem(Label(f"{i + 1}. {text}", markup=False))
            for i, text in enumerate(self.state.queued_prompts)
        )
        view.index = (
            min(index, len(self.state.queued_prompts) - 1) if self.state.queued_prompts else None
        )
        self.edit_index = None
        self.query_one(TextArea).load_text("")

    @on(ListView.Selected, "#queue-list")
    def edit(self, event: ListView.Selected) -> None:
        index = event.list_view.index
        if index is not None and index < len(self.state.queued_prompts):
            self.edit_index = index
            editor = self.query_one(TextArea)
            editor.load_text(self.state.queued_prompts[index])
            editor.focus()

    def action_save(self) -> None:
        if self.edit_index is None:
            return
        try:
            self.manager.edit_queue(self.state, self.edit_index, self.query_one(TextArea).text)
        except (ValueError, IndexError) as exc:
            self.notify(str(exc), severity="error")
            return
        self._rebuild(self.edit_index)
        self.query_one(ListView).focus()

    def action_remove(self) -> None:
        index = self.query_one(ListView).index
        if index is not None:
            self.manager.remove_queued(self.state, index)
            self._rebuild(index)

    def _move(self, offset: int) -> None:
        if self.edit_index is not None:
            self.notify("Save the edit with Ctrl+S before reordering", severity="warning")
            return
        index = self.query_one(ListView).index
        if index is not None:
            self._rebuild(self.manager.move_queued(self.state, index, offset))

    def action_earlier(self) -> None:
        self._move(-1)

    def action_later(self) -> None:
        self._move(1)

    def action_resume(self) -> None:
        if self.edit_index is not None:
            self.notify("Save the edit with Ctrl+S before resuming", severity="warning")
            return
        try:
            self.manager.resume_queue(self.state)
        except ValueError as exc:
            self.notify(str(exc), severity="error")
        else:
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class ResultsScreen(ModalScreen[tuple[str, DispatchRun, DispatchTarget] | None]):
    BINDINGS: ClassVar = [
        ("escape", "close", "Close"),
        Binding("ctrl+r", "retry", "Retry failed target", priority=True),
    ]

    def __init__(self, runs: Callable[[], list[DispatchRun]]) -> None:
        super().__init__()
        self.runs = runs
        self.rows: list[tuple[DispatchRun, DispatchTarget]] = []
        self._signature: tuple = ()

    def compose(self) -> ComposeResult:
        with Vertical(classes="workflow-dialog"):
            yield Label("DISPATCH RESULTS // PER TARGET")
            yield ListView(id="results-list")
            with VerticalScroll(id="results-detail-scroll"):
                yield Static("No dispatches yet.", id="results-detail", markup=False)
            yield Static(
                "↑ ↓ MOVE   ENTER TRANSCRIPT   ^R RETRY FAILED   ESC RETURN", classes="modal-help"
            )

    def on_mount(self) -> None:
        self._refresh()
        self.query_one(ListView).focus()
        self.set_interval(0.5, self._refresh)

    def _refresh(self) -> None:
        rows = [(run, target) for run in reversed(self.runs()) for target in run.targets]
        signature = tuple((run.id, target.agent_id, target.status) for run, target in rows)
        if signature != self._signature:
            view = self.query_one(ListView)
            selected = self._selected()
            self.rows = rows
            view.clear()
            view.extend(
                ListItem(
                    Label(
                        f"{run.created_at:%m-%d %H:%M} {run.id[:8]} // "
                        f"{target.callsign} [{target.provider}] {target.status.upper()}",
                        markup=False,
                    )
                )
                for run, target in rows
            )
            view.index = rows.index(selected) if selected in rows else (0 if rows else None)
            self._signature = signature
        self._detail()

    def _selected(self) -> tuple[DispatchRun, DispatchTarget] | None:
        index = self.query_one(ListView).index
        return self.rows[index] if index is not None and index < len(self.rows) else None

    @on(ListView.Highlighted)
    def highlight(self) -> None:
        self._detail()

    def _detail(self) -> None:
        selected = self._selected()
        if selected:
            run, target = selected
            self.query_one("#results-detail", Static).update(
                f"RUN {run.id}\n{target.callsign}: {target.status} // {target.elapsed_seconds:.1f}s\n"
                f"{target.error or ''}\n\nPROMPT\n{run.prompt or '[Not persisted; metadata only]'}"
            )

    @on(ListView.Selected)
    def select(self) -> None:
        selected = self._selected()
        if selected:
            self.dismiss(("open", *selected))

    def action_retry(self) -> None:
        selected = self._selected()
        if selected and not selected[0].prompt:
            self.notify("Original prompt is unavailable after restart", severity="warning")
        elif selected and selected[1].status == "failed":
            self.dismiss(("retry", *selected))
        else:
            self.notify("Select a failed target to retry", severity="warning")

    def action_close(self) -> None:
        self.dismiss(None)
