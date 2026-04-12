from __future__ import annotations

from pathlib import Path

import pytest

from backend.contracts.domain import UserFacingErrorException
from backend.contracts.enums import ErrorCode
from backend.security.safety import (
    DEFAULT_IGNORE_PATTERNS,
    DEFAULT_SENSITIVE_PATTERNS,
    assert_path_within_repo,
    build_default_read_policy,
    find_sensitive_pattern,
    match_repo_pattern,
    resolve_repo_relative_path,
)


def test_build_default_read_policy_matches_spec_defaults() -> None:
    policy = build_default_read_policy()

    assert policy.read_only is True
    assert policy.allow_exec is False
    assert policy.allow_dependency_install is False
    assert policy.allow_private_github is False
    assert policy.sensitive_patterns == list(DEFAULT_SENSITIVE_PATTERNS)
    assert policy.ignore_patterns == list(DEFAULT_IGNORE_PATTERNS)
    assert policy.max_source_files_full_analysis == 3000


def test_assert_path_within_repo_allows_internal_path(tmp_path: Path) -> None:
    candidate = tmp_path / "backend" / "main.py"

    assert_path_within_repo(tmp_path, candidate)


def test_assert_path_within_repo_rejects_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"

    with pytest.raises(UserFacingErrorException) as exc_info:
        assert_path_within_repo(tmp_path, outside)

    assert exc_info.value.error.error_code == ErrorCode.PATH_ESCAPE_DETECTED


def test_assert_path_within_repo_rejects_symlink_escape(tmp_path: Path) -> None:
    outside_dir = tmp_path.parent / "outside-dir"
    outside_dir.mkdir()
    target = outside_dir / "secret.txt"
    target.write_text("secret", encoding="utf-8")

    link_path = tmp_path / "escape-link"
    try:
        link_path.symlink_to(outside_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not available in this environment")

    with pytest.raises(UserFacingErrorException) as exc_info:
        assert_path_within_repo(tmp_path, link_path / "secret.txt")

    assert exc_info.value.error.error_code == ErrorCode.PATH_ESCAPE_DETECTED


def test_resolve_repo_relative_path_rejects_parent_escape(tmp_path: Path) -> None:
    with pytest.raises(UserFacingErrorException) as exc_info:
        resolve_repo_relative_path(tmp_path, "../secrets.txt")

    assert exc_info.value.error.error_code == ErrorCode.PATH_ESCAPE_DETECTED


@pytest.mark.parametrize(
    ("relative_path", "is_directory", "pattern", "expected"),
    [
        (".env", False, ".env", True),
        ("apps/api/.env.prod", False, ".env.*", True),
        ("config/token_store.json", False, "token*", True),
        ("src/node_modules/pkg/index.js", False, "node_modules/", True),
        ("src/app.py", False, "node_modules/", False),
        ("src/pkg/settings.py", False, "/src/pkg/settings.py", True),
        ("other/src/pkg/settings.py", False, "/src/pkg/settings.py", False),
    ],
)
def test_match_repo_pattern(
    relative_path: str,
    is_directory: bool,
    pattern: str,
    expected: bool,
) -> None:
    assert match_repo_pattern(relative_path, is_directory=is_directory, pattern=pattern) is expected


def test_find_sensitive_pattern_returns_first_matching_rule() -> None:
    assert find_sensitive_pattern("config/token_store.json") == "token*"
    assert find_sensitive_pattern("docs/readme.md") is None
