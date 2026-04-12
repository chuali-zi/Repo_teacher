from __future__ import annotations

import re
from pathlib import PureWindowsPath

from backend.contracts.dto import ValidateRepoData

GITHUB_URL_PATTERN = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)


def classify_repo_input(input_value: str) -> ValidateRepoData:
    value = input_value.strip()
    if not value:
        return _invalid()
    if GITHUB_URL_PATTERN.match(value):
        return ValidateRepoData(
            input_kind="github_url",
            is_valid=True,
            normalized_input=value.rstrip("/").removesuffix(".git"),
            message=None,
        )
    if _looks_like_absolute_path(value):
        return ValidateRepoData(
            input_kind="local_path",
            is_valid=True,
            normalized_input=value,
            message=None,
        )
    return _invalid()


def _looks_like_absolute_path(value: str) -> bool:
    return PureWindowsPath(value).is_absolute() or value.startswith("/")


def _invalid() -> ValidateRepoData:
    return ValidateRepoData(
        input_kind="unknown",
        is_valid=False,
        normalized_input=None,
        message="请输入本地仓库绝对路径或 https://github.com/owner/repo 格式的公开仓库 URL",
    )

