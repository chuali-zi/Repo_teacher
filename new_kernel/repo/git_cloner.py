# GitCloner：用 git CLI 子进程做 shallow clone 到本地缓存目录，超时映射 GIT_CLONE_TIMEOUT、无访问权映射 GITHUB_REPO_INACCESSIBLE，返回 CloneResult。
from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence
from uuid import uuid4

from ..contracts import ErrorCode, GithubRepositoryRef
from .errors import RepoModuleError, repo_api_error


GIT_CLONE_TIMEOUT_SECONDS = 30


class GitCommandRunner(Protocol):
    def __call__(
        self,
        args: Sequence[str],
        *,
        capture_output: bool,
        text: bool,
        check: bool,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        ...


@dataclass(frozen=True)
class CloneResult:
    repo_root: Path
    commit_sha: str | None
    branch: str | None
    is_temp_dir: bool


class GitCloner:
    def __init__(
        self,
        *,
        runner: GitCommandRunner | None = None,
        timeout_seconds: int = GIT_CLONE_TIMEOUT_SECONDS,
        clone_parent: Path | None = None,
    ) -> None:
        self._runner = runner or subprocess.run
        self._timeout_seconds = timeout_seconds
        self._clone_parent = clone_parent

    def clone(
        self,
        ref: GithubRepositoryRef,
        *,
        branch: str | None = None,
        destination_root: Path | None = None,
    ) -> CloneResult:
        clone_branch = branch or ref.resolved_branch
        target_dir, is_temp_dir = self._make_target_dir(ref, destination_root)
        command = ["git", "clone", "--depth=1"]
        if clone_branch:
            command.extend(["--branch", clone_branch])
        command.extend([ref.normalized_url, str(target_dir)])

        try:
            self._runner(
                command,
                capture_output=True,
                text=True,
                check=True,
                timeout=self._timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            _cleanup_clone_dir(target_dir)
            raise RepoModuleError(
                repo_api_error(
                    error_code=ErrorCode.GIT_CLONE_TIMEOUT,
                    message="GitHub 仓库 clone 超时，请稍后重试",
                    retryable=True,
                    internal_detail=f"timeout after {self._timeout_seconds}s: {exc}",
                )
            ) from exc
        except FileNotFoundError as exc:
            _cleanup_clone_dir(target_dir)
            raise RepoModuleError(
                repo_api_error(
                    error_code=ErrorCode.GIT_CLONE_FAILED,
                    message="当前环境无法执行 git clone，请确认已安装 git 后重试",
                    retryable=True,
                    internal_detail=str(exc),
                )
            ) from exc
        except subprocess.CalledProcessError as exc:
            _cleanup_clone_dir(target_dir)
            stderr = (exc.stderr or "").strip()
            error_code = (
                ErrorCode.GITHUB_REPO_INACCESSIBLE
                if _is_repo_inaccessible(stderr)
                else ErrorCode.GIT_CLONE_FAILED
            )
            message = (
                "GitHub 仓库不可访问，请确认仓库存在且为公开仓库"
                if error_code == ErrorCode.GITHUB_REPO_INACCESSIBLE
                else "GitHub 仓库 clone 失败，请稍后重试"
            )
            raise RepoModuleError(
                repo_api_error(
                    error_code=error_code,
                    message=message,
                    retryable=True,
                    internal_detail=stderr or str(exc),
                )
            ) from exc

        resolved_root = target_dir.resolve(strict=True)
        return CloneResult(
            repo_root=resolved_root,
            commit_sha=self._read_commit_sha(resolved_root),
            branch=clone_branch,
            is_temp_dir=is_temp_dir,
        )

    def _make_target_dir(
        self,
        ref: GithubRepositoryRef,
        destination_root: Path | None,
    ) -> tuple[Path, bool]:
        if destination_root is not None:
            parent = destination_root.expanduser().resolve(strict=False)
            parent.mkdir(parents=True, exist_ok=True)
            safe_name = _safe_dir_name(f"{ref.owner}_{ref.repo}")
            return parent / f"{safe_name}_{uuid4().hex[:8]}", False

        if self._clone_parent is not None:
            parent = self._clone_parent.expanduser().resolve(strict=False)
            parent.mkdir(parents=True, exist_ok=True)
            safe_name = _safe_dir_name(f"{ref.owner}_{ref.repo}")
            return parent / f"{safe_name}_{uuid4().hex[:8]}", False

        return Path(tempfile.mkdtemp(prefix="repo_tutor_clone_")), True

    def _read_commit_sha(self, repo_root: Path) -> str | None:
        try:
            result = self._runner(
                ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
        except (subprocess.SubprocessError, OSError):
            return None
        commit_sha = (result.stdout or "").strip()
        return commit_sha or None


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


def _safe_dir_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)
    return cleaned.strip("_") or "repo"
