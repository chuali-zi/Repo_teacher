from __future__ import annotations

from backend.contracts.domain import SessionContext, UserFacingError
from backend.contracts.enums import ErrorCode, SessionStatus


def invalid_request_error(
    active_session: SessionContext | None,
    message: str,
) -> UserFacingError:
    return UserFacingError(
        error_code=ErrorCode.INVALID_REQUEST,
        message=message,
        retryable=True,
        stage=active_session.status if active_session else SessionStatus.IDLE,
        input_preserved=True,
    )


def analysis_failed_error(exc: Exception, *, stage: SessionStatus) -> UserFacingError:
    return UserFacingError(
        error_code=ErrorCode.ANALYSIS_FAILED,
        message="分析过程出错，请重试或尝试其他仓库。",
        retryable=True,
        stage=stage,
        input_preserved=True,
        internal_detail=str(exc),
    )


def llm_failed_error(exc: Exception) -> UserFacingError:
    is_timeout = isinstance(exc, TimeoutError)
    return UserFacingError(
        error_code=ErrorCode.LLM_API_TIMEOUT if is_timeout else ErrorCode.LLM_API_FAILED,
        message=(
            "LLM 调用超时，请稍后重试或缩小问题范围。"
            if is_timeout
            else "LLM 调用失败，请检查 llm_config.json 或稍后重试。"
        ),
        retryable=True,
        stage=SessionStatus.CHATTING,
        input_preserved=True,
        internal_detail=str(exc),
    )
