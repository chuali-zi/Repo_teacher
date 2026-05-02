"""Helpers for returning the public API envelope."""

from __future__ import annotations

from typing import TypeVar

from ..contracts import ApiEnvelope, ApiError


T = TypeVar("T")


def success(data: T, *, session_id: str | None = None) -> ApiEnvelope[T]:
    return ApiEnvelope[T](ok=True, session_id=session_id, data=data, error=None)


def failure(error: ApiError, *, session_id: str | None = None) -> ApiEnvelope[object]:
    return ApiEnvelope[object](ok=False, session_id=session_id, data=None, error=error)


__all__ = ["failure", "success"]
