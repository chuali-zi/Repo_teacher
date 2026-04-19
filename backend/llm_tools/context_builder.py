from __future__ import annotations

from backend.agent_runtime.context_budget import build_llm_tool_context as build_budgeted_tool_context
from backend.agent_tools import DEFAULT_TOOL_REGISTRY, ToolContext
from backend.contracts.domain import (
    ConversationState,
    FileTreeSnapshot,
    LlmToolContext,
    LlmToolDefinition,
    LlmToolResult,
    RepositoryContext,
)
from backend.contracts.enums import PromptScenario


def tool_definitions() -> list[LlmToolDefinition]:
    return DEFAULT_TOOL_REGISTRY.definitions()


def build_llm_tool_context(
    *,
    repository: RepositoryContext,
    file_tree: FileTreeSnapshot,
    conversation: ConversationState,
    scenario: PromptScenario | None = None,
) -> LlmToolContext:
    return build_budgeted_tool_context(
        repository=repository,
        file_tree=file_tree,
        conversation=conversation,
        scenario=scenario,
    )


def read_file_excerpt(
    repository: RepositoryContext,
    file_tree: FileTreeSnapshot,
    *,
    relative_path: str,
    start_line: int = 1,
    max_lines: int = 80,
) -> LlmToolResult:
    return DEFAULT_TOOL_REGISTRY.execute(
        "read_file_excerpt",
        {
            "relative_path": relative_path,
            "start_line": start_line,
            "max_lines": max_lines,
        },
        ToolContext(repository=repository, file_tree=file_tree),
    )


def search_text(
    repository: RepositoryContext,
    file_tree: FileTreeSnapshot,
    *,
    query: str,
    max_matches: int = 20,
) -> LlmToolResult:
    return DEFAULT_TOOL_REGISTRY.execute(
        "search_text",
        {
            "query": query,
            "max_matches": max_matches,
        },
        ToolContext(repository=repository, file_tree=file_tree),
    )
