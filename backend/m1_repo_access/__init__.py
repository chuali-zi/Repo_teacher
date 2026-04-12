"""M1 repository access layer.

Deterministically validates local repositories or clones public GitHub repositories
into a temporary directory without executing repository code.
"""

from pathlib import PureWindowsPath

from backend.contracts.domain import (
    ReadPolicySnapshot,
    RepositoryContext,
    TempResourceSet,
    UserFacingError,
    UserFacingErrorException,
)
from backend.contracts.enums import CleanupStatus, ErrorCode, SessionStatus
from backend.m1_repo_access.github_repo_cloner import clone_public_github_repository
from backend.m1_repo_access.input_validator import classify_repo_input
from backend.m1_repo_access.local_repo_accessor import access_local_repository


def access_repository(
    input_value: str,
    read_policy: ReadPolicySnapshot,
) -> tuple[RepositoryContext, TempResourceSet]:
    validation = classify_repo_input(input_value)
    if not validation.is_valid:
        raise UserFacingErrorException(
            UserFacingError(
                error_code=_invalid_input_error_code(input_value),
                message=validation.message or "请输入本地仓库绝对路径或 GitHub 公开仓库 URL",
                retryable=True,
                stage=SessionStatus.ACCESSING,
                input_preserved=bool(input_value.strip()),
            )
        )

    normalized_input = validation.normalized_input or input_value
    if validation.input_kind == "github_url" and validation.is_valid:
        return clone_public_github_repository(normalized_input, read_policy)

    repository = access_local_repository(normalized_input, read_policy)
    return repository, TempResourceSet(
        clone_dir=None,
        cleanup_required=False,
        cleanup_status=CleanupStatus.NOT_NEEDED,
    )


def _invalid_input_error_code(input_value: str) -> ErrorCode:
    stripped = input_value.strip()
    if stripped.startswith("https://github.com/") or stripped.startswith("http://github.com/"):
        return ErrorCode.GITHUB_URL_INVALID
    if PureWindowsPath(stripped).is_absolute() or stripped.startswith("/"):
        return ErrorCode.PATH_ESCAPE_DETECTED
    return ErrorCode.PATH_ESCAPE_DETECTED


__all__ = ["access_local_repository", "access_repository", "clone_public_github_repository"]
