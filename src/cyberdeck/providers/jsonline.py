"""Shared, protocol-neutral JSON-lines framing for stdio adapters."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any


def encode_message(message: Mapping[str, Any]) -> bytes:
    """Encode one compact JSON object with its required line delimiter."""
    return json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"


def decode_message(
    line: bytes,
    *,
    protocol: str,
    error_type: type[RuntimeError],
) -> dict[str, Any]:
    """Decode and validate one JSON-lines protocol object."""
    try:
        message = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise error_type(f"Malformed {protocol} message: {exc}") from exc
    if not isinstance(message, dict):
        raise error_type(f"{protocol} message must be a JSON object")
    return message


def cancel_pending(pending: Mapping[object, asyncio.Future[Any]]) -> None:
    """Cancel every unresolved request during intentional shutdown."""
    for future in pending.values():
        if not future.done():
            future.cancel()


def fail_pending(pending: Mapping[object, asyncio.Future[Any]], error: BaseException) -> None:
    """Fail every unresolved request when the transport is lost."""
    for future in pending.values():
        if not future.done():
            future.set_exception(error)


def cancel_tasks(*tasks: asyncio.Task[None] | None) -> None:
    for task in tasks:
        if task:
            task.cancel()
