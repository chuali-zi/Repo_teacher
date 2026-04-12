from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

from fastapi.responses import StreamingResponse

from backend.contracts.domain import UserFacingError
from backend.contracts.dto import ErrorEvent, UserFacingErrorDto
from backend.contracts.enums import ClientView, RuntimeEventType
from backend.contracts.sse import encode_sse_stream
from backend.m5_session import session_service
from backend.m5_session.state_machine import view_for_status


def _event_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def _single_error_event(event: ErrorEvent) -> AsyncIterator[ErrorEvent]:
    yield event


def error_sse_response(session_id: str | None, error: UserFacingError) -> StreamingResponse:
    active_session = session_service.store.active_session
    status = active_session.status if active_session else error.stage
    sub_status = active_session.conversation.sub_status if active_session else None
    event = ErrorEvent(
        event_id=_event_id("evt"),
        event_type=RuntimeEventType.ERROR,
        session_id=session_id
        or (active_session.session_id if active_session else "unknown_session"),
        occurred_at=_utc_now(),
        error=UserFacingErrorDto.from_domain(error),
        status=status,
        sub_status=sub_status,
        view=view_for_status(status, sub_status) if active_session else ClientView.INPUT,
    )
    return StreamingResponse(
        encode_sse_stream(_single_error_event(event)),
        media_type="text/event-stream; charset=utf-8",
    )
