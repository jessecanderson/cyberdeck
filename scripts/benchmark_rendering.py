"""Measure large transcript and operation rendering without setting a flaky CI limit."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from time import perf_counter

from cyberdeck.app import CyberdeckApp
from cyberdeck.domain import (
    AgentStatus,
    OperationEntry,
    OperationState,
    TranscriptEntry,
)


async def benchmark(messages: int, operations: int) -> None:
    app = CyberdeckApp(skip_boot=True)
    async with app.run_test(size=(160, 50)) as pilot:
        state = app.manager.register("benchmark", Path.cwd(), status=AgentStatus.READY)
        state.transcript.extend(
            TranscriptEntry(
                "assistant" if index % 2 else "user",
                f"message {index}\n" + ("payload " * 20),
            )
            for index in range(messages)
        )
        state.operations.extend(
            OperationEntry(
                "commandExecution",
                f"operation {index}",
                OperationState.SUCCEEDED,
            )
            for index in range(operations)
        )
        await app.present_agent(state)
        started = perf_counter()
        app._render_active(follow_end=False)
        await pilot.pause()
        elapsed = perf_counter() - started
        print(f"messages={messages} operations={operations} render_seconds={elapsed:.4f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--messages", type=int, default=1000)
    parser.add_argument("--operations", type=int, default=500)
    args = parser.parse_args()
    asyncio.run(benchmark(args.messages, args.operations))


if __name__ == "__main__":
    main()
