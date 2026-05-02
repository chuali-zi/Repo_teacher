"""Sidecar term explanation endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ...contracts import (
    ApiEnvelope,
    ErrorCode,
    ErrorStage,
    SidecarExplainData,
    SidecarExplainRequest,
)
from ..dependencies import call_maybe_async, get_runtime, get_session, require_dependency
from ..envelope import success
from ..errors import ApiModuleError, api_error, error_from_dependency_exception


router = APIRouter(prefix="/api/v4/sidecar", tags=["sidecar"])


@router.post(
    "/explain",
    response_model=ApiEnvelope[SidecarExplainData],
    response_model_exclude_none=True,
)
async def explain_term(
    payload: SidecarExplainRequest,
    request: Request,
) -> ApiEnvelope[SidecarExplainData]:
    runtime = get_runtime(request)
    explainer = require_dependency(runtime, "sidecar_explainer", stage=ErrorStage.SIDECAR)
    session = None
    if payload.session_id:
        session = await get_session(runtime, payload.session_id, stage=ErrorStage.SIDECAR)

    try:
        result = await _call_explainer(explainer, payload=payload, session=session)
    except Exception as exc:
        raise error_from_dependency_exception(
            exc,
            stage=ErrorStage.SIDECAR,
            default_code=ErrorCode.LLM_API_FAILED,
            message="术语解释失败，请稍后重试。",
        ) from exc

    data = _coerce_explain_data(result)
    return success(data, session_id=payload.session_id)


async def _call_explainer(explainer: Any, *, payload: SidecarExplainRequest, session: Any) -> Any:
    method = getattr(explainer, "process", None) or getattr(explainer, "explain", None)
    if method is None:
        raise ApiModuleError(
            api_error(
                error_code=ErrorCode.INVALID_STATE,
                message="SidecarExplainer 未提供 process 接口。",
                retryable=False,
                stage=ErrorStage.SIDECAR,
                internal_detail="sidecar explainer missing process/explain",
            ),
            status_code=500,
            session_id=payload.session_id,
        )
    attempts = (
        ((), {"request": payload, "session": session}),
        ((), {"payload": payload, "session": session}),
        ((payload,), {}),
    )
    last_error: TypeError | None = None
    for args, kwargs in attempts:
        try:
            return await call_maybe_async(method, *args, **kwargs)
        except TypeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise RuntimeError("unreachable")


def _coerce_explain_data(result: Any) -> SidecarExplainData:
    if isinstance(result, SidecarExplainData):
        return result
    try:
        return SidecarExplainData.model_validate(result)
    except Exception as exc:
        raise ApiModuleError(
            api_error(
                error_code=ErrorCode.INVALID_STATE,
                message="SidecarExplainer 返回了无效结果。",
                retryable=False,
                stage=ErrorStage.SIDECAR,
                internal_detail=f"unexpected sidecar result: {type(result).__name__}",
            ),
            status_code=500,
        ) from exc
