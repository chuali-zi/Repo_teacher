"""List safe repository directory entries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .safe_paths import MAX_FILE_SIZE_BYTES, is_sensitive_file, resolve_under_root
from .search_repo import relative_path, should_skip_directory
from .tool_protocol import (
    BaseTool,
    ToolAlias,
    ToolContext,
    ToolDefinition,
    ToolParameter,
    ToolPromptHints,
    ToolResult,
)


MAX_RECURSIVE_DEPTH = 4


@dataclass(frozen=True)
class DirectoryEntry:
    path: str
    kind: str
    size_bytes: int | None = None


class ListDir(BaseTool):
    """List directory entries without exposing blocked paths."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="list_dir",
            description="List safe files and directories under a repository directory.",
            parameters=[
                ToolParameter(
                    "path",
                    "string",
                    "Repository-relative directory path.",
                    required=False,
                    default=".",
                ),
                ToolParameter(
                    "recursive",
                    "boolean",
                    "Whether to recurse into subdirectories up to a shallow depth.",
                    required=False,
                    default=False,
                ),
            ],
        )

    def get_prompt_hints(self, language: str = "zh") -> ToolPromptHints:
        _ = language
        return ToolPromptHints(
            short_description="List safe repository directory entries.",
            when_to_use="Use to understand a small directory before choosing files to read.",
            input_format='{"path": "backend", "recursive": false}',
            aliases=(
                ToolAlias("ls", "Alias for list_dir."),
                ToolAlias("list_directory", "Alias for list_dir."),
            ),
        )

    async def execute(
        self,
        *,
        ctx: ToolContext,
        path: str = ".",
        recursive: bool = False,
    ) -> ToolResult:
        if not isinstance(path, str) or not path.strip():
            return ToolResult.fail(
                "path must be a non-empty string",
                error_code="invalid_path",
                metadata={"path": path},
            )

        try:
            root = Path(ctx.repo_root).expanduser().resolve(strict=True)
            target = resolve_under_root(path, root)
        except (OSError, ValueError) as exc:
            return ToolResult.fail(
                f"Unsafe directory path: {exc}",
                error_code="unsafe_path",
                metadata={"path": path, "exception_type": type(exc).__name__},
            )

        rel_target = relative_path(root, target)
        if rel_target == "":
            rel_target = "."
        if rel_target != "." and is_sensitive_file(rel_target):
            return ToolResult.fail(
                "Directory is blocked by repository safety policy.",
                error_code="blocked_path",
                metadata={"path": rel_target},
            )
        if not target.exists():
            return ToolResult.fail(
                "Directory does not exist.",
                error_code="not_found",
                metadata={"path": rel_target},
            )
        if not target.is_dir():
            return ToolResult.fail(
                "Path is not a directory.",
                error_code="not_directory",
                metadata={"path": rel_target},
            )

        entries: list[DirectoryEntry] = []
        total_entries = 0
        for entry in _iter_entries(root, target, recursive=bool(recursive)):
            total_entries += 1
            if len(entries) < ctx.max_search_hits:
                entries.append(entry)

        content = "\n".join(_format_entry(entry) for entry in entries)
        if not content:
            content = f"{rel_target} has no visible safe entries."

        metadata = {
            "path": rel_target,
            "recursive": bool(recursive),
            "entries": total_entries,
            "returned_entries": len(entries),
            "max_depth": MAX_RECURSIVE_DEPTH if recursive else 1,
        }
        if total_entries > len(entries):
            metadata.update(
                {
                    "truncated": True,
                    "original_entries": total_entries,
                    "returned_entries": len(entries),
                }
            )
        return ToolResult.ok(content, metadata=metadata)


def _iter_entries(root: Path, directory: Path, *, recursive: bool) -> Iterable[DirectoryEntry]:
    base_depth = len(directory.relative_to(root).parts)
    yield from _iter_entries_inner(root, directory, recursive=recursive, base_depth=base_depth)


def _iter_entries_inner(
    root: Path,
    directory: Path,
    *,
    recursive: bool,
    base_depth: int,
) -> Iterable[DirectoryEntry]:
    try:
        children = sorted(
            directory.iterdir(),
            key=lambda item: (not item.is_dir(), item.name.lower()),
        )
    except OSError:
        return

    for child in children:
        try:
            if child.is_symlink():
                continue
            rel = relative_path(root, child)
            if child.is_dir():
                if should_skip_directory(child.name) or is_sensitive_file(rel):
                    continue
                yield DirectoryEntry(path=f"{rel}/", kind="dir")
                depth = len(child.relative_to(root).parts) - base_depth
                if recursive and depth < MAX_RECURSIVE_DEPTH:
                    yield from _iter_entries_inner(
                        root,
                        child,
                        recursive=recursive,
                        base_depth=base_depth,
                    )
                continue
            if not child.is_file():
                continue
            if is_sensitive_file(rel) or is_sensitive_file(
                child,
                max_file_size_bytes=MAX_FILE_SIZE_BYTES,
            ):
                continue
            yield DirectoryEntry(path=rel, kind="file", size_bytes=child.stat().st_size)
        except OSError:
            continue


def _format_entry(entry: DirectoryEntry) -> str:
    if entry.kind == "dir":
        return f"[dir]  {entry.path}"
    return f"[file] {entry.path} ({entry.size_bytes} bytes)"


__all__ = ["DirectoryEntry", "ListDir"]
