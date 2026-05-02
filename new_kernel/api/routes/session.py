"""Session snapshot endpoint."""

from __future__ import annotations

import importlib
from typing import Any

from fastapi import APIRouter, Query, Request

from ...contracts import ApiEnvelope, ChatMode, ErrorStage, SessionSnapshotData
from ..dependencies import call_maybe_async, get_runtime, get_session
from ..envelope import success


router = APIRouter(prefix="/api/v4/session", tags=["session"])


@router.get(
    "",
    response_model=ApiEnvelope[SessionSnapshotData],
    response_model_exclude_none=True,
)
async def get_session_snapshot(
    request: Request,
    session_id: str = Query(min_length=1),
) -> ApiEnvelope[SessionSnapshotData]:
    runtime = get_runtime(request)
    session = await get_session(runtime, session_id, stage=ErrorStage.IDLE)
    snapshot = await _build_snapshot(session)
    return success(snapshot, session_id=session_id)


async def _build_snapshot(session: Any) -> SessionSnapshotData:
    builder = _find_snapshot_builder()
    if builder is not None:
        result = await call_maybe_async(builder, session)
        if isinstance(result, SessionSnapshotData):
            return result
        return SessionSnapshotData.model_validate(result)

    return SessionSnapshotData(
        session_id=getattr(session, "session_id", None),
        repository=getattr(session, "repository", None),
        agent_status=getattr(session, "agent_status", None),
        parse_log=list(getattr(session, "parse_log", []) or []),
        messages=list(getattr(session, "messages", []) or []),
        current_code=getattr(session, "current_code", None),
        mode=getattr(session, "mode", ChatMode.CHAT) or ChatMode.CHAT,
    )


def _find_snapshot_builder() -> Any | None:
    try:
        module = importlib.import_module("...session.snapshot", package=__package__)
    except ImportError:
        return None
    for name in ("build_snapshot", "snapshot_session", "create_snapshot"):
        builder = getattr(module, name, None)
        if callable(builder):
            return builder
    return None
