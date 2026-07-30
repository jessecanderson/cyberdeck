from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

from rich import box
from rich.console import Group
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView, Static

from ..domain import AgentState, OperationEntry, PendingApproval, TranscriptEntry


def ice_level(agent: AgentState, approval: PendingApproval) -> tuple[str, str]:
    """Classify an approval for display; the provider remains the authority."""
    params = approval.params
    tool_call = params.get("toolCall") if isinstance(params.get("toolCall"), dict) else {}
    raw_input = tool_call.get("rawInput") if isinstance(tool_call.get("rawInput"), dict) else {}
    command = str(
        params.get("command") or raw_input.get("command") or tool_call.get("title") or ""
    ).casefold()
    dangerous = (
        "rm -rf",
        "sudo ",
        "git reset --hard",
        "git clean -f",
        "mkfs",
        "dd if=",
        "chmod -r",
        "chown -r",
        "> /dev/",
    )
    if any(pattern in command for pattern in dangerous) or (
        ("curl " in command or "wget " in command) and "|" in command
    ):
        return "BLACK ICE", "#ff243b"
    grant_root = params.get("grantRoot")
    if grant_root:
        try:
            Path(grant_root).expanduser().resolve().relative_to(agent.config.working_directory)
        except (OSError, RuntimeError, ValueError):
            return "BLACK ICE", "#ff243b"
    if approval.method == "item/commandExecution/requestApproval":
        return "GRAY ICE", "#e9b949"
    return "WHITE ICE", "#00e8f2"


class ApprovalMessage(Static):
    can_focus = False

    def __init__(self, agent: AgentState, approval: PendingApproval) -> None:
        self.agent, self.approval = agent, approval
        level, _ = ice_level(agent, approval)
        super().__init__(classes=f"approval-message {level.lower().replace(' ', '-')}")

    def render(self):
        params = self.approval.params
        tool_call = params.get("toolCall") if isinstance(params.get("toolCall"), dict) else {}
        raw_input = tool_call.get("rawInput") if isinstance(tool_call.get("rawInput"), dict) else {}
        options = [option for option in params.get("options") or [] if isinstance(option, dict)]
        level, color = ice_level(self.agent, self.approval)
        is_command = self.approval.method == "item/commandExecution/requestApproval"
        details = Text()
        for label, value in (
            ("OPERATIVE", self.agent.config.name.upper()),
            (
                "ACTION",
                tool_call.get("title") or ("EXECUTE COMMAND" if is_command else "MODIFY FILES"),
            ),
            (
                "TARGET",
                params.get("command")
                or raw_input.get("command")
                or params.get("grantRoot")
                or "workspace files",
            ),
            ("PATH", params.get("cwd") or str(self.agent.config.working_directory)),
            ("REASON", params.get("reason") or "Agent operation requires authorization"),
        ):
            details.append(f"{label:<10}", style=f"bold {color}")
            details.append(f"{value}\n", style="#f4d8dc")
        if options:
            offered = ", ".join(
                str(option.get("name") or option.get("kind") or option.get("optionId"))
                for option in options
            )
            details.append(f"{'OPTIONS':<10}", style=f"bold {color}")
            details.append(f"{offered}\n", style="#f4d8dc")
        actions = Text(
            "/approve   /trust   /deny   /approve all",
            style=f"bold {color}",
        )
        actions.justify = "center"
        return Panel(
            Group(details, Text(""), actions),
            title=f"{level} // ICE GATE // AUTHORIZATION REQUIRED",
            box=box.DOUBLE,
            border_style=color,
            padding=(0, 1),
        )


def _move_focused_list(view: ListView, direction: int) -> None:
    if not view.children:
        return
    current = view.index if view.index is not None else 0
    view.index = max(0, min(len(view.children) - 1, current + direction))


def trace_class(operation: OperationEntry) -> str:
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


class TerminalMessage(Static):
    def __init__(self, entry: TranscriptEntry, state: AgentState | None) -> None:
        self.entry, self.agent = entry, state
        super().__init__()

    def render(self):
        entry, state = self.entry, self.agent
        time = entry.created_at.strftime("%H:%M:%S")
        if entry.role == "user" and state:
            identity, style = "YOU ▶", "bold #e62acb"
        elif entry.role == "assistant" and state:
            identity, style = f"{state.config.name.upper()} ▶", "bold #cce7ed"
        else:
            identity, style = "SYS ▶", "bold #e9b949"
        lines = entry.text.splitlines() or [""]
        structured = len(lines) > 1 and lines[0].lstrip().startswith(("```", "#", "- ", "* "))
        prefix = Text(f"{time} ", style="bold #72d900")
        prefix.append(identity, style=style)
        prefix.append("" if structured else f" {lines[0]}", style="#d7faff")
        if len(lines) == 1:
            return prefix
        # Markdown supplies restrained headings/lists, links and highlighted fenced code.
        markdown = entry.text if structured else "\n".join(lines[1:])
        return Group(prefix, Padding(Markdown(markdown), (0, 0, 0, len(time) + 2)))


class TranscriptSelection(ModalScreen[list[TranscriptEntry] | None]):
    """Keyboard-only whole-message selection; transcript entries are never mutated."""

    BINDINGS: ClassVar = [
        Binding("up", "previous", "Previous", priority=True),
        Binding("down", "next", "Next", priority=True),
        Binding("space", "toggle", "Select", priority=True),
        Binding("enter", "confirm", "Copy", priority=True),
        Binding("escape", "cancel", "Cancel", priority=True),
    ]

    def __init__(self, entries: list[TranscriptEntry]) -> None:
        super().__init__()
        self.entries = entries
        self.selected: set[int] = set()

    def compose(self) -> ComposeResult:
        with Vertical(id="transcript-select-dialog"):
            yield Label("TRANSCRIPT SELECT // WHOLE MESSAGES", id="transcript-select-title")
            yield ListView(id="transcript-select-list")
            yield Static(
                "↑↓ MOVE   SPACE SELECT   ENTER COPY   ESC CANCEL",
                classes="modal-help",
            )

    def on_mount(self) -> None:
        self._rebuild(0)
        self.query_one("#transcript-select-list", ListView).focus()

    def _rebuild(self, index: int | None = None) -> None:
        view = self.query_one("#transcript-select-list", ListView)
        view.clear()
        for position, entry in enumerate(self.entries):
            mark = "◆" if position in self.selected else "◇"
            preview = entry.text.replace("\n", " ↵ ")
            view.append(ListItem(Label(f"{mark} {entry.role.upper():<9} {preview}")))
        if self.entries:
            view.index = min(index or 0, len(self.entries) - 1)

    def action_previous(self) -> None:
        _move_focused_list(self.query_one("#transcript-select-list", ListView), -1)

    def action_next(self) -> None:
        _move_focused_list(self.query_one("#transcript-select-list", ListView), 1)

    def action_toggle(self) -> None:
        view = self.query_one("#transcript-select-list", ListView)
        if view.index is None:
            return
        index = view.index
        self.selected.symmetric_difference_update({index})
        self._rebuild(index)

    def action_confirm(self) -> None:
        if self.selected:
            self.dismiss([self.entries[index] for index in sorted(self.selected)])

    def action_cancel(self) -> None:
        self.dismiss(None)


class EmptyGrid(Static):
    def render(self) -> Group:
        return Group(
            Text("LOCAL GRID // NO OPERATIVES", style="bold #00e8f2"),
            Text("\nNo active constructs are mapped to this deck.", style="#607087"),
            Text("\n\n^N  INITIALIZE UPLINK", style="bold #52e891"),
            Text("\n^R  OPEN ARCHIVE", style="#8ba2b3"),
            Text("\n\n待機中 // AWAITING OPERATOR", style="#283748"),
        )


class OperationDetail(ModalScreen[None]):
    BINDINGS: ClassVar = [("escape", "close", "Close")]

    def __init__(self, operation: OperationEntry) -> None:
        super().__init__()
        self.operation = operation

    def compose(self) -> ComposeResult:
        op = self.operation
        fields = [
            "GRID TRACE // OPERATION DETAIL",
            "",
            f"CLASS      {trace_class(op)}",
            f"TYPE       {op.kind}",
            f"STATE      {op.state.value}",
            f"SUMMARY    {op.summary}",
        ]
        for label, value in (
            ("CWD", op.cwd),
            ("DURATION", f"{op.duration_ms} ms" if op.duration_ms else None),
            ("EXIT CODE", op.exit_code),
            ("FILES", ", ".join(op.files) or None),
            ("ERROR", op.error),
        ):
            if value is not None:
                fields.append(f"{label:<10} {value}")
        body: list[object] = [Text("\n".join(fields))]
        if op.command:
            body += [Text("\nCOMMAND", style="bold #00f5ff"), Syntax(op.command, "bash")]
        if op.arguments:
            body += [
                Text("\nARGUMENTS", style="bold #00f5ff"),
                Syntax(json.dumps(op.arguments, indent=2), "json"),
            ]
        if op.diff:
            body += [Text("\nDIFF", style="bold #00f5ff"), Syntax(op.diff, "diff")]
        if op.output:
            body += [Text("\nOUTPUT", style="bold #00f5ff"), Text(op.output)]
        with VerticalScroll(id="operation-detail"):
            yield Static(Group(*body))
            yield Static("ESC  RETURN TO OPERATIONS", classes="modal-help")

    def on_mount(self) -> None:
        self.query_one("#operation-detail", VerticalScroll).focus()

    def action_close(self) -> None:
        self.dismiss(None)
