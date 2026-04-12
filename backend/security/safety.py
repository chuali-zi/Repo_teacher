from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

from backend.contracts.domain import ReadPolicySnapshot, UserFacingError, UserFacingErrorException
from backend.contracts.enums import ErrorCode, SessionStatus

DEFAULT_SENSITIVE_PATTERNS: tuple[str, ...] = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.crt",
    "id_rsa",
    "id_ed25519",
    "credentials*",
    "secrets*",
    "token*",
)

DEFAULT_IGNORE_PATTERNS: tuple[str, ...] = (
    ".git/",
    ".venv/",
    "venv/",
    "node_modules/",
    "__pycache__/",
    ".pytest_cache/",
    "dist/",
    "build/",
)

def build_default_read_policy() -> ReadPolicySnapshot:
    return ReadPolicySnapshot(
        read_only=True,
        allow_exec=False,
        allow_dependency_install=False,
        allow_private_github=False,
        sensitive_patterns=list(DEFAULT_SENSITIVE_PATTERNS),
        ignore_patterns=list(DEFAULT_IGNORE_PATTERNS),
        max_source_files_full_analysis=3000,
    )


def assert_path_within_repo(repo_root: Path, candidate: Path) -> None:
    root = repo_root.resolve(strict=True)
    resolved_candidate = candidate.resolve(strict=False)
    try:
        resolved_candidate.relative_to(root)
    except ValueError as exc:
        raise UserFacingErrorException(
            UserFacingError(
                error_code=ErrorCode.PATH_ESCAPE_DETECTED,
                message="检测到路径越界，已停止读取该仓库",
                retryable=False,
                stage=SessionStatus.ACCESSING,
                input_preserved=True,
                internal_detail=(
                    f"candidate={resolved_candidate.as_posix()} is outside repo_root={root.as_posix()}"
                ),
            )
        ) from exc


def resolve_repo_relative_path(repo_root: Path, relative_path: str) -> Path:
    safe_relative = PurePosixPath(relative_path)
    if safe_relative.is_absolute() or ".." in safe_relative.parts:
        raise UserFacingErrorException(
            UserFacingError(
                error_code=ErrorCode.PATH_ESCAPE_DETECTED,
                message="检测到路径越界，已停止读取该仓库",
                retryable=False,
                stage=SessionStatus.ACCESSING,
                input_preserved=True,
                internal_detail=f"relative_path={relative_path}",
            )
        )

    candidate = repo_root / safe_relative
    assert_path_within_repo(repo_root, candidate)
    return candidate


def find_sensitive_pattern(
    relative_path: str,
    *,
    is_directory: bool = False,
    patterns: tuple[str, ...] = DEFAULT_SENSITIVE_PATTERNS,
) -> str | None:
    for pattern in patterns:
        if match_repo_pattern(relative_path, is_directory=is_directory, pattern=pattern):
            return pattern
    return None


def match_repo_pattern(relative_path: str, *, is_directory: bool, pattern: str) -> bool:
    normalized_path = relative_path.strip("/")
    normalized_pattern = pattern.strip()
    if not normalized_path or not normalized_pattern:
        return False

    dir_only = normalized_pattern.endswith("/")
    normalized_pattern = normalized_pattern.rstrip("/")

    anchored = normalized_pattern.startswith("/")
    normalized_pattern = normalized_pattern.lstrip("/")
    if not normalized_pattern:
        return False

    if dir_only:
        candidates = [normalized_path] if anchored else suffix_candidates(normalized_path)
        return any(
            fnmatchcase(candidate, normalized_pattern)
            or candidate.startswith(normalized_pattern + "/")
            for candidate in candidates
        )

    if "/" not in normalized_pattern:
        path_parts = PurePosixPath(normalized_path).parts
        return any(fnmatchcase(part, normalized_pattern) for part in path_parts)

    candidates = [normalized_path] if anchored else suffix_candidates(normalized_path)
    return any(fnmatchcase(candidate, normalized_pattern) for candidate in candidates)


def suffix_candidates(relative_path: str) -> list[str]:
    parts = PurePosixPath(relative_path).parts
    return ["/".join(parts[index:]) for index in range(len(parts))]
