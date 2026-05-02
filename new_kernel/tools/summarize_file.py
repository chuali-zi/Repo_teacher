"""Summarize a safe repository file through an injected callable or local heuristics."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Awaitable, Callable

from .safe_paths import MAX_FILE_SIZE_BYTES, is_sensitive_file, resolve_under_root
from .search_repo import relative_path
from .tool_protocol import (
    BaseTool,
    ToolAlias,
    ToolContext,
    ToolDefinition,
    ToolParameter,
    ToolPromptHints,
    ToolResult,
)


SummarizerCallable = Callable[[str], Awaitable[str]]

SYMBOL_PATTERNS = (
    re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("),
    re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b"),
    re.compile(r"^\s*(?:export\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\("),
    re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][A-Za-z0-9_$]*)\b"),
    re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*="),
)


class SummarizeFile(BaseTool):
    """Summarize one file without importing the LLM layer."""

    def __init__(self, summarizer: SummarizerCallable | None = None) -> None:
        self._summarizer = summarizer

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="summarize_file",
            description="Summarize the purpose and important symbols of a repository file.",
            parameters=[
                ToolParameter("path", "string", "Repository-relative file path to summarize."),
            ],
        )

    def get_prompt_hints(self, language: str = "zh") -> ToolPromptHints:
        _ = language
        return ToolPromptHints(
            short_description="Summarize a file before reading exact ranges.",
            when_to_use="Use when a file is relevant but too large to inspect line by line first.",
            input_format='{"path": "src/app.py"}',
            aliases=(
                ToolAlias("summarize", "Alias for summarize_file."),
                ToolAlias("file_summary", "Alias for summarize_file."),
            ),
        )

    async def execute(self, *, ctx: ToolContext, path: str) -> ToolResult:
        if not isinstance(path, str) or not path.strip():
            return ToolResult.fail(
                "path must be a non-empty string",
                error_code="invalid_path",
                metadata={"path": path},
            )

        try:
            root = Path(ctx.repo_root).expanduser().resolve(strict=True)
            resolved = resolve_under_root(path, root)
        except (OSError, ValueError) as exc:
            return ToolResult.fail(
                f"Unsafe file path: {exc}",
                error_code="unsafe_path",
                metadata={"path": path, "exception_type": type(exc).__name__},
            )

        rel = relative_path(root, resolved)
        if is_sensitive_file(rel) or is_sensitive_file(
            resolved,
            max_file_size_bytes=MAX_FILE_SIZE_BYTES,
        ):
            return ToolResult.fail(
                "File is blocked by repository safety policy.",
                error_code="blocked_path",
                metadata={"path": rel},
            )
        if not resolved.exists():
            return ToolResult.fail(
                "File does not exist.",
                error_code="not_found",
                metadata={"path": rel},
            )
        if not resolved.is_file():
            return ToolResult.fail(
                "Path is not a file.",
                error_code="not_file",
                metadata={"path": rel},
            )

        try:
            lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            return ToolResult.fail(
                f"Unable to read file: {exc}",
                error_code="read_failed",
                metadata={"path": rel, "exception_type": type(exc).__name__},
            )

        excerpt, truncated = _build_excerpt(lines, max_lines=ctx.max_lines)
        metadata = {
            "path": rel,
            "original_lines": len(lines),
            "excerpt_lines": excerpt.count("\n") + 1 if excerpt else 0,
            "truncated": truncated,
            "summarizer": "injected" if self._summarizer else "heuristic",
        }

        if self._summarizer is not None:
            try:
                summary = (await self._summarizer(excerpt)).strip()
            except Exception as exc:  # pragma: no cover - injected boundary
                return ToolResult.fail(
                    f"File summarizer failed: {exc}",
                    error_code="summarizer_failed",
                    metadata={
                        "path": rel,
                        "exception_type": type(exc).__name__,
                    },
                )
            if summary:
                return ToolResult.ok(summary, metadata=metadata)

        return ToolResult.ok(_heuristic_summary(rel, lines), metadata=metadata)


def _build_excerpt(lines: list[str], *, max_lines: int) -> tuple[str, bool]:
    if len(lines) <= max_lines:
        return "\n".join(lines), False
    if max_lines <= 2:
        return "\n".join(lines[:max_lines]), True
    budget_without_marker = max_lines - 1
    head_count = max(1, int(budget_without_marker * 0.7))
    tail_count = max(1, budget_without_marker - head_count)
    excerpt_lines = [
        *lines[:head_count],
        f"... omitted {len(lines) - head_count - tail_count} lines ...",
        *lines[-tail_count:],
    ]
    return "\n".join(excerpt_lines), True


def _heuristic_summary(path: str, lines: list[str]) -> str:
    symbols = _extract_symbols(lines)
    non_empty = [line.strip() for line in lines if line.strip()]
    first_lines = non_empty[:3]
    parts = [
        f"File: {path}",
        f"Lines: {len(lines)}",
    ]
    if symbols:
        parts.append("Key symbols: " + ", ".join(symbols[:20]))
    if first_lines:
        parts.append("Opening context:")
        parts.extend(f"- {line[:160]}" for line in first_lines)
    return "\n".join(parts)


def _extract_symbols(lines: list[str]) -> list[str]:
    symbols: list[str] = []
    seen: set[str] = set()
    for line in lines:
        for pattern in SYMBOL_PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            symbol = match.group(1)
            if symbol not in seen:
                symbols.append(symbol)
                seen.add(symbol)
            break
    return symbols


__all__ = ["SummarizeFile", "SummarizerCallable"]
