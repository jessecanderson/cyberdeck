"""Platform clipboard boundary with deterministic error reporting."""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable


class ClipboardService:
    def __init__(self, writer: Callable[[str], None] | None = None) -> None:
        self._writer = writer

    def write(self, text: str, terminal_writer: Callable[[str], None]) -> str:
        if self._writer is not None:
            self._writer(text)
            return "configured writer"
        if sys.platform == "darwin":
            return self._write_macos(text)
        try:
            terminal_writer(text)
        except Exception as exc:
            raise RuntimeError(f"terminal clipboard failed: {exc}") from exc
        return "terminal protocol"

    @staticmethod
    def _write_macos(text: str) -> str:
        executable = shutil.which("pbcopy")
        if not executable:
            raise RuntimeError("pbcopy is unavailable")
        try:
            subprocess.run(
                [executable],
                input=text,
                text=True,
                check=True,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"pbcopy failed: {exc}") from exc
        return "pbcopy"
