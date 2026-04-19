"""Registry-backed tool execution for the M6 function-calling loop."""

from __future__ import annotations

import json
from typing import Any

from backend.agent_tools import (
    DEFAULT_TOOL_REGISTRY,
    GLOBAL_TOOL_RESULT_CACHE,
    ToolContext,
    ToolResultCache,
    serialize_tool_result,
    to_api_tool_name,
)
from backend.contracts.domain import (
    FileTreeSnapshot,
    RepositoryContext,
)

TOOL_SCHEMAS: list[dict[str, Any]] = DEFAULT_TOOL_REGISTRY.openai_schemas()


def tool_schemas_for(tool_names: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
    schemas: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tool_name in tool_names:
        normalized = normalize_tool_name(tool_name)
        if normalized in seen:
            continue
        try:
            spec = DEFAULT_TOOL_REGISTRY.get(normalized)
        except KeyError:
            continue
        schemas.append(spec.openai_schema())
        seen.add(spec.tool_name)
    return schemas


def execute_tool_call(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    repository: RepositoryContext,
    file_tree: FileTreeSnapshot,
    result_cache: ToolResultCache | None = None,
) -> str:
    normalized = normalize_tool_name(tool_name)
    try:
        spec = DEFAULT_TOOL_REGISTRY.get(normalized)
    except KeyError:
        return json.dumps({"error": f"未知工具: {tool_name}"}, ensure_ascii=False)

    ctx = ToolContext(
        repository=repository,
        file_tree=file_tree,
    )
    cached = None
    cache = result_cache if result_cache is not None else GLOBAL_TOOL_RESULT_CACHE
    if spec.deterministic:
        cached = cache.get(spec.tool_name, arguments, ctx)
    if cached is not None:
        return serialize_tool_result(cached)

    result = DEFAULT_TOOL_REGISTRY.execute(spec.tool_name, arguments, ctx)
    if spec.deterministic:
        cache.set(spec.tool_name, arguments, ctx, result)
    return serialize_tool_result(result)


def normalize_tool_name(tool_name: str) -> str:
    return DEFAULT_TOOL_REGISTRY.normalize_name(tool_name)


def api_tool_name(tool_name: str) -> str:
    try:
        return DEFAULT_TOOL_REGISTRY.api_name(tool_name)
    except KeyError:
        return to_api_tool_name(tool_name)
