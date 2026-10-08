"""Bounded, versioned persistence of workspace and session metadata only."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .domain import AgentState, DispatchRun, DispatchTarget, current_time


@dataclass(frozen=True, slots=True)
class SessionReference:
    thread_id: str
    callsign: str
    provider: str
    workspace: Path
    native_agent: str | None = None


class SessionStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.errors: list[str] = []
        self.workspaces: list[Path] = []
        self.sessions: list[SessionReference] = []
        self.dispatches: list[DispatchRun] = []
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                not isinstance(data, dict)
                or type(data.get("schema_version")) is not int
                or data["schema_version"] != 1
            ):
                raise ValueError("unsupported metadata schema")
            self.workspaces = [Path(_string(path)) for path in data.get("workspaces", [])][:20]
            self.sessions = [_session(row) for row in data.get("sessions", [])][:50]
            self.dispatches = [_dispatch(row) for row in data.get("dispatches", [])][-50:]
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            self.workspaces, self.sessions, self.dispatches = [], [], []
            self.errors.append(f"Saved metadata ignored: {type(exc).__name__}; use /sessions reset")

    def remember(self, state: AgentState, *, sessions: bool) -> None:
        workspace = state.config.working_directory
        self.workspaces = [workspace, *[p for p in self.workspaces if p != workspace]][:20]
        if sessions and state.thread_id and state.capabilities.load_session:
            reference = SessionReference(
                state.thread_id,
                state.config.name,
                state.config.provider,
                workspace,
                state.config.native_agent,
            )
            self.sessions = [
                reference,
                *[
                    row
                    for row in self.sessions
                    if (row.provider, row.thread_id) != (reference.provider, reference.thread_id)
                ],
            ][:50]

    def forget(self, state: AgentState) -> None:
        self.sessions = [
            row
            for row in self.sessions
            if (row.provider, row.thread_id) != (state.config.provider, state.thread_id)
        ]

    def reset(self) -> None:
        self.workspaces, self.sessions, self.dispatches = [], [], []
        self.save()

    def save(self) -> None:
        data = {
            "schema_version": 1,
            "workspaces": [str(path) for path in self.workspaces[:20]],
            "sessions": [
                {
                    "thread_id": row.thread_id,
                    "callsign": row.callsign,
                    "provider": row.provider,
                    "workspace": str(row.workspace),
                    "native_agent": row.native_agent,
                }
                for row in self.sessions[:50]
            ],
            "dispatches": [_dispatch_metadata(run) for run in self.dispatches[-50:]],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent, delete=False
            ) as handle:
                temporary = Path(handle.name)
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _string(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError("invalid metadata value")
    return value


def _session(row: dict) -> SessionReference:
    native = row.get("native_agent")
    return SessionReference(
        _string(row["thread_id"]),
        _string(row["callsign"]),
        _string(row["provider"]),
        Path(_string(row["workspace"])),
        _string(native) if native is not None else None,
    )


def _dispatch_metadata(run: DispatchRun) -> dict:
    return {
        "id": run.id,
        "created_at": run.created_at.isoformat(),
        "targets": [
            {
                "agent_id": target.agent_id,
                "callsign": target.callsign,
                "provider": target.provider,
                "status": target.status,
                "started_at": target.started_at.isoformat(),
                "finished_at": target.finished_at.isoformat() if target.finished_at else None,
            }
            for target in run.targets
        ],
    }


def _timestamp(value: object) -> datetime:
    timestamp = datetime.fromisoformat(_string(value))
    if timestamp.tzinfo is None:
        raise ValueError("metadata timestamp needs timezone")
    return timestamp


def _dispatch(row: dict) -> DispatchRun:
    targets = []
    for item in row["targets"]:
        status = _string(item["status"])
        if status not in {"sending", "running", "completed", "failed", "cancelled", "unknown"}:
            raise ValueError("invalid dispatch status")
        finished = _timestamp(item["finished_at"]) if item.get("finished_at") else None
        if finished is None:
            status, finished = "unknown", current_time()
        targets.append(
            DispatchTarget(
                _string(item["agent_id"]),
                _string(item["callsign"]),
                _string(item["provider"]),
                status,
                _timestamp(item["started_at"]),
                finished,
            )
        )
    return DispatchRun("", targets, _string(row["id"]), _timestamp(row["created_at"]))
