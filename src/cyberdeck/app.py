from __future__ import annotations

import asyncio
import getpass
import json
import random
import shlex
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from rich import box
from rich.console import Group
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen, Screen
from textual.widgets import Input, Label, ListItem, ListView, Static

from .domain import AgentState, AgentStatus, OperationEntry, ThreadSummary, TranscriptEntry
from .manager import AgentManager
from .providers import AgentEvent


class BootScreen(Screen[None]):
    BINDINGS: ClassVar = [("enter", "skip", "Skip"), ("escape", "skip", "Skip")]
    POST_SPEED: ClassVar = 1.3
    BOOT_LINES: ClassVar = [
        ("   ██████╗██╗   ██╗██████╗ ███████╗██████╗ ", "bold #00e8f2", 0.04),
        ("  ██╔════╝╚██╗ ██╔╝██╔══██╗██╔════╝██╔══██╗", "bold #00e8f2", 0.04),
        ("  ██║      ╚████╔╝ ██████╔╝█████╗  ██████╔╝", "bold #00e8f2", 0.04),
        ("  ██║       ╚██╔╝  ██╔══██╗██╔══╝  ██╔══██╗", "bold #00e8f2", 0.04),
        ("  ╚██████╗   ██║   ██████╔╝███████╗██║  ██║", "bold #00e8f2", 0.04),
        ("   ╚═════╝   ╚═╝   ╚═════╝ ╚══════╝╚═╝  ╚═╝", "bold #00e8f2", 0.07),
        ("       ██████╗ ███████╗ ██████╗██╗  ██╗", "bold #e62acb", 0.04),
        ("       ██╔══██╗██╔════╝██╔════╝██║ ██╔╝", "bold #e62acb", 0.04),
        ("       ██║  ██║█████╗  ██║     █████╔╝ ", "bold #e62acb", 0.04),
        ("       ██║  ██║██╔══╝  ██║     ██╔═██╗ ", "bold #e62acb", 0.04),
        ("       ██████╔╝███████╗╚██████╗██║  ██╗", "bold #e62acb", 0.04),
        ("       ╚═════╝ ╚══════╝ ╚═════╝╚═╝  ╚═╝", "bold #e62acb", 0.08),
        ("", "", 0.04),
        ("                 C Y B E R D E C K   2 . 5 . 1", "bold #cce7ed", 0.12),
        ("                OPEN DECK SYSTEMS // ROM REVISION 251", "#607087", 0.24),
        ("", "", 0.06),
        ("CYBERDECK QUANTUM BIOS v0.1.0 // BUILD 2088.07.24-NIGHTLY", "bold #00e8f2", 0.10),
        ("OPEN DECK SYSTEMS // NO WARRANTY // TRUST NO PROCESS", "#607087", 0.12),
        ("", "", 0.04),
        ("[ FIRMWARE ] Initiating power-on self-test", "bold #e62acb", 0.12),
        ("  Mainboard........ ODS NIGHTWAVE Mk IV", "#cce7ed", 0.05),
        ("  Firmware ROM..... checksum 9F:2A:77:CD ............ PASS", "#52e891", 0.06),
        ("  CMOS clock....... synchronized to local reality ... PASS", "#52e891", 0.05),
        ("  Watchdog......... armed at 0xDEADC0DE .............. PASS", "#52e891", 0.05),
        ("  Thermal grid..... 31.4°C / nominal ................ PASS", "#52e891", 0.05),
        ("  Battery.......... 98% / 47h projected ............. PASS", "#52e891", 0.08),
        ("", "", 0.04),
        ("[ COMPUTE ] Enumerating cognition hardware", "bold #e62acb", 0.10),
        ("  CPU0.............. 16-core neural scalar array", "#cce7ed", 0.05),
        ("  CPU1.............. speculative intuition coprocessor", "#cce7ed", 0.05),
        ("  Vector engine..... 8192 lanes online", "#cce7ed", 0.05),
        ("  Memory bank 00.... 128 TB ECC ...................... OK", "#52e891", 0.04),
        ("  Memory bank 01.... 128 TB ECC ...................... OK", "#52e891", 0.04),
        ("  Memory bank 02.... 128 TB ECC ...................... OK", "#52e891", 0.04),
        ("  Memory bank 03.... 128 TB ECC ...................... OK", "#52e891", 0.04),
        ("  Memory bank 04.... 128 TB ECC ...................... OK", "#52e891", 0.05),
        ("  Total memory...... 640 TB / no anomalies detected", "#52e891", 0.08),
        ("", "", 0.04),
        ("[ BUS ] Probing attached systems", "bold #e62acb", 0.10),
        ("  /dev/tty0......... phosphor terminal ............... FOUND", "#52e891", 0.05),
        ("  /dev/entropy...... quantum noise source ............ FOUND", "#52e891", 0.05),
        ("  /dev/mind......... wetware compatibility bridge .... FOUND", "#52e891", 0.05),
        ("  /dev/null......... infinite capacity ................ FOUND", "#52e891", 0.05),
        ("  Agent bus......... 8 virtual slots / 0 occupied", "#cce7ed", 0.06),
        ("  Archive bus....... Codex history bridge ............. FOUND", "#52e891", 0.07),
        ("  Network........... loopback only / stealth mode", "#cce7ed", 0.08),
        ("", "", 0.04),
        ("[ SECURITY ] Establishing containment", "bold #e62acb", 0.10),
        ("  Secure enclave.... challenge accepted ............... PASS", "#52e891", 0.05),
        ("  Workspace roots... access matrix loaded ............. PASS", "#52e891", 0.05),
        ("  Command policy.... approval interlocks armed ......... PASS", "#52e891", 0.05),
        ("  Sandbox walls..... [████████████████████] 100%", "#52e891", 0.07),
        ("  Corporate telemetry................................. ABSENT", "#52e891", 0.08),
        ("", "", 0.04),
        ("[ BOOT ] Searching bootable media", "bold #e62acb", 0.10),
        ("  PXE neural uplink................................. TIMEOUT", "#e9b949", 0.06),
        ("  /dev/nvme0n1p1.... CYBERDECK_CORE ................ VALID", "#52e891", 0.06),
        ("  Bootloader........ NΞON/GRUB 13.37", "#cce7ed", 0.06),
        ("  Selected entry.... CYBERDECK LOCAL AGENT HOST", "bold #00e8f2", 0.12),
        ("", "", 0.04),
        ("[ KERNEL ] Loading /boot/vmlinuz-cyberdeck", "bold #e62acb", 0.09),
        ("  Decompressing kernel [█████░░░░░░░░░░░░░░░]  25%", "#cce7ed", 0.07),
        ("  Decompressing kernel [██████████░░░░░░░░░░]  50%", "#cce7ed", 0.07),
        ("  Decompressing kernel [███████████████░░░░░]  75%", "#cce7ed", 0.07),
        ("  Decompressing kernel [████████████████████] 100%", "#52e891", 0.09),
        ("  Loading module textual.ui ......................... OK", "#52e891", 0.05),
        ("  Loading module asyncio.reactor ..................... OK", "#52e891", 0.05),
        ("  Loading module codex.app_server .................... OK", "#52e891", 0.05),
        ("  Loading module archive.uplink ...................... OK", "#52e891", 0.05),
        ("  Loading module chromatic_aberration ........ EXCESSIVE", "#e9b949", 0.08),
        ("", "", 0.04),
        ("[ SERVICES ] Starting userspace", "bold #e62acb", 0.10),
        ("  [ OK ] Mounted /workspace", "#52e891", 0.05),
        ("  [ OK ] Started local agent supervisor", "#52e891", 0.05),
        ("  [ OK ] Started archive uplink", "#52e891", 0.05),
        ("  [ OK ] Started operations telemetry", "#52e891", 0.05),
        ("  [ OK ] Started transcript renderer", "#52e891", 0.05),
        ("  [ OK ] Reached target cyberdeck.uplink", "#52e891", 0.10),
        ("", "", 0.04),
        ("SYSTEM READY // HANDING CONTROL TO /CYBERDECK/CORE", "bold #00e8f2", 0.22),
    ]

    def compose(self) -> ComposeResult:
        yield Static(id="boot-log")
        yield Static("[ F2 ] BIOS     [ ENTER / ESC ] SKIP POST", id="boot-skip")

    def on_mount(self) -> None:
        self._noise_rng = random.Random()
        self._boot_output: list[tuple[str, str]] = []
        self.set_interval(0.11, self._render_noise)
        self.run_boot_sequence()

    def _render_noise(self) -> None:
        """Repaint POST and phosphor noise into one terminal-cell surface."""
        log = self.query_one("#boot-log", Static)
        width, height = max(log.size.width - 4, 1), max(log.size.height, 1)
        visible = self._boot_output[-height:]
        rows = visible + [("", "")] * (height - len(visible))
        frame = Text()
        glyphs = ("·", "∙", "░", "﹒")
        interference_row = (
            self._noise_rng.randrange(height)
            if width > 24 and self._noise_rng.random() < 0.25
            else -1
        )
        for row_index, (line, style) in enumerate(rows):
            clipped = line[:width]
            frame.append(clipped, style=style)
            remainder = width - len(clipped)
            cells = [" "] * remainder
            for _ in range(max(1, remainder // 90)):
                if cells:
                    cells[self._noise_rng.randrange(len(cells))] = self._noise_rng.choice(glyphs)
            if row_index == interference_row and remainder > 8:
                start = self._noise_rng.randrange(max(1, remainder - 6))
                length = min(self._noise_rng.randrange(4, 12), remainder - start)
                cells[start : start + length] = "─" * length
            frame.append("".join(cells), style="#172936")
            if row_index < height - 1:
                frame.append("\n")
        log.update(frame)

    @work(exclusive=True)
    async def run_boot_sequence(self) -> None:
        for line, style, delay in self.BOOT_LINES:
            self._boot_output.append((line, style))
            self._render_noise()
            await asyncio.sleep(delay * self.POST_SPEED)
        self.dismiss(None)

    def action_skip(self) -> None:
        self.dismiss(None)


class HelpScreen(ModalScreen[None]):
    BINDINGS: ClassVar = [("escape", "close", "Close")]
    HELP_TEXT = """LOCAL COMMANDS

/new [name] [path]   Initialize a new uplink
/restore             Open ARCHIVE UPLINK
/agents              List connected uplinks
/agent               Open OPERATIVE CONTROL
/rename NAME          Persist a new callsign
/interrupt  /retry    Stop a turn / restore an errored uplink
/disconnect /archive  Remove reversibly / archive and remove
/dispatch             Open SIGNAL MULTIPLEXER
/clear  /path        Clear view / show active path
/help  /quit         Reference / shutdown

KEYBOARD

Ctrl+N new   Ctrl+R restore   Ctrl+G control   Ctrl+P switch
Ctrl+B dispatch   Ctrl+O operations
Ctrl+J/K switch uplink   Esc close window   Ctrl+Q quit
"""

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Label("ODS // COMMAND REFERENCE", id="help-title")
            yield Static(self.HELP_TEXT, id="help-content")
            yield Static("ESC  RETURN", classes="modal-help")

    def action_close(self) -> None:
        self.dismiss(None)


class FirewallRequest(ModalScreen[str]):
    BINDINGS: ClassVar = [
        ("a", "authorize", "Authorize once"),
        ("t", "trust", "Trust for session"),
        ("d", "deny", "Deny"),
        ("escape", "deny", "Deny"),
    ]

    def __init__(self, agent: AgentState, event: AgentEvent) -> None:
        super().__init__()
        self.agent, self.event = agent, event

    def compose(self) -> ComposeResult:
        params = self.event.params or {}
        is_command = self.event.method == "item/commandExecution/requestApproval"
        details = Text()
        for label, value in (
            ("PROCESS", f"{self.agent.config.name}@codex"),
            ("ACTION", "EXECUTE COMMAND" if is_command else "MODIFY FILES"),
            ("TARGET", params.get("command") or params.get("grantRoot") or "workspace files"),
            ("PATH", params.get("cwd") or str(self.agent.config.working_directory)),
            ("REASON", params.get("reason") or "Agent operation requires authorization"),
        ):
            details.append(f"{label:<10}", style="bold #ff3b4f")
            details.append(f"{value}\n", style="#f4d8dc")
        actions = Text("[A] AUTHORIZE ONCE   [T] TRUST SESSION   [D] DENY", style="bold #ff3b4f")
        actions.justify = "center"
        yield Static(
            Panel(Group(details, Text(""), actions), title="FIREWALL ACCESS REQUEST", box=box.DOUBLE,
                  border_style="#ff243b", padding=(1, 1)), id="firewall-panel"
        )

    def action_authorize(self) -> None: self.dismiss("accept")
    def action_trust(self) -> None: self.dismiss("acceptForSession")
    def action_deny(self) -> None: self.dismiss("decline")


class SpawnAgent(ModalScreen[tuple[str, Path] | None]):
    BINDINGS: ClassVar = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="spawn-dialog"):
            yield Label("ODS // INITIALIZE UPLINK", id="spawn-title")
            yield Input(placeholder="Callsign", id="agent-name")
            yield Input(value=str(Path.cwd()), placeholder="Working directory", id="agent-path")
            yield Static("ENTER  JACK IN   •   ESC  ABORT", classes="modal-help", id="spawn-help")

    @on(Input.Submitted)
    def submit(self) -> None:
        name = self.query_one("#agent-name", Input).value.strip()
        path = Path(self.query_one("#agent-path", Input).value).expanduser().resolve()
        if not name:
            self.query_one("#agent-name", Input).focus(); return
        if not path.is_dir():
            self.query_one("#spawn-help", Static).update("PATH NOT FOUND // RETRY"); return
        self.dismiss((name, path))

    def action_cancel(self) -> None: self.dismiss(None)


class RestoreScreen(ModalScreen[list[tuple[ThreadSummary, str]]]):
    """Searchable, multi-select archive picker. Space toggles; Enter restores."""
    BINDINGS: ClassVar = [
        ("escape", "cancel", "Cancel"), ("space", "toggle", "Select"),
        ("enter", "restore", "Restore"),
    ]

    def __init__(self, threads: list[ThreadSummary]) -> None:
        super().__init__()
        self.threads = threads
        self.filtered = threads
        self.selected: set[str] = set()

    def compose(self) -> ComposeResult:
        with Vertical(id="restore-dialog"):
            yield Label("ARCHIVE UPLINK // NON-ARCHIVED INTERACTIVE THREADS", id="restore-title")
            yield Input(placeholder="SEARCH callsign / project / transcript", id="restore-search")
            yield ListView(id="restore-list")
            yield Input(placeholder="Callsign for selected unnamed thread", id="restore-name")
            yield Static("SPACE  SELECT   ENTER  RESTORE   ESC  ABORT", id="restore-help")

    def on_mount(self) -> None:
        self._rebuild()
        self.query_one("#restore-search", Input).focus()

    @on(Input.Changed, "#restore-search")
    def search(self, event: Input.Changed) -> None:
        term = event.value.casefold()
        self.filtered = [t for t in self.threads if term in " ".join(
            (t.name or "", t.source, str(t.cwd), t.preview)).casefold()]
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
        if view.index is None or view.index >= len(self.filtered): return
        thread = self.filtered[view.index]
        if thread.is_open:
            self.query_one("#restore-help", Static).update("THREAD ALREADY OPEN // SELECT ANOTHER")
            return
        self.selected.symmetric_difference_update({thread.id})
        index = view.index
        self._rebuild(); view.index = index

    def action_restore(self) -> None:
        # Enter in the search field first selects the highlighted row.
        chosen = [thread for thread in self.threads if thread.id in self.selected]
        if not chosen:
            self.action_toggle(); return
        unnamed = [thread for thread in chosen if not thread.name]
        supplied = self.query_one("#restore-name", Input).value.strip()
        if unnamed and (len(unnamed) > 1 or not supplied):
            self.query_one("#restore-help", Static).update(
                "SELECT ONE UNNAMED THREAD AND ENTER A CALLSIGN"
            )
            self.query_one("#restore-name", Input).focus(); return
        self.dismiss([(thread, thread.name or supplied) for thread in chosen])

    @on(Input.Submitted)
    def submitted(self) -> None:
        self.action_restore()

    def action_cancel(self) -> None: self.dismiss([])


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS: ClassVar = [("y", "yes", "Confirm"), ("n", "no", "Cancel"), ("escape", "no", "Cancel")]

    def __init__(self, title: str, message: str) -> None:
        super().__init__(); self.title_text, self.message = title, message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label(self.title_text, id="confirm-title")
            yield Static(self.message, id="confirm-message")
            yield Static("Y  CONFIRM   N / ESC  ABORT", classes="modal-help")

    def action_yes(self) -> None: self.dismiss(True)
    def action_no(self) -> None: self.dismiss(False)


class OperativeControl(ModalScreen[tuple[str, str | None] | None]):
    BINDINGS: ClassVar = [("escape", "cancel", "Close")]
    ACTIONS = ("rename", "interrupt", "retry", "disconnect", "archive")

    def __init__(self, agent: AgentState) -> None:
        super().__init__(); self.agent = agent

    def compose(self) -> ComposeResult:
        with Vertical(id="control-dialog"):
            yield Label(f"OPERATIVE CONTROL // {self.agent.config.name}", id="control-title")
            yield Input(value=self.agent.config.name, placeholder="New callsign", id="control-name")
            yield ListView(*(ListItem(Label(action.upper())) for action in self.ACTIONS), id="control-list")
            yield Static("ENTER  EXECUTE   ESC  RETURN", classes="modal-help")

    def on_mount(self) -> None: self.query_one("#control-list", ListView).index = 0

    @on(ListView.Selected, "#control-list")
    def selected(self, event: ListView.Selected) -> None:
        index = event.list_view.index
        if index is not None:
            action = self.ACTIONS[index]
            name = self.query_one("#control-name", Input).value.strip() if action == "rename" else None
            self.dismiss((action, name))

    def action_cancel(self) -> None: self.dismiss(None)


class AgentSwitcher(ModalScreen[AgentState | None]):
    BINDINGS: ClassVar = [("escape", "cancel", "Close"), ("enter", "choose", "Switch")]

    def __init__(self, agents: list[AgentState], active: AgentState | None) -> None:
        super().__init__(); self.agents, self.filtered, self.active = agents, agents, active

    def compose(self) -> ComposeResult:
        with Vertical(id="switch-dialog"):
            yield Label("UPLINK MATRIX // AGENT SWITCHER", id="switch-title")
            yield Input(placeholder="SEARCH callsign / project / cwd / status", id="switch-search")
            yield ListView(id="switch-list")
            yield Static("ENTER  SWITCH   ESC  RETURN", classes="modal-help")

    def on_mount(self) -> None: self._rebuild(); self.query_one("#switch-search", Input).focus()

    @on(Input.Changed, "#switch-search")
    def search(self, event: Input.Changed) -> None:
        term = event.value.casefold()
        self.filtered = [a for a in self.agents if term in " ".join((a.config.name, a.config.working_directory.name, str(a.config.working_directory), a.status.value)).casefold()]
        self._rebuild()

    def _rebuild(self) -> None:
        view = self.query_one("#switch-list", ListView); view.clear()
        for agent in self.filtered:
            active = " [ACTIVE]" if agent is self.active else ""
            view.append(ListItem(Label(f"{agent.config.name}  {agent.status.value.upper()}{active}\n  {agent.config.working_directory}")))
        if self.filtered: view.index = 0

    def action_choose(self) -> None:
        index = self.query_one("#switch-list", ListView).index
        if index is not None and index < len(self.filtered): self.dismiss(self.filtered[index])

    def action_cancel(self) -> None: self.dismiss(None)


class DispatchScreen(ModalScreen[tuple[list[AgentState], str] | None]):
    BINDINGS: ClassVar = [("escape", "cancel", "Close"), ("space", "toggle", "Select"), ("ctrl+enter", "transmit", "Transmit")]

    def __init__(self, agents: list[AgentState]) -> None:
        super().__init__(); self.agents, self.filtered, self.selected = agents, agents, set()

    def compose(self) -> ComposeResult:
        with Vertical(id="dispatch-dialog"):
            yield Label("SIGNAL MULTIPLEXER // GUARDED DISPATCH", id="dispatch-title")
            yield Input(placeholder="SEARCH targets", id="dispatch-search")
            yield ListView(id="dispatch-list")
            yield Input(placeholder="Signal payload", id="dispatch-prompt")
            yield Static("SPACE  SELECT   CTRL+ENTER  TRANSMIT   ESC  ABORT", id="dispatch-help")

    def on_mount(self) -> None: self._rebuild(); self.query_one("#dispatch-search", Input).focus()

    @on(Input.Changed, "#dispatch-search")
    def search(self, event: Input.Changed) -> None:
        term = event.value.casefold()
        self.filtered = [a for a in self.agents if term in " ".join((a.config.name, str(a.config.working_directory), a.status.value)).casefold()]
        self._rebuild()

    def _rebuild(self) -> None:
        view = self.query_one("#dispatch-list", ListView); view.clear()
        for agent in self.filtered:
            mark = "◆" if agent.config.id in self.selected else "◇"
            view.append(ListItem(Label(f"{mark} {agent.config.name}  [{agent.status.value.upper()}]  {agent.config.working_directory.name}")))
        if self.filtered: view.index = 0

    def action_toggle(self) -> None:
        view = self.query_one("#dispatch-list", ListView); index = view.index
        if index is None or index >= len(self.filtered): return
        self.selected.symmetric_difference_update({self.filtered[index].config.id}); self._rebuild(); view.index = index

    def action_transmit(self) -> None:
        targets = [a for a in self.agents if a.config.id in self.selected]
        prompt = self.query_one("#dispatch-prompt", Input).value.strip()
        if len(targets) < 2 or not prompt:
            self.query_one("#dispatch-help", Static).update("SELECT 2+ TARGETS AND ENTER A SIGNAL")
            return
        blocked = [f"{a.config.name}:{a.status.value.upper()}" for a in targets if a.status is not AgentStatus.READY]
        if blocked:
            self.query_one("#dispatch-help", Static).update("BLOCKED // " + ", ".join(blocked)); return
        self.dismiss((targets, prompt))

    def action_cancel(self) -> None: self.dismiss(None)


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
        prefix = Text(f"{time} ", style="bold #72d900"); prefix.append(identity, style=style)
        prefix.append("" if structured else f" {lines[0]}", style="#d7faff")
        if len(lines) == 1:
            return prefix
        # Markdown supplies restrained headings/lists, links and highlighted fenced code.
        markdown = entry.text if structured else "\n".join(lines[1:])
        return Group(prefix, Padding(Markdown(markdown), (0, 0, 0, len(time) + 2)))


class OperationDetail(ModalScreen[None]):
    BINDINGS: ClassVar = [("escape", "close", "Close")]
    def __init__(self, operation: OperationEntry) -> None:
        super().__init__(); self.operation = operation
    def compose(self) -> ComposeResult:
        op = self.operation
        fields = [f"TYPE       {op.kind}", f"STATE      {op.state.value}",
                  f"SUMMARY    {op.summary}"]
        for label, value in (("CWD", op.cwd), ("DURATION", f"{op.duration_ms} ms" if op.duration_ms else None),
                             ("EXIT CODE", op.exit_code), ("FILES", ", ".join(op.files) or None),
                             ("ERROR", op.error)):
            if value is not None: fields.append(f"{label:<10} {value}")
        body: list[object] = [Text("\n".join(fields))]
        if op.command: body += [Text("\nCOMMAND", style="bold #00f5ff"), Syntax(op.command, "bash")]
        if op.arguments: body += [Text("\nARGUMENTS", style="bold #00f5ff"), Syntax(json.dumps(op.arguments, indent=2), "json")]
        if op.diff: body += [Text("\nDIFF", style="bold #00f5ff"), Syntax(op.diff, "diff")]
        if op.output: body += [Text("\nOUTPUT", style="bold #00f5ff"), Text(op.output)]
        with VerticalScroll(id="operation-detail"):
            yield Static(Group(*body))
            yield Static("ESC  RETURN TO OPERATIONS", classes="modal-help")
    def action_close(self) -> None: self.dismiss(None)


class CyberdeckApp(App[None]):
    CSS_PATH = "cyberdeck.tcss"
    TITLE = "CYBERDECK"
    BINDINGS: ClassVar = [
        ("ctrl+n", "spawn_agent", "New"), ("ctrl+r", "restore", "Restore"),
        ("ctrl+o", "operations", "Ops"), ("ctrl+j", "next_agent", "Next"),
        ("ctrl+k", "previous_agent", "Previous"), ("ctrl+q", "quit", "Quit"),
        Binding("ctrl+g", "agent_control", "Control", priority=True),
        Binding("ctrl+p", "agent_switcher", "Switch", priority=True),
        Binding("ctrl+b", "dispatch", "Dispatch", priority=True),
        Binding("up", "prompt_previous", "History", show=False, priority=True),
        Binding("down", "prompt_next", "History", show=False, priority=True),
        Binding("tab", "complete_prompt", "Complete", show=False, priority=True),
    ]
    LOCAL_COMMANDS: ClassVar = {
        "/new": "initialize a new uplink",
        "/restore": "open Archive Uplink",
        "/agents": "list connected uplinks",
        "/agent": "open Operative Control",
        "/rename": "persist a new callsign",
        "/interrupt": "interrupt the active turn",
        "/retry": "restore an errored uplink",
        "/disconnect": "reversibly close the active uplink",
        "/archive": "archive and close the active uplink",
        "/dispatch": "transmit to multiple ready agents",
        "/older": "load 50 older turns",
        "/clear": "clear the active transcript",
        "/path": "show the active working directory",
        "/help": "open command reference",
        "/quit": "shut down Cyberdeck",
    }

    def __init__(self, *, skip_boot: bool = False, manager: AgentManager | None = None) -> None:
        super().__init__(); self.skip_boot = skip_boot
        self.manager = manager or AgentManager(self._agent_event)
        self.manager._on_event = self._agent_event
        self._system_transcript: list[TranscriptEntry] = []
        self._prompt_completions: list[tuple[str, str]] = []
        self._network_phase = 0
        self._prompt_history: list[str] = []
        self._history_index: int | None = None
        self._history_draft = ""
        self._draft_agent_id: str | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="top-rail"):
            yield Static("ODS // CYBERDECK", id="deck-brand")
            yield Static(id="uplink-count")
            yield Static(id="deck-clock")
        with Horizontal(id="workspace"):
            with Vertical(id="sidebar"):
                yield Label("──── AGENTS ────", id="sidebar-title")
                yield ListView(id="agents")
                yield Static("^N NEW\n^P MATRIX", id="spawn-hint")
            with Vertical(id="main-panel"):
                with Vertical(id="agent-header"), Horizontal(id="agent-primary"):
                    yield Static("NO ACTIVE UPLINK", id="agent-name")
                    yield Static(id="agent-model")
                    yield Static("│ STATE OFFLINE", id="agent-state")
                    yield Static("│ awaiting uplink", id="agent-activity")
                    yield Static("NET [····]", id="agent-network")
                    yield Static("MNEM [······] --", id="agent-mnem")
                    yield Static(id="agent-cwd")
                yield VerticalScroll(id="conversation")
                with Vertical(id="operations-console"):
                    yield Static("OPS // NORMALIZED ACTIVITY", id="operations-title")
                    yield ListView(id="operations-list")
                yield Static(id="autocomplete")
                with Vertical(id="prompt-zone"):
                    yield Static("▶ DECK://", id="prompt-label")
                    with Horizontal(id="prompt-bar"):
                        yield Static("local@deck:~ $", id="prompt-prefix")
                        yield Input(placeholder="jack in... type a command or message", id="prompt")
        yield Static("^N NEW  ^R RESTORE  ^G CONTROL  ^P SWITCH  ^B DISPATCH  ^O OPS  ^Q QUIT", id="shortcut-rail")

    def on_mount(self) -> None:
        self.query_one("#operations-console").display = False
        self._update_rails(); self.set_interval(1, self._update_rails)
        self.set_interval(0.28, self._update_network)
        self.query_one("#prompt", Input).focus()
        if not self.skip_boot: self.push_screen(BootScreen())

    async def on_unmount(self) -> None: await self.manager.shutdown()

    def _update_rails(self) -> None:
        active = sum(
            a.status not in {AgentStatus.ERROR, AgentStatus.STOPPED, AgentStatus.STARTING}
            for a in self.manager.agents
        )
        now = datetime.now().astimezone().strftime("%H:%M:%S")
        try:
            self.query_one("#uplink-count", Static).update(
                f"UPLINKS {active:02d}/{len(self.manager.agents):02d}"
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
            self.query_one("#agent-state", Static).update(
                f"│ STATE {state.status.value.upper()}"
            )
            self.query_one("#agent-activity", Static).update(f"│ {state.current_activity}")
            self._update_network()
            self._update_mnem(state)

    def _update_mnem(self, state: AgentState) -> None:
        meter = self.screen_stack[0].query_one("#agent-mnem", Static)
        if not state.context_window:
            meter.update(Text("MNEM [······] --", style="#607087"))
            return
        percent = min(100, round(state.context_tokens / state.context_window * 100))
        filled = min(6, round(percent / 100 * 6))
        bar = "█" * filled + "░" * (6 - filled)
        color = "#52e891" if percent < 70 else "#e9b949" if percent < 90 else "#ff3b4f"
        meter.update(Text(f"MNEM [{bar}] {percent:02d}%", style=f"bold {color}"))

    def _update_network(self) -> None:
        state = self._active_agent()
        try:
            indicator = self.screen_stack[0].query_one("#agent-network", Static)
        except (IndexError, NoMatches):
            return
        if not state:
            indicator.update(Text("NET [····]", style="#607087"))
            return
        self._network_phase = (self._network_phase + 1) % 4
        patterns = ("▁▃▅▇", "▃▅▇▅", "▅▇▅▃", "▇▅▃▁")
        if state.status is AgentStatus.ERROR:
            label, color = "NET [LOST]", "#ff3b4f"
        elif state.status is AgentStatus.FIREWALL_HOLD:
            label, color = "NET [HOLD]", "#ff3b4f"
        elif state.status in {AgentStatus.PROCESSING, AgentStatus.EXECUTING, AgentStatus.EDITING, AgentStatus.RESTORING}:
            label, color = f"NET [{patterns[self._network_phase]}]", "#e9b949"
        else:
            label, color = f"NET [{patterns[self._network_phase]}]", "#52e891"
        indicator.update(Text(label, style=f"bold {color}"))

    def action_spawn_agent(self) -> None: self.push_screen(SpawnAgent(), self._spawn_result)
    def _spawn_result(self, result):
        if result: self._spawn(*result)

    @work(exclusive=False)
    async def _spawn(self, name: str, path: Path) -> None:
        try:
            state = self.manager.register(name, path)
        except ValueError as exc:
            self._write_local(str(exc)); return
        await self._add_agent_item(state, select=True)
        try: await self.manager.connect(state)
        except Exception as exc:  # noqa: BLE001
            self._write_local(f"uplink failed for {name}: {exc}")
        self._refresh_all()

    def action_restore(self) -> None: self._discover_restore()

    @work(exclusive=True)
    async def _discover_restore(self) -> None:
        try:
            threads = await self.manager.discover_threads(Path.cwd())
        except Exception as exc:  # noqa: BLE001
            self._write_local(f"archive uplink unavailable: {exc}"); return
        self.push_screen(RestoreScreen(threads), self._restore_result)

    def _restore_result(self, selections):
        for summary, name in selections: self._restore_one(summary, name)

    @work(exclusive=False)
    async def _restore_one(self, summary: ThreadSummary, name: str) -> None:
        try:
            state = self.manager.register(name, summary.cwd, status=AgentStatus.RESTORING)
        except ValueError as exc:
            self._write_local(str(exc)); return
        state.thread_id, state.restored = summary.id, True
        await self._add_agent_item(state, select=True); self._refresh_all()
        # Manager.restore owns registration, so remove the UI placeholder before invoking it.
        self.manager.agents.remove(state)
        try:
            await self.manager.restore(summary, name)
            index = self.query_one("#agents", ListView).index or 0
            self.manager.agents.insert(index, self.manager.agents.pop())
        except Exception as exc:  # noqa: BLE001
            state.status = AgentStatus.ERROR; state.current_activity = str(exc)
            failed = next(
                (agent for agent in self.manager.agents if agent.thread_id == summary.id), None
            )
            if failed:
                self.manager.agents.remove(failed)
            self.manager.agents.insert(self.query_one("#agents", ListView).index or 0, state)
        self._refresh_all()

    async def _add_agent_item(self, state: AgentState, *, select: bool) -> None:
        view = self.query_one("#agents", ListView)
        await view.append(ListItem(Label(self._agent_label(state))))
        if select: view.index = len(view.children) - 1

    @on(Input.Submitted, "#prompt")
    async def send_prompt(self, event: Input.Submitted) -> None:
        prompt = event.value.strip()
        if not prompt: return
        self._prompt_history.append(prompt)
        self._history_index = None
        self._history_draft = ""
        event.input.value = ""
        state_for_draft = self._active_agent()
        if state_for_draft: state_for_draft.prompt_draft = ""
        if prompt.startswith("/"): await self._run_local_command(prompt); return
        state = self._active_agent()
        if not state: self._write_local("No active uplink. Use /new or /restore."); return
        if state.status is not AgentStatus.READY:
            self._write_local(f"{state.config.name} is {state.status.value.upper()}; wait for READY"); return
        # Manager timestamps once and owns the durable entry.
        try: await self.manager.send(state, prompt)
        except Exception as exc:  # noqa: BLE001
            self._write_local(f"transmission failed: {exc}")
        self._refresh_all()

    @on(Input.Changed, "#prompt")
    def prompt_changed(self, event: Input.Changed) -> None:
        self._prompt_completions = self._complete(event.value)
        panel = self.screen_stack[0].query_one("#autocomplete", Static)
        if not self._prompt_completions:
            panel.display = False
            return
        rows = Text()
        for index, (value, description) in enumerate(self._prompt_completions[:6]):
            rows.append(
                "TAB  " if index == 0 else "     ",
                style="bold #e62acb" if index == 0 else "",
            )
            rows.append(value, style="bold #00e8f2" if index == 0 else "#8ba2b3")
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
        completion = self._prompt_completions[0][0]
        raw = prompt.value
        if raw.startswith("/") and " " not in raw:
            prompt.value = completion + (" " if completion == "/new" else "")
        else:
            head, separator, _ = raw.rpartition(" ")
            prompt.value = f"{head}{separator}{completion}"
        prompt.cursor_position = len(prompt.value)

    def _complete(self, value: str) -> list[tuple[str, str]]:
        if not value:
            return []
        if value.startswith("/") and " " not in value:
            return [
                (command, description)
                for command, description in self.LOCAL_COMMANDS.items()
                if command.startswith(value) and command != value
            ]
        token = value.rsplit(" ", 1)[-1]
        is_new_path = value.startswith("/new ") and value.count(" ") >= 2
        if not (is_new_path or token.startswith(("/", "./", "../", "~"))):
            return []
        try:
            expanded = Path(token or ".").expanduser()
            directory = expanded if not token or token.endswith("/") else expanded.parent
            prefix = "" if not token or token.endswith("/") else expanded.name
            matches = sorted(
                (path for path in directory.iterdir() if path.is_dir() and path.name.startswith(prefix)),
                key=lambda path: path.name.casefold(),
            )
        except (OSError, RuntimeError, ValueError):
            return []
        results: list[tuple[str, str]] = []
        for path in matches[:12]:
            completed = str(path) + "/"
            if token.startswith("~"):
                try:
                    completed = f"~/{path.relative_to(Path.home())}/"
                except ValueError:
                    pass
            results.append((completed, "directory"))
        return results

    @on(ListView.Highlighted, "#agents")
    def selected_agent_changed(self) -> None:
        state = self._active_agent()
        if state: state.unread_count = 0
        prompt = self.screen_stack[0].query_one("#prompt", Input)
        if self._draft_agent_id:
            previous = next((a for a in self.manager.agents if str(a.config.id) == self._draft_agent_id), None)
            if previous: previous.prompt_draft = prompt.value
        prompt.value = state.prompt_draft if state else ""
        self._draft_agent_id = str(state.config.id) if state else None
        self._history_index = None
        self._render_active()

    @on(ListView.Selected, "#operations-list")
    def operation_selected(self, event: ListView.Selected) -> None:
        state = self._active_agent()
        if state and event.list_view.index is not None and event.list_view.index < len(state.operations):
            self.push_screen(OperationDetail(state.operations[event.list_view.index]))

    def action_operations(self) -> None:
        console = self.query_one("#operations-console")
        console.display = not console.display
        if console.display: self.query_one("#operations-list", ListView).focus()
        else: self.query_one("#prompt", Input).focus()

    def action_next_agent(self) -> None: self._move_agent(1)
    def action_previous_agent(self) -> None: self._move_agent(-1)

    def action_prompt_previous(self) -> None:
        if self.screen is not self.screen_stack[0]: return
        prompt = self.query_one("#prompt", Input)
        if not prompt.has_focus or not self._prompt_history: return
        if self._history_index is None:
            self._history_draft = prompt.value; self._history_index = len(self._prompt_history) - 1
        elif self._history_index > 0: self._history_index -= 1
        prompt.value = self._prompt_history[self._history_index]
        prompt.cursor_position = len(prompt.value)

    def action_prompt_next(self) -> None:
        if self.screen is not self.screen_stack[0]: return
        prompt = self.query_one("#prompt", Input)
        if not prompt.has_focus or self._history_index is None: return
        if self._history_index < len(self._prompt_history) - 1:
            self._history_index += 1; prompt.value = self._prompt_history[self._history_index]
        else:
            self._history_index = None; prompt.value = self._history_draft
        prompt.cursor_position = len(prompt.value)

    def action_agent_control(self) -> None:
        state = self._active_agent()
        if not state: self._write_local("No active uplink."); return
        self.push_screen(OperativeControl(state), lambda result: self._control_result(state, result))

    def action_agent_switcher(self) -> None:
        self.push_screen(AgentSwitcher(self.manager.agents, self._active_agent()), self._switch_result)

    def _switch_result(self, state: AgentState | None) -> None:
        if state and state in self.manager.agents:
            self.query_one("#agents", ListView).index = self.manager.agents.index(state)

    def action_dispatch(self) -> None:
        self.push_screen(DispatchScreen(self.manager.agents), self._dispatch_result)

    def _dispatch_result(self, result) -> None:
        if result: self._dispatch(*result)

    @work(exclusive=False)
    async def _dispatch(self, targets: list[AgentState], prompt: str) -> None:
        try:
            results = await self.manager.dispatch(targets, prompt)
            rows = [f"{name}: {'FAILED // ' + error if error else 'TRANSMITTED'}" for name, error in results.items()]
            self._write_local("DISPATCH SUMMARY\n" + "\n".join(rows))
        except Exception as exc:  # noqa: BLE001
            self._write_local(f"dispatch blocked: {exc}")
        self._refresh_all()

    def _control_result(self, state: AgentState, result) -> None:
        if not result: return
        action, argument = result
        if action == "disconnect" and state.status not in {AgentStatus.READY, AgentStatus.ERROR}:
            self.push_screen(ConfirmScreen("DISCONNECT BUSY OPERATIVE", f"Interrupt and disconnect {state.config.name}?"), lambda yes: self._lifecycle(state, action, argument) if yes else None)
        elif action == "archive":
            self.push_screen(ConfirmScreen("ARCHIVE OPERATIVE", f"Archive {state.config.name}? This removes it from Archive Uplink."), lambda yes: self._lifecycle(state, action, argument) if yes else None)
        else: self._lifecycle(state, action, argument)

    @work(exclusive=False)
    async def _lifecycle(self, state: AgentState, action: str, argument: str | None = None) -> None:
        try:
            operation = getattr(self.manager, action)
            await operation(state, argument) if action == "rename" else await operation(state)
            if action in {"disconnect", "archive"}: self._sync_agent_list()
            self._write_local(f"{action} complete: {argument or state.config.name}")
        except Exception as exc:  # noqa: BLE001
            self._write_local(f"{action} failed: {exc}")
        self._refresh_all()

    def _sync_agent_list(self) -> None:
        view = self.query_one("#agents", ListView); view.clear()
        for state in self.manager.agents: view.append(ListItem(Label(self._agent_label(state))))
        if self.manager.agents: view.index = min(view.index or 0, len(self.manager.agents) - 1)
    def _move_agent(self, direction: int) -> None:
        view = self.query_one("#agents", ListView)
        if self.manager.agents: view.index = ((view.index or 0) + direction) % len(self.manager.agents)

    def _active_agent(self) -> AgentState | None:
        index = self.screen_stack[0].query_one("#agents", ListView).index
        return self.manager.agents[index] if index is not None and index < len(self.manager.agents) else None

    def _render_active(self, *, follow_end: bool = True) -> None:
        main = self.screen_stack[0]
        state = self._active_agent(); conversation = main.query_one("#conversation", VerticalScroll)
        conversation.remove_children()
        entries = state.transcript if state else self._system_transcript
        if state and state.history_cursor:
            conversation.mount(Static("↑ LOAD OLDER TURNS  //  /older", classes="load-older"))
        for entry in entries: conversation.mount(TerminalMessage(entry, state))
        prefix = main.query_one("#prompt-prefix", Static)
        prefix.update(f"{getpass.getuser()}@{state.config.name}:{self.display_path(state.config.working_directory)} $" if state else "local@deck:~ $")
        self._render_operations(); self._update_rails()
        if follow_end:
            self.call_after_refresh(lambda: conversation.scroll_end(animate=False))

    def _render_operations(self) -> None:
        view = self.screen_stack[0].query_one("#operations-list", ListView); view.clear()
        state = self._active_agent()
        if not state: return
        for op in state.operations:
            glyph = {"succeeded": "✓", "failed": "!", "approval": "?", "running": "◐", "pending": "○"}[op.state.value]
            view.append(ListItem(Label(f"{op.created_at:%H:%M:%S}  {op.kind:<18} {glyph} {op.summary}")))

    def _write_local(self, text: str) -> None:
        state = self._active_agent(); (state.transcript if state else self._system_transcript).append(TranscriptEntry("system", text))
        self._render_active()

    async def _run_local_command(self, command_line: str) -> None:
        try: parts = shlex.split(command_line)
        except ValueError as exc: self._write_local(f"command parse error: {exc}"); return
        command, args = parts[0].lower(), parts[1:]
        if command in {"/help", "/?"}: self.push_screen(HelpScreen())
        elif command == "/restore": self.action_restore()
        elif command == "/new":
            if not args: self.action_spawn_agent()
            else:
                path = Path(args[1]).expanduser().resolve() if len(args) > 1 else Path.cwd()
                if path.is_dir(): self._spawn(args[0], path)
                else: self._write_local(f"path not found: {path}")
        elif command == "/agents":
            self._write_local("\n".join(f"{i+1}. {a.config.name} [{a.status.value}] {a.config.working_directory}" for i, a in enumerate(self.manager.agents)) or "no uplinks connected")
        elif command == "/older":
            state = self._active_agent()
            if state: self._load_older(state)
        elif command == "/clear":
            (self._active_agent().transcript if self._active_agent() else self._system_transcript).clear(); self._render_active()
        elif command == "/path": self._write_local(str(self._active_agent().config.working_directory if self._active_agent() else Path.cwd()))
        elif command == "/agent": self.action_agent_control()
        elif command == "/dispatch": self.action_dispatch()
        elif command in {"/rename", "/interrupt", "/retry", "/disconnect", "/archive"}:
            state = self._active_agent()
            if not state: self._write_local("No active uplink.")
            elif command == "/rename" and not args: self._write_local("usage: /rename CALLSIGN")
            else: self._control_result(state, (command[1:], args[0] if args else None))
        elif command in {"/quit", "/exit"}: self.exit()
        else: self._write_local(f"unknown local command: {command} (try /help)")

    @work(exclusive=False)
    async def _load_older(self, state: AgentState) -> None:
        try: await self.manager.load_older(state)
        except Exception as exc:  # noqa: BLE001
            self._write_local(f"history load failed: {exc}")
        self._render_active(follow_end=False)

    def _agent_event(self, state: AgentState, event: AgentEvent) -> None:
        if state is not self._active_agent(): state.unread_count += 1
        if event.kind in {"error", "transport_closed"} and isinstance(self.screen, FirewallRequest) and self.screen.agent is state:
            self.screen.dismiss("decline")
        if event.kind == "approval" and event.request_id is not None:
            self.push_screen(FirewallRequest(state, event), lambda decision: self._approval_decided(state, event, decision))
        elif event.kind == "error" and state is self._active_agent(): self._write_local(f"error: {event.text}")
        elif event.kind == "assistant_delta" and state is self._active_agent():
            conversation = self.screen_stack[0].query_one("#conversation", VerticalScroll)
            messages = list(conversation.query(TerminalMessage))
            expected = len(state.transcript)
            if state.history_cursor:
                # The load-older control isn't a TerminalMessage and doesn't affect this count.
                expected = len(state.transcript)
            if len(messages) < expected:
                conversation.mount(TerminalMessage(state.transcript[-1], state))
            elif messages:
                messages[-1].refresh(layout=True)
            self._refresh_agent_labels()
            self._update_rails()
            self.call_after_refresh(lambda: conversation.scroll_end(animate=False))
            return
        self._refresh_all()

    def _approval_decided(self, state, event, decision):
        if event.request_id is not None: self._respond_to_approval(state, event.request_id, decision)

    @work(exclusive=False)
    async def _respond_to_approval(self, state, request_id, decision):
        try: await self.manager.respond_approval(state, request_id, decision)
        except Exception as exc:  # noqa: BLE001
            self._write_local(f"firewall response failed: {exc}")

    def _refresh_all(self) -> None:
        self._refresh_agent_labels()
        self._render_active()

    def _refresh_agent_labels(self) -> None:
        view = self.screen_stack[0].query_one("#agents", ListView)
        for item, state in zip(view.children, self.manager.agents, strict=False):
            item.query_one(Label).update(self._agent_label(state))

    @staticmethod
    def _agent_label(state: AgentState) -> Text:
        color = {
            AgentStatus.READY: "#52e891",
            AgentStatus.ERROR: "#ff3b4f",
            AgentStatus.FIREWALL_HOLD: "#ff3b4f",
            AgentStatus.RESTORING: "#e9b949",
        }.get(state.status, "#e62acb")
        glyph = {
            AgentStatus.READY: "●",
            AgentStatus.RESTORING: "↻",
            AgentStatus.ERROR: "!",
            AgentStatus.FIREWALL_HOLD: "!",
        }.get(state.status, "◐")
        label = Text()
        label.append(f"{glyph} ", style=f"bold {color}")
        label.append(f"SYN::{state.config.name.upper()}", style=f"bold {color}")
        if state.unread_count:
            label.append(f"  +{state.unread_count}", style="bold #e9b949")
        label.append(f"  {state.status.value}", style="#7a879a")
        label.append(f"\n  └─ {state.config.working_directory.name}", style="#46566c")
        return label

    @staticmethod
    def display_path(path: Path) -> str:
        try: return f"~/{path.relative_to(Path.home())}"
        except ValueError: return str(path)


def main() -> None: CyberdeckApp().run()
if __name__ == "__main__": main()
