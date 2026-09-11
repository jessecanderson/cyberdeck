"""Metadata-only discovery of harness-native agent definitions."""

from __future__ import annotations

import json
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

MAX_METADATA_BYTES = 256 * 1024


@dataclass(frozen=True, slots=True)
class NativeAgent:
    runtime_id: str
    native_id: str
    display_name: str
    description: str
    scope: str
    source_path: Path
    launch_supported: bool
    unavailable_reason: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryDiagnostic:
    runtime_id: str
    source_path: Path
    message: str


@dataclass(frozen=True, slots=True)
class NativeAgentCatalog:
    agents: tuple[NativeAgent, ...] = ()
    diagnostics: tuple[DiscoveryDiagnostic, ...] = ()


def discover_native_agents(
    workspace: Path,
    *,
    home: Path | None = None,
) -> NativeAgentCatalog:
    """Read identity metadata from documented Codex and Kiro agent roots."""
    home = (home or Path.home()).expanduser().resolve()
    workspace = workspace.expanduser().resolve()
    agents: list[NativeAgent] = []
    diagnostics: list[DiscoveryDiagnostic] = []
    codex_roots = _unique_roots(
        (
            (home / ".codex" / "agents", "personal"),
            (workspace / ".codex" / "agents", "workspace"),
        )
    )
    for root, scope in codex_roots:
        paths, traversal_error = _files(root, (".toml",), recursive=False)
        if traversal_error:
            diagnostics.append(DiscoveryDiagnostic("codex", root, traversal_error))
        for path in paths:
            try:
                data = _load(path, root, "codex")
                name, description = _identity(data)
                agents.append(
                    NativeAgent(
                        "codex",
                        path.stem,
                        name,
                        description,
                        scope,
                        path,
                        False,
                        "Codex App Server does not support named primary-agent selection",
                    )
                )
            except (OSError, TypeError, ValueError, tomllib.TOMLDecodeError) as exc:
                diagnostics.append(DiscoveryDiagnostic("codex", path, str(exc)))

    kiro: dict[str, NativeAgent] = {}
    kiro_scopes: dict[str, str] = {}
    kiro_roots = _unique_roots(
        (
            (home / ".kiro" / "agents", "personal"),
            (workspace / ".kiro" / "agents", "workspace"),
        )
    )
    for root, scope in kiro_roots:
        paths, traversal_error = _files(root, (".json", ".md"), recursive=True)
        if traversal_error:
            diagnostics.append(DiscoveryDiagnostic("kiro", root, traversal_error))
        for path in paths:
            try:
                data = _load(path, root, "kiro")
                name, description = _identity(data)
                native_id = path.relative_to(root).with_suffix("").as_posix()
                if kiro_scopes.get(native_id) == scope:
                    diagnostics.append(
                        DiscoveryDiagnostic(
                            "kiro",
                            path,
                            f"duplicate native agent id in {scope} scope: {native_id}",
                        )
                    )
                    continue
                kiro[native_id] = NativeAgent(
                    "kiro", native_id, name, description, scope, path, True
                )
                kiro_scopes[native_id] = scope
            except (OSError, TypeError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
                diagnostics.append(DiscoveryDiagnostic("kiro", path, str(exc)))
    agents.extend(kiro.values())
    return NativeAgentCatalog(
        tuple(sorted(agents, key=lambda row: (row.runtime_id, row.native_id, row.scope))),
        tuple(diagnostics),
    )


def _unique_roots(roots: tuple[tuple[Path, str], ...]) -> tuple[tuple[Path, str], ...]:
    unique: dict[Path, str] = {}
    for root, scope in roots:
        unique[root] = scope
    return tuple(unique.items())


def _files(
    root: Path, suffixes: tuple[str, ...], *, recursive: bool
) -> tuple[tuple[Path, ...], str | None]:
    paths: list[Path] = []
    try:
        candidates = root.rglob("*") if recursive else root.glob("*")
        for path in candidates:
            if path.suffix.casefold() in suffixes:
                paths.append(path)
    except OSError as exc:
        return tuple(sorted(paths)), f"catalog traversal failed: {exc}"
    return tuple(sorted(paths)), None


def _load(path: Path, root: Path, runtime_id: str) -> dict[str, Any]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("skipped: not a regular file")
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("skipped: file resolves outside the agent root") from exc
    if info.st_size > MAX_METADATA_BYTES:
        raise ValueError(f"skipped: metadata exceeds {MAX_METADATA_BYTES} bytes")
    text = path.read_text(encoding="utf-8")
    if runtime_id == "codex":
        data = tomllib.loads(text)
    elif path.suffix.casefold() == ".json":
        data = json.loads(text)
    else:
        data = _markdown_front_matter(text)
    if not isinstance(data, dict):
        raise TypeError("metadata must be an object")
    return data


def _markdown_front_matter(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("Markdown agent is missing YAML front matter")
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise ValueError("Markdown agent has unterminated YAML front matter") from exc
    data = yaml.safe_load("\n".join(lines[1:end]))
    return data if isinstance(data, dict) else {}


def _identity(data: dict[str, Any]) -> tuple[str, str]:
    name = data.get("name")
    description = data.get("description")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("metadata requires a non-empty name")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("metadata requires a non-empty description")
    return name.strip(), description.strip()
