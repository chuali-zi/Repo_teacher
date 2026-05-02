"""Find symbol references with safe text search."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .search_repo import iter_safe_files, relative_path, validate_glob
from .tool_protocol import (
    BaseTool,
    ToolAlias,
    ToolContext,
    ToolDefinition,
    ToolParameter,
    ToolPromptHints,
    ToolResult,
)


MAX_SYMBOL_LENGTH = 128


@dataclass(frozen=True)
class ReferenceHit:
    path: str
    line_number: int
    before: str
    line: str
    after: str


class FindReferences(BaseTool):
    """Find textual references for a symbol without LSP coupling."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="find_references",
            description="Find references to a symbol using bounded repository text search.",
            parameters=[
                ToolParameter("symbol", "string", "Symbol, route, function, class, or identifier."),
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
            short_description="Find references to a symbol.",
            when_to_use="Use after identifying a function, class, route, or variable name.",
            input_format='{"symbol": "SessionStore", "glob": "**/*.py"}',
            aliases=(
                ToolAlias("refs", "Alias for find_references."),
                ToolAlias("find_refs", "Alias for find_references."),
            ),
        )

    async def execute(
        self,
        *,
        ctx: ToolContext,
        symbol: str,
        glob: str | None = None,
    ) -> ToolResult:
        if not isinstance(symbol, str) or not symbol.strip():
            return ToolResult.fail(
                "symbol must be a non-empty string",
                error_code="invalid_symbol",
                metadata={"symbol": symbol},
            )
        symbol = symbol.strip()
        if len(symbol) > MAX_SYMBOL_LENGTH:
            return ToolResult.fail(
                "symbol is too long",
                error_code="invalid_symbol",
                metadata={"symbol_length": len(symbol), "max_symbol_length": MAX_SYMBOL_LENGTH},
            )

        glob_error = validate_glob(glob)
        if glob_error is not None:
            return glob_error

        try:
            root = Path(ctx.repo_root).expanduser().resolve(strict=True)
        except OSError as exc:
            return ToolResult.fail(
                f"Invalid repository root: {exc}",
                error_code="invalid_repo_root",
                metadata={"exception_type": type(exc).__name__},
            )

        regex = _symbol_regex(symbol)
        hits: list[ReferenceHit] = []
        total_hits = 0
        scanned_files = 0
        for file_path in iter_safe_files(root, glob=glob):
            scanned_files += 1
            try:
                lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            rel = relative_path(root, file_path)
            for index, line in enumerate(lines):
                if not regex.search(line):
                    continue
                total_hits += 1
                if len(hits) < ctx.max_search_hits:
                    hits.append(
                        ReferenceHit(
                            path=rel,
                            line_number=index + 1,
                            before=_context_line(lines, index - 1),
                            line=line.strip(),
                            after=_context_line(lines, index + 1),
                        )
                    )

        content = "\n".join(_format_hit(hit) for hit in hits)
        if not content:
            content = f"No references found for symbol: {symbol}"

        metadata = {
            "symbol": symbol,
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
        return ToolResult.ok(content, metadata=metadata)


def _symbol_regex(symbol: str) -> re.Pattern[str]:
    escaped = re.escape(symbol)
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", symbol):
        return re.compile(rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])")
    return re.compile(escaped)


def _context_line(lines: list[str], index: int) -> str:
    if index < 0 or index >= len(lines):
        return ""
    return lines[index].strip()


def _format_hit(hit: ReferenceHit) -> str:
    parts = [f"{hit.path}:{hit.line_number}"]
    if hit.before:
        parts.append(f"  {hit.before}")
    parts.append(f"> {hit.line}")
    if hit.after:
        parts.append(f"  {hit.after}")
    return "\n".join(parts)


__all__ = ["FindReferences", "ReferenceHit"]
