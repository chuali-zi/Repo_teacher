"""Path hardening helpers for read-only repository tools."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Iterable


MAX_FILE_SIZE_BYTES = 1_000_000
"""Default max size accepted by read-only tools for a single file."""

SENSITIVE_FILENAMES: set[str] = {
    ".env",
    ".env.local",
    ".env.development",
    ".env.production",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "secrets",
}

SENSITIVE_NAME_MARKERS: tuple[str, ...] = (
    "secret",
    "secrets",
    "credential",
    "credentials",
    "private_key",
)

SENSITIVE_EXTENSIONS: set[str] = {".pem", ".key", ".p12", ".pfx", ".crt", ".cer"}

SENSITIVE_DIRECTORY_SEGMENTS = {".git", ".svn", ".hg"}

BINARY_EXTENSIONS: set[str] = {
    ".7z",
    ".a",
    ".avi",
    ".bin",
    ".bmp",
    ".class",
    ".dll",
    ".dmg",
    ".doc",
    ".docx",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".mov",
    ".mp3",
    ".mp4",
    ".o",
    ".obj",
    ".pdf",
    ".png",
    ".pyc",
    ".rar",
    ".so",
    ".tar",
    ".webp",
    ".woff",
    ".woff2",
    ".xls",
    ".xlsx",
    ".zip",
}


def resolve_under_root(path: str | Path, repo_root: str | Path) -> Path:
    """
    Resolve `path` under `repo_root` and reject traversal outside the root.

    The result is a normalized absolute path that must be within `repo_root`.
    """
    root = Path(repo_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"repo_root is not a directory: {root}")

    candidate = (root / Path(path)).resolve(strict=False)
    if not _is_within_root(candidate, root):
        raise ValueError(f"path escapes repository root: {path}")

    if _contains_symlink(candidate, root):
        raise ValueError(f"path contains symlink component: {path}")

    return candidate


def is_sensitive_file(path: str | Path, *, max_file_size_bytes: int | None = None) -> bool:
    """
    Return True when a path must be blocked by read tools.

    Checks include sensitive names, sensitive segments, binary types, and
    optional oversized files.
    """
    parts = _path_parts(path)
    if not parts:
        return True

    if ".." in parts:
        return True

    filename = parts[-1]
    extension = Path(filename).suffix.lower()
    filename_lower = filename.lower()

    if any(part in SENSITIVE_DIRECTORY_SEGMENTS or part == "secrets" for part in parts):
        return True
    if filename_lower in SENSITIVE_FILENAMES:
        return True
    if extension in SENSITIVE_EXTENSIONS:
        return True
    if any(_contains_marker(part, SENSITIVE_NAME_MARKERS) for part in parts):
        return True
    if extension in BINARY_EXTENSIONS:
        return True
    if extension == ".lock":
        return True

    if max_file_size_bytes is None:
        return False
    return _is_large_file(path, max_file_size_bytes=max_file_size_bytes)


def _is_within_root(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _contains_symlink(path: Path, root: Path) -> bool:
    current = root
    try:
        rel_parts = path.resolve(strict=False).relative_to(root).parts
    except ValueError:
        return True
    except OSError:
        return True

    for part in rel_parts:
        current = current / part
        try:
            if current.is_symlink():
                return True
        except OSError:
            return True
    return False


def _path_parts(path: str | Path) -> tuple[str, ...]:
    normalized = PurePosixPath(path).as_posix().replace("\\", "/").lstrip("/")
    if not normalized or normalized in {".", "..", "../", "./"}:
        return ()
    parts = [part for part in normalized.split("/") if part and part != "."]
    return tuple(part.lower() for part in parts)


def _contains_marker(part: str, markers: Iterable[str]) -> bool:
    lowered = part.lower()
    return any(marker in lowered for marker in markers)


def _is_large_file(path: str | Path, *, max_file_size_bytes: int) -> bool:
    target = Path(path)
    try:
        return (
            target.exists()
            and target.is_file()
            and target.stat().st_size > max_file_size_bytes
        )
    except OSError:
        return False


__all__ = [
    "MAX_FILE_SIZE_BYTES",
    "resolve_under_root",
    "is_sensitive_file",
    "SENSITIVE_FILENAMES",
    "SENSITIVE_NAME_MARKERS",
    "SENSITIVE_EXTENSIONS",
    "SENSITIVE_DIRECTORY_SEGMENTS",
    "BINARY_EXTENSIONS",
]
