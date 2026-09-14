from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ToolPermissionContext,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from cyberdeck.providers import ClaudeAcpAdapter, ClaudeAgentSdkAdapter, claude_environment


def result(
    *,
    session_id: str = "00000000-0000-4000-8000-000000000001",
    is_error: bool = False,
    terminal_reason: str = "completed",
    text: str | None = None,
) -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=10,
        duration_api_ms=8,
        is_error=is_error,
        num_turns=1,
        session_id=session_id,
        result=text,
        terminal_reason=terminal_reason,
        usage={
            "input_tokens": 20,
            "cache_read_input_tokens": 5,
            "cache_creation_input_tokens": 3,
            "output_tokens": 7,
        },
        model_usage={"claude-test": {"contextWindow": 200_000}},  # type: ignore[typeddict-item]
    )


class FakeClaudeClient:
    def __init__(self, options: ClaudeAgentOptions, responses: list[object] | None = None) -> None:
        self.options = options
        self.responses = responses or []
        self.queries: list[tuple[str, str]] = []
        self.connected = False
        self.disconnected = False
        self.interrupted = False

    async def connect(self) -> None:
        self.connected = True

    async def query(self, prompt: str, session_id: str = "default") -> None:
        self.queries.append((prompt, session_id))

    async def receive_response(self):
        for message in self.responses:
            yield message

    async def interrupt(self) -> None:
        self.interrupted = True

    async def disconnect(self) -> None:
        self.disconnected = True


def adapter_with(
    responses: list[object] | None = None,
    *,
    deployment: str = "anthropic",
) -> tuple[ClaudeAgentSdkAdapter, list[FakeClaudeClient]]:
    clients: list[FakeClaudeClient] = []

    def factory(options: ClaudeAgentOptions) -> FakeClaudeClient:
        client = FakeClaudeClient(options, responses)
        clients.append(client)
        return client

    adapter = ClaudeAgentSdkAdapter(
        deployment=deployment,  # type: ignore[arg-type]
        environment={"PATH": "/opt/bin", "ANTHROPIC_API_KEY": "provider-owned"},
        client_factory=factory,
        session_id_factory=lambda: "00000000-0000-4000-8000-000000000001",
    )
    return adapter, clients


@pytest.mark.parametrize(
    ("deployment", "provider", "enabled"),
    [
        ("anthropic", "claude", None),
        ("bedrock", "claude-bedrock", "CLAUDE_CODE_USE_BEDROCK"),
        ("vertex", "claude-vertex", "CLAUDE_CODE_USE_VERTEX"),
    ],
)
@pytest.mark.asyncio
async def test_claude_adapter_uses_bundled_sdk_and_selects_route(
    tmp_path: Path, deployment: str, provider: str, enabled: str | None
) -> None:
    adapter, clients = adapter_with(deployment=deployment)

    await adapter.start(tmp_path)

    client = clients[0]
    options = client.options
    assert client.connected is True
    assert adapter.model_provider == provider
    assert options.cli_path is None
    assert options.session_id == "00000000-0000-4000-8000-000000000001"
    assert options.cwd == tmp_path.resolve()
    assert options.env["ANTHROPIC_API_KEY"] == "provider-owned"
    assert options.env["CLAUDE_AGENT_SDK_CLIENT_APP"].startswith("cyberdeck/")
    selected = {
        name
        for name in ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX")
        if name in options.env
    }
    assert selected == ({enabled} if enabled else set())
    settings = json.loads(options.settings or "{}")
    assert settings["env"]["CLAUDE_CODE_USE_BEDROCK"] == ("1" if deployment == "bedrock" else "0")
    assert settings["env"]["CLAUDE_CODE_USE_VERTEX"] == ("1" if deployment == "vertex" else "0")
    assert options.can_use_tool is not None
    await adapter.stop()
    assert client.disconnected is True


@pytest.mark.asyncio
async def test_claude_stream_tool_and_usage_mapping(tmp_path: Path) -> None:
    session_id = "00000000-0000-4000-8000-000000000001"
    responses = [
        StreamEvent(
            uuid="assistant-1",
            session_id=session_id,
            event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Grid"}},
        ),
        AssistantMessage(
            content=[
                TextBlock("Grid"),
                ToolUseBlock("tool-1", "Bash", {"command": "pytest -q"}),
            ],
            model="claude-test",
            uuid="assistant-1",
        ),
        UserMessage(content=[ToolResultBlock("tool-1", "242 passed", False)]),
        result(),
    ]
    adapter, clients = adapter_with(responses)
    await adapter.start(tmp_path)

    await adapter.send("validate")

    events = [await adapter._events.get() for _ in range(6)]
    assert clients[0].queries == [("validate", session_id)]
    assert [(event.kind, event.text) for event in events if event] == [
        ("status", "ready"),
        ("assistant_delta", "Grid"),
        ("operation", ""),
        ("operation", ""),
        ("token_usage", ""),
        ("status", "ready"),
    ]
    assert events[1] and events[1].message_id == "assistant-1"
    assert events[2] and events[2].params == {
        "id": "tool-1",
        "type": "commandExecution",
        "name": "Bash",
        "status": "running",
        "params": {"command": "pytest -q"},
        "command": "pytest -q",
        "files": [],
    }
    assert events[3] and events[3].params["status"] == "completed"
    token_usage = events[4].params["tokenUsage"] if events[4] and events[4].params else {}
    assert token_usage["last"] == {
        "inputTokens": 23,
        "cachedInputTokens": 5,
        "outputTokens": 7,
        "totalTokens": 35,
    }
    assert token_usage["modelContextWindow"] == 200_000
    assert adapter.model == "claude-test"
    await adapter.stop()


@pytest.mark.asyncio
async def test_claude_groups_stream_envelopes_into_one_assistant_message(
    tmp_path: Path,
) -> None:
    session_id = "00000000-0000-4000-8000-000000000001"
    responses = [
        StreamEvent(
            uuid="stream-envelope-1",
            session_id=session_id,
            event={
                "type": "message_start",
                "message": {"id": "claude-message-1", "model": "claude-test"},
            },
        ),
        StreamEvent(
            uuid="stream-envelope-2",
            session_id=session_id,
            event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": "One"}},
        ),
        StreamEvent(
            uuid="stream-envelope-3",
            session_id=session_id,
            event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": " line"}},
        ),
        AssistantMessage(
            [TextBlock("One line")],
            "claude-test",
            message_id="claude-message-1",
            uuid="transcript-entry-1",
        ),
        result(),
    ]
    adapter, _ = adapter_with(responses)
    await adapter.start(tmp_path)

    await adapter.send("respond")

    events = [await adapter._events.get() for _ in range(5)]
    assistant_events = [event for event in events if event and event.kind == "assistant_delta"]
    assert [(event.text, event.message_id) for event in assistant_events] == [
        ("One", "claude-message-1"),
        (" line", "claude-message-1"),
    ]
    await adapter.stop()


@pytest.mark.asyncio
async def test_claude_uses_complete_text_when_partial_stream_is_absent(tmp_path: Path) -> None:
    adapter, _ = adapter_with(
        [
            AssistantMessage([TextBlock("Complete response")], "claude-test", uuid="message-1"),
            result(),
        ]
    )
    await adapter.start(tmp_path)

    await adapter.send("respond")

    events = [await adapter._events.get() for _ in range(4)]
    assert events[1] and (events[1].kind, events[1].text) == (
        "assistant_delta",
        "Complete response",
    )
    await adapter.stop()


class PermissionClient(FakeClaudeClient):
    def __init__(self, options: ClaudeAgentOptions) -> None:
        super().__init__(options)
        self.permission_result: PermissionResultAllow | PermissionResultDeny | None = None

    async def receive_response(self):
        assert self.options.can_use_tool is not None
        self.permission_result = await self.options.can_use_tool(
            "Bash",
            {"command": "git status"},
            ToolPermissionContext(
                tool_use_id="tool-permission-1",
                title="Run git status?",
                display_name="Run command",
                description="Inspect the working tree",
            ),
        )
        yield result()


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["accept", "decline"])
async def test_claude_permission_bridge(tmp_path: Path, decision: str) -> None:
    clients: list[PermissionClient] = []

    def factory(options: ClaudeAgentOptions) -> PermissionClient:
        client = PermissionClient(options)
        clients.append(client)
        return client

    adapter = ClaudeAgentSdkAdapter(
        client_factory=factory,
        session_id_factory=lambda: "00000000-0000-4000-8000-000000000001",
    )
    await adapter.start(tmp_path)
    ready = await adapter._events.get()
    send = asyncio.create_task(adapter.send("inspect"))
    approval = await asyncio.wait_for(adapter._events.get(), timeout=1)

    assert ready and ready.kind == "status"
    assert approval and approval.kind == "approval"
    assert approval.request_id == "tool-permission-1"
    assert approval.method == "item/commandExecution/requestApproval"
    assert approval.params and approval.params["command"] == "git status"
    await adapter.respond_approval("tool-permission-1", decision)
    await asyncio.wait_for(send, timeout=1)

    response = clients[0].permission_result
    if decision == "accept":
        assert isinstance(response, PermissionResultAllow)
        assert response.updated_input == {"command": "git status"}
    else:
        assert isinstance(response, PermissionResultDeny)
    await adapter.stop()


@pytest.mark.asyncio
async def test_claude_interrupt_and_resume_use_sdk_controls(tmp_path: Path) -> None:
    adapter, clients = adapter_with([result(terminal_reason="aborted_streaming")])
    await adapter.start(tmp_path)
    await adapter.interrupt_turn()
    assert clients[0].interrupted is True
    await adapter.stop()

    resumed, resumed_clients = adapter_with()
    history = await resumed.resume_thread("existing-session", tmp_path)
    assert history.transcript == []
    assert resumed.thread_id == "existing-session"
    assert resumed_clients[0].options.resume == "existing-session"
    assert resumed_clients[0].options.session_id is None
    await resumed.stop()


@pytest.mark.asyncio
async def test_claude_provider_error_is_delivered_without_uncertain_replay(tmp_path: Path) -> None:
    adapter, _ = adapter_with(
        [result(is_error=True, terminal_reason="api_error", text="login required")]
    )
    await adapter.start(tmp_path)

    await adapter.send("hello")

    events = [await adapter._events.get() for _ in range(3)]
    assert [event.kind for event in events if event] == ["status", "token_usage", "error"]
    assert events[-1] and events[-1].text == "login required"
    await adapter.stop()


@pytest.mark.asyncio
async def test_claude_connect_timeout_disconnects_partial_client(tmp_path: Path) -> None:
    clients: list[FakeClaudeClient] = []

    class SlowClient(FakeClaudeClient):
        async def connect(self) -> None:
            await asyncio.sleep(1)

    def factory(options: ClaudeAgentOptions) -> SlowClient:
        client = SlowClient(options)
        clients.append(client)
        return client

    adapter = ClaudeAgentSdkAdapter(client_factory=factory, connect_timeout=0.01)

    with pytest.raises(TimeoutError, match="connection timed out after 0.01s"):
        await adapter.start(tmp_path)

    assert clients[0].disconnected is True
    assert adapter.client is None


def test_claude_environment_rejects_unknown_deployment() -> None:
    with pytest.raises(ValueError, match="Unsupported Claude deployment"):
        claude_environment("other", {})  # type: ignore[arg-type]


def test_claude_acp_name_remains_a_compatibility_alias() -> None:
    assert ClaudeAcpAdapter is ClaudeAgentSdkAdapter
