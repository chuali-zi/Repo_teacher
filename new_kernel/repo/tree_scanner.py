# TreeScanner：遍历 repo_root 文件树，跳过噪声目录 / 敏感文件 / 二进制 / 大文件 / symlink，统计 file_count、识别 primary_language，返回 TreeScanResult。
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from ..contracts import ErrorCode
from .errors import RepoModuleError, repo_api_error


ScanSkipReason = Literal[
    "ignored_directory",
    "sensitive_path",
    "binary_file",
    "large_file",
    "unreadable",
    "symlink",
    "scan_limit",
]

IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    "bower_components",
    "vendor",
    "dist",
    "build",
    "out",
    "target",
    ".next",
    ".nuxt",
    ".cache",
    "coverage",
}

SENSITIVE_FILENAMES = {
    ".env",
    ".env.local",
    ".env.development",
    ".env.production",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}
SENSITIVE_NAME_MARKERS = ("secret", "secrets", "credential", "credentials", "private_key")
SENSITIVE_EXTENSIONS = {".pem", ".key", ".p12", ".pfx", ".crt", ".cer"}
BINARY_EXTENSIONS = {
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
    ".DS_Store".lower(),
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".lockb",
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

LANGUAGE_BY_EXTENSION = {
    ".bash": "Shell",
    ".c": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".cs": "C#",
    ".css": "CSS",
    ".go": "Go",
    ".h": "C/C++",
    ".hpp": "C++",
    ".html": "HTML",
    ".java": "Java",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".json": "JSON",
    ".kt": "Kotlin",
    ".md": "Markdown",
    ".php": "PHP",
    ".py": "Python",
    ".pyi": "Python",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".scala": "Scala",
    ".scss": "SCSS",
    ".sh": "Shell",
    ".sql": "SQL",
    ".swift": "Swift",
    ".toml": "TOML",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".vue": "Vue",
    ".yaml": "YAML",
    ".yml": "YAML",
}
SOURCE_EXTENSIONS = {
    ".bash",
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".php",
    ".py",
    ".pyi",
    ".rb",
    ".rs",
    ".scala",
    ".scss",
    ".sh",
    ".sql",
    ".swift",
    ".ts",
    ".tsx",
    ".vue",
}
ENTRY_FILENAMES = {"Dockerfile", "Makefile", "Justfile", "Rakefile"}


@dataclass(frozen=True)
class ScannedFile:
    path: str
    size_bytes: int
    extension: str | None
    language: str | None
    is_source: bool
    depth: int


@dataclass(frozen=True)
class ScannedDirectory:
    path: str
    depth: int


@dataclass(frozen=True)
class SkippedPath:
    path: str
    reason: ScanSkipReason


@dataclass(frozen=True)
class TreeScanResult:
    repo_root: Path
    files: tuple[ScannedFile, ...]
    directories: tuple[ScannedDirectory, ...]
    skipped: tuple[SkippedPath, ...]
    file_count: int
    primary_language: str | None
    language_counts: dict[str, int]

    @property
    def source_files(self) -> tuple[ScannedFile, ...]:
        return tuple(file for file in self.files if file.is_source)


class TreeScanner:
    def __init__(
        self,
        *,
        max_file_size_bytes: int = 1_000_000,
        max_files: int = 5_000,
    ) -> None:
        self._max_file_size_bytes = max_file_size_bytes
        self._max_files = max_files

    def scan(self, repo_root: str | Path) -> TreeScanResult:
        root = Path(repo_root).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise RepoModuleError(
                repo_api_error(
                    error_code=ErrorCode.REPO_SCAN_FAILED,
                    message="仓库扫描失败：目标路径不是目录",
                    retryable=False,
                    internal_detail=str(root),
                )
            )

        files: list[ScannedFile] = []
        directories: list[ScannedDirectory] = []
        skipped: list[SkippedPath] = []
        self._scan_dir(root, root, files, directories, skipped)
        language_counts = Counter(file.language for file in files if file.language and file.is_source)
        if not language_counts:
            language_counts = Counter(file.language for file in files if file.language)
        primary_language = language_counts.most_common(1)[0][0] if language_counts else None

        return TreeScanResult(
            repo_root=root,
            files=tuple(sorted(files, key=lambda item: item.path)),
            directories=tuple(sorted(directories, key=lambda item: item.path)),
            skipped=tuple(skipped),
            file_count=len(files),
            primary_language=primary_language,
            language_counts=dict(language_counts),
        )

    def _scan_dir(
        self,
        repo_root: Path,
        current_dir: Path,
        files: list[ScannedFile],
        directories: list[ScannedDirectory],
        skipped: list[SkippedPath],
    ) -> None:
        if len(files) >= self._max_files:
            skipped.append(SkippedPath(_relative_path(repo_root, current_dir), "scan_limit"))
            return

        try:
            entries = sorted(current_dir.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
        except OSError:
            skipped.append(SkippedPath(_relative_path(repo_root, current_dir), "unreadable"))
            return

        for entry in entries:
            relative_path = _relative_path(repo_root, entry)
            if entry.is_symlink():
                skipped.append(SkippedPath(relative_path, "symlink"))
                continue
            if entry.is_dir():
                if is_ignored_directory(entry.name) or is_sensitive_path(relative_path):
                    skipped.append(SkippedPath(relative_path, "ignored_directory"))
                    continue
                directories.append(ScannedDirectory(path=relative_path, depth=_depth(relative_path)))
                self._scan_dir(repo_root, entry, files, directories, skipped)
                continue
            if not entry.is_file():
                continue

            scanned_file = self._build_file(repo_root, entry, skipped)
            if scanned_file is not None:
                files.append(scanned_file)

    def _build_file(
        self,
        repo_root: Path,
        file_path: Path,
        skipped: list[SkippedPath],
    ) -> ScannedFile | None:
        relative_path = _relative_path(repo_root, file_path)
        extension = file_path.suffix.lower() or None
        if is_sensitive_path(relative_path):
            skipped.append(SkippedPath(relative_path, "sensitive_path"))
            return None
        if extension in BINARY_EXTENSIONS:
            skipped.append(SkippedPath(relative_path, "binary_file"))
            return None

        try:
            size_bytes = file_path.stat().st_size
        except OSError:
            skipped.append(SkippedPath(relative_path, "unreadable"))
            return None
        if size_bytes > self._max_file_size_bytes:
            skipped.append(SkippedPath(relative_path, "large_file"))
            return None

        language = detect_language(file_path.name, extension)
        return ScannedFile(
            path=relative_path,
            size_bytes=size_bytes,
            extension=extension,
            language=language,
            is_source=is_source_file(file_path.name, extension),
            depth=_depth(relative_path),
        )


def detect_language(filename: str, extension: str | None) -> str | None:
    if filename in ENTRY_FILENAMES:
        return "Build"
    if extension is None:
        return None
    return LANGUAGE_BY_EXTENSION.get(extension)


def is_source_file(filename: str, extension: str | None) -> bool:
    return filename in ENTRY_FILENAMES or (extension or "") in SOURCE_EXTENSIONS


def is_ignored_directory(name: str) -> bool:
    return name.lower() in IGNORED_DIRECTORY_NAMES


def is_sensitive_path(relative_path: str) -> bool:
    parts = [part.lower() for part in PurePosixPath(relative_path).parts]
    if not parts:
        return False
    filename = parts[-1]
    if filename in SENSITIVE_FILENAMES or Path(filename).suffix.lower() in SENSITIVE_EXTENSIONS:
        return True
    return any(marker in part for part in parts for marker in SENSITIVE_NAME_MARKERS)


def resolve_repo_path(repo_root: str | Path, relative_path: str) -> Path:
    root = Path(repo_root).expanduser().resolve(strict=True)
    candidate = (root / relative_path).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise RepoModuleError(
            repo_api_error(
                error_code=ErrorCode.REPO_SCAN_FAILED,
                message="仓库路径越界，已拒绝读取",
                retryable=False,
                internal_detail=f"{relative_path} escaped {root}",
            )
        ) from exc
    return candidate


def _relative_path(repo_root: Path, path: Path) -> str:
    try:
        value = path.resolve(strict=False).relative_to(repo_root).as_posix()
    except ValueError:
        value = path.name
    return value or "."


def _depth(relative_path: str) -> int:
    if relative_path == ".":
        return 0
    return len(PurePosixPath(relative_path).parts)
