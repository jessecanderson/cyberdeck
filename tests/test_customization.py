from datetime import date
from pathlib import Path

import pytest

from cyberdeck.app import CyberdeckApp
from cyberdeck.config import ConfigStore, DeckConfig, RuntimeConfig
from cyberdeck.journal import JournalStore
from cyberdeck.modules import ModuleInputMode
from cyberdeck.themes import import_theme, load_theme

THEME = """schema_version = 1
id = "afterglow"
name = "Afterglow"
author = "Deck Operator"

[colors]
primary = "#ffb000"
secondary = "#ff5f5f"
background = "#050200"
surface = "#120900"
foreground = "#ffe9bf"
muted = "#8f7651"
success = "#80d080"
warning = "#ffb000"
error = "#ff4040"

[styles]
heading = "bold"
muted = "dim"
"""


def test_config_round_trip(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.toml")
    expected = DeckConfig("afterglow", "journal", tmp_path / "notes")
    store.save(expected)
    assert store.load() == expected


def test_config_round_trip_preserves_runtime_definitions(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.toml")
    expected = DeckConfig(
        default_runtime="work-agent",
        runtimes=(
            RuntimeConfig(
                "work-agent",
                "Work ACP",
                ("work-agent", "--acp"),
                ("WORK_AGENT_PROFILE",),
            ),
        ),
    )

    store.save(expected)

    assert store.load() == expected


def test_config_ignores_reserved_runtime_override_without_losing_preferences(
    tmp_path: Path,
) -> None:
    store = ConfigStore(tmp_path / "config.toml")
    store.path.write_text(
        '[deck]\ntheme = "afterglow"\n\n[[runtimes]]\n'
        'id = "codex"\nlabel = "Override"\ncommand = ["other"]\n',
        encoding="utf-8",
    )

    config = store.load()

    assert config.active_theme == "afterglow"
    assert config.runtimes == ()


def test_journal_uses_portable_daily_markdown(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal")
    day = date(2026, 7, 25)
    assert store.read(day).startswith("# Saturday, July 25, 2026")
    updated = store.append_quick_entry(day, "Remember the signal")
    assert "Remember the signal" in updated
    assert store.path_for(day).read_text(encoding="utf-8") == updated
    assert store.days("signal") == [day]


def test_journal_search_normalizes_japanese_unicode(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal")
    day = date(2026, 7, 25)
    store.write(day, "今日は日本語で日記を書く。がんばります。\n")
    assert store.days("日本語") == [day]
    assert store.days("か\u3099んばります") == [day]


def test_theme_validation_and_import(tmp_path: Path) -> None:
    source = tmp_path / "source.toml"
    source.write_text(THEME, encoding="utf-8")
    parsed = load_theme(source)
    assert parsed.id == "afterglow"
    imported = import_theme(source, tmp_path / "themes")
    assert imported == parsed
    assert (tmp_path / "themes" / "afterglow.toml").exists()
    with pytest.raises(FileExistsError):
        import_theme(source, tmp_path / "themes")


def test_theme_rejects_structural_keys(tmp_path: Path) -> None:
    source = tmp_path / "unsafe.toml"
    source.write_text(THEME.replace('muted = "#8f7651"', 'layout = "evil.tcss"'), encoding="utf-8")
    with pytest.raises(ValueError, match="Missing theme colors|Unknown theme colors"):
        load_theme(source)


@pytest.mark.asyncio
async def test_shell_switches_modules_and_routes_journal_prompt(tmp_path: Path) -> None:
    config_store = ConfigStore(tmp_path / "config.toml")
    journal = JournalStore(tmp_path / "journal")
    async with CyberdeckApp(
        skip_boot=True, config_store=config_store, journal_store=journal
    ).run_test() as pilot:
        await pilot.pause()
        await pilot.app._switch_module("journal")
        await pilot.pause()
        assert pilot.app.active_module_id == "journal"
        assert pilot.app.deck_modules["journal"].input_mode is ModuleInputMode.WORKSPACE_EDITOR
        assert pilot.app.query_one("#journal-module").display is True
        assert pilot.app.query_one("#agent-module").display is False
        assert pilot.app.query_one("#journal-editor").has_focus is True
        module_labels = [
            str(item.query_one("Label").content)
            for item in pilot.app.query_one("#modules").children
        ]
        assert any("JOURNAL  ACTIVE" in label for label in module_labels)
        assert any("AGENT COMMAND  STANDBY" in label for label in module_labels)
        await pilot.app._handle_journal_prompt("First modular entry")
        assert "First modular entry" in journal.read(pilot.app._journal_day)
        await pilot.app._switch_module("agents")
        assert pilot.app.query_one("#agent-module").display is True
        assert config_store.load().active_module == "agents"


@pytest.mark.asyncio
async def test_journal_editor_owns_keys_and_restores_focus_and_cursor(tmp_path: Path) -> None:
    async with CyberdeckApp(
        skip_boot=True,
        config_store=ConfigStore(tmp_path / "config.toml"),
        journal_store=JournalStore(tmp_path / "journal"),
    ).run_test() as pilot:
        await pilot.pause()
        await pilot.app._switch_module("journal")
        await pilot.pause()
        editor = pilot.app.query_one("#journal-editor")
        editor.load_text("first\nsecond")
        editor.move_cursor((1, 2))
        await pilot.press("up")
        assert editor.cursor_location == (0, 2)
        editor.move_cursor((1, 3))

        await pilot.press("ctrl+l")
        assert pilot.app.query_one("#prompt").has_focus is True
        await pilot.press("escape")
        assert editor.has_focus is True

        await pilot.app._switch_module("agents")
        await pilot.app._switch_module("journal")
        await pilot.pause()
        assert editor.has_focus is True
        assert editor.cursor_location == (1, 3)


@pytest.mark.asyncio
async def test_journal_ctrl_s_round_trips_japanese(tmp_path: Path) -> None:
    journal = JournalStore(tmp_path / "journal")
    async with CyberdeckApp(
        skip_boot=True,
        config_store=ConfigStore(tmp_path / "config.toml"),
        journal_store=journal,
    ).run_test() as pilot:
        await pilot.pause()
        await pilot.app._switch_module("journal")
        await pilot.pause()
        editor = pilot.app.query_one("#journal-editor")
        editor.load_text("# 日記\n\n今日はCyberdeckで書きます。\n")
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert journal.read(pilot.app._journal_day) == editor.text


@pytest.mark.asyncio
async def test_journal_command_line_keeps_quick_entry_behavior(tmp_path: Path) -> None:
    journal = JournalStore(tmp_path / "journal")
    async with CyberdeckApp(
        skip_boot=True,
        config_store=ConfigStore(tmp_path / "config.toml"),
        journal_store=journal,
    ).run_test() as pilot:
        await pilot.pause()
        await pilot.app._switch_module("journal")
        await pilot.pause()
        await pilot.press("ctrl+l")
        await pilot.press(*"日本語のクイックメモ")
        await pilot.press("enter")
        assert "日本語のクイックメモ" in journal.read(pilot.app._journal_day)


@pytest.mark.asyncio
async def test_enter_from_journal_date_list_focuses_editor(tmp_path: Path) -> None:
    async with CyberdeckApp(
        skip_boot=True,
        config_store=ConfigStore(tmp_path / "config.toml"),
        journal_store=JournalStore(tmp_path / "journal"),
    ).run_test() as pilot:
        await pilot.pause()
        await pilot.app._switch_module("journal")
        await pilot.pause()
        days = pilot.app.query_one("#journal-days")
        days.focus()
        await pilot.press("enter")
        assert pilot.app.query_one("#journal-editor").has_focus is True
