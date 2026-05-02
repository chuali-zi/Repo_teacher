"""Error mapping and FastAPI exception handlers for the API layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..contracts import ApiError, ErrorCode, ErrorStage
from .envelope import failure


@dataclass(frozen=True)
class ApiModuleError(Exception):
    error: ApiError
    status_code: int = 400
    session_id: str | None = None

    def __str__(self) -> str:
        return self.error.message


def api_error(
    *,
    error_code: ErrorCode,
    message: str,
    retryable: bool,
    stage: ErrorStage,
    input_preserved: bool = True,
    internal_detail: str | None = None,
) -> ApiError:
    return ApiError(
        error_code=error_code,
        message=message,
        retryable=retryable,
        stage=stage,
        input_preserved=input_preserved,
        internal_detail=internal_detail,
    )


def envelope_response(
    error: ApiError,
    *,
    status_code: int,
    session_id: str | None = None,
) -> JSONResponse:
    envelope = failure(error, session_id=session_id)
    return JSONResponse(
        status_code=status_code,
        content=envelope.model_dump(mode="json", exclude_none=True),
    )


def map_unknown_exception(exc: Exception, *, stage: ErrorStage = ErrorStage.IDLE) -> ApiError:
    return api_error(
        error_code=ErrorCode.INVALID_STATE,
        message="服务处理请求时发生内部错误。",
        retryable=True,
        stage=stage,
        internal_detail=f"{exc.__class__.__name__}: {exc}",
    )


async def api_module_error_handler(_: Request, exc: ApiModuleError) -> JSONResponse:
    return envelope_response(exc.error, status_code=exc.status_code, session_id=exc.session_id)


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    error = api_error(
        error_code=ErrorCode.INVALID_REQUEST,
        message="请求参数不符合接口协议。",
        retryable=False,
        stage=ErrorStage.IDLE,
        internal_detail=str(exc.errors()),
    )
    return envelope_response(error, status_code=422)


async def unknown_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    return envelope_response(map_unknown_exception(exc), status_code=500)


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiModuleError, api_module_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unknown_exception_handler)


def error_from_dependency_exception(
    exc: Exception,
    *,
    stage: ErrorStage,
    default_code: ErrorCode = ErrorCode.INVALID_STATE,
    message: str = "请求处理失败。",
    retryable: bool = True,
) -> ApiModuleError:
    candidate = getattr(exc, "error", None)
    if isinstance(candidate, ApiError):
        return ApiModuleError(candidate, status_code=_status_for_error(candidate))
    to_api_error = getattr(exc, "to_api_error", None)
    if callable(to_api_error):
        try:
            candidate = to_api_error(stage=stage)
        except TypeError:
            candidate = None
        if isinstance(candidate, ApiError):
            return ApiModuleError(candidate, status_code=_status_for_error(candidate))
    return ApiModuleError(
        api_error(
            error_code=default_code,
            message=message,
            retryable=retryable,
            stage=stage,
            internal_detail=f"{exc.__class__.__name__}: {exc}",
        ),
        status_code=500,
    )


def _status_for_error(error: ApiError) -> int:
    status_by_code: dict[ErrorCode, int] = {
        ErrorCode.INVALID_REQUEST: 400,
        ErrorCode.GITHUB_URL_INVALID: 400,
        ErrorCode.GITHUB_REPO_INACCESSIBLE: 400,
        ErrorCode.GIT_CLONE_TIMEOUT: 504,
        ErrorCode.GIT_CLONE_FAILED: 502,
        ErrorCode.REPO_SCAN_FAILED: 500,
        ErrorCode.SESSION_NOT_FOUND: 404,
        ErrorCode.INVALID_STATE: 409,
        ErrorCode.LLM_API_FAILED: 502,
        ErrorCode.LLM_API_TIMEOUT: 504,
        ErrorCode.RUN_CANCELLED: 409,
    }
    return status_by_code.get(ErrorCode(error.error_code), 500)


def envelope_payload(data: Any) -> dict[str, Any]:
    if hasattr(data, "model_dump"):
        return data.model_dump(mode="json", exclude_none=True)
    return dict(data)


__all__ = [
    "ApiModuleError",
    "api_error",
    "envelope_response",
    "error_from_dependency_exception",
    "install_exception_handlers",
    "map_unknown_exception",
]
