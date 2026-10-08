"""Incremental transcript and operation presentation."""

from __future__ import annotations

from textual.containers import VerticalScroll
from textual.widgets import Label, ListItem, ListView, Static

from ..domain import AgentState, OperationEntry, TranscriptEntry
from .transcript import ApprovalMessage, EmptyGrid, TerminalMessage


class ConversationView(VerticalScroll):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._identity: object = None
        self._positions: dict[object, float] = {}
        self._entries: list[TranscriptEntry] = []
        self._messages: list[TerminalMessage] = []
        self._texts: list[str] = []
        self._decorations: tuple = ()

    def reading_position(self, state: AgentState | None) -> float:
        identity = state.config.id if state else None
        if identity != self._identity:
            self._positions[self._identity] = self.scroll_y
            return self._positions.get(identity, 0.0)
        return self.scroll_y

    def show_entries(self, state: AgentState | None, entries: list[TranscriptEntry]) -> None:
        identity = state.config.id if state else None
        decorations = (
            state.history_cursor if state else None,
            tuple(id(approval) for approval in state.pending_approvals) if state else (),
            not entries and state is None,
        )
        prefix = len(entries) >= len(self._entries) and all(
            left is right for left, right in zip(self._entries, entries)
        )
        if identity != self._identity or decorations != self._decorations or not prefix:
            self.remove_children()
            self._entries, self._messages, self._texts = [], [], []
            if not state and not entries:
                self.mount(EmptyGrid())
            if state and state.history_cursor:
                self.mount(Static("↑ LOAD OLDER TURNS  //  /older", classes="load-older"))
            self._identity, self._decorations = identity, decorations
            for entry in entries:
                self._append(entry, state)
            if state:
                for approval in state.pending_approvals:
                    self.mount(ApprovalMessage(state, approval))
            return
        for index, entry in enumerate(entries[: len(self._entries)]):
            if entry.text != self._texts[index]:
                self._messages[index].refresh(layout=True)
                self._texts[index] = entry.text
        for entry in entries[len(self._entries) :]:
            self._append(entry, state)

    def _append(self, entry: TranscriptEntry, state: AgentState | None) -> None:
        message = TerminalMessage(entry, state)
        self.mount(message)
        self._entries.append(entry)
        self._messages.append(message)
        self._texts.append(entry.text)


def operation_label(operation: OperationEntry) -> str:
    glyph, phase = {
        "succeeded": ("✓", "CLEAR"),
        "failed": ("!", "FAULT"),
        "approval": ("?", "INTERLOCK"),
        "running": ("◐", "ACTIVE"),
        "pending": ("○", "QUEUED"),
    }[operation.state.value]
    trace = {
        "commandExecution": "TRACE",
        "fileChange": "PATCH",
        "mcpToolCall": "PROBE",
        "dynamicToolCall": "PROBE",
        "webSearch": "SCAN",
    }.get(operation.kind, "SIGNAL")
    if operation.state.value == "approval":
        trace = "ICE"
    elif operation.state.value == "failed":
        trace = "FAULT"
    return (
        f"{operation.created_at:%H:%M:%S}  {trace:<7} {phase:<9} {glyph} "
        f"{operation.kind:<16} {operation.summary}"
    )


class OperationsView(ListView):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.shown_operations: list[OperationEntry] = []
        self._labels: list[str] = []
        self._widgets: list[Label] = []
        self._identity: object = None

    def show_operations(self, state: AgentState | None, filter_by: str = "all") -> None:
        operations = state.operations if state else []
        if filter_by == "failed":
            operations = [op for op in operations if op.state.value == "failed"]
        elif filter_by == "files":
            operations = [op for op in operations if op.kind == "fileChange"]
        labels = [operation_label(op) for op in operations]
        identity = (state.config.id if state else None, filter_by)
        if identity != self._identity or len(labels) < len(self._labels):
            self.clear()
            self._labels = []
            self._widgets = []
            self._identity = identity
        for index, label in enumerate(labels[: len(self._labels)]):
            if self._labels[index] != label:
                self._widgets[index].update(label)
        for label in labels[len(self._labels) :]:
            widget = Label(label, markup=False)
            self._widgets.append(widget)
            self.append(ListItem(widget))
        self._labels = labels
        self.shown_operations = list(operations)
