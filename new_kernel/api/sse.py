"""SSE response adapter.

Only this module serializes public ``SseEvent`` models into text/event-stream.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request
from fastapi.responses import StreamingResponse

from ..contracts import RepoTutorSseEvent


EventFilter = Callable[[RepoTutorSseEvent], bool]


def sse_response(
    event_bus: Any,
    request: Request,
    *,
    event_filter: EventFilter | None = None,
    heartbeat_seconds: float = 15.0,
) -> StreamingResponse:
    return StreamingResponse(
        _event_stream(
            event_bus,
            request,
            event_filter=event_filter,
            heartbeat_seconds=heartbeat_seconds,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _event_stream(
    event_bus: Any,
    request: Request,
    *,
    event_filter: EventFilter | None,
    heartbeat_seconds: float,
):
    subscription = await _maybe_await(event_bus.subscribe())
    try:
        if hasattr(subscription, "__aiter__"):
            async for event in subscription:
                if await request.is_disconnected():
                    break
                if event_filter is None or event_filter(event):
                    yield encode_sse_event(event)
            return

        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(subscription.get(), timeout=heartbeat_seconds)
            except TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if event_filter is None or event_filter(event):
                yield encode_sse_event(event)
    finally:
        unsubscribe = getattr(event_bus, "unsubscribe", None)
        if callable(unsubscribe):
            await _maybe_await(unsubscribe(subscription))


def encode_sse_event(event: RepoTutorSseEvent) -> str:
    event_type = getattr(event, "event_type")
    event_name = getattr(event_type, "value", str(event_type))
    return f"event: {event_name}\ndata: {_event_json(event)}\n\n"


def _event_json(event: RepoTutorSseEvent) -> str:
    if hasattr(event, "model_dump_json"):
        return event.model_dump_json()
    if hasattr(event, "model_dump"):
        return json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
    return json.dumps(event, ensure_ascii=False, default=str)


async def _maybe_await(value: Any | Awaitable[Any]) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


__all__ = ["encode_sse_event", "sse_response"]
