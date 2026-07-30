from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import RuntimeConfig
from .providers import AcpAgentAdapter, AgentAdapter, CodexAppServerAdapter, KiroAcpAdapter


@dataclass(frozen=True, slots=True)
class RuntimeDefinition:
    id: str
    label: str
    kind: str
    command: tuple[str, ...]
    environment_allowlist: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RuntimePreflight:
    runtime_id: str
    label: str
    available: bool
    detail: str
    version: str | None = None


class RuntimeRegistry:
    """Runtime definitions, adapter construction, and credential-free preflight."""

    def __init__(
        self,
        configured: tuple[RuntimeConfig, ...] = (),
        *,
        approval_policy: str = "on-request",
        sandbox: str = "workspace-write",
    ) -> None:
        self.approval_policy = approval_policy
        self.sandbox = sandbox
        self._definitions: dict[str, RuntimeDefinition] = {
            "codex": RuntimeDefinition(
                "codex", "Codex (native App Server)", "codex", ("codex",)
            ),
            "kiro": RuntimeDefinition("kiro", "Kiro (ACP v1)", "kiro", ("kiro-cli", "acp")),
        }
        for runtime in configured:
            if runtime.id in self._definitions:
                raise ValueError(f"Configured runtime id is reserved: {runtime.id}")
            self._definitions[runtime.id] = RuntimeDefinition(
                runtime.id,
                runtime.label,
                "acp",
                runtime.command,
                runtime.environment_allowlist,
            )
        self._preflight_cache: dict[str, RuntimePreflight] = {}

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(self._definitions)

    def definition(self, runtime_id: str) -> RuntimeDefinition:
        try:
            return self._definitions[runtime_id.casefold()]
        except KeyError as exc:
            raise ValueError(f"Unknown agent runtime: {runtime_id}") from exc

    def create(self, runtime_id: str) -> AgentAdapter:
        definition = self.definition(runtime_id)
        if definition.kind == "codex":
            executable = self._resolve_executable(definition.command[0])
            return CodexAppServerAdapter(
                executable,
                approval_policy=self.approval_policy,
                sandbox=self.sandbox,
            )
        if definition.kind == "kiro":
            return KiroAcpAdapter(self._resolve_executable(definition.command[0]))
        command = (self._resolve_executable(definition.command[0]), *definition.command[1:])
        environment = None
        if definition.environment_allowlist:
            names = {"PATH", "HOME", "LANG", "LC_ALL", *definition.environment_allowlist}
            environment = {name: os.environ[name] for name in names if name in os.environ}
        return AcpAgentAdapter(
            command,
            provider=definition.id,
            environment=environment,
        )

    def preflight(self, runtime_id: str, *, refresh: bool = False) -> RuntimePreflight:
        runtime_id = runtime_id.casefold()
        if not refresh and runtime_id in self._preflight_cache:
            return self._preflight_cache[runtime_id]
        definition = self.definition(runtime_id)
        executable = self._find_executable(definition.command[0])
        if not executable:
            result = RuntimePreflight(
                runtime_id,
                definition.label,
                False,
                f"executable not found: {definition.command[0]}",
            )
        else:
            version = self._version(executable)
            result = RuntimePreflight(
                runtime_id,
                definition.label,
                True,
                "executable ready; authentication verified when connecting",
                version,
            )
        self._preflight_cache[runtime_id] = result
        return result

    def preflights(self, *, refresh: bool = False) -> tuple[RuntimePreflight, ...]:
        return tuple(self.preflight(runtime_id, refresh=refresh) for runtime_id in self.ids)

    @staticmethod
    def _find_executable(command: str) -> str | None:
        path = Path(command).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
        discovered = shutil.which(command)
        if discovered:
            return discovered
        if command == "kiro-cli":
            user_install = Path.home() / ".local" / "bin" / "kiro-cli"
            if user_install.is_file() and os.access(user_install, os.X_OK):
                return str(user_install)
        return None

    def _resolve_executable(self, command: str) -> str:
        executable = self._find_executable(command)
        if not executable:
            raise RuntimeError(
                f"Runtime preflight failed: executable not found: {command}. "
                "Install it or update [[runtimes]].command in config.toml."
            )
        return executable

    @staticmethod
    def _version(executable: str) -> str | None:
        try:
            result = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        text = (result.stdout or result.stderr).strip().splitlines()
        return text[0][:120] if text else None
