import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from rich.cells import cell_len, chop_cells
from textual.containers import VerticalScroll
from textual.widgets import Input, Label, ListItem, Static

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
from cyberdeck.config import ConfigStore, RuntimeConfig
from cyberdeck.domain import (
    AgentCapabilities,
    AgentConfig,
    AgentState,
    AgentStatus,
    OperationEntry,
    OperationState,
    PendingApproval,
    ThreadSummary,
    TranscriptEntry,
)
from cyberdeck.manager import AgentManager
from cyberdeck.module_registry import ModuleRegistry
from cyberdeck.providers import AgentEvent
from cyberdeck.runtimes import RuntimePreflight, RuntimeRegistry


@pytest.mark.asyncio
async def test_app_mounts() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        await pilot.pause()
        assert pilot.app.query_one("#agent-header") is not None
        assert pilot.app.query_one("#prompt").disabled is False
        assert pilot.app.query_one("#top-rail") is not None
        assert pilot.app.query_one("#conversation") is not None
        assert pilot.app.query_one("#signal-trace") is not None
        transition = pilot.app.query_one("#state-transition")
        assert transition.display is True
        assert transition.visible is False
        assert pilot.app.query_one(EmptyGrid) is not None
        assert "LOCAL GRID 00/00" in str(pilot.app.query_one("#uplink-count").content)
        assert "NO ACTIVE CONSTRUCT" in str(pilot.app.query_one("#agent-name").content)
        assert "STATE OFFLINE" in str(pilot.app.query_one("#agent-state").content)
        assert (
            pilot.app.query_one("#sidebar-title").size.width
            == pilot.app.query_one("#sidebar").content_size.width
        )
        assert "接続" in str(pilot.app.query_one("#sidebar-title").content)
        assert "LOCAL GRID" in str(pilot.app.query_one("#sidebar-title").content)
        assert "MODULE BAY" in str(pilot.app.query_one("#modules-title").content)
        assert "電脳端末" in str(pilot.app.query_one("#deck-brand").content)


@pytest.mark.asyncio
async def test_public_application_test_seams_present_agents_and_run_commands() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        state = pilot.app.manager.register("ghost", Path("/tmp"), status=AgentStatus.READY)

        await pilot.app.present_agent(state)
        await pilot.app.execute_command("/path")

        assert pilot.app.active_agent() is state
        assert state.transcript[-1].text == str(Path("/tmp").resolve())


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
def test_agent_label_surfaces_attention(status: AgentStatus, unread: int, attention: str) -> None:
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
        help_scroll = pilot.app.screen.query_one("#help-scroll")
        assert help_scroll.has_focus
        await pilot.press("down", "down", "down")
        await pilot.pause()
        assert help_scroll.scroll_y > 0
        await pilot.press("escape")
        await pilot.pause()
        assert pilot.app.screen.__class__.__name__ != "HelpScreen"


@pytest.mark.asyncio
async def test_help_screen_is_generated_from_every_registered_command() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        await pilot.app._run_local_command("/help")
        await pilot.pause()
        content = str(pilot.app.screen.query_one("#help-content").content)
        for command in pilot.app._all_local_commands():
            assert command in content


@pytest.mark.asyncio
async def test_about_reports_version_and_copies_safe_manifest(monkeypatch) -> None:
    copied: list[str] = []
    monkeypatch.setattr(
        CyberdeckApp, "_executable_version", staticmethod(lambda _name: "codex 1.2.3")
    )
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
async def test_boot_screen_is_shown(tmp_path: Path) -> None:
    registry = ModuleRegistry(tmp_path / "modules", tmp_path / "module-config")
    async with CyberdeckApp(module_registry=registry).run_test() as pilot:
        await pilot.pause()
        assert (
            pilot.app.screen.id is not None or pilot.app.screen.__class__.__name__ == "BootScreen"
        )
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
    japanese = next(line for line, _style, _delay in BootScreen.BOOT_LINES if "零界技研" in line)
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
        provider = pilot.app.screen.query_one("#spawn-provider")
        dialog = pilot.app.screen.query_one("#spawn-dialog")
        assert dialog.outer_size.height == 28
        assert name.outer_size.height == 3
        assert path.outer_size.height == 3
        assert provider.outer_size.height == 3
        assert provider.value == "codex"
        name.focus()
        await pilot.press("g", "h", "o", "s", "t")
        assert name.value == "ghost"


@pytest.mark.asyncio
async def test_spawn_agent_refuses_unavailable_runtime() -> None:
    unavailable = RuntimePreflight("offline", "Offline ACP", False, "executable missing")
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        pilot.app.push_screen(SpawnAgent((unavailable,), "offline"))
        await pilot.pause()
        pilot.app.screen.query_one("#spawn-agent-name", Input).value = "molly"
        pilot.app.screen.query_one("#spawn-provider", Input).focus()
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(pilot.app.screen, SpawnAgent)
        assert "RUNTIME UNAVAILABLE" in str(pilot.app.screen.query_one("#spawn-help").content)


def test_new_command_autocompletes_agent_runtimes() -> None:
    app = CyberdeckApp(skip_boot=True)
    assert app._complete("/new ghost ")[:2] == [
        ("codex", "agent runtime"),
        ("kiro", "agent runtime"),
    ]
    assert app._complete("/new ghost k") == [("kiro", "agent runtime")]
    assert app._complete("/new ghost kiro /tm") == [("/tmp/", "directory")]
    assert app._complete("/new ghost /tmp/ k") == [("kiro", "agent runtime")]
    assert app._complete("/new ghost /tmp/ ") == [
        ("codex", "agent runtime"),
        ("kiro", "agent runtime"),
    ]
    assert app._complete("/approve a") == [("all", "approve every pending ICE request once")]
    assert app._complete("/tr") == [("/trust", "trust the latest ICE request for this session")]
    assert app._complete("/de") == [
        ("/deny", "deny the latest ICE request"),
        ("/density", "show or set workspace density: standard|compact"),
    ]


def test_new_command_autocompletes_configured_runtime() -> None:
    app = CyberdeckApp(skip_boot=True)
    app.manager = AgentManager(
        app._agent_event,
        runtime_registry=RuntimeRegistry(
            (RuntimeConfig("work-agent", "Work ACP", (sys.executable,)),)
        ),
    )

    assert app._complete("/new molly w") == [("work-agent", "agent runtime")]


@pytest.mark.asyncio
async def test_new_command_routes_explicit_provider_to_spawn(monkeypatch) -> None:
    app = CyberdeckApp(skip_boot=True)
    calls: list[tuple[str, Path, str]] = []

    monkeypatch.setattr(
        app,
        "_spawn",
        lambda name, path, provider="codex": calls.append((name, path, provider)),
    )

    await app._run_local_command("/new wintermute kiro /tmp")
    await app._run_local_command("/new ghost /tmp")
    await app._run_local_command("/new cipher kiro")

    assert calls == [
        ("wintermute", Path("/tmp").resolve(), "kiro"),
        ("ghost", Path("/tmp").resolve(), "codex"),
        ("cipher", Path.cwd(), "kiro"),
    ]


@pytest.mark.asyncio
async def test_approval_request_renders_inline_without_blocking_other_agents() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        state = pilot.app.manager.register("ghost", Path("/tmp"), status=AgentStatus.FIREWALL_HOLD)
        state.pending_approvals.append(
            PendingApproval(
                7,
                "item/commandExecution/requestApproval",
                {"command": "npm install", "cwd": "/tmp", "reason": "network access"},
            )
        )
        await pilot.app._add_agent_item(state, select=True)
        pilot.app._render_active()
        await pilot.pause()
        assert pilot.app.screen is pilot.app.screen_stack[0]
        widget = pilot.app.query_one(ApprovalMessage)
        assert widget is not None
        assert ice_level(state, widget.approval)[0] == "GRAY ICE"


@pytest.mark.asyncio
async def test_overflowing_transcript_reveals_and_scrolls_focused_approval() -> None:
    async with CyberdeckApp(skip_boot=True).run_test(size=(100, 30)) as pilot:
        state = pilot.app.manager.register(
            "wintermute", Path("/tmp"), status=AgentStatus.FIREWALL_HOLD
        )
        state.transcript.extend(
            TranscriptEntry("assistant", f"Historical response {index}") for index in range(30)
        )
        state.pending_approvals.append(
            PendingApproval(
                "permission-7",
                "session/request_permission",
                {
                    "toolCall": {"title": "run validation"},
                    "options": [
                        {"optionId": "yes", "name": "Allow", "kind": "allow_once"},
                        {"optionId": "no", "name": "Reject", "kind": "reject_once"},
                    ],
                },
            )
        )
        await pilot.app._add_agent_item(state, select=True)
        await pilot.pause()

        pilot.app._agent_event(
            state,
            AgentEvent(
                "approval",
                request_id="permission-7",
                method="session/request_permission",
            ),
        )
        await pilot.pause()

        conversation = pilot.app.query_one("#conversation", VerticalScroll)
        approval = pilot.app.query_one(ApprovalMessage)
        assert approval.can_focus is False
        assert pilot.app.query_one("#prompt").has_focus
        assert conversation.scroll_y > 0
        assert approval.region.y >= conversation.content_region.y

        before = conversation.scroll_y
        await pilot.press("up")
        await pilot.pause()
        assert conversation.scroll_y < before


@pytest.mark.asyncio
async def test_approve_all_requires_confirmation_and_resolves_batch() -> None:
    class ApprovalAdapter:
        def __init__(self) -> None:
            self.approvals: list[tuple[str, str]] = []

        async def respond_approval(self, request_id: str, decision: str) -> None:
            self.approvals.append((request_id, decision))

        async def stop(self) -> None:
            pass

    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        state = pilot.app.manager.register("ghost", Path("/tmp"), status=AgentStatus.FIREWALL_HOLD)
        state.pending_approvals.extend(
            [
                PendingApproval("permission-7", "session/request_permission", {"options": []}),
                PendingApproval("permission-8", "session/request_permission", {"options": []}),
            ]
        )
        adapter = ApprovalAdapter()
        pilot.app.manager.attach_adapter(state, adapter)
        await pilot.app._add_agent_item(state, select=True)

        await pilot.app._run_local_command("/approve all")
        assert isinstance(pilot.app.screen, ConfirmScreen)
        await pilot.press("y")
        await pilot.pause()

        assert adapter.approvals == [
            ("permission-7", "accept"),
            ("permission-8", "accept"),
        ]
        assert state.pending_approvals == []


@pytest.mark.asyncio
async def test_ice_card_keeps_prompt_typing_and_accepts_slash_decision() -> None:
    class ApprovalAdapter:
        def __init__(self) -> None:
            self.approvals: list[tuple[str, str]] = []

        async def respond_approval(self, request_id: str, decision: str) -> None:
            self.approvals.append((request_id, decision))

        async def stop(self) -> None:
            pass

    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        state = pilot.app.manager.register(
            "wintermute", Path("/tmp"), status=AgentStatus.FIREWALL_HOLD
        )
        state.pending_approvals.append(
            PendingApproval(
                "permission-9",
                "session/request_permission",
                {"options": []},
            )
        )
        adapter = ApprovalAdapter()
        pilot.app.manager.attach_adapter(state, adapter)
        await pilot.app._add_agent_item(state, select=True)
        await pilot.pause()
        pilot.app.query_one("#prompt").focus()
        assert pilot.app._active_agent() is state

        await pilot.press("y")
        await pilot.pause()

        prompt = pilot.app.query_one("#prompt", Input)
        assert prompt.value == "y"
        assert adapter.approvals == []
        assert len(state.pending_approvals) == 1

        prompt.value = ""
        await pilot.app._run_local_command("/approve")
        await pilot.pause()

        assert adapter.approvals == [("permission-9", "accept")]
        assert state.pending_approvals == []


@pytest.mark.asyncio
async def test_prompt_accepts_draft_while_acp_turn_remains_open() -> None:
    release = asyncio.Event()

    class DelayedAdapter:
        thread_id = "kiro-session"
        model = "kiro-test"
        model_provider = "kiro"

        async def send(self, prompt: str) -> None:
            await release.wait()

        async def stop(self) -> None:
            release.set()

    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        state = pilot.app.manager.register(
            "wintermute", Path("/tmp"), provider="kiro", status=AgentStatus.READY
        )
        pilot.app.manager.attach_adapter(state, DelayedAdapter())
        await pilot.app._add_agent_item(state, select=True)
        await pilot.pause()

        prompt = pilot.app.query_one("#prompt", Input)
        prompt.value = "start long turn"
        prompt.focus()
        await pilot.press("enter")
        await pilot.pause()

        assert state.status is AgentStatus.PROCESSING
        await pilot.press("n", "e", "x", "t")
        await pilot.pause()

        assert prompt.has_focus
        assert prompt.value == "next"
        release.set()
        await pilot.pause()


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
        await pilot.press("ctrl+o")
        operations = pilot.app.query_one("#operations-list")
        assert operations.has_focus
        assert operations.index == 0
        await pilot.press("down")
        assert operations.index == 1


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
async def test_agent_switcher_arrows_select_results_without_mouse() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        for name in ("ghost", "molly", "case"):
            state = pilot.app.manager.register(name, Path("/tmp"), status=AgentStatus.READY)
            await pilot.app._add_agent_item(state, select=name == "ghost")
        await pilot.pause(0.2)

        await pilot.press("ctrl+p")
        assert isinstance(pilot.app.screen, AgentSwitcher)
        search = pilot.app.screen.query_one("#switch-search")
        results = pilot.app.screen.query_one("#switch-list")
        assert search.has_focus
        assert results.index == 0

        await pilot.press("down", "down", "up")
        assert search.has_focus
        assert results.index == 1
        await pilot.press("enter")
        await pilot.pause()

        assert pilot.app._active_agent().config.name == "molly"


@pytest.mark.asyncio
async def test_control_and_dispatch_lists_navigate_from_initial_input() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        for name in ("ghost", "molly", "case"):
            state = pilot.app.manager.register(name, Path("/tmp"), status=AgentStatus.READY)
            await pilot.app._add_agent_item(state, select=name == "ghost")
        await pilot.pause(0.2)

        await pilot.press("ctrl+g")
        assert isinstance(pilot.app.screen, OperativeControl)
        control = pilot.app.screen.query_one("#control-list")
        await pilot.press("down", "down")
        assert control.index == 2
        await pilot.press("escape")

        await pilot.press("ctrl+b")
        assert isinstance(pilot.app.screen, DispatchScreen)
        search = pilot.app.screen.query_one("#dispatch-search")
        targets = pilot.app.screen.query_one("#dispatch-list")
        await pilot.press("down", "space")
        assert search.has_focus
        assert search.value == ""
        assert targets.index == 1
        assert pilot.app.manager.agents[1].config.id in pilot.app.screen.selected
        await pilot.press("space")
        assert pilot.app.manager.agents[1].config.id not in pilot.app.screen.selected
        await pilot.press("enter")
        assert pilot.app.manager.agents[1].config.id in pilot.app.screen.selected


@pytest.mark.asyncio
async def test_restore_arrows_navigate_results_while_search_keeps_focus() -> None:
    threads = [
        ThreadSummary(
            id=f"thread-{index}",
            name=name,
            source="cli",
            cwd=Path("/tmp"),
            preview="restorable thread",
            updated_at=datetime.now(UTC),
        )
        for index, name in enumerate(("ghost", "molly", "case"))
    ]
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        pilot.app.push_screen(RestoreScreen(threads))
        await pilot.pause()
        search = pilot.app.screen.query_one("#restore-search")
        results = pilot.app.screen.query_one("#restore-list")

        await pilot.press("down", "down", "up")

        assert search.has_focus
        assert results.index == 1
        await pilot.press("space")
        assert search.value == ""
        assert threads[1].id in pilot.app.screen.selected
        assert "◆" in str(results.children[1].query_one("Label").content)


@pytest.mark.asyncio
async def test_operative_control_marks_unsupported_capabilities() -> None:
    state = AgentState(AgentConfig("molly", Path("/tmp"), provider="kiro"))
    state.capabilities = AgentCapabilities(load_session=True, interrupt=True)
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        pilot.app.push_screen(OperativeControl(state))
        await pilot.pause()

        labels = [str(label.content) for label in pilot.app.screen.query("#control-list Label")]
        assert "RENAME  [UNAVAILABLE]" in labels
        assert "RETRY" in labels
        assert "ARCHIVE  [UNAVAILABLE]" in labels


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
    expected = {
        "/agent",
        "/rename",
        "/interrupt",
        "/retry",
        "/disconnect",
        "/archive",
        "/dispatch",
        "/copy",
        "/send",
        "/pipe",
        "/kill",
        "/approve",
        "/trust",
        "/deny",
        "/runtimes",
    }
    assert expected <= set(app.LOCAL_COMMANDS)


@pytest.mark.asyncio
async def test_arrow_keys_select_autocomplete_and_tab_accepts_highlight() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        prompt = pilot.app.query_one("#prompt")
        prompt.focus()
        prompt.value = "/mo"
        await pilot.pause()

        assert [row[0] for row in pilot.app._prompt_completions[:3]] == [
            "/modules",
            "/module",
        ]
        assert pilot.app._completion_index == 0
        await pilot.press("down")
        assert pilot.app._completion_index == 1

        await pilot.press("tab")
        assert prompt.value == "/module"


@pytest.mark.asyncio
async def test_density_autocomplete_advances_to_and_accepts_mode() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        prompt = pilot.app.query_one("#prompt")
        prompt.focus()
        prompt.value = "/dens"
        await pilot.pause()

        await pilot.press("tab")
        await pilot.pause()
        assert prompt.value == "/density "
        assert [row[0] for row in pilot.app._prompt_completions] == [
            "standard",
            "compact",
        ]

        await pilot.press("down", "tab")
        assert prompt.value == "/density compact"


def test_density_argument_completion_filters_prefix_and_stops_when_complete() -> None:
    app = CyberdeckApp(skip_boot=True)
    assert app._complete("/density c") == [("compact", "use compact workspace presentation")]
    assert app._complete("/density compact") == []


@pytest.mark.asyncio
async def test_enter_accepts_highlighted_completion_before_submitting() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        prompt = pilot.app.query_one("#prompt")
        prompt.focus()
        prompt.value = "/density c"
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert prompt.value == "/density compact"
        assert pilot.app.deck_config.density == "standard"

        await pilot.press("enter")
        await pilot.pause()

        assert prompt.value == ""
        assert pilot.app.deck_config.density == "compact"


@pytest.mark.asyncio
async def test_restore_space_binding_does_not_capture_normal_prompt_spaces() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        prompt = pilot.app.query_one("#prompt")
        prompt.focus()
        await pilot.press("a", "space", "b")
        assert prompt.value == "a b"


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
    assert app._complete("/switch gh") == [("Ghost", "ready agent")]


@pytest.mark.asyncio
async def test_navigation_wraps_many_agents_and_switches_by_callsign() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        for index in range(40):
            state = pilot.app.manager.register(
                f"agent-{index:02d}", Path("/tmp"), status=AgentStatus.READY
            )
            await pilot.app._add_agent_item(state, select=index == 0)

        prompt = pilot.app.query_one("#prompt")
        prompt.focus()
        await pilot.press("ctrl+k")
        assert pilot.app._active_agent().config.name == "agent-39"
        await pilot.press("ctrl+j")
        assert pilot.app._active_agent().config.name == "agent-00"

        await pilot.app._run_local_command("/switch AGENT-27")
        assert pilot.app._active_agent().config.name == "agent-27"
        assert pilot.app.query_one("#agents").index == 27


@pytest.mark.asyncio
async def test_f6_and_slash_command_cycle_modules() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        await pilot.pause(0.2)
        assert pilot.app.active_module_id == "agents"


@pytest.mark.asyncio
async def test_density_command_and_f7_are_presentation_only_and_persisted(
    tmp_path: Path,
) -> None:
    store = ConfigStore(tmp_path / "config.toml")
    async with CyberdeckApp(skip_boot=True, config_store=store).run_test() as pilot:
        state = pilot.app.manager.register("ghost", Path("/tmp"), status=AgentStatus.READY)
        state.transcript.append(TranscriptEntry("assistant", "unchanged signal"))
        await pilot.app._add_agent_item(state, select=True)
        original = list(state.transcript)

        await pilot.app._run_local_command("/density compact")
        await pilot.pause()

        assert pilot.app.screen_stack[0].has_class("compact")
        assert pilot.app.deck_config.show_boot is True
        assert store.load().density == "compact"
        assert state.transcript == original
        assert "\n" not in str(
            pilot.app.query_one(f"#{pilot.app._agent_row_id(state)}").query_one(Label).render()
        )

        await pilot.press("f7")
        await pilot.pause()

        assert not pilot.app.screen_stack[0].has_class("compact")
        assert store.load().density == "standard"
        assert state.transcript == original
        await pilot.press("f6")
        await pilot.pause(0.2)
        assert pilot.app.active_module_id == "journal"

        await pilot.app._run_local_command("/next-module")
        await pilot.pause(0.2)
        assert pilot.app.active_module_id == "agents"


@pytest.mark.asyncio
async def test_context_commands_report_usage_and_clear_only_local_display() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        state = pilot.app.manager.register("ghost", Path("/tmp"), status=AgentStatus.READY)
        state.capabilities = AgentCapabilities(context_compaction=True)
        state.context_tokens = 32_000
        state.context_window = 128_000
        state.transcript.append(TranscriptEntry("assistant", "provider remembers this"))
        await pilot.app._add_agent_item(state, select=True)

        await pilot.app._run_local_command("/context")
        assert "32,000/128,000 tokens (25.0%)" in state.transcript[-1].text
        assert "COMPACT READY" in state.transcript[-1].text
        assert "RUNTIME codex" in state.transcript[-1].text
        assert "CLEAR   display only" in state.transcript[-1].text

        await pilot.app._run_local_command("/clear")
        assert state.transcript == []
        assert state.context_tokens == 32_000


@pytest.mark.asyncio
async def test_whole_message_selection_copies_verbatim_and_cancel_is_non_mutating() -> None:
    copied: list[str] = []
    async with CyberdeckApp(skip_boot=True, clipboard_writer=copied.append).run_test() as pilot:
        state = pilot.app.manager.register("ghost", Path("/tmp"), status=AgentStatus.READY)
        state.transcript.extend(
            [
                TranscriptEntry("user", "first\nline"),
                TranscriptEntry("assistant", "second"),
                TranscriptEntry("system", "third"),
            ]
        )
        original = list(state.transcript)
        await pilot.app._add_agent_item(state, select=True)

        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("space", "down", "space", "enter")
        await pilot.pause()
        assert copied == ["first\nline\n\nsecond"]
        assert state.transcript == original

        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("space", "escape")
        await pilot.pause()
        assert copied == ["first\nline\n\nsecond"]
        assert state.transcript == original


@pytest.mark.asyncio
async def test_selection_scrolls_and_preserves_markdown_code_text() -> None:
    copied: list[str] = []
    async with CyberdeckApp(skip_boot=True, clipboard_writer=copied.append).run_test(
        size=(80, 24)
    ) as pilot:
        state = pilot.app.manager.register("ghost", Path("/tmp"), status=AgentStatus.READY)
        state.transcript.extend(
            TranscriptEntry("assistant", f"message {index}") for index in range(20)
        )
        code = "```python\nprint('signal')\n```"
        state.transcript.append(TranscriptEntry("assistant", code))
        await pilot.app._add_agent_item(state, select=True)

        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press(*(["down"] * 20), "space", "enter")
        await pilot.pause()

        assert copied == [code]


@pytest.mark.asyncio
async def test_selection_reports_clipboard_failure() -> None:
    def fail(_text: str) -> None:
        raise RuntimeError("clipboard unavailable")

    async with CyberdeckApp(skip_boot=True, clipboard_writer=fail).run_test() as pilot:
        state = pilot.app.manager.register("ghost", Path("/tmp"), status=AgentStatus.READY)
        state.transcript.append(TranscriptEntry("assistant", "signal"))
        await pilot.app._add_agent_item(state, select=True)

        await pilot.press("ctrl+e")
        await pilot.pause()
        await pilot.press("space", "enter")
        await pilot.pause()

        assert "CLIPBOARD FAULT" in state.transcript[-1].text


@pytest.mark.asyncio
async def test_agent_label_refresh_uses_stable_row_identity() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        first = pilot.app.manager.register("first", Path("/tmp"), status=AgentStatus.READY)
        second = pilot.app.manager.register("second", Path("/tmp"), status=AgentStatus.READY)
        await pilot.app._add_agent_item(first, select=True)
        await pilot.app._add_agent_item(second, select=False)

        # A non-agent ListItem must not make label refresh depend on positional shape.
        await pilot.app.query_one("#agents").append(ListItem(Static("decoy")))
        second.status = AgentStatus.ERROR
        pilot.app._refresh_agent_label(second)
        row = pilot.app.query_one(f"#{pilot.app._agent_row_id(second)}")
        assert "ATTN::FAULT" in str(row.query_one(Label).render())


@pytest.mark.asyncio
async def test_copy_defaults_to_latest_assistant_response() -> None:
    copied: list[str] = []
    async with CyberdeckApp(skip_boot=True, clipboard_writer=copied.append).run_test() as pilot:
        state = pilot.app.manager.register("ghost", Path("/tmp"), status=AgentStatus.READY)
        state.transcript.extend(
            [
                TranscriptEntry("assistant", "first"),
                TranscriptEntry("user", "next"),
                TranscriptEntry("assistant", "latest"),
            ]
        )
        await pilot.app._add_agent_item(state, select=True)
        await pilot.app._run_local_command("/copy")
        assert copied == ["latest"]


@pytest.mark.asyncio
async def test_copy_numeric_count_grabs_latest_assistant_outputs() -> None:
    copied: list[str] = []
    async with CyberdeckApp(skip_boot=True, clipboard_writer=copied.append).run_test() as pilot:
        state = pilot.app.manager.register("ghost", Path("/tmp"), status=AgentStatus.READY)
        state.transcript.extend(
            [
                TranscriptEntry("assistant", "oldest"),
                TranscriptEntry("user", "question"),
                TranscriptEntry("assistant", "middle\nresponse"),
                TranscriptEntry("system", "diagnostic"),
                TranscriptEntry("assistant", "latest"),
            ]
        )
        await pilot.app._add_agent_item(state, select=True)

        await pilot.app._run_local_command("/copy 2")

        assert copied == ["middle\nresponse\n\nlatest"]


@pytest.mark.asyncio
async def test_copy_numeric_count_rejects_zero() -> None:
    copied: list[str] = []
    async with CyberdeckApp(skip_boot=True, clipboard_writer=copied.append).run_test() as pilot:
        state = pilot.app.manager.register("ghost", Path("/tmp"), status=AgentStatus.READY)
        state.transcript.append(TranscriptEntry("assistant", "latest"))
        await pilot.app._add_agent_item(state, select=True)

        await pilot.app._run_local_command("/copy 0")

        assert copied == []
        assert "at least 1" in state.transcript[-1].text


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
        await pilot.pause()
        assert "ghost [CODEX]" in pilot.app.screen.message
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
        assert banner.visible is True
        assert "CONSTRUCT ACTIVE // SIGNAL ENGAGED" in str(banner.content)


@pytest.mark.asyncio
async def test_state_transition_does_not_resize_conversation() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        state = pilot.app.manager.register("ghost", Path("/tmp"), status=AgentStatus.READY)
        await pilot.app._add_agent_item(state, select=True)
        await pilot.pause()
        conversation = pilot.app.query_one("#conversation")
        initial_region = conversation.region

        pilot.app._agent_event(state, AgentEvent("status", "processing"))
        await pilot.pause()
        assert conversation.region == initial_region

        pilot.app._hide_transition(pilot.app._transition_serial)
        await pilot.pause()
        assert conversation.region == initial_region


@pytest.mark.asyncio
async def test_restore_banner_is_only_shown_for_initial_ready_event() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        state = pilot.app.manager.register("ghost", Path("/tmp"), status=AgentStatus.READY)
        state.restored = True
        await pilot.app._add_agent_item(state, select=True)

        pilot.app._agent_event(state, AgentEvent("status", "ready"))
        banner = pilot.app.query_one("#state-transition")
        assert "CONSTRUCT RESTORED" in str(banner.content)
        assert state.restored is False

        pilot.app._agent_event(state, AgentEvent("status", "ready"))
        assert "GRID MAPPED // CARRIER STABLE" in str(banner.content)


@pytest.mark.asyncio
async def test_background_unread_count_tracks_messages_not_protocol_events() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        active = pilot.app.manager.register("ghost", Path("/tmp"), status=AgentStatus.READY)
        background = pilot.app.manager.register("molly", Path("/tmp"), status=AgentStatus.READY)
        await pilot.app._add_agent_item(active, select=True)
        await pilot.app._add_agent_item(background, select=False)

        background.transcript.append(TranscriptEntry("assistant", "first", source_id="one"))
        pilot.app._agent_event(background, AgentEvent("assistant_delta", "first", message_id="one"))
        pilot.app._agent_event(
            background, AgentEvent("assistant_delta", " continues", message_id="one")
        )
        pilot.app._agent_event(background, AgentEvent("token_usage"))
        pilot.app._agent_event(background, AgentEvent("status", "ready"))
        assert background.unread_count == 1

        background.transcript.append(TranscriptEntry("assistant", "second", source_id="two"))
        pilot.app._agent_event(
            background, AgentEvent("assistant_delta", "second", message_id="two")
        )
        assert background.unread_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["error", "transport_closed"])
async def test_agent_failure_shows_reason_and_retry_instruction(kind: str) -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        state = pilot.app.manager.register("ghost", Path("/tmp"), status=AgentStatus.READY)
        await pilot.app._add_agent_item(state, select=True)

        pilot.app._agent_event(state, AgentEvent(kind, "Codex app-server closed stdout"))

        notice = state.transcript[-1]
        assert notice.role == "system"
        assert "GRID FRACTURE // SIGNAL LOST" in notice.text
        assert "Codex app-server closed stdout" in notice.text
        assert "RECOVERY AVAILABLE // run /retry" in notice.text


@pytest.mark.asyncio
async def test_background_agent_failure_keeps_recovery_notice_with_owner() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        active = pilot.app.manager.register("ghost", Path("/tmp"), status=AgentStatus.READY)
        failed = pilot.app.manager.register("molly", Path("/tmp"), status=AgentStatus.READY)
        await pilot.app._add_agent_item(active, select=True)
        await pilot.app._add_agent_item(failed, select=False)

        pilot.app._agent_event(failed, AgentEvent("transport_closed", "reader failed"))

        assert not active.transcript
        assert "reader failed" in failed.transcript[-1].text
        assert "/retry" in failed.transcript[-1].text
