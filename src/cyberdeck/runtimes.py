from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from packaging.version import InvalidVersion, Version

from .config import RuntimeConfig
from .providers import (
    AcpAgentAdapter,
    AgentAdapter,
    ClaudeAcpAdapter,
    ClaudeDeployment,
    CodexAppServerAdapter,
    KiroAcpAdapter,
)


@dataclass(frozen=True, slots=True)
class RuntimeDefinition:
    id: str
    label: str
    kind: str
    command: tuple[str, ...]
    environment_allowlist: tuple[str, ...] = ()
    claude_deployment: ClaudeDeployment | None = None


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
            "codex": RuntimeDefinition("codex", "Codex (native App Server)", "codex", ("codex",)),
            "kiro": RuntimeDefinition("kiro", "Kiro (ACP v1)", "kiro", ("kiro-cli", "acp")),
            "claude": RuntimeDefinition(
                "claude",
                "Claude (Anthropic)",
                "claude",
                ("claude-agent-acp",),
                claude_deployment="anthropic",
            ),
            "claude-bedrock": RuntimeDefinition(
                "claude-bedrock",
                "Claude (Amazon Bedrock)",
                "claude",
                ("claude-agent-acp",),
                claude_deployment="bedrock",
            ),
            "claude-vertex": RuntimeDefinition(
                "claude-vertex",
                "Claude (Google Vertex AI)",
                "claude",
                ("claude-agent-acp",),
                claude_deployment="vertex",
            ),
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

    def create(self, runtime_id: str, native_agent: str | None = None) -> AgentAdapter:
        definition = self.definition(runtime_id)
        if definition.kind == "codex":
            if native_agent is not None:
                raise ValueError(
                    "Codex native agents are view only: App Server does not support "
                    "named primary-agent selection"
                )
            executable = self._resolve_executable(definition.command[0])
            return CodexAppServerAdapter(
                executable,
                approval_policy=self.approval_policy,
                sandbox=self.sandbox,
            )
        if definition.kind == "kiro":
            return KiroAcpAdapter(self._resolve_executable(definition.command[0]), native_agent)
        if definition.kind == "claude":
            if native_agent is not None:
                raise ValueError(f"Runtime {definition.id} does not support native-agent launch")
            assert definition.claude_deployment is not None
            return ClaudeAcpAdapter(
                self._resolve_executable(definition.command[0]),
                deployment=definition.claude_deployment,
            )
        if native_agent is not None:
            raise ValueError(f"Runtime {definition.id} does not support native-agent launch")
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
                self._missing_executable_detail(definition),
            )
        elif definition.kind == "claude":
            result = self._claude_preflight(definition, executable)
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

    def _claude_preflight(self, definition: RuntimeDefinition, executable: str) -> RuntimePreflight:
        node = self._find_executable("node")
        node_version = self._version(node) if node else None
        match = re.search(r"(?:^|\s)v?(\d+)(?:\.|$)", node_version or "")
        if not match or int(match.group(1)) < 22:
            found = node_version or "not found"
            return RuntimePreflight(
                definition.id,
                definition.label,
                False,
                f"Node.js 22+ required; found {found}",
            )
        adapter_version = self._version(executable)
        try:
            compatible_adapter = Version(adapter_version or "").release[:2] == (0, 76)
        except InvalidVersion:
            compatible_adapter = False
        if not compatible_adapter:
            found = adapter_version or "unknown"
            return RuntimePreflight(
                definition.id,
                definition.label,
                False,
                f"Claude ACP 0.76.x required; found {found}",
                adapter_version,
            )
        deployment = definition.claude_deployment or "anthropic"
        guidance = {
            "anthropic": "Claude Code or Anthropic credentials are verified on first prompt",
            "bedrock": "AWS credentials, region, and model access are verified on first prompt",
            "vertex": "Google credentials, project, region, and model access are verified on first prompt",
        }[deployment]
        return RuntimePreflight(
            definition.id,
            definition.label,
            True,
            f"ACP adapter ready with {node_version}; {guidance}",
            adapter_version,
        )

    @staticmethod
    def _missing_executable_detail(definition: RuntimeDefinition) -> str:
        if definition.kind == "claude":
            return (
                "executable not found: claude-agent-acp; install "
                "@agentclientprotocol/claude-agent-acp@0.76.0 with Node.js 22+"
            )
        return f"executable not found: {definition.command[0]}"

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
