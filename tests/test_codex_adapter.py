import asyncio
import json

import pytest

from cyberdeck.providers.base import AgentEvent
from cyberdeck.providers.codex import (
    CODEX_STREAM_LIMIT,
    CodexAppServerAdapter,
    CodexProtocolError,
)


class Writer:
    def __init__(self) -> None:
        self.data = b""

    def write(self, data: bytes) -> None:
        self.data += data

    async def drain(self) -> None:
        pass


def test_agent_event_preserves_positional_provider_compatibility() -> None:
    event = AgentEvent("approval", "", 42, "request/approval", {"id": 1})

    assert event.request_id == 42
    assert event.method == "request/approval"
    assert event.params == {"id": 1}
    assert event.message_id is None


@pytest.mark.asyncio
async def test_request_is_json_rpc() -> None:
    adapter = CodexAppServerAdapter()
    writer = Writer()
    adapter.process = type("Process", (), {"stdin": writer})()

    task = asyncio.create_task(adapter._request("thread/start", {"cwd": "/tmp"}))
    await asyncio.sleep(0)
    message = json.loads(writer.data)
    assert message == {
        "id": 1,
        "method": "thread/start",
        "params": {"cwd": "/tmp"},
    }
    adapter._pending[1].set_result({"thread": {"id": "abc"}})
    assert await task == {"thread": {"id": "abc"}}


@pytest.mark.asyncio
async def test_send_requires_started_thread() -> None:
    with pytest.raises(CodexProtocolError):
        await CodexAppServerAdapter().send("hello")


@pytest.mark.asyncio
async def test_send_emits_processing_status() -> None:
    adapter = CodexAppServerAdapter()
    writer = Writer()
    adapter.process = type("Process", (), {"stdin": writer})()
    adapter.thread_id = "thread-1"

    task = asyncio.create_task(adapter.send("hello"))
    await asyncio.sleep(0)
    adapter._pending[1].set_result({"turn": {"id": "turn-1"}})
    await task
    event = await adapter._events.get()
    assert event is not None
    assert (event.kind, event.text) == ("status", "processing")
    assert adapter.active_turn_id == "turn-1"


@pytest.mark.asyncio
async def test_interrupt_uses_active_turn_and_clears_it() -> None:
    adapter = CodexAppServerAdapter()
    writer = Writer()
    adapter.process = type("Process", (), {"stdin": writer})()
    adapter.thread_id, adapter.active_turn_id = "thread-1", "turn-2"

    task = asyncio.create_task(adapter.interrupt_turn())
    await asyncio.sleep(0)
    assert json.loads(writer.data) == {
        "id": 1, "method": "turn/interrupt",
        "params": {"threadId": "thread-1", "turnId": "turn-2"},
    }
    adapter._pending[1].set_result({})
    await task
    assert adapter.active_turn_id is None


@pytest.mark.asyncio
async def test_archive_uses_thread_registry() -> None:
    adapter = CodexAppServerAdapter()
    writer = Writer()
    adapter.process = type("Process", (), {"stdin": writer})()
    adapter.thread_id = "thread-1"
    task = asyncio.create_task(adapter.archive_thread())
    await asyncio.sleep(0)
    assert json.loads(writer.data) == {
        "id": 1, "method": "thread/archive", "params": {"threadId": "thread-1"}
    }
    adapter._pending[1].set_result({})
    await task


@pytest.mark.asyncio
async def test_unexpected_stdout_eof_emits_transport_closed() -> None:
    reader = asyncio.StreamReader()
    reader.feed_eof()
    adapter = CodexAppServerAdapter()
    adapter.process = type("Process", (), {"stdout": reader})()
    await adapter._read_stdout()
    event = await adapter._events.get()
    assert event is not None
    assert event.kind == "transport_closed"


@pytest.mark.asyncio
async def test_intentional_stdout_eof_is_silent() -> None:
    reader = asyncio.StreamReader()
    reader.feed_eof()
    adapter = CodexAppServerAdapter()
    adapter._intentional_shutdown = True
    adapter.process = type("Process", (), {"stdout": reader})()
    await adapter._read_stdout()
    assert adapter._events.empty()


@pytest.mark.asyncio
async def test_stdout_accepts_json_rpc_lines_larger_than_asyncio_default() -> None:
    text = "signal" * 12_000
    message = {
        "method": "item/agentMessage/delta",
        "params": {"delta": text, "itemId": "message-1"},
    }
    encoded = json.dumps(message).encode() + b"\n"
    assert len(encoded) > 64 * 1024
    assert len(encoded) < CODEX_STREAM_LIMIT

    reader = asyncio.StreamReader(limit=CODEX_STREAM_LIMIT)
    reader.feed_data(encoded)
    reader.feed_eof()
    adapter = CodexAppServerAdapter()
    adapter._intentional_shutdown = True
    adapter.process = type("Process", (), {"stdout": reader})()

    await adapter._read_stdout()

    event = await adapter._events.get()
    assert event is not None
    assert event.kind == "assistant_delta"
    assert event.text == text


@pytest.mark.asyncio
async def test_approval_response_uses_server_request_id() -> None:
    adapter = CodexAppServerAdapter()
    writer = Writer()
    adapter.process = type("Process", (), {"stdin": writer})()

    await adapter.respond_approval(42, "accept")

    assert json.loads(writer.data) == {"id": 42, "result": {"decision": "accept"}}


@pytest.mark.asyncio
async def test_list_turns_requests_full_descending_page() -> None:
    adapter = CodexAppServerAdapter()
    writer = Writer()
    adapter.process = type("Process", (), {"stdin": writer})()
    adapter.thread_id = "thread-7"

    task = asyncio.create_task(adapter.list_turns(cursor="older", limit=50))
    await asyncio.sleep(0)
    message = json.loads(writer.data)
    assert message["method"] == "thread/turns/list"
    assert message["params"] == {
        "threadId": "thread-7",
        "limit": 50,
        "sortDirection": "desc",
        "itemsView": "full",
        "cursor": "older",
    }
    adapter._pending[1].set_result({"data": [], "nextCursor": None})
    assert (await task).next_cursor is None


@pytest.mark.asyncio
async def test_set_thread_name_uses_codex_registry() -> None:
    adapter = CodexAppServerAdapter()
    writer = Writer()
    adapter.process = type("Process", (), {"stdin": writer})()
    task = asyncio.create_task(adapter.set_thread_name("thread-1", "ghost"))
    await asyncio.sleep(0)
    assert json.loads(writer.data) == {
        "id": 1,
        "method": "thread/name/set",
        "params": {"threadId": "thread-1", "name": "ghost"},
    }
    adapter._pending[1].set_result({})
    await task


@pytest.mark.asyncio
async def test_token_usage_notification_becomes_agent_event() -> None:
    adapter = CodexAppServerAdapter()
    params = {
        "threadId": "thread-1",
        "turnId": "turn-1",
        "tokenUsage": {
            "last": {"totalTokens": 32000},
            "total": {"totalTokens": 50000},
            "modelContextWindow": 128000,
        },
    }
    await adapter._handle_notification(
        {"method": "thread/tokenUsage/updated", "params": params}
    )
    event = await adapter._events.get()
    assert event is not None
    assert event.kind == "token_usage"
    assert event.params == params


@pytest.mark.asyncio
async def test_agent_message_delta_preserves_item_identity() -> None:
    adapter = CodexAppServerAdapter()
    await adapter._handle_notification(
        {
            "method": "item/agentMessage/delta",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "itemId": "message-7",
                "delta": "Signal acquired.",
            },
        }
    )

    event = await adapter._events.get()
    assert event is not None
    assert event.kind == "assistant_delta"
    assert event.message_id == "message-7"
    assert event.text == "Signal acquired."
