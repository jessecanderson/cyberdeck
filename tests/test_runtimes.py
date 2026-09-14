from __future__ import annotations

import sys
from pathlib import Path

import pytest

from cyberdeck.config import RuntimeConfig
from cyberdeck.manager import AgentManager
from cyberdeck.providers import AcpAgentAdapter, ClaudeAcpAdapter
from cyberdeck.providers.codex import CodexAppServerAdapter
from cyberdeck.runtimes import RuntimeRegistry


def test_registry_exposes_built_in_and_configured_runtimes() -> None:
    registry = RuntimeRegistry(
        (RuntimeConfig("work-agent", "Work ACP", (sys.executable, "agent.py")),)
    )

    assert registry.ids == (
        "codex",
        "kiro",
        "claude",
        "claude-bedrock",
        "claude-vertex",
        "work-agent",
    )
    assert registry.definition("codex").kind == "codex"
    assert registry.definition("kiro").kind == "kiro"
    custom = registry.create("work-agent")
    assert isinstance(custom, AcpAgentAdapter)
    assert custom.command == (sys.executable, "agent.py")
    assert custom.model_provider == "work-agent"


def test_registry_preflight_reports_missing_executable() -> None:
    registry = RuntimeRegistry(
        (RuntimeConfig("offline", "Offline ACP", ("missing-cyberdeck-agent",)),)
    )

    result = registry.preflight("offline")

    assert result.available is False
    assert result.detail == "executable not found: missing-cyberdeck-agent"


def test_manager_registers_configured_runtime() -> None:
    registry = RuntimeRegistry(
        (RuntimeConfig("work-agent", "Work ACP", (sys.executable, "agent.py")),)
    )
    manager = AgentManager(lambda state, event: None, runtime_registry=registry)

    state = manager.register("molly", Path("/tmp"), provider="work-agent")

    assert state.config.provider == "work-agent"


def test_registry_rejects_reserved_runtime_override() -> None:
    for runtime_id in ("codex", "kiro", "claude", "claude-bedrock", "claude-vertex"):
        with pytest.raises(ValueError, match="reserved"):
            RuntimeRegistry((RuntimeConfig(runtime_id, "Other", (sys.executable,)),))


def test_registry_passes_validated_codex_policy_to_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        RuntimeRegistry, "_find_executable", staticmethod(lambda _name: sys.executable)
    )
    registry = RuntimeRegistry(approval_policy="never", sandbox="read-only")

    adapter = registry.create("codex")

    assert isinstance(adapter, CodexAppServerAdapter)
    assert adapter.approval_policy == "never"
    assert adapter.sandbox == "read-only"


def test_registry_constructs_exact_kiro_native_agent_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        RuntimeRegistry, "_find_executable", staticmethod(lambda _name: "/opt/bin/kiro-cli")
    )

    default = RuntimeRegistry().create("kiro")
    selected = RuntimeRegistry().create("kiro", "security/reviewer")

    assert default.command == ("/opt/bin/kiro-cli", "acp")
    assert selected.command == (
        "/opt/bin/kiro-cli",
        "acp",
        "--agent",
        "security/reviewer",
    )


def test_registry_rejects_native_agent_for_unsupported_runtimes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(RuntimeRegistry, "_find_executable", staticmethod(lambda name: name))

    with pytest.raises(ValueError, match="view only"):
        RuntimeRegistry().create("codex", "reviewer")
    registry = RuntimeRegistry(
        (RuntimeConfig("work-agent", "Work ACP", (sys.executable, "agent.py")),)
    )
    with pytest.raises(ValueError, match="does not support"):
        registry.create("work-agent", "reviewer")


@pytest.mark.parametrize(
    ("runtime_id", "deployment"),
    [
        ("claude", "anthropic"),
        ("claude-bedrock", "bedrock"),
        ("claude-vertex", "vertex"),
    ],
)
def test_registry_constructs_claude_deployment_adapter(
    monkeypatch: pytest.MonkeyPatch,
    runtime_id: str,
    deployment: str,
) -> None:
    monkeypatch.setattr(RuntimeRegistry, "_find_executable", staticmethod(lambda name: name))

    adapter = RuntimeRegistry().create(runtime_id)

    assert isinstance(adapter, ClaudeAcpAdapter)
    assert adapter.model_provider == runtime_id
    assert adapter.command == ("claude-agent-acp",)
    expected = None if deployment == "anthropic" else f"CLAUDE_CODE_USE_{deployment.upper()}"
    selected = {
        name
        for name in ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX")
        if name in adapter.environment
    }
    assert selected == ({expected} if expected else set())


def test_claude_preflight_requires_node_22(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        RuntimeRegistry,
        "_find_executable",
        staticmethod(lambda name: f"/opt/bin/{name}"),
    )
    monkeypatch.setattr(
        RuntimeRegistry,
        "_version",
        staticmethod(lambda executable: "v20.17.0" if executable.endswith("node") else "0.76.0"),
    )

    result = RuntimeRegistry().preflight("claude")

    assert result.available is False
    assert result.detail == "Node.js 22+ required; found v20.17.0"


def test_claude_preflight_reports_adapter_and_cloud_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        RuntimeRegistry,
        "_find_executable",
        staticmethod(lambda name: f"/opt/bin/{name}"),
    )
    monkeypatch.setattr(
        RuntimeRegistry,
        "_version",
        staticmethod(lambda executable: "v22.23.2" if executable.endswith("node") else "0.76.0"),
    )

    result = RuntimeRegistry().preflight("claude-bedrock")

    assert result.available is True
    assert result.version == "0.76.0"
    assert "AWS credentials, region, and model access" in result.detail


def test_claude_preflight_rejects_unvalidated_adapter_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        RuntimeRegistry,
        "_find_executable",
        staticmethod(lambda name: f"/opt/bin/{name}"),
    )
    monkeypatch.setattr(
        RuntimeRegistry,
        "_version",
        staticmethod(lambda executable: "v22.23.2" if executable.endswith("node") else "0.77.0"),
    )

    result = RuntimeRegistry().preflight("claude-vertex")

    assert result.available is False
    assert result.version == "0.77.0"
    assert result.detail == "Claude ACP 0.76.x required; found 0.77.0"
