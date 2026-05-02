"""GitHub input resolution endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ...contracts import (
    ApiEnvelope,
    ErrorCode,
    ErrorStage,
    ResolveGithubUrlData,
    ResolveGithubUrlRequest,
)
from ..dependencies import call_maybe_async, get_runtime, require_dependency
from ..envelope import success
from ..errors import ApiModuleError, api_error


router = APIRouter(prefix="/api/v4/github", tags=["github"])


@router.post(
    "/resolve",
    response_model=ApiEnvelope[ResolveGithubUrlData],
    response_model_exclude_none=True,
)
async def resolve_github_url(
    payload: ResolveGithubUrlRequest,
    request: Request,
) -> ApiEnvelope[ResolveGithubUrlData]:
    runtime = get_runtime(request)
    resolver = require_dependency(runtime, "github_resolver", stage=ErrorStage.REPO_PARSE)
    try:
        data = await call_maybe_async(resolver.resolve, payload.input_value, verify=True)
    except TypeError:
        data = await call_maybe_async(resolver.resolve, payload.input_value)
    except Exception as exc:
        raise ApiModuleError(
            api_error(
                error_code=ErrorCode.GITHUB_REPO_INACCESSIBLE,
                message="GitHub 仓库校验失败，请稍后重试。",
                retryable=True,
                stage=ErrorStage.REPO_PARSE,
                internal_detail=f"{exc.__class__.__name__}: {exc}",
            ),
            status_code=502,
        ) from exc

    if not isinstance(data, ResolveGithubUrlData):
        raise ApiModuleError(
            api_error(
                error_code=ErrorCode.INVALID_STATE,
                message="GitHub 解析器返回了无效结果。",
                retryable=False,
                stage=ErrorStage.REPO_PARSE,
                internal_detail=f"unexpected resolver result: {type(data).__name__}",
            ),
            status_code=500,
        )
    return success(data)
