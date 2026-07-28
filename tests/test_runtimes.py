from __future__ import annotations

import sys
from pathlib import Path

import pytest

from cyberdeck.config import RuntimeConfig
from cyberdeck.manager import AgentManager
from cyberdeck.providers import AcpAgentAdapter
from cyberdeck.providers.codex import CodexAppServerAdapter
from cyberdeck.runtimes import RuntimeRegistry


def test_registry_exposes_built_in_and_configured_runtimes() -> None:
    registry = RuntimeRegistry(
        (RuntimeConfig("work-agent", "Work ACP", (sys.executable, "agent.py")),)
    )

    assert registry.ids == ("codex", "kiro", "work-agent")
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
    with pytest.raises(ValueError, match="reserved"):
        RuntimeRegistry((RuntimeConfig("codex", "Other", (sys.executable,)),))


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
