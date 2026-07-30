from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4


def current_time() -> datetime:
    """Return one canonical, timezone-aware timestamp for domain state."""
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class AgentCapabilities:
    load_session: bool = False
    history: bool = False
    rename: bool = False
    archive: bool = False
    interrupt: bool = True
    approvals: bool = True
    tool_events: bool = True
    model_selection: bool = False
    templates: bool = False
    remote_transport: bool = False
    context_compaction: bool = False

    def supports(self, action: str) -> bool:
        return {
            "retry": self.load_session,
            "rename": self.rename,
            "archive": self.archive,
            "interrupt": self.interrupt,
            "approvals": self.approvals,
            "history": self.history,
            "compact": self.context_compaction,
        }.get(action, True)


class AgentStatus(str, Enum):
    STARTING = "starting"
    RESTORING = "restoring"
    READY = "ready"
    PROCESSING = "processing"
    EXECUTING = "executing"
    EDITING = "editing"
    FIREWALL_HOLD = "ice hold"
    ERROR = "error"
    STOPPED = "stopped"


class OperationState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    APPROVAL = "approval"


@dataclass(slots=True)
class AgentConfig:
    name: str
    working_directory: Path
    provider: str = "codex"
    id: UUID = field(default_factory=uuid4)


@dataclass(slots=True)
class TranscriptEntry:
    role: str
    text: str
    created_at: datetime = field(default_factory=current_time)
    source_id: str | None = None


@dataclass(slots=True)
class PendingApproval:
    request_id: int | str
    method: str
    params: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=current_time)


@dataclass(slots=True)
class OperationEntry:
    kind: str
    summary: str
    state: OperationState = OperationState.RUNNING
    created_at: datetime = field(default_factory=current_time)
    id: str | None = None
    command: str | None = None
    cwd: str | None = None
    output: str | None = None
    diff: str | None = None
    files: list[str] = field(default_factory=list)
    duration_ms: int | None = None
    exit_code: int | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(slots=True)
class ThreadSummary:
    id: str
    name: str | None
    source: str
    cwd: Path
    preview: str
    updated_at: datetime
    model: str | None = None
    provider: str = "codex"
    is_open: bool = False


@dataclass(slots=True)
class HistoryPage:
    transcript: list[TranscriptEntry] = field(default_factory=list)
    operations: list[OperationEntry] = field(default_factory=list)
    next_cursor: str | None = None


@dataclass(slots=True)
class AgentState:
    config: AgentConfig
    status: AgentStatus = AgentStatus.STARTING
    thread_id: str | None = None
    transcript: list[TranscriptEntry] = field(default_factory=list)
    operations: list[OperationEntry] = field(default_factory=list)
    model: str | None = None
    model_provider: str = "codex"
    current_activity: str = "initializing uplink"
    unread_count: int = 0
    unread_message_index: int | None = None
    history_cursor: str | None = None
    restored: bool = False
    context_tokens: int = 0
    context_window: int | None = None
    context_percentage: float | None = None
    prompt_draft: str = ""
    error_message: str | None = None
    recovery_attempts: int = 0
    pending_approvals: list[PendingApproval] = field(default_factory=list)
    capabilities: AgentCapabilities = field(default_factory=AgentCapabilities)


def parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        try:
            return parse_timestamp(datetime.fromisoformat(value))
        except ValueError:
            pass
    return current_time()


def map_history_turns(turns: list[dict[str, Any]], next_cursor: str | None = None) -> HistoryPage:
    """Normalize durable app-server turns into stable conversation and operation rows."""
    page = HistoryPage(next_cursor=next_cursor)
    ordered = sorted(turns, key=lambda turn: parse_timestamp(turn.get("createdAt")))
    for turn in ordered:
        fallback_time = parse_timestamp(turn.get("createdAt"))
        for item in turn.get("items") or []:
            item_type = item.get("type", "unknown")
            created = parse_timestamp(item.get("createdAt") or fallback_time)
            if item_type == "userMessage":
                text = item.get("text") or "".join(
                    part.get("text", "")
                    for part in item.get("content", [])
                    if isinstance(part, dict)
                )
                page.transcript.append(
                    TranscriptEntry(
                        "user",
                        text,
                        created,
                        str(item["id"]) if item.get("id") is not None else None,
                    )
                )
            elif item_type == "agentMessage":
                page.transcript.append(
                    TranscriptEntry(
                        "assistant",
                        item.get("text", ""),
                        created,
                        str(item["id"]) if item.get("id") is not None else None,
                    )
                )
            elif item_type in {
                "commandExecution",
                "fileChange",
                "mcpToolCall",
                "dynamicToolCall",
                "webSearch",
            }:
                page.operations.append(operation_from_item(item, created))
    return page


def operation_from_item(item: dict[str, Any], created_at: datetime | None = None) -> OperationEntry:
    kind = item.get("type", "tool")
    status = str(item.get("status", "running")).lower()
    if status in {"completed", "success", "succeeded"}:
        state = OperationState.SUCCEEDED
    elif status in {"failed", "error", "declined"}:
        state = OperationState.FAILED
    elif status in {"pending", "queued"}:
        state = OperationState.PENDING
    else:
        state = OperationState.RUNNING
    command = item.get("command")
    files = [
        str(change.get("path", change)) if isinstance(change, dict) else str(change)
        for change in item.get("changes", item.get("files", []))
    ]
    tool = item.get("tool") or item.get("name") or item.get("server")
    summary = command or (", ".join(files[:3]) if files else None) or tool or kind
    return OperationEntry(
        kind=kind,
        summary=str(summary),
        state=state,
        created_at=parse_timestamp(created_at or item.get("createdAt")),
        id=str(item["id"]) if item.get("id") is not None else None,
        command=command,
        cwd=item.get("cwd"),
        output=item.get("aggregatedOutput") or item.get("output"),
        diff=item.get("diff"),
        files=files,
        duration_ms=item.get("durationMs"),
        exit_code=item.get("exitCode"),
        arguments=item.get("arguments") or item.get("params") or {},
        error=item.get("error"),
    )
