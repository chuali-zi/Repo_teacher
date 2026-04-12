from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from backend.contracts.domain import UserFacingErrorException
from backend.contracts.enums import CleanupStatus, ErrorCode, RepoSourceType
from backend.m1_repo_access import access_repository
from backend.m1_repo_access.github_repo_cloner import (
    GIT_CLONE_TIMEOUT_SECONDS,
    clone_public_github_repository,
)
from backend.m1_repo_access.input_validator import classify_repo_input
from backend.m1_repo_access.local_repo_accessor import access_local_repository
from backend.security.safety import build_default_read_policy


def test_classify_repo_input_normalizes_public_github_url() -> None:
    result = classify_repo_input("https://github.com/openai/example.git/")

    assert result.is_valid is True
    assert result.input_kind == "github_url"
    assert result.normalized_input == "https://github.com/openai/example"


def test_access_local_repository_returns_verified_context(tmp_path: Path) -> None:
    read_policy = build_default_read_policy()

    context = access_local_repository(str(tmp_path), read_policy)

    assert context.source_type == RepoSourceType.LOCAL_PATH
    assert context.root_path == str(tmp_path.resolve())
    assert context.access_verified is True
    assert context.read_policy == read_policy
    assert context.is_temp_dir is False


def test_access_local_repository_rejects_missing_path(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing-repo"

    with pytest.raises(UserFacingErrorException) as exc_info:
        access_local_repository(str(missing_path), build_default_read_policy())

    assert exc_info.value.error.error_code == ErrorCode.LOCAL_PATH_NOT_FOUND


def test_access_repository_rejects_invalid_github_url() -> None:
    with pytest.raises(UserFacingErrorException) as exc_info:
        access_repository("https://github.com/openai", build_default_read_policy())

    assert exc_info.value.error.error_code == ErrorCode.GITHUB_URL_INVALID


def test_clone_public_github_repository_returns_temp_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["timeout"] = kwargs["timeout"]
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    context, temp_resources = clone_public_github_repository(
        "https://github.com/openai/example",
        build_default_read_policy(),
    )

    assert captured["command"] == [
        "git",
        "clone",
        "--depth=1",
        "https://github.com/openai/example",
        context.root_path,
    ]
    assert captured["timeout"] == GIT_CLONE_TIMEOUT_SECONDS
    assert context.source_type == RepoSourceType.GITHUB_URL
    assert context.display_name == "openai/example"
    assert context.access_verified is True
    assert temp_resources.clone_dir == context.root_path
    assert temp_resources.cleanup_required is True
    assert temp_resources.cleanup_status == CleanupStatus.PENDING


def test_clone_public_github_repository_maps_inaccessible_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(
            returncode=128,
            cmd=command,
            stderr="remote: Repository not found.",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(UserFacingErrorException) as exc_info:
        clone_public_github_repository(
            "https://github.com/openai/example",
            build_default_read_policy(),
        )

    assert exc_info.value.error.error_code == ErrorCode.GITHUB_REPO_INACCESSIBLE


def test_clone_public_github_repository_maps_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(UserFacingErrorException) as exc_info:
        clone_public_github_repository(
            "https://github.com/openai/example",
            build_default_read_policy(),
        )

    assert exc_info.value.error.error_code == ErrorCode.GIT_CLONE_TIMEOUT
