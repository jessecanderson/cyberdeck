"""Provider-neutral state transitions for normalized agent events."""

from __future__ import annotations

from .domain import (
    AgentState,
    AgentStatus,
    OperationState,
    PendingApproval,
    TranscriptEntry,
    operation_from_item,
)
from .providers import AgentEvent


def apply_agent_event(state: AgentState, event: AgentEvent) -> None:
    """Apply one normalized provider event to agent state."""
    handlers = {
        "status": _status,
        "user_replay": _user_replay,
        "assistant_delta": _assistant_delta,
        "operation": _operation,
        "approval": _approval,
        "token_usage": _token_usage,
        "context_usage": _context_usage,
        "error": _failure,
        "transport_closed": _failure,
    }
    handler = handlers.get(event.kind)
    if handler:
        handler(state, event)


def _status(state: AgentState, event: AgentEvent) -> None:
    normalized = "processing" if event.text == "working" else event.text
    state.status = AgentStatus(normalized)
    state.current_activity = (
        "generating response" if state.status is AgentStatus.PROCESSING else "awaiting input"
    )


def _user_replay(state: AgentState, event: AgentEvent) -> None:
    latest = state.transcript[-1] if state.transcript else None
    if latest is not None and latest.role == "user":
        latest.text += event.text
    else:
        state.transcript.append(TranscriptEntry("user", event.text))
    state.current_activity = "hydrating provider session"


def _assistant_delta(state: AgentState, event: AgentEvent) -> None:
    latest = state.transcript[-1] if state.transcript else None
    same_message = (
        latest is not None
        and latest.role == "assistant"
        and (event.message_id is None or latest.source_id == event.message_id)
    )
    if same_message:
        latest.text += event.text
    else:
        state.transcript.append(
            TranscriptEntry("assistant", event.text, source_id=event.message_id)
        )
    state.status = AgentStatus.PROCESSING
    state.current_activity = "streaming response"


def _operation(state: AgentState, event: AgentEvent) -> None:
    operation = operation_from_item(event.params or {})
    existing = next((item for item in state.operations if item.id == operation.id), None)
    if existing and operation.id:
        state.operations[state.operations.index(existing)] = operation
    else:
        state.operations.append(operation)
    state.status = AgentStatus.EDITING if operation.kind == "fileChange" else AgentStatus.EXECUTING
    state.current_activity = operation.summary
    if event.method == "item/completed" and operation.state is OperationState.RUNNING:
        operation.state = OperationState.SUCCEEDED


def _approval(state: AgentState, event: AgentEvent) -> None:
    state.status = AgentStatus.FIREWALL_HOLD
    state.current_activity = "ICE authorization required"
    if event.request_id is not None:
        state.pending_approvals.append(
            PendingApproval(
                request_id=event.request_id,
                method=event.method,
                params=event.params or {},
            )
        )


def _token_usage(state: AgentState, event: AgentEvent) -> None:
    usage = (event.params or {}).get("tokenUsage") or {}
    last = usage.get("last") or {}
    state.context_tokens = int(last.get("totalTokens") or 0)
    window = usage.get("modelContextWindow")
    state.context_window = int(window) if window else None
    state.context_percentage = None


def _context_usage(state: AgentState, event: AgentEvent) -> None:
    percentage = float((event.params or {}).get("percentage") or 0)
    state.context_percentage = max(0.0, min(100.0, percentage))


def _failure(state: AgentState, event: AgentEvent) -> None:
    state.status = AgentStatus.ERROR
    state.current_activity = event.text
    state.error_message = event.text
    state.pending_approvals.clear()
