from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import uuid4

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ClaudeSDKError,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ToolPermissionContext,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from .. import __version__
from ..domain import AgentCapabilities, HistoryPage, ThreadSummary
from .base import AgentEvent

ClaudeDeployment = Literal["anthropic", "bedrock", "vertex"]

_RUNTIME_IDS: dict[ClaudeDeployment, str] = {
    "anthropic": "claude",
    "bedrock": "claude-bedrock",
    "vertex": "claude-vertex",
}
_CLOUD_SELECTORS = (
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_MANTLE",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)


class ClaudeProviderError(RuntimeError):
    """The bundled Claude Agent SDK could not complete a provider operation."""


class _ClaudeClient(Protocol):
    async def connect(self) -> None: ...

    async def query(self, prompt: str, session_id: str = "default") -> None: ...

    def receive_response(self) -> AsyncIterator[Any]: ...

    async def interrupt(self) -> None: ...

    async def disconnect(self) -> None: ...


def claude_environment(
    deployment: ClaudeDeployment,
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Select one Claude inference route without inspecting provider credentials."""
    if deployment not in _RUNTIME_IDS:
        raise ValueError(f"Unsupported Claude deployment: {deployment}")
    environment = dict(os.environ if source is None else source)
    for name in _CLOUD_SELECTORS:
        environment.pop(name, None)
    if deployment == "bedrock":
        environment["CLAUDE_CODE_USE_BEDROCK"] = "1"
    elif deployment == "vertex":
        environment["CLAUDE_CODE_USE_VERTEX"] = "1"
    return environment


def _claude_route_settings(deployment: ClaudeDeployment) -> dict[str, str]:
    settings = {name: "0" for name in _CLOUD_SELECTORS}
    if deployment == "bedrock":
        settings["CLAUDE_CODE_USE_BEDROCK"] = "1"
    elif deployment == "vertex":
        settings["CLAUDE_CODE_USE_VERTEX"] = "1"
    return settings


class ClaudeAgentSdkAdapter:
    """One persistent Claude Code session through Anthropic's Python Agent SDK."""

    def __init__(
        self,
        *,
        deployment: ClaudeDeployment = "anthropic",
        environment: Mapping[str, str] | None = None,
        client_factory: Callable[[ClaudeAgentOptions], _ClaudeClient] = ClaudeSDKClient,
        session_id_factory: Callable[[], str] = lambda: str(uuid4()),
        connect_timeout: float = 30.0,
    ) -> None:
        if deployment not in _RUNTIME_IDS:
            raise ValueError(f"Unsupported Claude deployment: {deployment}")
        if connect_timeout <= 0:
            raise ValueError("Claude connect timeout must be positive")
        self.deployment = deployment
        self.model_provider = _RUNTIME_IDS[deployment]
        self.environment = claude_environment(deployment, environment)
        self._route_settings = _claude_route_settings(deployment)
        self._client_factory = client_factory
        self._session_id_factory = session_id_factory
        self.connect_timeout = connect_timeout
        self.capabilities = AgentCapabilities(
            load_session=True,
            history=False,
            interrupt=True,
            approvals=True,
            tool_events=True,
        )
        self.thread_id: str | None = None
        self.model: str | None = "Claude Code"
        self.cwd: Path | None = None
        self.client: _ClaudeClient | None = None
        self._events: asyncio.Queue[AgentEvent | None] = asyncio.Queue()
        self._permissions: dict[
            str,
            tuple[
                asyncio.Future[PermissionResultAllow | PermissionResultDeny],
                dict[str, Any],
                ToolPermissionContext,
            ],
        ] = {}
        self._assistant_segment = 0
        self._assistant_message_id: str | None = None
        self._assistant_boundary = True
        self._streamed_text = False
        self._tools: dict[str, tuple[str, str, dict[str, Any]]] = {}
        self._stopped = False

    async def start(self, working_directory: Path, name: str | None = None) -> None:
        del name
        session_id = self._session_id_factory()
        await self._connect(working_directory, session_id=session_id)
        self.thread_id = session_id
        await self._events.put(AgentEvent("status", "ready", params={"connection_ready": True}))

    async def resume_thread(self, thread_id: str, working_directory: Path) -> HistoryPage:
        await self._connect(working_directory, resume=thread_id)
        self.thread_id = thread_id
        await self._events.put(AgentEvent("status", "ready", params={"connection_ready": True}))
        return HistoryPage()

    async def _connect(
        self,
        working_directory: Path,
        *,
        session_id: str | None = None,
        resume: str | None = None,
    ) -> None:
        cwd = working_directory.expanduser().resolve()
        if not cwd.is_dir():
            raise ValueError(f"Working directory does not exist: {cwd}")
        self.cwd = cwd
        self._stopped = False
        environment = dict(self.environment)
        environment["CLAUDE_AGENT_SDK_CLIENT_APP"] = f"cyberdeck/{__version__}"
        options = ClaudeAgentOptions(
            cwd=cwd,
            session_id=session_id,
            resume=resume,
            env=environment,
            settings=json.dumps({"env": self._route_settings}, separators=(",", ":")),
            permission_mode="default",
            can_use_tool=self._request_permission,
            include_partial_messages=True,
        )
        client = self._client_factory(options)
        self.client = client
        try:
            async with asyncio.timeout(self.connect_timeout):
                await client.connect()
        except TimeoutError as exc:
            with suppress(ClaudeSDKError, OSError, TimeoutError):
                await self._disconnect_client(client)
            self.client = None
            raise TimeoutError(
                f"Claude Agent SDK connection timed out after {self.connect_timeout:g}s"
            ) from exc
        except BaseException:
            with suppress(ClaudeSDKError, OSError, TimeoutError):
                await self._disconnect_client(client)
            self.client = None
            raise

    async def send(self, prompt: str) -> None:
        client = self._require_client()
        if not self.thread_id:
            raise ClaudeProviderError("Claude session has not started")
        self._assistant_boundary = True
        self._streamed_text = False
        await client.query(prompt, session_id=self.thread_id)
        received_result = False
        async for message in client.receive_response():
            await self._handle_message(message)
            if isinstance(message, ResultMessage):
                received_result = True
        if not received_result:
            raise ClaudeProviderError("Claude response ended without a result")

    async def _handle_message(self, message: Any) -> None:
        if isinstance(message, StreamEvent):
            await self._handle_stream_event(message)
            return
        if isinstance(message, AssistantMessage):
            self.model = message.model or self.model
            if message.parent_tool_use_id is not None:
                return
            self._adopt_assistant_message_id(message.message_id or message.uuid)
            for block in message.content:
                if isinstance(block, TextBlock) and not self._streamed_text:
                    await self._emit_text(block.text, self._current_assistant_message_id())
                elif isinstance(block, ToolUseBlock):
                    await self._emit_tool_start(block)
            self._streamed_text = False
            self._assistant_boundary = True
            return
        if isinstance(message, UserMessage) and isinstance(message.content, list):
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    await self._emit_tool_result(block)
            return
        if isinstance(message, SystemMessage):
            session_id = message.data.get("session_id")
            model = message.data.get("model")
            if session_id and not self.thread_id:
                self.thread_id = str(session_id)
            if model:
                self.model = str(model)
            return
        if isinstance(message, ResultMessage):
            self.thread_id = message.session_id or self.thread_id
            await self._emit_usage(message)
            interrupted = message.terminal_reason in {"aborted_streaming", "aborted_tools"}
            if message.is_error and not interrupted:
                reason = (
                    message.result or "; ".join(message.errors or ()) or "Claude request failed"
                )
                await self._events.put(AgentEvent("error", reason))
            else:
                await self._events.put(AgentEvent("status", "ready"))

    async def _handle_stream_event(self, message: StreamEvent) -> None:
        if message.parent_tool_use_id is not None:
            return
        event = message.event
        if event.get("type") == "message_start":
            raw_message = event.get("message") or {}
            self._adopt_assistant_message_id(raw_message.get("id"))
            model = raw_message.get("model")
            if model:
                self.model = str(model)
            return
        if event.get("type") != "content_block_delta":
            return
        delta = event.get("delta") or {}
        if delta.get("type") != "text_delta" or not delta.get("text"):
            return
        self._adopt_assistant_message_id(message.uuid)
        self._streamed_text = True
        await self._emit_text(str(delta["text"]), self._current_assistant_message_id())

    async def _emit_text(self, text: str, message_id: str | None) -> None:
        if text:
            await self._events.put(AgentEvent("assistant_delta", text, message_id=message_id))

    async def _emit_tool_start(self, block: ToolUseBlock) -> None:
        kind = self._tool_kind(block.name)
        self._tools[block.id] = (kind, block.name, block.input)
        await self._events.put(
            AgentEvent(
                "operation",
                method="item/started",
                params={
                    "id": block.id,
                    "type": kind,
                    "name": block.name,
                    "status": "running",
                    "params": block.input,
                    "command": block.input.get("command"),
                    "files": self._tool_files(block.name, block.input),
                },
            )
        )
        self._assistant_boundary = True

    async def _emit_tool_result(self, block: ToolResultBlock) -> None:
        kind, name, input_data = self._tools.pop(block.tool_use_id, ("dynamicToolCall", "tool", {}))
        await self._events.put(
            AgentEvent(
                "operation",
                method="item/completed",
                params={
                    "id": block.tool_use_id,
                    "type": kind,
                    "name": name,
                    "status": "failed" if block.is_error else "completed",
                    "output": self._display_content(block.content),
                    "params": input_data,
                    "command": input_data.get("command"),
                    "files": self._tool_files(name, input_data),
                },
            )
        )
        self._assistant_boundary = True

    def _current_assistant_message_id(self) -> str:
        if self._assistant_boundary or self._assistant_message_id is None:
            self._assistant_segment += 1
            session = self.thread_id or "pending"
            self._assistant_message_id = f"claude:{session}:{self._assistant_segment}"
            self._assistant_boundary = False
        return self._assistant_message_id

    def _adopt_assistant_message_id(self, message_id: str | None) -> None:
        if message_id and self._assistant_boundary:
            self._assistant_message_id = message_id
            self._assistant_boundary = False

    async def _emit_usage(self, message: ResultMessage) -> None:
        usage = message.usage or {}
        input_tokens = int(usage.get("input_tokens") or 0)
        cached_tokens = int(usage.get("cache_read_input_tokens") or 0)
        cache_creation = int(usage.get("cache_creation_input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        context_window = next(
            (
                int(model.get("contextWindow"))
                for model in (message.model_usage or {}).values()
                if model.get("contextWindow")
            ),
            None,
        )
        await self._events.put(
            AgentEvent(
                "token_usage",
                params={
                    "tokenUsage": {
                        "last": {
                            "inputTokens": input_tokens + cache_creation,
                            "cachedInputTokens": cached_tokens,
                            "outputTokens": output_tokens,
                            "totalTokens": input_tokens
                            + cached_tokens
                            + cache_creation
                            + output_tokens,
                        },
                        "modelContextWindow": context_window,
                    }
                },
            )
        )

    async def _request_permission(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResultAllow | PermissionResultDeny:
        request_id = context.tool_use_id or str(uuid4())
        future: asyncio.Future[PermissionResultAllow | PermissionResultDeny] = (
            asyncio.get_running_loop().create_future()
        )
        self._permissions[request_id] = (future, input_data, context)
        method = (
            "item/commandExecution/requestApproval"
            if tool_name == "Bash"
            else "claude/tool/requestApproval"
        )
        await self._events.put(
            AgentEvent(
                "approval",
                request_id=request_id,
                method=method,
                params={
                    "toolCall": {
                        "toolCallId": request_id,
                        "title": context.display_name or context.title or tool_name,
                        "rawInput": input_data,
                    },
                    "command": input_data.get("command"),
                    "cwd": str(self.cwd) if self.cwd else None,
                    "reason": context.description or context.decision_reason,
                    "options": [
                        {"optionId": "allow", "name": "Allow once", "kind": "allow_once"},
                        {
                            "optionId": "allow-session",
                            "name": "Allow for session",
                            "kind": "allow_always",
                        },
                        {"optionId": "deny", "name": "Deny", "kind": "reject_once"},
                    ],
                },
            )
        )
        try:
            return await future
        finally:
            self._permissions.pop(request_id, None)

    async def respond_approval(self, request_id: int | str, decision: str) -> None:
        pending = self._permissions.get(str(request_id))
        if pending is None:
            raise ClaudeProviderError(f"Unknown Claude permission request: {request_id}")
        future, input_data, context = pending
        if future.done():
            return
        if decision == "decline":
            future.set_result(PermissionResultDeny(message="Denied by Cyberdeck operator"))
            return
        updates = context.suggestions if decision == "acceptForSession" else None
        future.set_result(
            PermissionResultAllow(updated_input=input_data, updated_permissions=updates or None)
        )

    async def interrupt_turn(self) -> None:
        await self._require_client().interrupt()

    async def compact_context(self) -> None:
        raise ClaudeProviderError("Claude SDK context compaction is not exposed by Cyberdeck")

    async def set_thread_name(self, thread_id: str, name: str) -> None:
        del thread_id, name
        raise ClaudeProviderError("Claude SDK session naming is not exposed by Cyberdeck")

    async def archive_thread(self) -> None:
        raise ClaudeProviderError("Claude SDK session archiving is not exposed by Cyberdeck")

    async def list_threads(
        self, working_directory: Path, *, cursor: str | None = None
    ) -> tuple[list[ThreadSummary], str | None]:
        del working_directory, cursor
        return [], None

    async def list_turns(self, *, cursor: str | None = None) -> HistoryPage:
        del cursor
        return HistoryPage()

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        for future, _, _ in tuple(self._permissions.values()):
            if not future.done():
                future.set_result(PermissionResultDeny(message="Claude session stopped"))
        self._permissions.clear()
        client, self.client = self.client, None
        if client is not None:
            await self._disconnect_client(client)
        await self._events.put(None)

    async def events(self) -> AsyncIterator[AgentEvent]:
        while (event := await self._events.get()) is not None:
            yield event

    async def _disconnect_client(self, client: _ClaudeClient) -> None:
        async with asyncio.timeout(10):
            await client.disconnect()

    def _require_client(self) -> _ClaudeClient:
        if self.client is None:
            raise ClaudeProviderError("Claude Agent SDK client is not connected")
        return self.client

    @staticmethod
    def _tool_kind(name: str) -> str:
        if name == "Bash":
            return "commandExecution"
        if name in {"Edit", "Write", "NotebookEdit"}:
            return "fileChange"
        if name.startswith("mcp__"):
            return "mcpToolCall"
        return "dynamicToolCall"

    @staticmethod
    def _tool_files(name: str, input_data: dict[str, Any]) -> list[str]:
        if name not in {"Edit", "Write", "NotebookEdit"}:
            return []
        path = input_data.get("file_path") or input_data.get("notebook_path")
        return [str(path)] if path else []

    @staticmethod
    def _display_content(content: str | list[dict[str, Any]] | None) -> str | None:
        if content is None or isinstance(content, str):
            return content
        return json.dumps(content, ensure_ascii=False)


# Compatibility export for applications written against Cyberdeck 0.4.0.
ClaudeAcpAdapter = ClaudeAgentSdkAdapter
