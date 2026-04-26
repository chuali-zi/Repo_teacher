# GithubResolver：把 owner/repo 或 GitHub URL 规范化，用 git ls-remote --symref 校验仓库公开可访问，返回 ResolveGithubUrlData / GithubRepositoryRef。
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Protocol, Sequence

from ..contracts import ErrorCode, GithubRepositoryRef, ResolveGithubUrlData
from .errors import RepoModuleError, repo_api_error


GITHUB_INPUT_RE = re.compile(
    r"^(?:https://github\.com/)?"
    r"(?P<owner>[A-Za-z0-9_.-]+)/"
    r"(?P<repo>[A-Za-z0-9_.-]+?)"
    r"(?:\.git)?/?$"
)
GITHUB_RESOLVE_TIMEOUT_SECONDS = 10


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
class RemoteHead:
    default_branch: str | None
    commit_sha: str | None


class GithubResolver:
    def __init__(
        self,
        *,
        runner: GitCommandRunner | None = None,
        timeout_seconds: int = GITHUB_RESOLVE_TIMEOUT_SECONDS,
    ) -> None:
        self._runner = runner or subprocess.run
        self._timeout_seconds = timeout_seconds

    def resolve(self, input_value: str, *, verify: bool = True) -> ResolveGithubUrlData:
        parsed = parse_github_input(input_value)
        if parsed is None:
            return ResolveGithubUrlData(
                input_kind="unknown",
                is_valid=False,
                message="请输入 https://github.com/owner/repo 格式的公开 GitHub 仓库地址",
            )

        owner, repo, normalized_url = parsed
        default_branch: str | None = None
        if verify:
            try:
                remote = self.inspect_remote_head(normalized_url)
            except RepoModuleError as exc:
                return ResolveGithubUrlData(
                    input_kind="github_url",
                    is_valid=False,
                    normalized_url=normalized_url,
                    owner=owner,
                    repo=repo,
                    display_name=f"{owner}/{repo}",
                    message=exc.error.message,
                )
            default_branch = remote.default_branch

        return ResolveGithubUrlData(
            input_kind="github_url",
            is_valid=True,
            normalized_url=normalized_url,
            owner=owner,
            repo=repo,
            default_branch=default_branch,
            display_name=f"{owner}/{repo}",
            message=None,
        )

    def resolve_ref(
        self,
        input_value: str,
        *,
        branch: str | None = None,
        verify: bool = True,
    ) -> GithubRepositoryRef:
        data = self.resolve(input_value, verify=verify)
        if not data.is_valid or data.normalized_url is None or data.owner is None or data.repo is None:
            error_code = (
                ErrorCode.GITHUB_REPO_INACCESSIBLE
                if data.input_kind == "github_url"
                else ErrorCode.GITHUB_URL_INVALID
            )
            raise RepoModuleError(
                repo_api_error(
                    error_code=error_code,
                    message=data.message
                    or "无法访问该 GitHub 仓库，请确认仓库存在且为公开仓库",
                    retryable=True,
                )
            )

        return GithubRepositoryRef(
            owner=data.owner,
            repo=data.repo,
            normalized_url=data.normalized_url,
            default_branch=data.default_branch,
            resolved_branch=branch or data.default_branch,
            commit_sha=None,
        )

    def inspect_remote_head(self, normalized_url: str) -> RemoteHead:
        try:
            result = self._runner(
                ["git", "ls-remote", "--symref", normalized_url, "HEAD"],
                capture_output=True,
                text=True,
                check=True,
                timeout=self._timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RepoModuleError(
                repo_api_error(
                    error_code=ErrorCode.GITHUB_REPO_INACCESSIBLE,
                    message="GitHub 仓库校验超时，请稍后重试",
                    retryable=True,
                    internal_detail=str(exc),
                )
            ) from exc
        except FileNotFoundError as exc:
            raise RepoModuleError(
                repo_api_error(
                    error_code=ErrorCode.GIT_CLONE_FAILED,
                    message="当前环境无法执行 git，请确认已安装 git 后重试",
                    retryable=True,
                    internal_detail=str(exc),
                )
            ) from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            raise RepoModuleError(
                repo_api_error(
                    error_code=ErrorCode.GITHUB_REPO_INACCESSIBLE,
                    message="GitHub 仓库不可访问，请确认仓库存在且为公开仓库",
                    retryable=True,
                    internal_detail=stderr or str(exc),
                )
            ) from exc

        return parse_remote_head(result.stdout or "")


def parse_github_input(input_value: str) -> tuple[str, str, str] | None:
    candidate = input_value.strip()
    match = GITHUB_INPUT_RE.match(candidate)
    if match is None:
        return None

    owner = match.group("owner")
    repo = match.group("repo").removesuffix(".git")
    if not owner or not repo or owner in {".", ".."} or repo in {".", ".."}:
        return None

    normalized_url = f"https://github.com/{owner}/{repo}"
    return owner, repo, normalized_url


def parse_remote_head(output: str) -> RemoteHead:
    default_branch: str | None = None
    commit_sha: str | None = None
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line.startswith("ref: refs/heads/") and line.endswith("\tHEAD"):
            default_branch = line.removeprefix("ref: refs/heads/").removesuffix("\tHEAD")
            continue
        if line.endswith("\tHEAD"):
            commit_sha = line.split("\t", 1)[0] or None
    return RemoteHead(default_branch=default_branch, commit_sha=commit_sha)
