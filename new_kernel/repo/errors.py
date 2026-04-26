# repo 模块错误协议：RepoModuleError 异常 + repo_api_error 工厂，把仓库接入阶段的失败统一打包成 contracts.ApiError(stage=REPO_PARSE)。
from __future__ import annotations

from dataclasses import dataclass

from ..contracts import ApiError, ErrorCode, ErrorStage


@dataclass(frozen=True)
class RepoModuleError(Exception):
    error: ApiError

    def __str__(self) -> str:
        return self.error.message


def repo_api_error(
    *,
    error_code: ErrorCode,
    message: str,
    retryable: bool,
    internal_detail: str | None = None,
) -> ApiError:
    return ApiError(
        error_code=error_code,
        message=message,
        retryable=retryable,
        stage=ErrorStage.REPO_PARSE,
        input_preserved=True,
        internal_detail=internal_detail,
    )
