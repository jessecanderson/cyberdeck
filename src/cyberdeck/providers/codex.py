from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from .. import __version__
from ..domain import (
    AgentCapabilities,
    HistoryPage,
    ThreadSummary,
    map_history_turns,
    parse_timestamp,
)
from .base import AgentEvent

# JSON-RPC messages are newline-delimited and can contain large tool or agent payloads.
# asyncio's 64 KiB default causes readline() to fail before JSON decoding.
CODEX_STREAM_LIMIT = 16 * 1024 * 1024


class CodexProtocolError(RuntimeError):
    pass


class CodexAppServerAdapter:
    """One Codex app-server process and one persistent Codex thread."""

    def __init__(self, executable: str = "codex") -> None:
        self.executable = executable
        self.process: asyncio.subprocess.Process | None = None
        self.thread_id: str | None = None
        self.active_turn_id: str | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._events: asyncio.Queue[AgentEvent | None] = asyncio.Queue()
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self.cwd: Path | None = None
        self.model: str | None = None
        self.model_provider: str = "codex"
        self.capabilities = AgentCapabilities(
            load_session=True,
            history=True,
            rename=True,
            archive=True,
            interrupt=True,
            approvals=True,
            tool_events=True,
            model_selection=True,
        )
        self._intentional_shutdown = False

    async def _initialize(self, working_directory: Path) -> Path:
        cwd = working_directory.expanduser().resolve()
        if not cwd.is_dir():
            raise ValueError(f"Working directory does not exist: {cwd}")
        self.cwd = cwd
        self._intentional_shutdown = False
        self.process = await asyncio.create_subprocess_exec(
            self.executable,
            "app-server",
            "--listen",
            "stdio://",
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=CODEX_STREAM_LIMIT,
        )
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())

        await self._request(
            "initialize",
            {
                "clientInfo": {
                    "name": "cyberdeck",
                    "title": "Cyberdeck",
                    "version": __version__,
                },
                "capabilities": {"experimentalApi": True},
            },
        )
        await self._notify("initialized")
        return cwd

    async def start(self, working_directory: Path, name: str | None = None) -> None:
        cwd = await self._initialize(working_directory)
        result = await self._request(
            "thread/start",
            {
                "cwd": str(cwd),
                "approvalPolicy": "on-request",
                "sandbox": "workspace-write",
                "experimentalRawEvents": False,
            },
        )
        self.thread_id = result["thread"]["id"]
        self.model = result.get("model")
        self.model_provider = result.get("modelProvider", "codex")
        if name:
            await self.set_thread_name(self.thread_id, name)
        await self._events.put(AgentEvent("status", "ready"))

    async def resume_thread(self, thread_id: str, working_directory: Path) -> HistoryPage:
        cwd = await self._initialize(working_directory)
        result = await self._request(
            "thread/resume",
            {
                "threadId": thread_id,
                "cwd": str(cwd),
                "approvalPolicy": "on-request",
                "sandbox": "workspace-write",
            },
        )
        self.thread_id = result.get("thread", {}).get("id", thread_id)
        self.model = result.get("model")
        self.model_provider = result.get("modelProvider", "codex")
        initial = result.get("initialTurnsPage")
        if initial:
            page = map_history_turns(initial.get("data", []), initial.get("nextCursor"))
        else:
            page = await self.list_turns(limit=50)
        await self._events.put(AgentEvent("status", "ready"))
        return page

    async def list_threads(
        self, working_directory: Path, *, cursor: str | None = None, limit: int = 100
    ) -> tuple[list[ThreadSummary], str | None]:
        if not self.process:
            await self._initialize(working_directory)
        params: dict[str, Any] = {
            "archived": False,
            "limit": limit,
            "sortKey": "updated_at",
            "sortDirection": "desc",
        }
        if cursor:
            params["cursor"] = cursor
        result = await self._request("thread/list", params)
        rows: list[ThreadSummary] = []
        for raw in result.get("data", []):
            source = raw.get("source", "unknown")
            if isinstance(source, dict):
                source = source.get("type") or next(iter(source), "unknown")
            preview = raw.get("preview") or raw.get("title") or ""
            rows.append(
                ThreadSummary(
                    id=raw["id"],
                    name=raw.get("name") or raw.get("title"),
                    source=str(source),
                    cwd=Path(raw.get("cwd") or working_directory),
                    preview=str(preview).replace("\n", " ")[:160],
                    updated_at=parse_timestamp(raw.get("updatedAt") or raw.get("createdAt")),
                    model=raw.get("model"),
                    provider=raw.get("modelProvider") or "codex",
                )
            )
        return rows, result.get("nextCursor")

    async def list_turns(self, *, cursor: str | None = None, limit: int = 50) -> HistoryPage:
        if not self.thread_id:
            raise CodexProtocolError("Agent has not started")
        params: dict[str, Any] = {
            "threadId": self.thread_id,
            "limit": limit,
            "sortDirection": "desc",
            "itemsView": "full",
        }
        if cursor:
            params["cursor"] = cursor
        result = await self._request("thread/turns/list", params)
        return map_history_turns(result.get("data", []), result.get("nextCursor"))

    async def set_thread_name(self, thread_id: str, name: str) -> None:
        await self._request("thread/name/set", {"threadId": thread_id, "name": name})

    async def send(self, prompt: str) -> None:
        if not self.thread_id:
            raise CodexProtocolError("Agent has not started")
        result = await self._request(
            "turn/start",
            {
                "threadId": self.thread_id,
                "input": [{"type": "text", "text": prompt, "text_elements": []}],
            },
        )
        self.active_turn_id = result.get("turn", {}).get("id")
        await self._events.put(AgentEvent("status", "processing"))

    async def interrupt_turn(self) -> None:
        if not self.thread_id or not self.active_turn_id:
            raise CodexProtocolError("Agent has no active turn")
        await self._request(
            "turn/interrupt",
            {"threadId": self.thread_id, "turnId": self.active_turn_id},
        )
        self.active_turn_id = None

    async def archive_thread(self) -> None:
        if not self.thread_id:
            raise CodexProtocolError("Agent has not started")
        await self._request("thread/archive", {"threadId": self.thread_id})

    async def stop(self) -> None:
        self._intentional_shutdown = True
        process = self.process
        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except TimeoutError:
                process.kill()
                await process.wait()
        for task in (self._reader_task, self._stderr_task):
            if task:
                task.cancel()
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        await self._events.put(None)

    async def respond_approval(self, request_id: int | str, decision: str) -> None:
        await self._write({"id": request_id, "result": {"decision": decision}})

    async def events(self) -> AsyncIterator[AgentEvent]:
        while (event := await self._events.get()) is not None:
            yield event

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self._write({"id": request_id, "method": method, "params": params})
        try:
            return await future
        finally:
            self._pending.pop(request_id, None)

    async def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"method": method}
        if params is not None:
            message["params"] = params
        await self._write(message)

    async def _write(self, message: dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            raise CodexProtocolError("Codex app-server is not running")
        self.process.stdin.write(json.dumps(message, separators=(",", ":")).encode() + b"\n")
        await self.process.stdin.drain()

    async def _read_stdout(self) -> None:
        assert self.process and self.process.stdout
        try:
            while line := await self.process.stdout.readline():
                message = json.loads(line)
                if "id" in message and ("result" in message or "error" in message):
                    request_id = message["id"]
                    future = self._pending.get(request_id)
                    if future and not future.done():
                        if "error" in message:
                            future.set_exception(CodexProtocolError(str(message["error"])))
                        else:
                            future.set_result(message.get("result", {}))
                    continue
                if "id" in message and "method" in message:
                    method = message.get("method", "")
                    if method in {
                        "item/commandExecution/requestApproval",
                        "item/fileChange/requestApproval",
                    }:
                        await self._events.put(
                            AgentEvent(
                                "approval",
                                request_id=message["id"],
                                method=method,
                                params=message.get("params") or {},
                            )
                        )
                    continue
                await self._handle_notification(message)
            if not self._intentional_shutdown:
                await self._transport_closed("Codex app-server closed stdout")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - convert transport failures to agent events
            if not self._intentional_shutdown:
                await self._transport_closed(f"Codex transport failure: {exc}")

    async def _transport_closed(self, reason: str) -> None:
        error = CodexProtocolError(reason)
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        await self._events.put(AgentEvent("transport_closed", reason))

    async def _read_stderr(self) -> None:
        assert self.process and self.process.stderr
        while line := await self.process.stderr.readline():
            text = line.decode(errors="replace").strip()
            if text and not text.startswith("WARNING: proceeding"):
                await self._events.put(AgentEvent("debug", text))

    async def _handle_notification(self, message: dict[str, Any]) -> None:
        method = message.get("method", "")
        params = message.get("params") or {}
        if method == "item/agentMessage/delta":
            await self._events.put(
                AgentEvent(
                    "assistant_delta",
                    params.get("delta", ""),
                    message_id=params.get("itemId"),
                )
            )
        elif method in {"item/started", "item/completed"}:
            item = params.get("item") or {}
            if item.get("type") not in {"userMessage", "agentMessage", "reasoning"}:
                await self._events.put(AgentEvent("operation", method=method, params=item))
        elif method == "thread/tokenUsage/updated":
            await self._events.put(AgentEvent("token_usage", params=params))
        elif method == "turn/completed":
            self.active_turn_id = None
            await self._events.put(AgentEvent("status", "ready"))
