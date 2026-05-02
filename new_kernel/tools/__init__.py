"""Read-only repository tools for the new kernel."""

from __future__ import annotations

from .find_references import FindReferences
from .list_dir import ListDir
from .read_file_range import ReadFileRange
from .search_repo import SearchRepo
from .summarize_file import SummarizeFile, SummarizerCallable
from .tool_protocol import (
    BaseTool,
    ToolAlias,
    ToolContext,
    ToolDefinition,
    ToolParameter,
    ToolPromptHints,
    ToolResult,
)
from .tool_runtime import ToolRuntime


def build_default_tools(*, summarizer: SummarizerCallable | None = None) -> list[BaseTool]:
    """Build the v1 read-only repo tool set."""
    return [
        ReadFileRange(),
        SearchRepo(),
        ListDir(),
        SummarizeFile(summarizer=summarizer),
        FindReferences(),
    ]


__all__ = [
    "BaseTool",
    "FindReferences",
    "ListDir",
    "ReadFileRange",
    "SearchRepo",
    "SummarizeFile",
    "SummarizerCallable",
    "ToolAlias",
    "ToolContext",
    "ToolDefinition",
    "ToolParameter",
    "ToolPromptHints",
    "ToolResult",
    "ToolRuntime",
    "build_default_tools",
]
