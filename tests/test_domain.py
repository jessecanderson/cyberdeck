from pathlib import Path

from cyberdeck.domain import AgentConfig, AgentState, AgentStatus


def test_agent_defaults() -> None:
    state = AgentState(AgentConfig(name="ghost", working_directory=Path("/tmp")))
    assert state.status is AgentStatus.STARTING
    assert state.config.provider == "codex"
    assert state.transcript == []

