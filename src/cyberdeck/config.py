from __future__ import annotations

import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


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

    @property
    def journal_path(self) -> Path:
        return self.journal_directory or (_user_root("data") / "journal")


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (_user_root("config") / "config.toml")

    def load(self) -> DeckConfig:
        try:
            data = tomllib.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
            return DeckConfig()
        journal = data.get("journal", {})
        configured = journal.get("directory")
        runtimes: list[RuntimeConfig] = []
        seen_runtime_ids: set[str] = set()
        for row in data.get("runtimes", []):
            if not isinstance(row, dict) or not row.get("id") or not row.get("command"):
                continue
            runtime_id = str(row["id"]).strip().casefold()
            if (
                not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", runtime_id)
                or runtime_id in seen_runtime_ids
                or runtime_id in {"codex", "kiro"}
            ):
                continue
            seen_runtime_ids.add(runtime_id)
            runtimes.append(
                RuntimeConfig(
                    id=runtime_id,
                    label=str(row.get("label") or row["id"]),
                    command=tuple(str(part) for part in row["command"]),
                    environment_allowlist=tuple(
                        str(name) for name in row.get("environment_allowlist") or ()
                    ),
                )
            )
        return DeckConfig(
            active_theme=str(data.get("deck", {}).get("theme", "ods")),
            active_module=str(data.get("deck", {}).get("module", "agents")),
            journal_directory=Path(configured).expanduser() if configured else None,
            default_runtime=str(
                data.get("agents", {}).get("default_runtime", "codex")
            ).casefold(),
            runtimes=tuple(runtimes),
        )

    def save(self, config: DeckConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        journal = str(config.journal_directory) if config.journal_directory else ""
        content = (
            "[deck]\n"
            f'theme = "{_escape(config.active_theme)}"\n'
            f'module = "{_escape(config.active_module)}"\n\n'
            "[journal]\n"
            f'directory = "{_escape(journal)}"\n'
            "\n[agents]\n"
            f'default_runtime = "{_escape(config.default_runtime)}"\n'
        )
        for runtime in config.runtimes:
            command = ", ".join(f'"{_escape(part)}"' for part in runtime.command)
            environment = ", ".join(
                f'"{_escape(name)}"' for name in runtime.environment_allowlist
            )
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


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def user_theme_directory() -> Path:
    return _user_root("data") / "themes"
