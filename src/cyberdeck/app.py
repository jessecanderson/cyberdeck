from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import platform
import random
import shlex
import shutil
import subprocess
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from importlib.metadata import version as package_version
from pathlib import Path
from typing import ClassVar

from rich import box
from rich.cells import cell_len, chop_cells
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
from textual.widget import Widget
from textual.widgets import Input, Label, ListItem, ListView, Static, TextArea

from . import __version__
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
from .modules import DeckCommand, DeckModule, ModuleInputMode, ModuleManifest
from .providers import AgentEvent
from .themes import DeckTheme, discover_themes, import_theme


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
        ("                 C Y B E R D E C K", "bold #cce7ed", 0.12),
        ("                OPEN DECK SYSTEMS // ROM REVISION 251", "#607087", 0.24),
        ("", "", 0.06),
        (f"CYBERDECK QUANTUM BIOS v{__version__} // RELEASE CHANNEL", "bold #00e8f2", 0.10),
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
        ("【 零界技研・企業拡張領域 】", "bold #e62acb", 0.12),
        ("  神経接続規格................ 読込完了", "#00e8f2", 0.06),
        ("  認証鍵...................... 有効", "#52e891", 0.06),
        ("  思考隔離層.................. 安定", "#52e891", 0.06),
        ("  擬似記憶領域................ 接続", "#52e891", 0.06),
        ("  外部監視.................... 検出なし", "#52e891", 0.08),
        ("  警告：境界外通信は記録されます", "bold #e9b949", 0.12),
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
        ("SYSTEM READY // システム起動完了 // HANDING CONTROL TO /CYBERDECK/CORE", "bold #00e8f2", 0.22),
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
            if width > 24 and self._noise_rng.random() < 0.45
            else -1
        )
        for row_index, (line, style) in enumerate(rows):
            chunks = chop_cells(line, width)
            clipped = chunks[0] if chunks else ""
            frame.append(clipped, style=style)
            remainder = width - cell_len(clipped)
            cells = [" "] * remainder
            for _ in range(max(2, remainder // 58)):
                if cells:
                    cells[self._noise_rng.randrange(len(cells))] = self._noise_rng.choice(glyphs)
            if row_index == interference_row and remainder > 8:
                start = self._noise_rng.randrange(max(1, remainder - 6))
                length = min(self._noise_rng.randrange(8, 25), remainder - start)
                cells[start : start + length] = "─" * length
            frame.append("".join(cells), style="#244255")
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
/send AGENT MESSAGE   Send a prompt to one ready agent
/pipe AGENT           Forward the latest agent response
/copy [all|TEXT]      Copy response, transcript, or text
/kill [AGENT|all]     Disconnect after confirmation
/modules /module NAME List or switch deck modules
/theme [NAME]         Select a theme
/theme import PATH    Validate and import a theme
/journal [YYYY-MM-DD] Open a daily Markdown entry
/today  /save         Open today / save Journal
/about                Open system manifest
/clear  /path        Clear view / show active path
/help  /quit         Reference / shutdown

KEYBOARD

Ctrl+N new   Ctrl+R restore   Ctrl+G control   Ctrl+P switch
Ctrl+B dispatch   Ctrl+M next module   Ctrl+L command line
Ctrl+S save editor   Ctrl+O operations
Ctrl+J/K switch uplink   Esc close window   Ctrl+Q quit
"""

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Label("ODS // COMMAND REFERENCE // 操作一覧", id="help-title")
            yield Static(self.HELP_TEXT, id="help-content")
            yield Static("ESC  RETURN", classes="modal-help")

    def action_close(self) -> None:
        self.dismiss(None)


class AboutScreen(ModalScreen[None]):
    BINDINGS: ClassVar = [("escape", "close", "Close"), ("c", "copy", "Copy")]

    def __init__(self, manifest: str) -> None:
        super().__init__()
        self.manifest = manifest

    def compose(self) -> ComposeResult:
        with Vertical(id="about-dialog"):
            yield Label("SYSTEM MANIFEST // システム情報", id="about-title")
            yield Static(self.manifest, id="about-content")
            yield Static("C  COPY DIAGNOSTICS     ESC  RETURN", classes="modal-help")

    def action_copy(self) -> None:
        self.app.copy_to_clipboard(self.manifest)
        self.notify("System manifest copied", title="DIAGNOSTICS")

    def action_close(self) -> None:
        self.dismiss(None)


def ice_level(agent: AgentState, approval: PendingApproval) -> tuple[str, str]:
    """Classify an approval for display; the provider remains the authority."""
    params = approval.params
    command = str(params.get("command") or "").casefold()
    dangerous = (
        "rm -rf", "sudo ", "git reset --hard", "git clean -f", "mkfs",
        "dd if=", "chmod -r", "chown -r", "> /dev/",
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
    can_focus = True
    BINDINGS: ClassVar = [
        ("y", "authorize", "Open once"),
        ("a", "trust", "Trust session"),
        ("n", "deny", "Seal"),
        ("escape", "release", "Return"),
    ]

    def __init__(self, agent: AgentState, approval: PendingApproval) -> None:
        self.agent, self.approval = agent, approval
        level, _ = ice_level(agent, approval)
        super().__init__(classes=f"approval-message {level.lower().replace(' ', '-')}")

    def render(self):
        params = self.approval.params
        level, color = ice_level(self.agent, self.approval)
        is_command = self.approval.method == "item/commandExecution/requestApproval"
        details = Text()
        for label, value in (
            ("OPERATIVE", self.agent.config.name.upper()),
            ("ACTION", "EXECUTE COMMAND" if is_command else "MODIFY FILES"),
            ("TARGET", params.get("command") or params.get("grantRoot") or "workspace files"),
            ("PATH", params.get("cwd") or str(self.agent.config.working_directory)),
            ("REASON", params.get("reason") or "Agent operation requires authorization"),
        ):
            details.append(f"{label:<10}", style=f"bold {color}")
            details.append(f"{value}\n", style="#f4d8dc")
        actions = Text("[Y] OPEN ONCE   [A] TRUST SESSION   [N] SEAL", style=f"bold {color}")
        actions.justify = "center"
        return Panel(
            Group(details, Text(""), actions),
            title=f"{level} // ICE GATE // AUTHORIZATION REQUIRED",
            box=box.DOUBLE,
            border_style=color,
            padding=(0, 1),
        )

    def _decide(self, decision: str) -> None:
        self.disabled = True
        self.app._approval_decided(self.agent, self.approval, decision)
        self.app.query_one("#prompt", Input).focus()

    def action_authorize(self) -> None: self._decide("accept")
    def action_trust(self) -> None: self._decide("acceptForSession")
    def action_deny(self) -> None: self._decide("decline")
    def action_release(self) -> None: self.app.query_one("#prompt", Input).focus()


class SpawnAgent(ModalScreen[tuple[str, Path] | None]):
    BINDINGS: ClassVar = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="spawn-dialog"):
            yield Label("ODS // INITIALIZE UPLINK", id="spawn-title")
            yield Input(placeholder="Callsign", id="spawn-agent-name")
            yield Input(value=str(Path.cwd()), placeholder="Working directory", id="spawn-agent-path")
            yield Static("ENTER  JACK IN   •   ESC  ABORT", classes="modal-help", id="spawn-help")

    @on(Input.Submitted)
    def submit(self) -> None:
        name = self.query_one("#spawn-agent-name", Input).value.strip()
        path = Path(self.query_one("#spawn-agent-path", Input).value).expanduser().resolve()
        if not name:
            self.query_one("#spawn-agent-name", Input).focus(); return
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


class ThemeScreen(ModalScreen[str | None]):
    BINDINGS: ClassVar = [("escape", "close", "Close")]

    def __init__(self, themes: list[DeckTheme], active: str) -> None:
        super().__init__()
        self.themes = themes
        self.active = active

    def compose(self) -> ComposeResult:
        with Vertical(id="theme-dialog"):
            yield Label("CHROMA MATRIX // 配色選択", id="theme-title")
            yield ListView(
                *(
                    ListItem(Label(f"{'●' if theme.id == self.active else '○'}  {theme.name}\n    {theme.id} // {theme.author}"))
                    for theme in self.themes
                ),
                id="theme-list",
            )
            yield Static("ENTER  APPLY     ESC  RETURN", classes="modal-help")

    @on(ListView.Selected, "#theme-list")
    def select_theme(self, event: ListView.Selected) -> None:
        if event.list_view.index is not None:
            self.dismiss(self.themes[event.list_view.index].id)

    def action_close(self) -> None:
        self.dismiss(None)


class AgentsWorkspace(Vertical):
    def compose(self) -> ComposeResult:
        with Vertical(id="agent-header"):
            with Horizontal(id="agent-primary"):
                yield Static("NO ACTIVE UPLINK", id="agent-name")
                yield Static(id="agent-model")
                yield Static("│ STATE OFFLINE", id="agent-state")
                yield Static("│ awaiting uplink", id="agent-activity")
                yield Static("NET [····]", id="agent-network")
                yield Static("MNEM [······] --", id="agent-mnem")
                yield Static(id="agent-cwd")
            yield Static("CARRIER // 通信 ··· OFFLINE", id="signal-trace")
        yield Static(id="state-transition")
        yield VerticalScroll(id="conversation")
        with Vertical(id="operations-console"):
            yield Static("OPS // NORMALIZED ACTIVITY", id="operations-title")
            yield ListView(id="operations-list")


class JournalWorkspace(Vertical):
    def compose(self) -> ComposeResult:
        with Horizontal(id="journal-header"):
            yield Static("JOURNAL // 日誌", id="journal-title")
            yield Static("LOCAL MARKDOWN // USER OWNED", id="journal-status")
        with Horizontal(id="journal-body"):
            with Vertical(id="journal-index"):
                yield Input(placeholder="search entries...", id="journal-search")
                yield ListView(id="journal-days")
            with Vertical(id="journal-document"):
                yield Static("TODAY", id="journal-date")
                yield TextArea(
                    "", language="markdown", soft_wrap=True, tab_behavior="indent",
                    id="journal-editor",
                )
        yield Static(
            "^L COMMAND   ESC RETURN TO EDITOR   ^S SAVE   UTF-8 // 日本語対応",
            id="journal-help",
        )


class BuiltinModule(DeckModule):
    def __init__(
        self,
        manifest: ModuleManifest,
        factory: Callable[[], Widget],
        prompt_handler: Callable[[str], Awaitable[None]],
        commands: tuple[DeckCommand, ...] = (),
        activate_handler: Callable[[], Awaitable[None]] | None = None,
        deactivate_handler: Callable[[], Awaitable[None]] | None = None,
        input_mode: ModuleInputMode = ModuleInputMode.DECK_PROMPT,
        focus_target: str | None = None,
        save_handler: Callable[[], Awaitable[bool] | bool] | None = None,
    ) -> None:
        self.manifest = manifest
        self._factory = factory
        self._prompt_handler = prompt_handler
        self._commands = commands
        self._activate_handler = activate_handler
        self._deactivate_handler = deactivate_handler
        self.input_mode = input_mode
        self.focus_target = focus_target
        self._save_handler = save_handler

    def build(self) -> Widget:
        return self._factory()

    def commands(self) -> tuple[DeckCommand, ...]:
        return self._commands

    async def activate(self) -> None:
        if self._activate_handler:
            await self._activate_handler()

    async def deactivate(self) -> None:
        if self._deactivate_handler:
            await self._deactivate_handler()

    async def save(self) -> bool:
        if not self._save_handler:
            return False
        result = self._save_handler()
        return await result if asyncio.iscoroutine(result) else result

    async def handle_prompt(self, text: str) -> None:
        await self._prompt_handler(text)


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
        Binding("ctrl+m", "next_module", "Module", priority=True),
        Binding("ctrl+l", "focus_command", "Command", priority=True),
        Binding("ctrl+s", "save_module", "Save", priority=True),
        Binding("escape", "workspace_focus", "Workspace", show=False),
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
        "/send": "send a prompt to one ready agent",
        "/pipe": "forward the latest response to an agent",
        "/copy": "copy response, transcript, or text",
        "/kill": "disconnect an agent after confirmation",
        "/modules": "list installed deck modules",
        "/module": "activate a deck module",
        "/theme": "select or import a color theme",
        "/journal": "open a dated journal entry",
        "/today": "open today's journal entry",
        "/save": "save the active journal entry",
        "/about": "open system manifest",
        "/older": "load 50 older turns",
        "/clear": "clear the active transcript",
        "/path": "show the active working directory",
        "/help": "open command reference",
        "/quit": "shut down Cyberdeck",
    }

    def __init__(
        self,
        *,
        skip_boot: bool = False,
        manager: AgentManager | None = None,
        config_store: ConfigStore | None = None,
        journal_store: JournalStore | None = None,
    ) -> None:
        super().__init__(); self.skip_boot = skip_boot
        self.manager = manager or AgentManager(self._agent_event)
        self.manager._on_event = self._agent_event
        self._persist_preferences = not skip_boot or config_store is not None
        self.config_store = config_store or ConfigStore()
        self.deck_config: DeckConfig = self.config_store.load()
        self.journal_store = journal_store or JournalStore(self.deck_config.journal_path)
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
        self._system_transcript: list[TranscriptEntry] = []
        self._prompt_completions: list[tuple[str, str]] = []
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
        self.deck_modules: dict[str, BuiltinModule] = {
            "agents": BuiltinModule(
                ModuleManifest("agents", "AGENT COMMAND", "Multi-agent operations", 10),
                lambda: AgentsWorkspace(id="agent-module"),
                self._handle_agent_prompt,
            ),
            "journal": BuiltinModule(
                ModuleManifest("journal", "JOURNAL", "Daily Markdown log", 20),
                lambda: JournalWorkspace(id="journal-module"),
                self._handle_journal_prompt,
                commands=(
                    DeckCommand("/journal", "open a dated journal entry", self._command_journal),
                    DeckCommand("/today", "open today's journal entry", self._command_today),
                    DeckCommand("/save", "save the active journal entry", self._command_save),
                ),
                activate_handler=self._activate_journal,
                deactivate_handler=self._deactivate_journal,
                input_mode=ModuleInputMode.WORKSPACE_EDITOR,
                focus_target="#journal-editor",
                save_handler=self._save_journal_module,
            ),
        }

    def compose(self) -> ComposeResult:
        with Horizontal(id="top-rail"):
            yield Static("ODS // CYBERDECK // 電脳端末", id="deck-brand")
            yield Static(id="uplink-count")
            yield Static(id="deck-clock")
        with Horizontal(id="workspace"):
            with Vertical(id="sidebar"):
                yield Label("── AGENTS // 接続 ──", id="sidebar-title")
                yield ListView(id="agents")
                yield Label("── MODULES // 機能 ──", id="modules-title")
                yield ListView(
                    *(
                        ListItem(Label(self._module_label(module)))
                        for module in sorted(
                            self.deck_modules.values(), key=lambda item: item.manifest.order
                        )
                    ),
                    id="modules",
                )
                yield Static("^N NEW\n^P MATRIX", id="spawn-hint")
            with Vertical(id="main-panel"):
                for module in sorted(self.deck_modules.values(), key=lambda item: item.manifest.order):
                    yield module.build()
                yield Static(id="autocomplete")
                with Vertical(id="prompt-zone"):
                    yield Static("▶ DECK:// 端末", id="prompt-label")
                    with Horizontal(id="prompt-bar"):
                        yield Static("local@deck:~ $", id="prompt-prefix")
                        yield Input(placeholder="jack in... type a command or message", id="prompt")
        yield Static("^N NEW  ^R RESTORE  ^G CONTROL  ^P SWITCH  ^B DISPATCH  ^M MODULE  ^L CMD  ^S SAVE  ^O OPS  ^Q QUIT", id="shortcut-rail")

    def on_mount(self) -> None:
        self.query_one("#operations-console").display = False
        self.query_one("#state-transition").display = False
        self.query_one("#journal-module").display = False
        self._update_rails(); self.set_interval(1, self._update_rails)
        self.set_interval(0.28, self._update_network)
        self.query_one("#prompt", Input).focus()
        requested = self.deck_config.active_module if self._persist_preferences else "agents"
        self.call_after_refresh(lambda: self._activate_module(requested if requested in self.deck_modules else "agents"))
        for error in self._theme_errors:
            self.notify(error, title="THEME REJECTED", severity="warning")
        if not self.skip_boot: self.push_screen(BootScreen())

    async def on_unmount(self) -> None:
        if self._journal_dirty:
            self._save_journal()
        await self.manager.shutdown()

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
        self._network_phase = (self._network_phase + 1) % 4
        self._update_signal_trace(state)
        self._refresh_agent_labels()
        if not state:
            indicator.update(Text("NET [····]", style="#607087"))
            return
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
        banner.display = True
        self.set_timer(2.4, lambda: self._hide_transition(serial))

    def _hide_transition(self, serial: int) -> None:
        if serial == self._transition_serial:
            try:
                self.screen_stack[0].query_one("#state-transition", Static).display = False
            except (IndexError, NoMatches):
                return

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
        await self.deck_modules[self.active_module_id].handle_prompt(prompt)

    async def _handle_agent_prompt(self, prompt: str) -> None:
        state = self._active_agent()
        if not state: self._write_local("No active uplink. Use /new or /restore."); return
        if state.status is not AgentStatus.READY:
            self._write_local(f"{state.config.name} is {state.status.value.upper()}; wait for READY"); return
        try: await self.manager.send(state, prompt)
        except Exception as exc:  # noqa: BLE001
            self._write_local(f"transmission failed: {exc}")
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
        stripped = value.rstrip()
        words = stripped.split()
        if words and words[0] == "/module" and len(words) == 2 and not value.endswith(" "):
            prefix = words[1].casefold()
            return [
                (module_id, module.manifest.description)
                for module_id, module in self.deck_modules.items()
                if module_id.startswith(prefix)
            ]
        if words and words[0] == "/theme" and len(words) == 2 and not value.endswith(" "):
            prefix = words[1].casefold()
            return [
                (theme_id, theme.name)
                for theme_id, theme in self.deck_themes.items()
                if theme_id.startswith(prefix)
            ]
        if words and words[0] in {"/send", "/pipe", "/kill"} and len(words) == 2:
            if value.endswith(" "):
                return []
            prefix = words[1].casefold()
            candidates = [(agent.config.name, f"{agent.status.value} agent") for agent in self.manager.agents]
            if words[0] == "/kill":
                candidates.append(("all", "all connected agents"))
            return [(name, description) for name, description in candidates if name.casefold().startswith(prefix)]
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
        if self.is_mounted and self.active_module_id != "agents":
            self._activate_module("agents")
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

    @on(ListView.Selected, "#modules")
    def module_selected(self, event: ListView.Selected) -> None:
        if event.list_view.index is None:
            return
        ordered = sorted(self.deck_modules.values(), key=lambda item: item.manifest.order)
        self._activate_module(ordered[event.list_view.index].manifest.id)

    @on(ListView.Selected, "#operations-list")
    def operation_selected(self, event: ListView.Selected) -> None:
        state = self._active_agent()
        if state and event.list_view.index is not None and event.list_view.index < len(state.operations):
            self.push_screen(OperationDetail(state.operations[event.list_view.index]))

    def action_operations(self) -> None:
        if self.active_module_id != "agents":
            self.notify("Operations are available in AGENT COMMAND", severity="warning")
            return
        console = self.query_one("#operations-console")
        console.display = not console.display
        if console.display: self.query_one("#operations-list", ListView).focus()
        else: self.query_one("#prompt", Input).focus()

    def action_next_agent(self) -> None: self._move_agent(1)
    def action_previous_agent(self) -> None: self._move_agent(-1)

    def action_next_module(self) -> None:
        ordered = sorted(self.deck_modules, key=lambda key: self.deck_modules[key].manifest.order)
        index = ordered.index(self.active_module_id)
        self._activate_module(ordered[(index + 1) % len(ordered)])

    def action_focus_command(self) -> None:
        self.screen_stack[0].query_one("#prompt", Input).focus()

    def action_workspace_focus(self) -> None:
        self.call_after_refresh(self._focus_active_workspace)

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
        main.query_one("#agent-module").display = module_id == "agents"
        main.query_one("#journal-module").display = module_id == "journal"
        ordered = sorted(self.deck_modules.values(), key=lambda item: item.manifest.order)
        main.query_one("#modules", ListView).index = next(
            index for index, module in enumerate(ordered) if module.manifest.id == module_id
        )
        self._refresh_module_labels()
        prompt = main.query_one("#prompt", Input)
        prompt.placeholder = (
            "jack in... type a command or message"
            if module_id == "agents"
            else "quick journal entry... or /command"
        )
        if module_id == "journal":
            main.query_one("#prompt-prefix", Static).update("local@journal:today $")
        else:
            self._render_active()
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
        ordered = sorted(self.deck_modules.values(), key=lambda item: item.manifest.order)
        for item, module in zip(view.children, ordered, strict=True):
            item.query_one(Label).update(self._module_label(module))

    def _module_label(self, module: DeckModule) -> Text:
        active = module.manifest.id == self.active_module_id
        label = Text()
        label.append("● " if active else "◇ ", style="bold #52e891" if active else "#607087")
        label.append(module.manifest.title, style="bold #00e8f2" if active else "#8ba2b3")
        label.append("  ACTIVE" if active else "  STANDBY", style="bold #52e891" if active else "#607087")
        label.append(f"\n  {module.manifest.description}", style="#46566c")
        return label

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
        self.screen_stack[0].query_one("#journal-status", Static).update("MODIFIED // AUTOSAVE ARMED")
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
        try:
            index = self.screen_stack[0].query_one("#agents", ListView).index
        except (IndexError, NoMatches):
            return None
        return self.manager.agents[index] if index is not None and index < len(self.manager.agents) else None

    def _render_active(self, *, follow_end: bool = True) -> None:
        main = self.screen_stack[0]
        state = self._active_agent(); conversation = main.query_one("#conversation", VerticalScroll)
        conversation.remove_children()
        entries = state.transcript if state else self._system_transcript
        if state and state.history_cursor:
            conversation.mount(Static("↑ LOAD OLDER TURNS  //  /older", classes="load-older"))
        for entry in entries: conversation.mount(TerminalMessage(entry, state))
        if state:
            for approval in state.pending_approvals:
                conversation.mount(ApprovalMessage(state, approval))
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
        elif command == "/about": self.push_screen(AboutScreen(self._system_manifest()))
        elif command == "/restore": self.action_restore()
        elif command == "/new":
            if not args: self.action_spawn_agent()
            else:
                path = Path(args[1]).expanduser().resolve() if len(args) > 1 else Path.cwd()
                if path.is_dir(): self._spawn(args[0], path)
                else: self._write_local(f"path not found: {path}")
        elif command == "/agents":
            self._write_local("\n".join(f"{i+1}. {a.config.name} [{a.status.value}] {a.config.working_directory}" for i, a in enumerate(self.manager.agents)) or "no uplinks connected")
        elif command == "/modules":
            rows = [
                f"{'●' if module_id == self.active_module_id else '○'} {module_id:<10} {module.manifest.description}"
                for module_id, module in self.deck_modules.items()
            ]
            self.notify("\n".join(rows), title="DECK MODULES")
        elif command == "/module":
            if not args:
                self.notify(f"Active module: {self.active_module_id}", title="DECK MODULE")
            elif args[0].casefold() not in self.deck_modules:
                self.notify(f"Unknown module: {args[0]}", severity="error")
            else:
                self._activate_module(args[0].casefold())
        elif command == "/theme":
            self._theme_command(args)
        elif command in {"/journal", "/today", "/save"}:
            handlers = {
                deck_command.name: deck_command.handler
                for deck_command in self.deck_modules["journal"].commands()
            }
            result = handlers[command](args)
            if asyncio.iscoroutine(result):
                await result
        elif command == "/older":
            state = self._active_agent()
            if state: self._load_older(state)
        elif command == "/clear":
            (self._active_agent().transcript if self._active_agent() else self._system_transcript).clear(); self._render_active()
        elif command == "/path": self._write_local(str(self._active_agent().config.working_directory if self._active_agent() else Path.cwd()))
        elif command == "/agent": self.action_agent_control()
        elif command == "/dispatch": self.action_dispatch()
        elif command == "/copy": self._copy_command(args)
        elif command in {"/send", "/pipe"}: self._route_command(command, args)
        elif command == "/kill": self._request_kill(args)
        elif command in {"/rename", "/interrupt", "/retry", "/disconnect", "/archive"}:
            state = self._active_agent()
            if not state: self._write_local("No active uplink.")
            elif command == "/rename" and not args: self._write_local("usage: /rename CALLSIGN")
            else: self._control_result(state, (command[1:], args[0] if args else None))
        elif command in {"/quit", "/exit"}: self.exit()
        else: self._write_local(f"unknown local command: {command} (try /help)")

    def _system_manifest(self) -> str:
        codex_version = self._executable_version("codex")
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
            f"Codex CLI...... {codex_version}",
            "",
            f"Config......... {self.display_path(self.config_store.path)}",
            f"Journal........ {self.display_path(self.journal_store.directory)}",
            f"Themes......... {self.display_path(user_theme_directory())}",
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

    def _copy_command(self, args: list[str]) -> None:
        state = self._active_agent()
        if args and args[0].casefold() == "all":
            entries = state.transcript if state else self._system_transcript
            text = "\n\n".join(f"{entry.role.upper()}: {entry.text}" for entry in entries)
        elif args:
            text = " ".join(args)
        else:
            entries = state.transcript if state else self._system_transcript
            latest = next((entry for entry in reversed(entries) if entry.role == "assistant"), None)
            if not latest:
                self._write_local("nothing to copy: no assistant response"); return
            text = latest.text
        if not text:
            self._write_local("nothing to copy"); return
        self.copy_to_clipboard(text)
        self._write_local(f"copied {len(text)} characters to clipboard")

    def _find_agent(self, callsign: str) -> AgentState | None:
        name = callsign.casefold()
        return next((agent for agent in self.manager.agents if agent.config.name.casefold() == name), None)

    def _route_command(self, command: str, args: list[str]) -> None:
        usage = f"usage: {command} CALLSIGN" + (" MESSAGE" if command == "/send" else "")
        if not args:
            self._write_local(usage); return
        target = self._find_agent(args[0])
        if not target:
            self._write_local(f"unknown callsign: {args[0]}"); return
        if target.status is not AgentStatus.READY:
            self._write_local(f"{target.config.name} is {target.status.value.upper()}; requires READY"); return
        if command == "/send":
            payload = " ".join(args[1:]).strip()
            if not payload:
                self._write_local(usage); return
        else:
            source = self._active_agent()
            latest = next(
                (entry for entry in reversed(source.transcript) if entry.role == "assistant"),
                None,
            ) if source else None
            if not latest:
                self._write_local("nothing to pipe: no assistant response"); return
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
                self._write_local(f"unknown callsign: {args[0]}"); return
            targets = [target]
        else:
            active = self._active_agent()
            targets = [active] if active else []
        if not targets:
            self._write_local("no agents to kill"); return
        names = ", ".join(agent.config.name for agent in targets)
        self.push_screen(
            ConfirmScreen(
                "KILL UPLINK" if len(targets) == 1 else "KILL ALL UPLINKS",
                f"Disconnect {names}? Threads remain restorable through Archive Uplink.",
            ),
            lambda yes: self._kill_agents(targets) if yes else None,
        )

    @work(exclusive=False)
    async def _kill_agents(self, targets: list[AgentState]) -> None:
        results: list[str] = []
        for target in targets:
            try:
                await self.manager.disconnect(target)
                results.append(f"{target.config.name}: KILLED")
            except Exception as exc:  # noqa: BLE001
                results.append(f"{target.config.name}: FAILED // {exc}")
        self._sync_agent_list()
        self._write_local("KILL SUMMARY\n" + "\n".join(results))
        self._refresh_all()

    @work(exclusive=False)
    async def _load_older(self, state: AgentState) -> None:
        try: await self.manager.load_older(state)
        except Exception as exc:  # noqa: BLE001
            self._write_local(f"history load failed: {exc}")
        self._render_active(follow_end=False)

    def _agent_event(self, state: AgentState, event: AgentEvent) -> None:
        if state is not self._active_agent(): state.unread_count += 1
        if event.kind == "status":
            if event.text == "ready":
                self._show_transition(state, "CARRIER STABLE // 通信安定", "#52e891")
            elif event.text in {"processing", "working"}:
                self._show_transition(state, "SIGNAL ENGAGED // 稼働", "#00e8f2")
        elif event.kind == "approval":
            approval = state.pending_approvals[-1] if state.pending_approvals else None
            level, color = ice_level(state, approval) if approval else ("ICE", "#ff3b4f")
            self._show_transition(state, f"{level} INTERLOCK // 認証待機", color)
        elif event.kind in {"error", "transport_closed"}:
            self._show_transition(state, "SIGNAL LOST // 通信断", "#ff3b4f")
        if event.kind == "approval" and state is self._active_agent():
            self._refresh_all()
            self.call_after_refresh(self._focus_latest_approval)
            return
        if event.kind == "error" and state is self._active_agent(): self._write_local(f"error: {event.text}")
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

    def _focus_latest_approval(self) -> None:
        approvals = list(self.screen_stack[0].query(ApprovalMessage))
        if approvals:
            approvals[-1].focus()

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

    def _refresh_all(self) -> None:
        self._refresh_agent_labels()
        self._render_active()

    def _refresh_agent_labels(self) -> None:
        try:
            view = self.screen_stack[0].query_one("#agents", ListView)
        except (IndexError, NoMatches):
            return
        for item, state in zip(view.children, self.manager.agents, strict=False):
            item.query_one(Label).update(self._agent_label(state))

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
        if state.unread_count:
            label.append(f"  +{state.unread_count}", style="bold #e9b949")
        label.append(f"  {state.status.value}", style="#7a879a")
        label.append(f"\n  └─ {state.config.working_directory.name}", style="#46566c")
        return label

    @staticmethod
    def display_path(path: Path) -> str:
        try: return f"~/{path.relative_to(Path.home())}"
        except ValueError: return str(path)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cyberdeck",
        description="Open Deck Systems terminal workspace for local AI agents",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.parse_args()
    CyberdeckApp().run()


if __name__ == "__main__": main()
