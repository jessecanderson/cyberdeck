from pathlib import Path

import pytest

from cyberdeck.app import (
    AgentSwitcher,
    ConfirmScreen,
    CyberdeckApp,
    DispatchScreen,
    FirewallRequest,
    OperativeControl,
    RestoreScreen,
)
from cyberdeck.domain import AgentConfig, AgentState, AgentStatus, TranscriptEntry
from cyberdeck.providers import AgentEvent


@pytest.mark.asyncio
async def test_app_mounts() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        await pilot.pause()
        assert pilot.app.query_one("#agent-header") is not None
        assert pilot.app.query_one("#prompt").disabled is False
        assert pilot.app.query_one("#top-rail") is not None
        assert pilot.app.query_one("#conversation") is not None
        assert pilot.app.query_one("#sidebar-title").size.width == pilot.app.query_one("#sidebar").content_size.width


@pytest.mark.asyncio
async def test_local_help_command_does_not_require_agent() -> None:
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        prompt = pilot.app.query_one("#prompt")
        prompt.value = "/help"
        await pilot.press("enter")
        await pilot.pause()
        assert pilot.app.screen.__class__.__name__ == "HelpScreen"
        assert "/new" in pilot.app.screen.query_one("#help-content").renderable
        await pilot.press("escape")
        await pilot.pause()
        assert pilot.app.screen.__class__.__name__ != "HelpScreen"


@pytest.mark.asyncio
async def test_boot_screen_is_shown() -> None:
    async with CyberdeckApp().run_test() as pilot:
        await pilot.pause()
        assert pilot.app.screen.id is not None or pilot.app.screen.__class__.__name__ == "BootScreen"
        await pilot.press("enter")


@pytest.mark.asyncio
async def test_firewall_request_is_red_modal_and_can_be_denied() -> None:
    state = AgentState(AgentConfig("ghost", Path("/tmp")))
    event = AgentEvent(
        "approval",
        request_id=7,
        method="item/commandExecution/requestApproval",
        params={"command": "npm install", "cwd": "/tmp", "reason": "network access"},
    )
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        pilot.app.push_screen(FirewallRequest(state, event))
        await pilot.pause()
        assert pilot.app.screen.__class__.__name__ == "FirewallRequest"
        assert pilot.app.screen.query_one("#firewall-panel") is not None
        await pilot.press("d")


@pytest.mark.asyncio
async def test_firewall_request_can_be_trusted_for_session() -> None:
    state = AgentState(AgentConfig("ghost", Path("/tmp")))
    event = AgentEvent(
        "approval",
        request_id=8,
        method="item/fileChange/requestApproval",
        params={"grantRoot": "/tmp", "reason": "write generated files"},
    )
    result: list[str] = []
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        pilot.app.push_screen(FirewallRequest(state, event), result.append)
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        assert result == ["acceptForSession"]


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
    async with CyberdeckApp(skip_boot=True).run_test() as pilot:
        state = pilot.app.manager.register("ghost", Path("/tmp"), status=AgentStatus.READY)
        state.transcript.extend([
            TranscriptEntry("assistant", "first"),
            TranscriptEntry("user", "next"),
            TranscriptEntry("assistant", "latest"),
        ])
        await pilot.app._add_agent_item(state, select=True)
        pilot.app.copy_to_clipboard = copied.append
        await pilot.app._run_local_command("/copy")
        assert copied == ["latest"]


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
