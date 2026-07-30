from __future__ import annotations

import os
import re
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    id: str
    label: str
    command: tuple[str, ...]
    environment_allowlist: tuple[str, ...] = ()


def _user_root(kind: str) -> Path:
    if sys.platform == "darwin":
        leaf = "Application Support" if kind == "data" else "Preferences"
        return Path.home() / "Library" / leaf / "Cyberdeck"
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "Cyberdeck"
    variable = "XDG_DATA_HOME" if kind == "data" else "XDG_CONFIG_HOME"
    fallback = Path.home() / (".local/share" if kind == "data" else ".config")
    return Path(os.environ.get(variable, fallback)) / "cyberdeck"


@dataclass(slots=True)
class DeckConfig:
    active_theme: str = "ods"
    active_module: str = "agents"
    journal_directory: Path | None = None
    default_runtime: str = "codex"
    runtimes: tuple[RuntimeConfig, ...] = ()
    workspace_root: Path | None = None
    approval_policy: str = "on-request"
    sandbox_mode: str = "workspace-write"
    show_boot: bool = True
    density: str = "standard"
    schema_version: int = CONFIG_SCHEMA_VERSION

    @property
    def journal_path(self) -> Path:
        return self.journal_directory or (_user_root("data") / "journal")


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (_user_root("config") / "config.toml")
        self.errors: list[str] = []

    def load(self) -> DeckConfig:
        self.errors = []
        try:
            data = tomllib.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return DeckConfig()
        except (OSError, tomllib.TOMLDecodeError) as exc:
            self.errors.append(f"Configuration ignored: {exc}")
            return DeckConfig()
        return parse_config(data, self.errors)

    def save(self, config: DeckConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        journal = str(config.journal_directory) if config.journal_directory else ""
        content = (
            f"schema_version = {CONFIG_SCHEMA_VERSION}\n\n"
            "[deck]\n"
            f'theme = "{_escape(config.active_theme)}"\n'
            f'module = "{_escape(config.active_module)}"\n\n'
            f"show_boot = {'true' if config.show_boot else 'false'}\n\n"
            f'density = "{_escape(config.density)}"\n\n'
            "[journal]\n"
            f'directory = "{_escape(journal)}"\n'
            "\n[agents]\n"
            f'default_runtime = "{_escape(config.default_runtime)}"\n'
            f'approval_policy = "{_escape(config.approval_policy)}"\n'
            f'sandbox = "{_escape(config.sandbox_mode)}"\n'
            f'workspace_root = "{_escape(str(config.workspace_root or ""))}"\n'
        )
        for runtime in config.runtimes:
            command = ", ".join(f'"{_escape(part)}"' for part in runtime.command)
            environment = ", ".join(f'"{_escape(name)}"' for name in runtime.environment_allowlist)
            content += (
                "\n[[runtimes]]\n"
                f'id = "{_escape(runtime.id)}"\n'
                f'label = "{_escape(runtime.label)}"\n'
                f"command = [{command}]\n"
                f"environment_allowlist = [{environment}]\n"
            )
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, self.path)


def parse_config(data: Mapping[str, Any], errors: list[str]) -> DeckConfig:
    migrated = migrate_config(data, errors)
    if migrated is None:
        return DeckConfig()
    deck = _table(migrated, "deck")
    agents = _table(migrated, "agents")
    journal = _table(migrated, "journal")
    configured_journal = journal.get("directory")
    return DeckConfig(
        active_theme=str(deck.get("theme", "ods")),
        active_module=str(deck.get("module", "agents")),
        journal_directory=(
            Path(str(configured_journal)).expanduser() if configured_journal else None
        ),
        default_runtime=str(agents.get("default_runtime", "codex")).casefold(),
        runtimes=_parse_runtimes(migrated.get("runtimes", ()), errors),
        workspace_root=_workspace_root(agents.get("workspace_root"), errors),
        approval_policy=_choice(
            agents.get("approval_policy", "on-request"),
            {"untrusted", "on-failure", "on-request", "never"},
            "on-request",
            "approval_policy",
            errors,
        ),
        sandbox_mode=_choice(
            agents.get("sandbox", "workspace-write"),
            {"read-only", "workspace-write", "danger-full-access"},
            "workspace-write",
            "sandbox",
            errors,
        ),
        show_boot=_boolean(deck.get("show_boot", True), "show_boot", True, errors),
        density=_choice(
            deck.get("density", "standard"),
            {"standard", "compact"},
            "standard",
            "density",
            errors,
        ),
    )


def migrate_config(data: Mapping[str, Any], errors: list[str]) -> dict[str, Any] | None:
    """Return data at the current schema or reject an unsupported future schema."""
    raw_version = data.get("schema_version", 0)
    if not isinstance(raw_version, int) or isinstance(raw_version, bool):
        errors.append("Invalid schema_version; configuration ignored")
        return None
    if raw_version > CONFIG_SCHEMA_VERSION:
        errors.append(
            f"Configuration schema {raw_version} is newer than supported schema "
            f"{CONFIG_SCHEMA_VERSION}; configuration ignored"
        )
        return None
    migrated = dict(data)
    # Schema 0 is the unversioned 0.3.4 layout; its field names remain valid in v1.
    migrated["schema_version"] = CONFIG_SCHEMA_VERSION
    return migrated


def _table(data: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = data.get(name, {})
    return value if isinstance(value, Mapping) else {}


def _parse_runtimes(value: object, errors: list[str]) -> tuple[RuntimeConfig, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        errors.append("Ignored invalid runtime definitions")
        return ()
    rows: list[RuntimeConfig] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping) or not item.get("id") or not item.get("command"):
            continue
        runtime_id = str(item["id"]).strip().casefold()
        if (
            not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", runtime_id)
            or runtime_id in seen
            or runtime_id in {"codex", "kiro"}
        ):
            errors.append("Ignored invalid, duplicate, or reserved runtime definition")
            continue
        command = item["command"]
        if not isinstance(command, Sequence) or isinstance(command, (str, bytes)):
            errors.append(f"Ignored runtime '{runtime_id}' with invalid command")
            continue
        environment = item.get("environment_allowlist") or ()
        if not isinstance(environment, Sequence) or isinstance(environment, (str, bytes)):
            errors.append(f"Ignored runtime '{runtime_id}' with invalid environment allowlist")
            continue
        seen.add(runtime_id)
        rows.append(
            RuntimeConfig(
                runtime_id,
                str(item.get("label") or item["id"]),
                tuple(str(part) for part in command),
                tuple(str(name) for name in environment),
            )
        )
    return tuple(rows)


def _choice(
    value: object,
    allowed: set[str],
    default: str,
    name: str,
    errors: list[str],
) -> str:
    candidate = str(value).casefold()
    if candidate in allowed:
        return candidate
    errors.append(f"Invalid {name} '{candidate}'; using {default}")
    return default


def _workspace_root(value: object, errors: list[str]) -> Path | None:
    if not value:
        return None
    path = Path(str(value)).expanduser()
    if path.is_dir():
        return path
    errors.append(f"Invalid workspace_root '{path}'; using current directory")
    return None


def _boolean(value: object, name: str, default: bool, errors: list[str]) -> bool:
    if isinstance(value, bool):
        return value
    errors.append(f"Invalid {name} value; using {str(default).lower()}")
    return default


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def user_theme_directory() -> Path:
    return _user_root("data") / "themes"
