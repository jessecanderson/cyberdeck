from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from cyberdeck.domain import (
    AgentConfig,
    AgentState,
    AgentStatus,
    OperationEntry,
    PendingApproval,
    TranscriptEntry,
    parse_timestamp,
)
from cyberdeck.event_reducer import apply_agent_event
from cyberdeck.providers import AgentEvent


def test_agent_defaults() -> None:
    state = AgentState(AgentConfig(name="ghost", working_directory=Path("/tmp")))
    assert state.status is AgentStatus.STARTING
    assert state.config.provider == "codex"
    assert state.transcript == []


def test_agent_config_preserves_public_positional_id_contract() -> None:
    agent_id = uuid4()

    config = AgentConfig("ghost", Path("/tmp"), "kiro", agent_id)

    assert config.id == agent_id
    assert config.native_agent is None


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


def test_agent_transition_applies_error_and_ready_invariants() -> None:
    state = AgentState(AgentConfig(name="ghost", working_directory=Path("/tmp")))
    state.pending_approvals.append(PendingApproval(1, "approval"))

    state.transition_to(
        AgentStatus.ERROR,
        "transport lost",
        clear_approvals=True,
    )

    assert state.error_message == "transport lost"
    assert state.pending_approvals == []
    state.transition_to(AgentStatus.READY, "awaiting input")
    assert state.error_message is None


def test_completed_turn_reports_provider_token_usage() -> None:
    state = AgentState(
        AgentConfig(name="ghost", working_directory=Path("/tmp")),
        status=AgentStatus.PROCESSING,
    )
    apply_agent_event(
        state,
        AgentEvent(
            "token_usage",
            params={
                "tokenUsage": {
                    "last": {
                        "inputTokens": 1200,
                        "cachedInputTokens": 800,
                        "outputTokens": 300,
                        "reasoningOutputTokens": 100,
                        "totalTokens": 1500,
                    },
                    "modelContextWindow": 128000,
                }
            },
        ),
    )
    apply_agent_event(state, AgentEvent("status", "ready"))

    assert state.last_turn_usage is not None
    assert state.last_turn_usage.total_tokens == 1500
    assert state.transcript[-1].text == (
        "TURN USAGE // 1,500 total • 1,200 input • 800 cached • 300 output • 100 reasoning tokens"
    )


def test_ready_session_usage_does_not_look_like_a_completed_new_turn() -> None:
    state = AgentState(
        AgentConfig(name="ghost", working_directory=Path("/tmp")),
        status=AgentStatus.READY,
    )

    apply_agent_event(
        state,
        AgentEvent(
            "token_usage",
            params={"tokenUsage": {"last": {"totalTokens": 42}}},
        ),
    )

    assert state.transcript == []
    assert state.usage_report_pending is False
