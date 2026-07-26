from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from cyberdeck.providers import AcpAgentAdapter, AcpProtocolError

FAKE_AGENT = r'''
import json, sys

def receive(): return json.loads(sys.stdin.readline())
def send(message): print(json.dumps(message, separators=(",", ":")), flush=True)

initialize = receive()
send({"jsonrpc":"2.0","id":initialize["id"],"result":{
    "protocolVersion":1,
    "agentCapabilities":{"loadSession":True},
    "agentInfo":{"name":"fake-acp","version":"1.0"},
}})
new_session = receive()
send({"jsonrpc":"2.0","id":new_session["id"],"result":{
    "sessionId":"session-1",
    "models":{"currentModelId":"fake-model","availableModels":[]},
}})
prompt = receive()
assert prompt["params"]["prompt"] == [{"type":"text","text":"scan grid"}]
send({"jsonrpc":"2.0","method":"session/update","params":{
    "sessionId":"session-1",
    "update":{"sessionUpdate":"agent_message_chunk","content":{"type":"text","text":"Grid"}},
}})
send({"jsonrpc":"2.0","method":"session/update","params":{
    "sessionId":"session-1",
    "update":{"sessionUpdate":"agent_message_chunk","content":{"type":"text","text":" clear."}},
}})
send({"jsonrpc":"2.0","method":"session/update","params":{
    "sessionId":"session-1",
    "update":{"sessionUpdate":"tool_call","toolCallId":"tool-1","title":"scan","status":"in_progress"},
}})
send({"jsonrpc":"2.0","method":"session/update","params":{
    "sessionId":"session-1",
    "update":{"sessionUpdate":"agent_message_chunk","content":{"type":"text","text":"Scan complete."}},
}})
send({"jsonrpc":"2.0","id":prompt["id"],"result":{"stopReason":"end_turn"}})
'''

FAKE_PERMISSION_AGENT = r'''
import json, sys

def receive(): return json.loads(sys.stdin.readline())
def send(message): print(json.dumps(message, separators=(",", ":")), flush=True)

initialize = receive()
send({"jsonrpc":"2.0","id":initialize["id"],"result":{"protocolVersion":1}})
new_session = receive()
send({"jsonrpc":"2.0","id":new_session["id"],"result":{"sessionId":"session-2"}})
prompt = receive()
for request_id, title in (("permission-7", "write file"), ("permission-8", "run tests")):
    send({"jsonrpc":"2.0","id":request_id,"method":"session/request_permission","params":{
        "sessionId":"session-2",
        "toolCall":{"toolCallId":request_id,"title":title},
        "options":[
            {"optionId":request_id+"-yes","name":"Allow","kind":"allow_once"},
            {"optionId":request_id+"-always","name":"Always","kind":"allow_always"},
            {"optionId":request_id+"-no","name":"Reject","kind":"reject_once"},
        ],
    }})
answers = [receive(), receive()]
assert {answer["id"] for answer in answers} == {"permission-7", "permission-8"}
send({"jsonrpc":"2.0","id":prompt["id"],"result":{"stopReason":"end_turn"}})
'''


def adapter(script: str) -> AcpAgentAdapter:
    return AcpAgentAdapter(
        (sys.executable, "-u", "-c", script),
        provider="fake",
        initialize_timeout=2,
    )


@pytest.mark.asyncio
async def test_acp_v1_handshake_prompt_and_stream_mapping(tmp_path: Path) -> None:
    agent = adapter(FAKE_AGENT)
    await agent.start(tmp_path)
    await agent.send("scan grid")

    events = [await asyncio.wait_for(agent._events.get(), timeout=1) for _ in range(6)]
    assert [(event.kind, event.text) for event in events if event is not None] == [
        ("status", "ready"),
        ("assistant_delta", "Grid"),
        ("assistant_delta", " clear."),
        ("operation", ""),
        ("assistant_delta", "Scan complete."),
        ("status", "ready"),
    ]
    assistant_events = [event for event in events if event and event.kind == "assistant_delta"]
    assert assistant_events[0].message_id == assistant_events[1].message_id
    assert assistant_events[1].message_id != assistant_events[2].message_id
    assert agent.thread_id == "session-1"
    assert agent.model == "fake-model"
    assert agent.agent_capabilities == {"loadSession": True}
    assert agent.capabilities.load_session is True
    assert agent.capabilities.history is False
    await agent.stop()


@pytest.mark.asyncio
async def test_acp_keeps_overlapping_permission_option_lists_independent(
    tmp_path: Path,
) -> None:
    agent = adapter(FAKE_PERMISSION_AGENT)
    await agent.start(tmp_path)
    send_task = asyncio.create_task(agent.send("two operations"))

    ready = await asyncio.wait_for(agent._events.get(), timeout=1)
    first = await asyncio.wait_for(agent._events.get(), timeout=1)
    second = await asyncio.wait_for(agent._events.get(), timeout=1)
    assert ready and ready.kind == "status"
    assert first and first.request_id == "permission-7"
    assert second and second.request_id == "permission-8"
    assert len(agent._permission_options["permission-7"]) == 3
    assert len(agent._permission_options["permission-8"]) == 3

    await agent.respond_approval("permission-8", "decline")
    await agent.respond_approval("permission-7", "acceptForSession")
    await asyncio.wait_for(send_task, timeout=1)
    assert not agent._permission_options
    await agent.stop()


@pytest.mark.asyncio
async def test_acp_rejects_non_v1_agent(tmp_path: Path) -> None:
    script = r'''
import json, sys
message = json.loads(sys.stdin.readline())
print(json.dumps({"jsonrpc":"2.0","id":message["id"],"result":{"protocolVersion":2}}), flush=True)
'''
    agent = adapter(script)
    with pytest.raises(AcpProtocolError, match="version 1 required"):
        await agent.start(tmp_path)
    await agent.stop()


@pytest.mark.asyncio
async def test_acp_reports_malformed_json_as_transport_failure(tmp_path: Path) -> None:
    script = r'''
import sys
sys.stdin.readline()
print("{not-json", flush=True)
'''
    agent = adapter(script)
    with pytest.raises(
        AcpProtocolError,
        match=r"ACP transport failure: Malformed ACP message:",
    ):
        await agent.start(tmp_path)
    event = await asyncio.wait_for(agent._events.get(), timeout=1)
    assert event and event.kind == "transport_closed"
    assert "Malformed ACP message" in event.text
    await agent.stop()


@pytest.mark.asyncio
async def test_acp_resume_uses_session_load_and_preserves_session_id(
    tmp_path: Path,
) -> None:
    script = r'''
import json, sys

def receive(): return json.loads(sys.stdin.readline())
def send(message): print(json.dumps(message, separators=(",", ":")), flush=True)

initialize = receive()
send({"jsonrpc":"2.0","id":initialize["id"],"result":{
    "protocolVersion":1,"agentCapabilities":{"loadSession":True}
}})
load = receive()
assert load["method"] == "session/load"
assert load["params"]["sessionId"] == "kiro-session-7"
send({"jsonrpc":"2.0","method":"session/update","params":{
    "sessionId":"kiro-session-7",
    "update":{"sessionUpdate":"user_message_chunk","content":{
        "type":"text","text":"Earlier prompt."
    }}
}})
send({"jsonrpc":"2.0","method":"session/update","params":{
    "sessionId":"kiro-session-7",
    "update":{"sessionUpdate":"agent_message_chunk","content":{
        "type":"text","text":"Earlier response."
    }}
}})
send({"jsonrpc":"2.0","id":load["id"],"result":{
    "models":{"currentModelId":"kiro-test"}
}})
prompt = receive()
assert prompt["params"]["sessionId"] == "kiro-session-7"
send({"jsonrpc":"2.0","method":"session/update","params":{
    "sessionId":"kiro-session-7",
    "update":{"sessionUpdate":"agent_message_chunk","content":{
        "type":"text","text":"Context restored."
    }}
}})
send({"jsonrpc":"2.0","id":prompt["id"],"result":{"stopReason":"end_turn"}})
'''
    agent = adapter(script)

    history = await agent.resume_thread("kiro-session-7", tmp_path)
    await agent.send("continue")

    events = [await asyncio.wait_for(agent._events.get(), timeout=1) for _ in range(5)]
    assert agent.thread_id == "kiro-session-7"
    assert agent.model == "kiro-test"
    assert history.transcript == []
    assert [(event.kind, event.text) for event in events if event] == [
        ("user_replay", "Earlier prompt."),
        ("assistant_delta", "Earlier response."),
        ("status", "ready"),
        ("assistant_delta", "Context restored."),
        ("status", "ready"),
    ]
    await agent.stop()


@pytest.mark.asyncio
async def test_acp_resume_waits_for_previous_process_session_lock(
    tmp_path: Path,
) -> None:
    script = r'''
import json, sys

def receive(): return json.loads(sys.stdin.readline())
def send(message): print(json.dumps(message, separators=(",", ":")), flush=True)

initialize = receive()
send({"jsonrpc":"2.0","id":initialize["id"],"result":{
    "protocolVersion":1,"agentCapabilities":{"loadSession":True}
}})
first_load = receive()
send({"jsonrpc":"2.0","id":first_load["id"],"error":{
    "code":-32603,"message":"Internal error",
    "data":"Failed to start session: Session is active in another process (PID 7)"
}})
second_load = receive()
send({"jsonrpc":"2.0","id":second_load["id"],"result":{}})
'''
    agent = adapter(script)

    await agent.resume_thread("kiro-session-8", tmp_path)

    assert agent.thread_id == "kiro-session-8"
    await agent.stop()


@pytest.mark.asyncio
async def test_acp_interrupt_uses_session_cancel_notification(tmp_path: Path) -> None:
    script = r'''
import json, sys

def receive(): return json.loads(sys.stdin.readline())
def send(message): print(json.dumps(message, separators=(",", ":")), flush=True)

initialize = receive()
send({"jsonrpc":"2.0","id":initialize["id"],"result":{
    "protocolVersion":1,"agentCapabilities":{"loadSession":True}
}})
new_session = receive()
send({"jsonrpc":"2.0","id":new_session["id"],"result":{"sessionId":"cancel-me"}})
cancel = receive()
assert cancel == {"jsonrpc":"2.0","method":"session/cancel","params":{
    "sessionId":"cancel-me"
}}
'''
    agent = adapter(script)
    await agent.start(tmp_path)

    await agent.interrupt_turn()
    await asyncio.wait_for(agent.process.wait(), timeout=1)
    assert agent.capabilities.load_session is True
    await agent.stop()
