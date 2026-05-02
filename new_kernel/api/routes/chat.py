"""Main teaching chat endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request, status

from ...contracts import (
    ApiEnvelope,
    ChatMode,
    ErrorCode,
    ErrorStage,
    SendTeachingMessageData,
    SendTeachingMessageRequest,
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
from ..sse import sse_response


router = APIRouter(prefix="/api/v4/chat", tags=["chat"])


@router.post(
    "/messages",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ApiEnvelope[SendTeachingMessageData],
    response_model_exclude_none=True,
)
async def send_chat_message(
    payload: SendTeachingMessageRequest,
    request: Request,
) -> ApiEnvelope[SendTeachingMessageData]:
    runtime = get_runtime(request)
    stage = _stage_for_mode(payload.mode)
    session_id = get_session_id_header(request)
    session = await get_session(runtime, session_id, stage=stage)
    turn_runtime = require_dependency(runtime, "turn_runtime", stage=stage)

    try:
        result = await _start_turn(turn_runtime, session=session, payload=payload)
    except Exception as exc:
        raise error_from_dependency_exception(
            exc,
            stage=stage,
            message="提交教学消息失败。",
        ) from exc

    data = _coerce_turn_data(result)
    return success(data, session_id=session_id)


@router.get("/stream")
async def chat_stream(
    request: Request,
    session_id: str = Query(min_length=1),
    turn_id: str = Query(min_length=1),
):
    runtime = get_runtime(request)
    session = await get_session(runtime, session_id, stage=ErrorStage.CHAT)
    event_bus = _require_event_bus(session)

    def event_filter(event: Any) -> bool:
        event_turn_id = getattr(event, "turn_id", None)
        return event_turn_id is None or event_turn_id == turn_id

    return sse_response(event_bus, request, event_filter=event_filter)


async def _start_turn(turn_runtime: Any, *, session: Any, payload: SendTeachingMessageRequest) -> Any:
    start_turn = getattr(turn_runtime, "start_turn", None)
    if start_turn is None:
        raise ApiModuleError(
            api_error(
                error_code=ErrorCode.INVALID_STATE,
                message="TurnRuntime 未提供 start_turn 接口。",
                retryable=False,
                stage=_stage_for_mode(payload.mode),
                internal_detail="turn_runtime missing start_turn",
            ),
            status_code=500,
            session_id=get_session_id(session),
        )

    return await call_maybe_async(start_turn, state=session, request=payload)


def _coerce_turn_data(result: Any) -> SendTeachingMessageData:
    if isinstance(result, SendTeachingMessageData):
        return result
    try:
        return SendTeachingMessageData.model_validate(result)
    except Exception as exc:
        raise ApiModuleError(
            api_error(
                error_code=ErrorCode.INVALID_STATE,
                message="TurnRuntime 返回了无效结果。",
                retryable=False,
                stage=ErrorStage.CHAT,
                internal_detail=f"unexpected turn result: {type(result).__name__}",
            ),
            status_code=500,
        ) from exc


def _stage_for_mode(mode: ChatMode) -> ErrorStage:
    return ErrorStage.DEEP_RESEARCH if mode == ChatMode.DEEP else ErrorStage.CHAT


def _require_event_bus(session: Any) -> Any:
    event_bus = getattr(session, "event_bus", None)
    if event_bus is None or not callable(getattr(event_bus, "subscribe", None)):
        raise ApiModuleError(
            api_error(
                error_code=ErrorCode.INVALID_STATE,
                message="当前会话没有可订阅的事件流。",
                retryable=True,
                stage=ErrorStage.CHAT,
                internal_detail="session.event_bus missing subscribe",
            ),
            status_code=503,
            session_id=get_session_id(session),
        )
    return event_bus
