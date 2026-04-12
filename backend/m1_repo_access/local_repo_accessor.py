from __future__ import annotations

from pathlib import Path, PurePath, PureWindowsPath
from uuid import uuid4

from backend.contracts.domain import (
    ReadPolicySnapshot,
    RepositoryContext,
    UserFacingError,
    UserFacingErrorException,
)
from backend.contracts.enums import ErrorCode, RepoSourceType, SessionStatus


def access_local_repository(input_value: str, read_policy: ReadPolicySnapshot) -> RepositoryContext:
    path = Path(input_value)
    _assert_local_input_is_safe(input_value)

    resolved_path = path.resolve(strict=False)
    if not resolved_path.exists():
        raise UserFacingErrorException(
            _local_error(
                ErrorCode.LOCAL_PATH_NOT_FOUND,
                "本地仓库路径不存在，请检查后重试",
                input_value,
            )
        )
    if not resolved_path.is_dir():
        raise UserFacingErrorException(
            _local_error(
                ErrorCode.LOCAL_PATH_NOT_DIRECTORY,
                "本地仓库路径不是目录，请输入仓库根目录",
                input_value,
            )
        )

    try:
        next(resolved_path.iterdir(), None)
    except PermissionError as exc:
        raise UserFacingErrorException(
            _local_error(
                ErrorCode.LOCAL_PATH_NOT_READABLE,
                "本地仓库目录不可读，请检查权限后重试",
                input_value,
                internal_detail=str(exc),
            )
        ) from exc

    return RepositoryContext(
        repo_id=_new_repo_id(),
        source_type=RepoSourceType.LOCAL_PATH,
        display_name=resolved_path.name or resolved_path.anchor,
        input_value=input_value,
        root_path=str(resolved_path),
        is_temp_dir=False,
        owner=None,
        name=resolved_path.name or resolved_path.anchor,
        branch_or_ref=None,
        access_verified=True,
        read_policy=read_policy,
    )


def _assert_local_input_is_safe(input_value: str) -> None:
    path = Path(input_value)
    if not (path.is_absolute() or PureWindowsPath(input_value).is_absolute() or input_value.startswith("/")):
        raise UserFacingErrorException(
            _local_error(
                ErrorCode.PATH_ESCAPE_DETECTED,
                "请输入本地仓库绝对路径",
                input_value,
            )
        )

    if ".." in PurePath(input_value).parts:
        raise UserFacingErrorException(
            _local_error(
                ErrorCode.PATH_ESCAPE_DETECTED,
                "检测到路径越界，请直接输入仓库绝对路径",
                input_value,
            )
        )


def _new_repo_id() -> str:
    return f"repo_{uuid4().hex[:12]}"


def _local_error(
    error_code: ErrorCode,
    message: str,
    input_value: str,
    *,
    internal_detail: str | None = None,
) -> UserFacingError:
    return UserFacingError(
        error_code=error_code,
        message=message,
        retryable=error_code != ErrorCode.PATH_ESCAPE_DETECTED,
        stage=SessionStatus.ACCESSING,
        input_preserved=bool(input_value),
        internal_detail=internal_detail,
    )
