import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest
from textual.widgets import Static

import cyberdeck.module_registry as module_registry_module
from cyberdeck.app import CyberdeckApp
from cyberdeck.config import ConfigStore
from cyberdeck.journal import JournalStore
from cyberdeck.module_cli import configure_module_parser, scaffold_module
from cyberdeck.module_registry import ModuleRecord, ModuleRegistry
from cyberdeck.modules import (
    CYBERDECK_MODULE_API,
    DeckCommand,
    DeckModule,
    ModuleContext,
    ModuleManifest,
    ModuleStatus,
    validate_manifest,
)


def context_for(registry: ModuleRegistry, module_id: str) -> ModuleContext:
    return ModuleContext(
        module_id,
        registry.root / "data" / module_id,
        registry.config_root / module_id,
        lambda *_args: None,
        lambda _text: None,
        {},
    )


class ExternalModule(DeckModule):
    manifest = ModuleManifest(
        "status",
        "SYSTEM STATUS",
        "External module fixture",
        version="0.1.0",
        source="test",
    )

    def build(self):
        return Static("STATUS ONLINE")

    async def handle_prompt(self, text: str) -> None:
        return None


def test_manifest_contract_rejects_invalid_and_incompatible_ids() -> None:
    assert CYBERDECK_MODULE_API == 1
    validate_manifest(ExternalModule.manifest)
    with pytest.raises(ValueError, match="Module id"):
        validate_manifest(ModuleManifest("Bad ID", "BAD", "Invalid"))
    with pytest.raises(ValueError, match="reserved"):
        validate_manifest(ModuleManifest("agents", "BAD", "Reserved", source="external"))
    with pytest.raises(ValueError, match="incompatible"):
        validate_manifest(ModuleManifest("wrong-api", "BAD", "Invalid", api_version=99))


def test_registry_round_trip_and_corruption_recovery(tmp_path: Path) -> None:
    registry = ModuleRegistry(tmp_path / "modules", tmp_path / "config")
    registry.records["status"] = ModuleRecord(
        "status", "cyberdeck-module-status", "0.1.0", "local", "status-env"
    )
    registry.save()
    restored = ModuleRegistry(tmp_path / "modules", tmp_path / "config")
    assert restored.records["status"].package == "cyberdeck-module-status"
    payload = json.loads(restored.path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    restored.path.write_text("not json", encoding="utf-8")
    corrupt = ModuleRegistry(tmp_path / "modules", tmp_path / "config")
    assert corrupt.records == {}
    assert corrupt.errors


def test_install_requires_explicit_trust(tmp_path: Path) -> None:
    registry = ModuleRegistry(tmp_path / "modules", tmp_path / "config")
    with pytest.raises(PermissionError, match="explicit trust"):
        registry.install("anything", lambda module_id: context_for(registry, module_id))


def test_scaffolder_creates_entry_point_package(tmp_path: Path) -> None:
    project = scaffold_module("signal-status", tmp_path)
    pyproject = (project / "pyproject.toml").read_text(encoding="utf-8")
    source = (project / "src/signal_status/__init__.py").read_text(encoding="utf-8")
    assert '[project.entry-points."cyberdeck.modules"]' in pyproject
    assert "signal-status" in source
    with pytest.raises(FileExistsError):
        scaffold_module("signal-status", tmp_path)


def test_module_cli_exposes_complete_local_workflow() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    configure_module_parser(subparsers)
    for action in (
        "list",
        "info status",
        "install package --trust --disabled",
        "link ./module --trust",
        "validate ./module --trust",
        "update status --trust",
        "enable status",
        "disable status",
        "remove status --yes",
        "init status",
    ):
        parsed = parser.parse_args(f"module {action}".split())
        assert parsed.command == "module"


def test_module_commands_complete_actions_and_external_module_ids(tmp_path: Path) -> None:
    registry = ModuleRegistry(tmp_path / "modules", tmp_path / "config")
    registry.records["system-status"] = ModuleRecord(
        "system-status",
        "cyberdeck-module-system-status",
        "0.1.0",
        "local",
        "system-status-env",
        enabled=False,
        status=ModuleStatus.DISABLED.value,
    )
    app = CyberdeckApp(skip_boot=True, module_registry=registry)
    assert app._complete("/module li") == [
        ("link", "link an editable local module project")
    ]
    assert app._complete("/module enable sys") == [
        ("system-status", "disabled external module")
    ]


@pytest.mark.asyncio
async def test_completing_module_action_inserts_argument_separator(tmp_path: Path) -> None:
    async with CyberdeckApp(
        skip_boot=True,
        config_store=ConfigStore(tmp_path / "config.toml"),
        journal_store=JournalStore(tmp_path / "journal"),
        module_registry=ModuleRegistry(tmp_path / "modules", tmp_path / "module-config"),
    ).run_test() as pilot:
        prompt = pilot.app.query_one("#prompt")
        prompt.value = "/module li"
        await pilot.pause()
        pilot.app.action_complete_prompt()
        assert prompt.value == "/module link "


def test_pending_update_rolls_back_when_new_environment_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = ModuleRegistry(tmp_path / "modules", tmp_path / "config")
    old_environment = registry.root / "status-old"
    new_environment = registry.root / "status-new"
    old_environment.mkdir(parents=True)
    new_environment.mkdir()
    record = ModuleRecord(
        "status",
        "cyberdeck-module-status",
        "0.1.0",
        "local",
        old_environment.name,
        pending_environment=new_environment.name,
    )
    registry.records[record.id] = record
    registry.save()
    registry.apply_pending_updates()

    def load_environment(environment: Path, _context):
        if environment.name == new_environment.name:
            raise RuntimeError("new version failed to import")
        return ExternalModule(), "cyberdeck-module-status", "0.1.0"

    monkeypatch.setattr(registry, "_load_environment", load_environment)
    modules, failures = registry.discover_enabled(
        lambda module_id: context_for(registry, module_id)
    )
    assert "status" in modules
    assert "restored previous version" in failures["status"]
    assert record.environment == old_environment.name
    assert record.previous_environment is None
    assert record.status == ModuleStatus.ENABLED.value
    assert old_environment.exists()
    assert not new_environment.exists()


def test_remove_rejects_previous_environment_outside_module_root(tmp_path: Path) -> None:
    registry = ModuleRegistry(tmp_path / "modules", tmp_path / "config")
    environment = registry.root / "status"
    environment.mkdir(parents=True)
    outside = tmp_path / "do-not-delete"
    outside.mkdir()
    record = ModuleRecord(
        "status",
        "cyberdeck-module-status",
        "0.1.0",
        "local",
        environment.name,
        previous_environment="../../do-not-delete",
    )
    registry.records[record.id] = record

    with pytest.raises(ValueError, match="escaped the module root"):
        registry.remove(record.id)

    assert outside.exists()


@pytest.mark.integration
def test_local_module_installs_into_user_owned_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module_registry_module, "__version__", "0.2.0")
    project = scaffold_module("signal-status", tmp_path)
    pyproject = project / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            "cyberdeck-tui>=0.2,<0.3", "cyberdeck-tui>=0.1,<0.3"
        ),
        encoding="utf-8",
    )
    registry = ModuleRegistry(tmp_path / "modules", tmp_path / "config")
    distribution = tmp_path / "dist"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--no-isolation",
            "--wheel",
            "--outdir",
            str(distribution),
            str(project),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(distribution.glob("*.whl"))
    record, module = registry.install(
        str(wheel),
        lambda module_id: context_for(registry, module_id),
        trusted=True,
    )
    assert record.id == "signal-status"
    assert record.enabled is True
    assert module is not None
    assert registry.environment_path(record).is_dir()
    assert registry.root in registry.environment_path(record).parents
    registry.set_enabled(record.id, False)
    assert registry.records[record.id].status == ModuleStatus.DISABLED.value
    registry.remove(record.id)
    assert record.id not in registry.records


@pytest.mark.asyncio
async def test_external_module_hot_mount_preserves_shell_and_can_disable(tmp_path: Path) -> None:
    registry = ModuleRegistry(tmp_path / "modules", tmp_path / "module-config")
    registry.records["status"] = ModuleRecord(
        "status",
        "cyberdeck-module-status",
        "0.1.0",
        "test",
        "unused",
        enabled=False,
        status=ModuleStatus.DISABLED.value,
    )
    registry.save()
    async with CyberdeckApp(
        skip_boot=True,
        config_store=ConfigStore(tmp_path / "config.toml"),
        journal_store=JournalStore(tmp_path / "journal"),
        module_registry=registry,
    ).run_test() as pilot:
        await pilot.app._mount_external_module(ExternalModule())
        registry.set_enabled("status", True)
        assert pilot.app.active_module_id == "status"
        assert pilot.app.query_one("#status-module").display is True
        assert pilot.app.query_one("#agent-module").display is False
        assert str(pilot.app.query_one("#prompt-prefix").content) == "local@status:~ $"
        assert pilot.app.query_one("#prompt").placeholder == "module input... or /command"
        await pilot.app._disable_external_module("status")
        assert pilot.app.active_module_id == "agents"
        assert "status" not in pilot.app.deck_modules
        assert registry.records["status"].status == ModuleStatus.DISABLED.value


@pytest.mark.asyncio
async def test_external_command_collision_is_rejected_without_replacing_shell(
    tmp_path: Path,
) -> None:
    class ConflictingModule(ExternalModule):
        def commands(self):
            return DeckCommand("/help", "replace core help", lambda _args: None),

    async with CyberdeckApp(
        skip_boot=True,
        config_store=ConfigStore(tmp_path / "config.toml"),
        journal_store=JournalStore(tmp_path / "journal"),
        module_registry=ModuleRegistry(tmp_path / "modules", tmp_path / "module-config"),
    ).run_test() as pilot:
        with pytest.raises(ValueError, match="command collision"):
            await pilot.app._mount_external_module(ConflictingModule())
        assert pilot.app.active_module_id == "agents"
        assert "status" not in pilot.app.deck_modules
