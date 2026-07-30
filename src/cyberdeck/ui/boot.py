from __future__ import annotations

import asyncio
import random
from typing import ClassVar

from rich.cells import cell_len, chop_cells
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import Static

from .. import __version__


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
        ("[ GRID ] Mapping local cognition topology", "bold #e62acb", 0.10),
        ("  Local grid........ private workspace lattice ....... MAPPED", "#52e891", 0.05),
        ("  Provider gate..... Codex app-server ................. READY", "#52e891", 0.05),
        ("  ICE response...... authorization table .............. ARMED", "#e9b949", 0.05),
        ("  Constructs........ session memory index ............. READY", "#52e891", 0.07),
        ("  Operator link..... 待機中 / awaiting neural handshake", "#00e8f2", 0.10),
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
        (
            "SYSTEM READY // システム起動完了 // HANDING CONTROL TO /CYBERDECK/CORE",
            "bold #00e8f2",
            0.22,
        ),
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
        try:
            log = self.query_one("#boot-log", Static)
        except NoMatches:
            # The boot worker may begin before the screen's children finish mounting.
            return
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
