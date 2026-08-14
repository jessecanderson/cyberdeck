import subprocess

import pytest

from cyberdeck.clipboard import ClipboardService


def test_configured_clipboard_writer_is_preferred() -> None:
    copied: list[str] = []
    service = ClipboardService(copied.append)

    target = service.write("signal", lambda _text: pytest.fail("terminal writer used"))

    assert target == "configured writer"
    assert copied == ["signal"]


def test_terminal_clipboard_errors_are_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cyberdeck.clipboard.sys.platform", "linux")
    service = ClipboardService()

    with pytest.raises(RuntimeError, match="terminal clipboard failed: denied"):
        service.write("signal", lambda _text: (_ for _ in ()).throw(ValueError("denied")))


def test_macos_clipboard_reads_pbpaste(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cyberdeck.clipboard.sys.platform", "darwin")
    monkeypatch.setattr("cyberdeck.clipboard.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        "cyberdeck.clipboard.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "deck signal", ""),
    )

    assert ClipboardService().read("stale local value") == "deck signal"
