from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from .. import __version__
from ..domain import AgentCapabilities, HistoryPage
from .base import AgentEvent

ACP_STREAM_LIMIT = 16 * 1024 * 1024


class AcpProtocolError(RuntimeError):
    """Raised when an ACP agent rejects or violates the negotiated contract."""


class AcpAgentAdapter:
    """ACP v1 client for one local stdio agent process and session."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        provider: str,
        initialize_timeout: float = 15.0,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        if not command:
            raise ValueError("ACP command cannot be empty")
        self.command = tuple(command)
        self.model_provider = provider
        self.capabilities = AgentCapabilities()
        self.initialize_timeout = initialize_timeout
        self.environment = dict(environment) if environment is not None else None
        self.process: asyncio.subprocess.Process | None = None
        self.thread_id: str | None = None
        self.model: str | None = None
        self.agent_capabilities: dict[str, Any] = {}
        self.agent_info: dict[str, Any] = {}
        self.session_modes: dict[str, Any] = {}
        self.cwd: Path | None = None
        self._next_id = 1
        self._pending: dict[int | str, asyncio.Future[dict[str, Any]]] = {}
        self._permission_options: dict[int | str, list[dict[str, Any]]] = {}
        self._events: asyncio.Queue[AgentEvent | None] = asyncio.Queue()
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._intentional_shutdown = False
        self._transport_failure_reported = False
        self._loading_session = False
        self._assistant_segment = 0
        self._assistant_message_id: str | None = None
        self._assistant_boundary = True

    async def start(self, working_directory: Path, name: str | None = None) -> None:
        del name
        cwd = self._working_directory(working_directory)
        await self._initialize(cwd)
        result = await self._request("session/new", {"cwd": str(cwd), "mcpServers": []})
        self.thread_id = result.get("sessionId")
        if not self.thread_id:
            raise AcpProtocolError("session/new response did not include sessionId")
        self._capture_session_configuration(result)
        await self._events.put(AgentEvent("status", "ready"))

    async def resume_thread(self, thread_id: str, working_directory: Path) -> HistoryPage:
        """Resume provider context; ACP v1 does not return transcript history here."""
        cwd = self._working_directory(working_directory)
        await self._initialize(cwd)
        if not self.agent_capabilities.get("loadSession"):
            raise AcpProtocolError("ACP agent does not advertise session loading")
        params = {"sessionId": thread_id, "cwd": str(cwd), "mcpServers": []}
        self._loading_session = True
        try:
            for attempt in range(5):
                try:
                    result = await self._request("session/load", params)
                    break
                except AcpProtocolError as exc:
                    releasing = "Session is active in another process" in str(exc)
                    if not releasing or attempt == 4:
                        raise
                    # Kiro's ACP child may release its provider-owned session lock a
                    # moment after the stdio parent exits. This remains part of the
                    # operator-requested restore; it does not initiate recovery itself.
                    await asyncio.sleep(0.25 * (2**attempt))
        finally:
            self._loading_session = False
        self.thread_id = thread_id
        self._capture_session_configuration(result)
        await self._events.put(AgentEvent("status", "ready"))
        return HistoryPage()

    def _working_directory(self, working_directory: Path) -> Path:
        cwd = working_directory.expanduser().resolve()
        if not cwd.is_dir():
            raise ValueError(f"Working directory does not exist: {cwd}")
        self.cwd = cwd
        return cwd

    async def _initialize(self, cwd: Path) -> None:
        self._intentional_shutdown = False
        self._transport_failure_reported = False
        try:
            self.process = await asyncio.create_subprocess_exec(
                *self.command,
                cwd=cwd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=ACP_STREAM_LIMIT,
                start_new_session=os.name == "posix",
                env=self.environment,
            )
        except FileNotFoundError as exc:
            raise AcpProtocolError(f"ACP executable not found: {self.command[0]}") from exc
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())
        initialized = await asyncio.wait_for(
            self._request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": False, "writeTextFile": False},
                        "terminal": False,
                    },
                    "clientInfo": {"name": "cyberdeck", "version": __version__},
                },
            ),
            timeout=self.initialize_timeout,
        )
        version = initialized.get("protocolVersion")
        if version != 1:
            raise AcpProtocolError(f"ACP protocol version 1 required; agent returned {version!r}")
        self.agent_capabilities = initialized.get("agentCapabilities") or {}
        self.agent_info = initialized.get("agentInfo") or {}
        is_kiro = "kiro" in str(self.agent_info.get("name", "")).casefold()
        self.capabilities = AgentCapabilities(
            load_session=bool(self.agent_capabilities.get("loadSession")),
            # ACP session/load restores provider context, but does not define a
            # paged structured-history API equivalent to Codex turn/list.
            history=False,
            interrupt=True,
            approvals=True,
            tool_events=True,
            model_selection=bool(self.session_modes),
            # Context compaction is not part of ACP v1. Kiro exposes it through
            # its documented, strictly shaped slash-command extension.
            context_compaction=is_kiro,
        )
        self.model = str(self.agent_info.get("name") or "ACP")

    async def send(self, prompt: str) -> None:
        if not self.thread_id:
            raise AcpProtocolError("ACP session has not started")
        self._assistant_boundary = True
        await self._request(
            "session/prompt",
            {
                "sessionId": self.thread_id,
                "prompt": [{"type": "text", "text": prompt}],
            },
        )
        await self._events.put(AgentEvent("status", "ready"))

    async def interrupt_turn(self) -> None:
        if not self.thread_id:
            raise AcpProtocolError("ACP session has not started")
        await self._notify("session/cancel", {"sessionId": self.thread_id})

    async def compact_context(self) -> None:
        if not self.thread_id:
            raise AcpProtocolError("ACP session has not started")
        if not self.capabilities.context_compaction:
            raise AcpProtocolError("This ACP agent does not expose context compaction")
        await self._request(
            "_kiro.dev/commands/execute",
            {
                "sessionId": self.thread_id,
                "command": {"command": "compact", "args": {}},
            },
        )

    async def respond_approval(self, request_id: int | str, decision: str) -> None:
        options = self._permission_options.get(request_id, [])
        preferred = {
            "accept": ("allow_once", "allow_always"),
            "acceptForSession": ("allow_always", "allow_once"),
            "decline": ("reject_once", "reject_always"),
        }.get(decision, ("reject_once", "reject_always"))
        selected = next(
            (option for kind in preferred for option in options if option.get("kind") == kind),
            None,
        )
        if selected is None:
            raise AcpProtocolError(
                f"ACP agent offered no compatible permission option for {decision}"
            )
        await self._write(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "outcome": {
                        "outcome": "selected",
                        "optionId": selected["optionId"],
                    }
                },
            }
        )
        self._permission_options.pop(request_id, None)

    async def set_thread_name(self, thread_id: str, name: str) -> None:
        del thread_id, name
        raise AcpProtocolError("This ACP agent does not expose persistent session naming")

    async def archive_thread(self) -> None:
        raise AcpProtocolError("This ACP agent does not expose session archiving")

    async def list_turns(self, *, cursor: str | None = None, limit: int = 50) -> HistoryPage:
        del cursor, limit
        return HistoryPage()

    async def stop(self) -> None:
        self._intentional_shutdown = True
        process = self.process
        if process and process.returncode is None:
            self._signal_process(process, signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except TimeoutError:
                self._signal_process(process, getattr(signal, "SIGKILL", signal.SIGTERM))
                await process.wait()
        for task in (self._reader_task, self._stderr_task):
            if task:
                task.cancel()
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._permission_options.clear()
        await self._events.put(None)

    @staticmethod
    def _signal_process(process: asyncio.subprocess.Process, sig: signal.Signals) -> None:
        """Signal the adapter-owned ACP process tree without matching by name."""
        try:
            if os.name == "posix":
                os.killpg(process.pid, sig)
            elif sig is signal.SIGTERM:
                process.terminate()
            else:
                process.kill()
        except ProcessLookupError:
            pass

    async def events(self) -> AsyncIterator[AgentEvent]:
        while (event := await self._events.get()) is not None:
            yield event

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        try:
            return await future
        finally:
            self._pending.pop(request_id, None)

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        await self._write({"jsonrpc": "2.0", "method": method, "params": params})

    async def _write(self, message: dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            raise AcpProtocolError("ACP agent process is not running")
        self.process.stdin.write(json.dumps(message, separators=(",", ":")).encode() + b"\n")
        await self.process.stdin.drain()

    async def _read_stdout(self) -> None:
        assert self.process and self.process.stdout
        try:
            while line := await self.process.stdout.readline():
                try:
                    message = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise AcpProtocolError(f"Malformed ACP message: {exc}") from exc
                if not isinstance(message, dict):
                    raise AcpProtocolError("ACP message must be a JSON object")
                if "id" in message and ("result" in message or "error" in message):
                    self._handle_response(message)
                elif "id" in message and "method" in message:
                    await self._handle_agent_request(message)
                elif "method" in message:
                    await self._handle_notification(message)
            if not self._intentional_shutdown:
                await self._transport_closed("ACP agent closed stdout")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            if not self._intentional_shutdown:
                await self._transport_closed(f"ACP transport failure: {exc}")

    def _handle_response(self, message: dict[str, Any]) -> None:
        future = self._pending.get(message["id"])
        if not future or future.done():
            return
        if "error" in message:
            future.set_exception(AcpProtocolError(str(message["error"])))
        else:
            result = message.get("result")
            future.set_result(result if isinstance(result, dict) else {})

    async def _handle_agent_request(self, message: dict[str, Any]) -> None:
        method = str(message.get("method", ""))
        request_id = message["id"]
        params = message.get("params") or {}
        if method == "session/request_permission":
            self._assistant_boundary = True
            self._permission_options[request_id] = [
                option for option in params.get("options") or [] if isinstance(option, dict)
            ]
            await self._events.put(
                AgentEvent("approval", request_id=request_id, method=method, params=params)
            )
            return
        await self._write(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"Method not supported: {method}"},
            }
        )

    async def _handle_notification(self, message: dict[str, Any]) -> None:
        method = str(message.get("method", ""))
        params = message.get("params") or {}
        if method == "_kiro.dev/metadata":
            percentage = params.get("contextUsagePercentage")
            if percentage is not None:
                await self._events.put(
                    AgentEvent("context_usage", params={"percentage": percentage})
                )
            return
        if method != "session/update":
            if method.startswith("_kiro.dev/"):
                await self._events.put(AgentEvent("debug", f"Kiro extension: {method}"))
            return
        update = params.get("update") or {}
        update_type = str(update.get("sessionUpdate") or "")
        normalized = update_type.replace("-", "_").casefold()
        if normalized in {"agent_message_chunk", "agentmessagechunk"}:
            content = update.get("content") or {}
            text = content.get("text", "") if isinstance(content, dict) else str(content)
            if text:
                await self._events.put(
                    AgentEvent(
                        "assistant_delta",
                        text,
                        message_id=self._current_assistant_message_id(),
                    )
                )
        elif self._loading_session and normalized in {
            "user_message_chunk",
            "usermessagechunk",
        }:
            content = update.get("content") or {}
            text = content.get("text", "") if isinstance(content, dict) else str(content)
            if text:
                self._assistant_boundary = True
                await self._events.put(AgentEvent("user_replay", text))
        elif normalized in {"tool_call", "toolcall", "tool_call_update", "toolcallupdate"}:
            await self._events.put(
                AgentEvent("operation", method=update_type, params=self._operation(update))
            )
            self._assistant_boundary = True

    def _current_assistant_message_id(self) -> str:
        if self._assistant_boundary or self._assistant_message_id is None:
            self._assistant_segment += 1
            session = self.thread_id or "pending"
            self._assistant_message_id = f"acp:{session}:{self._assistant_segment}"
            self._assistant_boundary = False
        return self._assistant_message_id

    @staticmethod
    def _operation(update: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": update.get("toolCallId") or update.get("id"),
            "type": "toolCall",
            "name": update.get("title") or update.get("name") or "tool",
            "status": update.get("status") or "running",
            "params": update.get("rawInput") or update.get("input") or {},
            "output": update.get("rawOutput") or update.get("output"),
        }

    def _capture_session_configuration(self, result: dict[str, Any]) -> None:
        self.session_modes = result.get("modes") or {}
        models = result.get("models") or {}
        self.capabilities = replace(
            self.capabilities,
            model_selection=bool(models.get("availableModels")),
        )
        if models.get("currentModelId"):
            self.model = str(models["currentModelId"])

    async def _transport_closed(self, reason: str) -> None:
        if self._transport_failure_reported:
            return
        self._transport_failure_reported = True
        error = AcpProtocolError(reason)
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._permission_options.clear()
        await self._events.put(AgentEvent("transport_closed", reason))

    async def _read_stderr(self) -> None:
        assert self.process and self.process.stderr
        while line := await self.process.stderr.readline():
            text = line.decode(errors="replace").strip()
            if text:
                await self._events.put(AgentEvent("debug", text))


def kiro_executable() -> str:
    discovered = shutil.which("kiro-cli")
    if discovered:
        return discovered
    user_install = Path.home() / ".local" / "bin" / "kiro-cli"
    return str(user_install) if user_install.is_file() else "kiro-cli"


class KiroAcpAdapter(AcpAgentAdapter):
    def __init__(self, executable: str | None = None) -> None:
        super().__init__(
            (executable or kiro_executable(), "acp"),
            provider="kiro",
        )
