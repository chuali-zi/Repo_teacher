"""Read a bounded line range from a safe repository file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

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


class ReadFileRange(BaseTool):
    """Read-only file range tool."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="read_file_range",
            description="Read a specific inclusive line range from a repository file.",
            parameters=[
                ToolParameter("path", "string", "Repository-relative file path."),
                ToolParameter("start_line", "integer", "1-based inclusive start line."),
                ToolParameter("end_line", "integer", "1-based inclusive end line."),
            ],
        )

    def get_prompt_hints(self, language: str = "zh") -> ToolPromptHints:
        _ = language
        return ToolPromptHints(
            short_description="Read a safe file range with line numbers.",
            when_to_use="Use when you need exact source code from a known path and line range.",
            input_format='{"path": "src/app.py", "start_line": 1, "end_line": 80}',
            aliases=(
                ToolAlias("read_file", "Alias for reading a bounded file range."),
                ToolAlias("read_source", "Alias for reading source code by range."),
            ),
        )

    async def execute(
        self,
        *,
        ctx: ToolContext,
        path: str,
        start_line: int,
        end_line: int,
    ) -> ToolResult:
        if not isinstance(path, str) or not path.strip():
            return _fail("path must be a non-empty string", "invalid_path", path=path)

        try:
            start = _to_int(start_line, "start_line")
            end = _to_int(end_line, "end_line")
        except ValueError as exc:
            return _fail(str(exc), "invalid_range", path=path)
        if start < 1 or end < start:
            return _fail(
                "line range must satisfy 1 <= start_line <= end_line",
                "invalid_range",
                path=path,
                start_line=start,
                end_line=end,
            )

        resolved, rel_path, error = _resolve_safe_file(ctx.repo_root, path)
        if error is not None:
            return error

        try:
            lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            return _fail(
                f"Unable to read file: {exc}",
                "read_failed",
                path=rel_path,
                exception_type=type(exc).__name__,
            )

        total_lines = len(lines)
        if total_lines == 0:
            return ToolResult.ok(
                f"{rel_path} is empty.",
                metadata={
                    "path": rel_path,
                    "start_line": 0,
                    "end_line": 0,
                    "original_lines": 0,
                    "returned_lines": 0,
                },
            )
        if start > total_lines:
            return _fail(
                "start_line is beyond end of file",
                "range_out_of_bounds",
                path=rel_path,
                start_line=start,
                end_line=end,
                original_lines=total_lines,
            )

        requested_line_count = end - start + 1
        returned_line_count = min(requested_line_count, ctx.max_lines, total_lines - start + 1)
        returned_end = start + returned_line_count - 1
        selected = lines[start - 1 : returned_end]
        content = "\n".join(
            f"{line_number}: {line}"
            for line_number, line in enumerate(selected, start=start)
        )

        metadata: dict[str, Any] = {
            "path": rel_path,
            "start_line": start,
            "end_line": returned_end,
            "requested_start_line": start,
            "requested_end_line": end,
            "original_lines": total_lines,
            "returned_lines": returned_line_count,
        }
        if returned_line_count < requested_line_count and returned_end < min(end, total_lines):
            metadata.update(
                {
                    "truncated": True,
                    "truncation_reason": "max_lines",
                    "requested_lines": requested_line_count,
                }
            )
        if end > total_lines:
            metadata["requested_end_beyond_eof"] = True

        return ToolResult.ok(content, metadata=metadata)


def _resolve_safe_file(repo_root: str, path: str) -> tuple[Path, str, ToolResult | None]:
    try:
        resolved = resolve_under_root(path, repo_root)
    except (OSError, ValueError) as exc:
        return Path(), str(path), _fail(
            str(exc),
            "unsafe_path",
            path=path,
            exception_type=type(exc).__name__,
        )

    try:
        rel_path = resolved.relative_to(
            Path(repo_root).expanduser().resolve(strict=True)
        ).as_posix()
    except (OSError, ValueError):
        rel_path = path

    if is_sensitive_file(rel_path) or is_sensitive_file(
        resolved,
        max_file_size_bytes=MAX_FILE_SIZE_BYTES,
    ):
        return resolved, rel_path, _fail(
            "File is blocked by repository safety policy.",
            "blocked_path",
            path=rel_path,
        )
    if not resolved.exists():
        return resolved, rel_path, _fail("File does not exist.", "not_found", path=rel_path)
    if not resolved.is_file():
        return resolved, rel_path, _fail("Path is not a file.", "not_file", path=rel_path)
    return resolved, rel_path, None


def _to_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def _fail(content: str, error_code: str, **metadata: Any) -> ToolResult:
    return ToolResult.fail(content, error_code=error_code, metadata=metadata)


__all__ = ["ReadFileRange"]
