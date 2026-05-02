"""Per-session fan-out bus for public SSE event contracts."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Final

from ..contracts import RepoTutorSseEvent


_CLOSE_SENTINEL: Final = object()
_LOGGER = logging.getLogger(__name__)


class EventBus:
    """In-memory fan-out queue for a single session."""

    def __init__(self, *, max_queue_size: int = 256) -> None:
        if max_queue_size < 1:
            raise ValueError("max_queue_size must be at least 1")
        self._max_queue_size = max_queue_size
        self._subscribers: set[asyncio.Queue[RepoTutorSseEvent | object]] = set()
        self._closed = False

    async def emit(self, event: RepoTutorSseEvent) -> None:
        """Publish an event to current subscribers without replaying history."""

        if self._closed:
            return

        for queue in tuple(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                _LOGGER.warning("dropping SSE event for slow subscriber")

    async def publish(self, event: RepoTutorSseEvent) -> None:
        """Compatibility alias for older callers that still say publish."""

        await self.emit(event)

    def subscribe(self) -> "EventSubscription":
        """Return an independent async stream that receives future events only."""

        queue: asyncio.Queue[RepoTutorSseEvent | object] = asyncio.Queue(
            maxsize=self._max_queue_size
        )
        if self._closed:
            _put_close_sentinel(queue)
        else:
            self._subscribers.add(queue)

        return EventSubscription(queue=queue, owner=self)

    async def unsubscribe(self, subscription: object) -> None:
        """Close a subscription returned by subscribe when the caller is done."""

        closer = getattr(subscription, "aclose", None)
        if callable(closer):
            await closer()

    async def close(self) -> None:
        """Close all current subscribers and drop future emissions."""

        if self._closed:
            return
        self._closed = True
        for queue in tuple(self._subscribers):
            _put_close_sentinel(queue)
        self._subscribers.clear()

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def _discard(self, queue: asyncio.Queue[RepoTutorSseEvent | object]) -> None:
        self._subscribers.discard(queue)


class EventSubscription(AsyncIterator[RepoTutorSseEvent]):
    """Single subscriber view returned by EventBus.subscribe."""

    def __init__(
        self,
        *,
        queue: asyncio.Queue[RepoTutorSseEvent | object],
        owner: EventBus,
    ) -> None:
        self._queue = queue
        self._owner = owner
        self._closed = False

    def __aiter__(self) -> "EventSubscription":
        return self

    async def __anext__(self) -> RepoTutorSseEvent:
        if self._closed:
            raise StopAsyncIteration
        item = await self._queue.get()
        if item is _CLOSE_SENTINEL:
            await self.aclose()
            raise StopAsyncIteration
        return item

    async def get(self) -> RepoTutorSseEvent:
        return await self.__anext__()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._owner._discard(self._queue)


def _put_close_sentinel(queue: asyncio.Queue[RepoTutorSseEvent | object]) -> None:
    while True:
        try:
            queue.put_nowait(_CLOSE_SENTINEL)
            return
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                continue


__all__ = ["EventBus", "EventSubscription"]
