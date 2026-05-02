"""Safe in-process repository search tool."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

from .safe_paths import MAX_FILE_SIZE_BYTES, is_sensitive_file, resolve_under_root
from .tool_protocol import (
    BaseTool,
    ToolAlias,
    ToolContext,
    ToolDefinition,
    ToolParameter,
    ToolPromptHints,
    ToolResult,
)


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

MAX_SCANNED_FILES = 5_000
MAX_LINE_PREVIEW_CHARS = 320


@dataclass(frozen=True)
class SearchHit:
    path: str
    line_number: int
    line_text: str


class SearchRepo(BaseTool):
    """Search text files inside the repository root."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="search_repo",
            description="Search safe repository text files for a regular expression.",
            parameters=[
                ToolParameter("pattern", "string", "Python regular expression to search for."),
                ToolParameter(
                    "glob",
                    "string",
                    "Optional repository-relative glob.",
                    required=False,
                ),
            ],
        )

    def get_prompt_hints(self, language: str = "zh") -> ToolPromptHints:
        _ = language
        return ToolPromptHints(
            short_description="Search repository text files.",
            when_to_use=(
                "Use when you know a symbol, route, phrase, "
                "or filename fragment to locate."
            ),
            input_format='{"pattern": "class SessionStore", "glob": "**/*.py"}',
            aliases=(
                ToolAlias("search", "Alias for repository search."),
                ToolAlias("grep_repo", "Alias for repository search."),
            ),
        )

    async def execute(
        self,
        *,
        ctx: ToolContext,
        pattern: str,
        glob: str | None = None,
    ) -> ToolResult:
        if not isinstance(pattern, str) or not pattern:
            return ToolResult.fail(
                "pattern must be a non-empty string",
                error_code="invalid_pattern",
                metadata={"pattern": pattern},
            )

        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return ToolResult.fail(
                f"Invalid regular expression: {exc}",
                error_code="invalid_pattern",
                metadata={"pattern": pattern},
            )

        glob_error = validate_glob(glob)
        if glob_error is not None:
            return glob_error

        try:
            root = resolve_under_root(".", ctx.repo_root)
        except (OSError, ValueError) as exc:
            return ToolResult.fail(
                f"Invalid repository root: {exc}",
                error_code="invalid_repo_root",
                metadata={"exception_type": type(exc).__name__},
            )

        hits: list[SearchHit] = []
        total_hits = 0
        scanned_files = 0
        scan_limit_reached = False
        for file_path in iter_safe_files(root, glob=glob):
            if scanned_files >= MAX_SCANNED_FILES:
                scan_limit_reached = True
                break
            scanned_files += 1
            try:
                for line_number, line in enumerate(
                    file_path.read_text(encoding="utf-8", errors="replace").splitlines(),
                    start=1,
                ):
                    if not regex.search(line):
                        continue
                    total_hits += 1
                    if len(hits) < ctx.max_search_hits:
                        hits.append(
                            SearchHit(
                                path=relative_path(root, file_path),
                                line_number=line_number,
                                line_text=_preview_line(line),
                            )
                        )
            except OSError:
                continue

        content = "\n".join(
            f"{hit.path}:{hit.line_number}: {hit.line_text}" for hit in hits
        )
        if not content:
            content = f"No matches for pattern: {pattern}"

        metadata = {
            "pattern": pattern,
            "glob": glob,
            "hits": total_hits,
            "returned_hits": len(hits),
            "scanned_files": scanned_files,
        }
        if total_hits > len(hits):
            metadata.update(
                {
                    "truncated": True,
                    "original_hits": total_hits,
                    "returned_hits": len(hits),
                }
            )
        if scan_limit_reached:
            metadata["scan_limit_reached"] = True
            metadata["scan_limit"] = MAX_SCANNED_FILES

        return ToolResult.ok(content, metadata=metadata)


def validate_glob(glob: str | None) -> ToolResult | None:
    if glob is None or glob == "":
        return None
    if not isinstance(glob, str):
        return ToolResult.fail(
            "glob must be a string when provided",
            error_code="invalid_glob",
            metadata={"input_type": type(glob).__name__},
        )
    normalized = glob.replace("\\", "/").strip()
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        return ToolResult.fail(
            "glob must stay inside the repository root",
            error_code="invalid_glob",
            metadata={"glob": glob},
        )
    return None


def iter_safe_files(root: Path, *, glob: str | None = None) -> Iterable[Path]:
    for file_path in _walk_files(root):
        rel_path = relative_path(root, file_path)
        if glob and not PurePosixPath(rel_path).match(glob):
            continue
        if is_sensitive_file(rel_path) or is_sensitive_file(
            file_path,
            max_file_size_bytes=MAX_FILE_SIZE_BYTES,
        ):
            continue
        yield file_path


def _walk_files(root: Path) -> Iterable[Path]:
    try:
        entries = sorted(root.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    except OSError:
        return

    for entry in entries:
        try:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if should_skip_directory(entry.name):
                    continue
                yield from _walk_files(entry)
                continue
            if entry.is_file():
                yield entry
        except OSError:
            continue


def should_skip_directory(name: str) -> bool:
    return name.lower() in IGNORED_DIRECTORY_NAMES


def relative_path(root: Path, path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(root).as_posix()
    except ValueError:
        return path.name


def _preview_line(line: str) -> str:
    compact = line.strip()
    if len(compact) <= MAX_LINE_PREVIEW_CHARS:
        return compact
    return compact[: MAX_LINE_PREVIEW_CHARS - 3] + "..."


__all__ = [
    "IGNORED_DIRECTORY_NAMES",
    "SearchHit",
    "SearchRepo",
    "iter_safe_files",
    "relative_path",
    "should_skip_directory",
    "validate_glob",
]
