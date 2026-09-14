from __future__ import annotations

from pathlib import Path

import pytest

from cyberdeck.providers import ClaudeAcpAdapter, claude_environment


@pytest.mark.parametrize(
    ("deployment", "provider", "enabled"),
    [
        ("anthropic", "claude", None),
        ("bedrock", "claude-bedrock", "CLAUDE_CODE_USE_BEDROCK"),
        ("vertex", "claude-vertex", "CLAUDE_CODE_USE_VERTEX"),
    ],
)
def test_claude_adapter_selects_one_inference_route(deployment, provider, enabled) -> None:
    source = {
        "PATH": "/opt/bin",
        "ANTHROPIC_API_KEY": "provider-owned",
        "AWS_PROFILE": "work",
        "ANTHROPIC_VERTEX_PROJECT_ID": "project",
        "CLAUDE_CODE_USE_BEDROCK": "stale",
        "CLAUDE_CODE_USE_MANTLE": "stale",
        "CLAUDE_CODE_USE_VERTEX": "stale",
        "CLAUDE_CODE_USE_FOUNDRY": "stale",
    }

    adapter = ClaudeAcpAdapter(
        "/opt/bin/claude-agent-acp",
        deployment=deployment,
        environment=source,
    )

    assert adapter.model_provider == provider
    assert adapter.command == ("/opt/bin/claude-agent-acp",)
    assert adapter.environment["ANTHROPIC_API_KEY"] == "provider-owned"
    assert adapter.environment["AWS_PROFILE"] == "work"
    assert adapter.environment["ANTHROPIC_VERTEX_PROJECT_ID"] == "project"
    selected = {
        name
        for name in (
            "CLAUDE_CODE_USE_BEDROCK",
            "CLAUDE_CODE_USE_MANTLE",
            "CLAUDE_CODE_USE_VERTEX",
            "CLAUDE_CODE_USE_FOUNDRY",
        )
        if name in adapter.environment
    }
    assert selected == ({enabled} if enabled else set())
    params = adapter._session_params(Path("/workspace"), session_id="claude-session")
    settings = params["_meta"]["claudeCode"]["options"]["settings"]["env"]
    assert settings["CLAUDE_CODE_USE_BEDROCK"] == ("1" if deployment == "bedrock" else "0")
    assert settings["CLAUDE_CODE_USE_VERTEX"] == ("1" if deployment == "vertex" else "0")
    assert params["sessionId"] == "claude-session"


def test_claude_environment_rejects_unknown_deployment() -> None:
    with pytest.raises(ValueError, match="Unsupported Claude deployment"):
        claude_environment("other", {})  # type: ignore[arg-type]
