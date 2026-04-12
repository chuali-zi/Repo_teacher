from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from backend.contracts.domain import (
    ReadPolicySnapshot,
    RepositoryContext,
    TempResourceSet,
    UserFacingError,
    UserFacingErrorException,
)
from backend.contracts.enums import CleanupStatus, ErrorCode, RepoSourceType, SessionStatus

GITHUB_URL_PATTERN = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)
GIT_CLONE_TIMEOUT_SECONDS = 30


def clone_public_github_repository(
    github_url: str,
    read_policy: ReadPolicySnapshot,
) -> tuple[RepositoryContext, TempResourceSet]:
    match = GITHUB_URL_PATTERN.match(github_url.strip())
    if match is None:
        raise UserFacingErrorException(
            UserFacingError(
                error_code=ErrorCode.GITHUB_URL_INVALID,
                message="请输入 https://github.com/owner/repo 格式的公开仓库 URL",
                retryable=True,
                stage=SessionStatus.ACCESSING,
                input_preserved=bool(github_url),
            )
        )

    normalized_url = github_url.rstrip("/").removesuffix(".git")
    owner = match.group("owner")
    name = match.group("repo")
    clone_dir = Path(tempfile.mkdtemp(prefix="repo_tutor_clone_"))

    try:
        subprocess.run(
            ["git", "clone", "--depth=1", normalized_url, str(clone_dir)],
            capture_output=True,
            text=True,
            check=True,
            timeout=GIT_CLONE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        _cleanup_clone_dir(clone_dir)
        raise UserFacingErrorException(
            UserFacingError(
                error_code=ErrorCode.GIT_CLONE_TIMEOUT,
                message="GitHub 仓库 clone 超时，请稍后重试",
                retryable=True,
                stage=SessionStatus.ACCESSING,
                input_preserved=True,
                internal_detail=f"timeout after {GIT_CLONE_TIMEOUT_SECONDS}s: {exc}",
            )
        ) from exc
    except FileNotFoundError as exc:
        _cleanup_clone_dir(clone_dir)
        raise UserFacingErrorException(
            UserFacingError(
                error_code=ErrorCode.GIT_CLONE_FAILED,
                message="当前环境无法执行 git clone，请稍后重试",
                retryable=True,
                stage=SessionStatus.ACCESSING,
                input_preserved=True,
                internal_detail=str(exc),
            )
        ) from exc
    except subprocess.CalledProcessError as exc:
        _cleanup_clone_dir(clone_dir)
        stderr = (exc.stderr or "").strip()
        error_code = ErrorCode.GITHUB_REPO_INACCESSIBLE if _is_repo_inaccessible(stderr) else ErrorCode.GIT_CLONE_FAILED
        message = (
            "GitHub 仓库不可访问，请确认仓库存在且为公开仓库"
            if error_code == ErrorCode.GITHUB_REPO_INACCESSIBLE
            else "GitHub 仓库 clone 失败，请稍后重试"
        )
        raise UserFacingErrorException(
            UserFacingError(
                error_code=error_code,
                message=message,
                retryable=True,
                stage=SessionStatus.ACCESSING,
                input_preserved=True,
                internal_detail=stderr or str(exc),
            )
        ) from exc

    resolved_path = clone_dir.resolve()
    repository = RepositoryContext(
        repo_id=_new_repo_id(),
        source_type=RepoSourceType.GITHUB_URL,
        display_name=f"{owner}/{name}",
        input_value=github_url,
        root_path=str(resolved_path),
        is_temp_dir=True,
        owner=owner,
        name=name,
        branch_or_ref=None,
        access_verified=True,
        read_policy=read_policy,
    )
    temp_resources = TempResourceSet(
        clone_dir=str(resolved_path),
        cleanup_required=True,
        cleanup_status=CleanupStatus.PENDING,
    )
    return repository, temp_resources


def _cleanup_clone_dir(clone_dir: Path) -> None:
    shutil.rmtree(clone_dir, ignore_errors=True)


def _is_repo_inaccessible(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(
        marker in lowered
        for marker in (
            "repository not found",
            "not found",
            "authentication failed",
            "could not read username",
            "access denied",
            "permission denied",
        )
    )


def _new_repo_id() -> str:
    return f"repo_{uuid4().hex[:12]}"
