from datetime import UTC, datetime
from pathlib import Path

from cyberdeck.domain import (
    AgentConfig,
    AgentState,
    AgentStatus,
    OperationEntry,
    PendingApproval,
    TranscriptEntry,
    parse_timestamp,
)


def test_agent_defaults() -> None:
    state = AgentState(AgentConfig(name="ghost", working_directory=Path("/tmp")))
    assert state.status is AgentStatus.STARTING
    assert state.config.provider == "codex"
    assert state.transcript == []


def test_domain_timestamps_are_timezone_aware() -> None:
    transcript = TranscriptEntry("user", "hello")
    operation = OperationEntry("tool", "work")
    approval = PendingApproval(1, "approval")

    assert transcript.created_at.utcoffset() is not None
    assert operation.created_at.utcoffset() is not None
    assert approval.created_at.utcoffset() is not None


def test_parse_timestamp_normalizes_naive_datetimes_to_utc() -> None:
    parsed = parse_timestamp(datetime.fromisoformat("2026-07-30T12:00:00"))

    assert parsed.tzinfo is UTC
