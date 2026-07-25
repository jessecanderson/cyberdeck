from datetime import UTC, datetime

from cyberdeck.domain import OperationState, map_history_turns


def test_history_mapping_is_chronological_and_separates_operations() -> None:
    turns = [
        {
            "createdAt": "2026-07-24T14:00:00Z",
            "items": [
                {"type": "agentMessage", "text": "done"},
                {
                    "id": "cmd-1",
                    "type": "commandExecution",
                    "command": "pytest -q",
                    "cwd": "/work",
                    "status": "completed",
                    "exitCode": 0,
                    "aggregatedOutput": "2 passed",
                },
            ],
        },
        {
            "createdAt": "2026-07-24T13:00:00Z",
            "items": [{"type": "userMessage", "content": [{"type": "text", "text": "fix it"}]}],
        },
    ]

    page = map_history_turns(turns, "older")

    assert [(entry.role, entry.text) for entry in page.transcript] == [
        ("user", "fix it"),
        ("assistant", "done"),
    ]
    assert page.transcript[0].created_at < page.transcript[1].created_at
    assert page.operations[0].summary == "pytest -q"
    assert page.operations[0].state is OperationState.SUCCEEDED
    assert page.operations[0].exit_code == 0
    assert page.next_cursor == "older"


def test_unknown_history_items_are_ignored() -> None:
    page = map_history_turns(
        [{"createdAt": datetime.now(UTC), "items": [{"type": "futureThing"}]}]
    )
    assert page.transcript == []
    assert page.operations == []
