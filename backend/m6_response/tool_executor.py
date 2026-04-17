"""Bridges LLM function-calling with the existing read-only repository tools.

Defines OpenAI-compatible tool schemas for `repo.read_file_excerpt` and
`repo.search_text`, and dispatches tool calls to the implementations in
`backend.llm_tools.context_builder`.
"""

from __future__ import annotations

import json
from typing import Any

from backend.contracts.domain import (
    FileTreeSnapshot,
    LlmToolResult,
    RepositoryContext,
)
from backend.llm_tools.context_builder import read_file_excerpt, search_text

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file_excerpt",
            "description": (
                "安全读取仓库中一个非敏感文件的指定行范围摘录。"
                "用于按需查看用户追问涉及的源码细节。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "relative_path": {
                        "type": "string",
                        "description": "仓库内相对路径，如 backend/main.py",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "起始行号（从 1 开始），默认 1",
                        "default": 1,
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": "最多读取行数，默认 80，上限 160",
                        "default": 80,
                    },
                },
                "required": ["relative_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_text",
            "description": (
                "在仓库可读非敏感文本文件中搜索关键词，返回匹配行摘录。"
                "用于定位用户追问涉及的符号、函数名或关键词。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词",
                    },
                    "max_matches": {
                        "type": "integer",
                        "description": "最大返回条数，默认 20，上限 50",
                        "default": 20,
                    },
                },
                "required": ["query"],
            },
        },
    },
]


def execute_tool_call(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    repository: RepositoryContext,
    file_tree: FileTreeSnapshot,
) -> str:
    """Execute a single tool call and return a JSON string for the LLM."""
    if tool_name == "read_file_excerpt":
        result = read_file_excerpt(
            repository,
            file_tree,
            relative_path=arguments.get("relative_path", ""),
            start_line=arguments.get("start_line", 1),
            max_lines=arguments.get("max_lines", 80),
        )
    elif tool_name == "search_text":
        result = search_text(
            repository,
            file_tree,
            query=arguments.get("query", ""),
            max_matches=arguments.get("max_matches", 20),
        )
    else:
        return json.dumps(
            {"error": f"未知工具: {tool_name}"},
            ensure_ascii=False,
        )
    return _serialize_tool_result(result)


def _serialize_tool_result(result: LlmToolResult) -> str:
    payload = {
        "tool_name": result.tool_name,
        "summary": result.summary,
        **result.payload,
    }
    return json.dumps(payload, ensure_ascii=False, default=str)
