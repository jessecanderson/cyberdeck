import sys
from pathlib import Path

import pytest
from rich.cells import cell_len, chop_cells

from cyberdeck import __version__
from cyberdeck.app import (
    AboutScreen,
    AgentSwitcher,
    ApprovalMessage,
    BootScreen,
    ConfirmScreen,
    CyberdeckApp,
    DispatchScreen,
    EmptyGrid,
    OperativeControl,
    RestoreScreen,
    SpawnAgent,
    ice_level,
    main,
)
from cyberdeck.domain import (
    AgentConfig,
    AgentState,
    AgentStatus,
    OperationEntry,
    OperationState,
    PendingApproval,
    TranscriptEntry,
)
from cyberdeck.providers import AgentEvent


@pytest.mark.asyncio
async def test_app_mounts() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        await pilot.pause()
        assert pilot.app.query_one("#agent-header") is not None
        assert pilot.app.query_one("#prompt").disabled is False
        assert pilot.app.query_one("#top-rail") is not None
        assert pilot.app.query_one("#conversation") is not None
        assert pilot.app.query_one("#signal-trace") is not None
        assert pilot.app.query_one("#state-transition").display is False
        assert pilot.app.query_one(EmptyGrid) is not None
        assert "LOCAL GRID 00/00" in str(pilot.app.query_one("#uplink-count").content)
        assert "NO ACTIVE CONSTRUCT" in str(pilot.app.query_one("#agent-name").content)
        assert "STATE OFFLINE" in str(pilot.app.query_one("#agent-state").content)
        assert pilot.app.query_one("#sidebar-title").size.width == pilot.app.query_one("#sidebar").content_size.width
        assert "接続" in str(pilot.app.query_one("#sidebar-title").content)
        assert "LOCAL GRID" in str(pilot.app.query_one("#sidebar-title").content)
        assert "MODULE BAY" in str(pilot.app.query_one("#modules-title").content)
        assert "電脳端末" in str(pilot.app.query_one("#deck-brand").content)


def test_agent_label_exposes_real_local_provider_topology() -> None:
    app = CyberdeckApp(skip_boot=True)
    state = AgentState(
        AgentConfig("ghost", Path("/tmp")),
        status=AgentStatus.READY,
        model_provider="codex",
    )
    label = str(app._agent_label(state))
    assert "SYN::GHOST" in label
    assert "CODEX / LOCAL" in label
    assert "tmp" in label


@pytest.mark.parametrize(
    ("status", "unread", "attention"),
    [
        (AgentStatus.FIREWALL_HOLD, 0, "ATTN::ICE"),
        (AgentStatus.ERROR, 0, "ATTN::FAULT"),
        (AgentStatus.READY, 3, "ECHO +3"),
    ],
)
def test_agent_label_surfaces_attention(
    status: AgentStatus, unread: int, attention: str
) -> None:
    app = CyberdeckApp(skip_boot=True)
    state = AgentState(
        AgentConfig("ghost", Path("/tmp")),
        status=status,
        unread_count=unread,
    )
    assert attention in str(app._agent_label(state))


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        (OperationEntry("commandExecution", "ls"), "TRACE"),
        (OperationEntry("fileChange", "app.py"), "PATCH"),
        (OperationEntry("mcpToolCall", "issues"), "PROBE"),
        (OperationEntry("webSearch", "ACP"), "SCAN"),
        (OperationEntry("tool", "blocked", OperationState.APPROVAL), "ICE"),
        (OperationEntry("tool", "broken", OperationState.FAILED), "FAULT"),
    ],
)
def test_grid_trace_classes_are_semantic(operation: OperationEntry, expected: str) -> None:
    assert CyberdeckApp._trace_class(operation) == expected


@pytest.mark.asyncio
async def test_local_help_command_does_not_require_agent() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        prompt = pilot.app.query_one("#prompt")
        prompt.value = "/help"
        await pilot.press("enter")
        await pilot.pause()
        assert pilot.app.screen.__class__.__name__ == "HelpScreen"
        assert "/new" in str(pilot.app.screen.query_one("#help-content").content)
        await pilot.press("escape")
        await pilot.pause()
        assert pilot.app.screen.__class__.__name__ != "HelpScreen"


@pytest.mark.asyncio
async def test_about_reports_version_and_copies_safe_manifest(monkeypatch) -> None:
    copied: list[str] = []
    monkeypatch.setattr(CyberdeckApp, "_executable_version", staticmethod(lambda _name: "codex 1.2.3"))
    async with CyberdeckApp(skip_boot=True, clipboard_writer=copied.append).run_test() as pilot:
        await pilot.app._run_local_command("/about")
        await pilot.pause()
        assert isinstance(pilot.app.screen, AboutScreen)
        content = pilot.app.screen.manifest
        assert f"Cyberdeck...... {__version__}" in content
        assert "Codex CLI...... codex 1.2.3" in content
        assert "No prompts, transcripts" in content
        await pilot.press("c")
        assert copied == [content]


@pytest.mark.asyncio
async def test_boot_screen_is_shown() -> None:
    async with CyberdeckApp().run_test() as pilot:
        await pilot.pause()
        assert pilot.app.screen.id is not None or pilot.app.screen.__class__.__name__ == "BootScreen"
        await pilot.press("enter")


def test_boot_contains_fictional_japanese_extension_module() -> None:
    boot_text = "\n".join(line for line, _style, _delay in BootScreen.BOOT_LINES)
    assert "零界技研・企業拡張領域" in boot_text
    assert "神経接続規格" in boot_text
    assert "境界外通信は記録されます" in boot_text
    assert f"QUANTUM BIOS v{__version__}" in boot_text
    assert "2 . 5 . 1" not in boot_text


def test_boot_lines_clip_to_terminal_cells_without_wrapping() -> None:
    width = 32
    japanese = next(
        line for line, _style, _delay in BootScreen.BOOT_LINES if "零界技研" in line
    )
    clipped = chop_cells(japanese, width)[0]
    assert cell_len(clipped) <= width
    assert width - cell_len(clipped) >= 0


def test_version_flag_reports_installed_package_version(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["cyberdeck", "--version"])
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"cyberdeck {__version__}"


@pytest.mark.asyncio
async def test_spawn_agent_inputs_are_visible_and_accept_text() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        pilot.app.push_screen(SpawnAgent())
        await pilot.pause()
        name = pilot.app.screen.query_one("#spawn-agent-name")
        path = pilot.app.screen.query_one("#spawn-agent-path")
        assert name.outer_size.height == 3
        assert path.outer_size.height == 3
        name.focus()
        await pilot.press("g", "h", "o", "s", "t")
        assert name.value == "ghost"


@pytest.mark.asyncio
async def test_approval_request_renders_inline_without_blocking_other_agents() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        state = pilot.app.manager.register("ghost", Path("/tmp"), status=AgentStatus.FIREWALL_HOLD)
        state.pending_approvals.append(PendingApproval(
            7,
            "item/commandExecution/requestApproval",
            {"command": "npm install", "cwd": "/tmp", "reason": "network access"},
        ))
        await pilot.app._add_agent_item(state, select=True)
        pilot.app._render_active()
        await pilot.pause()
        assert pilot.app.screen is pilot.app.screen_stack[0]
        widget = pilot.app.query_one(ApprovalMessage)
        assert widget is not None
        assert ice_level(state, widget.approval)[0] == "GRAY ICE"


def test_dangerous_command_is_classified_as_black_ice() -> None:
    state = AgentState(AgentConfig("ghost", Path("/tmp")))
    approval = PendingApproval(
        8,
        "item/commandExecution/requestApproval",
        {"command": "sudo rm -rf /tmp/cache"},
    )
    assert ice_level(state, approval)[0] == "BLACK ICE"


@pytest.mark.asyncio
async def test_operations_console_toggles() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        console = pilot.app.query_one("#operations-console")
        assert console.display is False
        await pilot.press("ctrl+o")
        assert console.display is True
        await pilot.press("ctrl+o")
        assert console.display is False


@pytest.mark.asyncio
async def test_grid_trace_rows_include_class_and_phase() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        state = pilot.app.manager.register("ghost", Path("/tmp"), status=AgentStatus.READY)
        state.operations.extend(
            [
                OperationEntry("commandExecution", "pytest", OperationState.RUNNING),
                OperationEntry("fileChange", "app.py", OperationState.SUCCEEDED),
            ]
        )
        await pilot.app._add_agent_item(state, select=True)
        pilot.app._render_active()
        await pilot.pause()
        labels = [str(label.content) for label in pilot.app.query("#operations-list Label")]
        assert any("TRACE" in label and "ACTIVE" in label for label in labels)
        assert any("PATCH" in label and "CLEAR" in label for label in labels)


@pytest.mark.asyncio
async def test_grid_layout_survives_narrow_terminal() -> None:
    async with CyberdeckApp(skip_boot=True).run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        assert pilot.app.query_one("#sidebar").size.width >= 26
        assert pilot.app.query_one(EmptyGrid) is not None


@pytest.mark.asyncio
async def test_tab_in_restore_screen_moves_focus_without_prompt_lookup() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        pilot.app.push_screen(RestoreScreen([]))
        await pilot.pause()
        before = pilot.app.screen.focused
        await pilot.press("tab")
        await pilot.pause()
        assert pilot.app.screen.__class__.__name__ == "RestoreScreen"
        assert pilot.app.screen.focused is not before


@pytest.mark.asyncio
async def test_new_shortcuts_open_agent_overlays() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        state = pilot.app.manager.register("ghost", Path("/tmp"), status=AgentStatus.READY)
        await pilot.app._add_agent_item(state, select=True)
        await pilot.press("ctrl+g")
        assert isinstance(pilot.app.screen, OperativeControl)
        await pilot.press("escape")
        await pilot.press("ctrl+p")
        assert isinstance(pilot.app.screen, AgentSwitcher)
        await pilot.press("escape")
        await pilot.press("ctrl+b")
        assert isinstance(pilot.app.screen, DispatchScreen)


@pytest.mark.asyncio
async def test_prompt_history_restores_newest_draft() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        prompt = pilot.app.query_one("#prompt")
        prompt.value = "/path"
        await pilot.press("enter")
        prompt.value = "unsent draft"
        await pilot.press("up")
        assert prompt.value == "/path"
        await pilot.press("down")
        assert prompt.value == "unsent draft"


def test_lifecycle_and_dispatch_commands_are_autocompletable() -> None:
    app = CyberdeckApp(skip_boot=True)
    expected = {"/agent", "/rename", "/interrupt", "/retry", "/disconnect", "/archive", "/dispatch", "/copy", "/send", "/pipe", "/kill"}
    assert expected <= set(app.LOCAL_COMMANDS)


def test_prompt_completion_ignores_unresolvable_tilde_token() -> None:
    app = CyberdeckApp(skip_boot=True)
    assert app._complete("Create me a test.txt doc in ~d") == []


def test_agent_commands_complete_callsigns_and_kill_all() -> None:
    app = CyberdeckApp(skip_boot=True)
    app.manager.register("Ghost", Path("/tmp"), status=AgentStatus.READY)
    app.manager.register("Cipher", Path("/tmp"), status=AgentStatus.READY)
    assert app._complete("/send gh") == [("Ghost", "ready agent")]
    assert app._complete("/pipe ci") == [("Cipher", "ready agent")]
    assert ("all", "all connected agents") in app._complete("/kill a")


@pytest.mark.asyncio
async def test_copy_defaults_to_latest_assistant_response() -> None:
    copied: list[str] = []
    async with CyberdeckApp(skip_boot=True, clipboard_writer=copied.append).run_test() as pilot:
        state = pilot.app.manager.register("ghost", Path("/tmp"), status=AgentStatus.READY)
        state.transcript.extend([
            TranscriptEntry("assistant", "first"),
            TranscriptEntry("user", "next"),
            TranscriptEntry("assistant", "latest"),
        ])
        await pilot.app._add_agent_item(state, select=True)
        await pilot.app._run_local_command("/copy")
        assert copied == ["latest"]


def test_macos_clipboard_uses_pbcopy(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], str]] = []

    def run(command, *, input, text, check, timeout):
        assert text is True
        assert check is True
        assert timeout == 2
        calls.append((command, input))

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("cyberdeck.app.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("cyberdeck.app.subprocess.run", run)

    target = CyberdeckApp(skip_boot=True)._copy_text("deck signal")

    assert target == "pbcopy"
    assert calls == [(["/usr/bin/pbcopy"], "deck signal")]


@pytest.mark.asyncio
async def test_kill_requires_confirmation() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        state = pilot.app.manager.register("ghost", Path("/tmp"), status=AgentStatus.READY)
        await pilot.app._add_agent_item(state, select=True)
        await pilot.app._run_local_command("/kill ghost")
        assert isinstance(pilot.app.screen, ConfirmScreen)
        assert state in pilot.app.manager.agents
        await pilot.press("n")
        assert state in pilot.app.manager.agents
        await pilot.app._run_local_command("/kill ghost")
        await pilot.press("y")
        await pilot.pause()
        assert state not in pilot.app.manager.agents


@pytest.mark.asyncio
async def test_agent_events_show_real_state_transition_banner() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        state = pilot.app.manager.register("ghost", Path("/tmp"), status=AgentStatus.READY)
        await pilot.app._add_agent_item(state, select=True)
        pilot.app._agent_event(state, AgentEvent("status", "processing"))
        banner = pilot.app.query_one("#state-transition")
        assert banner.display is True
        assert "CONSTRUCT ACTIVE // SIGNAL ENGAGED" in str(banner.content)
