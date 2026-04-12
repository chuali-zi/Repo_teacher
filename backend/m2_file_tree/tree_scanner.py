from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha1
from pathlib import Path, PurePosixPath
from uuid import uuid4

from backend.contracts.domain import FileNode, FileTreeSnapshot, RepositoryContext
from backend.contracts.enums import FileNodeStatus, FileNodeType
from backend.m2_file_tree.file_filter import apply_file_filters
from backend.m2_file_tree.language_detector import detect_languages
from backend.m2_file_tree.repo_sizer import classify_repo_size
from backend.security.safety import assert_path_within_repo

SOURCE_EXTENSIONS: set[str] = {
    ".py",
    ".pyi",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".cs",
    ".kt",
    ".swift",
    ".scala",
    ".c",
    ".h",
    ".cpp",
    ".cc",
    ".cxx",
    ".hpp",
    ".hh",
    ".m",
    ".mm",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".sql",
    ".html",
    ".css",
    ".scss",
    ".sass",
    ".less",
    ".vue",
    ".svelte",
}

SOURCE_FILENAMES: set[str] = {"Dockerfile", "Makefile"}


def scan_repository_tree(repository: RepositoryContext) -> FileTreeSnapshot:
    repo_root = Path(repository.root_path).expanduser().resolve(strict=True)
    raw_nodes = _scan_path(repo_root, repo_root)
    nodes, ignored_rules, sensitive_matches = apply_file_filters(
        raw_nodes,
        ignore_patterns=repository.read_policy.ignore_patterns,
        sensitive_patterns=repository.read_policy.sensitive_patterns,
    )
    primary_language, language_stats = detect_languages(nodes)
    repo_size_level, source_code_file_count, degraded_scan_scope = classify_repo_size(
        nodes,
        repository.read_policy.max_source_files_full_analysis,
    )

    return FileTreeSnapshot(
        snapshot_id=f"fts_{uuid4().hex[:12]}",
        repo_id=repository.repo_id,
        generated_at=datetime.now(UTC),
        root_path=repo_root.as_posix(),
        nodes=nodes,
        ignored_rules=ignored_rules,
        sensitive_matches=sensitive_matches,
        language_stats=language_stats,
        primary_language=primary_language,
        repo_size_level=repo_size_level,
        source_code_file_count=source_code_file_count,
        degraded_scan_scope=degraded_scan_scope,
    )


def _scan_path(repo_root: Path, current_path: Path) -> list[FileNode]:
    nodes: list[FileNode] = []
    entries = sorted(
        current_path.iterdir(),
        key=lambda item: (not item.is_dir(), item.name.lower(), item.name),
    )
    for entry in entries:
        nodes.append(_build_node(repo_root, entry))
        if entry.is_dir():
            nodes.extend(_scan_path(repo_root, entry))
    return nodes


def _build_node(repo_root: Path, entry: Path) -> FileNode:
    assert_path_within_repo(repo_root, entry)
    relative_path = entry.relative_to(repo_root).as_posix()
    depth = len(PurePosixPath(relative_path).parts)
    parent = PurePosixPath(relative_path).parent.as_posix()
    if parent == ".":
        parent = None

    try:
        stat_result = entry.stat()
        is_directory = entry.is_dir()
        status = FileNodeStatus.NORMAL
        size_bytes = None if is_directory else stat_result.st_size
    except OSError:
        is_directory = False
        status = FileNodeStatus.UNREADABLE
        size_bytes = None

    extension = entry.suffix.lower() or None
    return FileNode(
        node_id=_node_id(relative_path),
        relative_path=relative_path,
        real_path=entry.resolve(strict=False).as_posix(),
        node_type=FileNodeType.DIRECTORY if is_directory else FileNodeType.FILE,
        extension=extension,
        status=status,
        is_source_file=_is_source_file(entry.name, extension),
        is_python_source=extension == ".py",
        size_bytes=size_bytes,
        depth=depth,
        parent_path=parent,
    )


def _node_id(relative_path: str) -> str:
    return f"node_{sha1(relative_path.encode('utf-8')).hexdigest()[:12]}"


def _is_source_file(filename: str, extension: str | None) -> bool:
    return filename in SOURCE_FILENAMES or (extension or "") in SOURCE_EXTENSIONS
