"""Cooperative cancellation primitives for a single chat turn."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Literal, TypeAlias


CancelReason: TypeAlias = Literal["user_escape", "new_repo", "manual"]


class CancelledError(Exception):
    """Raised at explicit cancellation checkpoints."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"turn cancelled: {reason}")


@dataclass
class CancellationToken:
    """A cooperative cancellation signal shared with teaching/deep loops."""

    session_id: str
    turn_id: str
    _cancelled: bool = field(default=False, init=False, repr=False)
    _reason: CancelReason | None = field(default=None, init=False, repr=False)
    _event: asyncio.Event = field(
        default_factory=asyncio.Event,
        init=False,
        repr=False,
        compare=False,
    )

    def cancel(self, reason: CancelReason) -> None:
        if reason not in {"user_escape", "new_repo", "manual"}:
            raise ValueError(f"invalid cancellation reason: {reason}")
        if self._cancelled:
            return
        self._cancelled = True
        self._reason = reason
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    @property
    def reason(self) -> CancelReason | None:
        return self._reason

    async def wait(self) -> CancelReason:
        await self._event.wait()
        return self._reason or "manual"

    def raise_if_cancelled(self) -> None:
        if self._cancelled:
            raise CancelledError(self._reason or "manual")


__all__ = ["CancelReason", "CancellationToken", "CancelledError"]
