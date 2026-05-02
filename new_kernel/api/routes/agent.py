"""Agent status endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from ...contracts import AgentStatus, ApiEnvelope, ErrorCode, ErrorStage
from ..dependencies import get_runtime, get_session
from ..envelope import success
from ..errors import ApiModuleError, api_error


router = APIRouter(prefix="/api/v4/agent", tags=["agent"])


@router.get(
    "/status",
    response_model=ApiEnvelope[AgentStatus],
    response_model_exclude_none=True,
)
async def get_agent_status(
    request: Request,
    session_id: str = Query(min_length=1),
) -> ApiEnvelope[AgentStatus]:
    runtime = get_runtime(request)
    session = await get_session(runtime, session_id, stage=ErrorStage.IDLE)
    agent_status = getattr(session, "agent_status", None)
    if not isinstance(agent_status, AgentStatus):
        raise ApiModuleError(
            api_error(
                error_code=ErrorCode.INVALID_STATE,
                message="当前会话还没有可用的 agent 状态。",
                retryable=True,
                stage=ErrorStage.IDLE,
                internal_detail="session.agent_status is missing or invalid",
            ),
            status_code=409,
            session_id=session_id,
        )
    return success(agent_status, session_id=session_id)
