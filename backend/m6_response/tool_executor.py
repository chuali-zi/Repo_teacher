"""Registry-backed tool execution for the M6 function-calling loop."""

from __future__ import annotations

import json
from typing import Any

from backend.agent_tools import (
    DEFAULT_TOOL_REGISTRY,
    GLOBAL_TOOL_RESULT_CACHE,
    ToolContext,
    serialize_tool_result,
)
from backend.contracts.domain import (
    AnalysisBundle,
    FileTreeSnapshot,
    RepositoryContext,
    TeachingSkeleton,
)

TOOL_SCHEMAS: list[dict[str, Any]] = DEFAULT_TOOL_REGISTRY.openai_schemas()


def execute_tool_call(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    repository: RepositoryContext,
    file_tree: FileTreeSnapshot,
    analysis: AnalysisBundle | None = None,
    teaching_skeleton: TeachingSkeleton | None = None,
) -> str:
    normalized = normalize_tool_name(tool_name)
    try:
        spec = DEFAULT_TOOL_REGISTRY.get(normalized)
    except KeyError:
        return json.dumps({"error": f"未知工具: {tool_name}"}, ensure_ascii=False)

    ctx = ToolContext(
        repository=repository,
        file_tree=file_tree,
        analysis=analysis,
        teaching_skeleton=teaching_skeleton,
    )
    cached = None
    if spec.deterministic:
        cached = GLOBAL_TOOL_RESULT_CACHE.get(spec.tool_name, arguments, ctx)
    if cached is not None:
        return serialize_tool_result(cached)

    result = DEFAULT_TOOL_REGISTRY.execute(spec.tool_name, arguments, ctx)
    if spec.deterministic:
        GLOBAL_TOOL_RESULT_CACHE.set(spec.tool_name, arguments, ctx, result)
    return serialize_tool_result(result)


def normalize_tool_name(tool_name: str) -> str:
    return DEFAULT_TOOL_REGISTRY.normalize_name(tool_name)
