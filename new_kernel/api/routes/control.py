"""Run control endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ...contracts import (
    AgentStatus,
    ApiEnvelope,
    CancelRunData,
    CancelRunRequest,
    ErrorCode,
    ErrorStage,
)
from ..dependencies import (
    call_maybe_async,
    get_runtime,
    get_session,
    get_session_id,
    get_session_id_header,
    require_dependency,
)
from ..envelope import success
from ..errors import ApiModuleError, api_error, error_from_dependency_exception


router = APIRouter(prefix="/api/v4/control", tags=["control"])


@router.post(
    "/cancel",
    response_model=ApiEnvelope[CancelRunData],
    response_model_exclude_none=True,
)
async def cancel_run(
    payload: CancelRunRequest,
    request: Request,
) -> ApiEnvelope[CancelRunData]:
    runtime = get_runtime(request)
    session_id = get_session_id_header(request)
    session = await get_session(runtime, session_id, stage=ErrorStage.CHAT)
    turn_runtime = require_dependency(runtime, "turn_runtime", stage=ErrorStage.CHAT)
    try:
        result = await _cancel(turn_runtime, session=session, payload=payload)
    except Exception as exc:
        raise error_from_dependency_exception(
            exc,
            stage=ErrorStage.CHAT,
            message="取消当前任务失败。",
        ) from exc
    data = _coerce_cancel_data(result, session=session)
    return success(data, session_id=session_id)


async def _cancel(turn_runtime: Any, *, session: Any, payload: CancelRunRequest) -> Any:
    method = getattr(turn_runtime, "cancel", None)
    if method is None:
        raise ApiModuleError(
            api_error(
                error_code=ErrorCode.INVALID_STATE,
                message="TurnRuntime 未提供取消接口。",
                retryable=False,
                stage=ErrorStage.CHAT,
                internal_detail="turn runtime missing cancel method",
            ),
            status_code=500,
            session_id=get_session_id(session),
        )
    return await call_maybe_async(method, state=session, reason=payload.reason)


def _coerce_cancel_data(result: Any, *, session: Any) -> CancelRunData:
    if isinstance(result, CancelRunData):
        return result
    if isinstance(result, bool):
        status = getattr(session, "agent_status", None)
        if isinstance(status, AgentStatus):
            return CancelRunData(
                cancelled=result,
                session_id=get_session_id(session),
                agent_status=status,
            )
    try:
        return CancelRunData.model_validate(result)
    except Exception as exc:
        raise ApiModuleError(
            api_error(
                error_code=ErrorCode.INVALID_STATE,
                message="TurnRuntime 返回了无效取消结果。",
                retryable=False,
                stage=ErrorStage.CHAT,
                internal_detail=f"unexpected cancel result: {type(result).__name__}",
            ),
            status_code=500,
            session_id=get_session_id(session),
        ) from exc
