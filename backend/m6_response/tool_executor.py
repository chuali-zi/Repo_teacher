"""Bridges LLM function-calling with the existing read-only repository tools.

Defines OpenAI-compatible tool schemas for `repo.read_file_excerpt` and
`repo.search_text`, and dispatches tool calls to the implementations in
`backend.llm_tools.context_builder`.
"""

from __future__ import annotations

import json
from typing import Any

from backend.contracts.domain import (
    AnalysisBundle,
    FileTreeSnapshot,
    LlmToolResult,
    RepositoryContext,
    TeachingSkeleton,
)
from backend.llm_tools.context_builder import read_file_excerpt, search_text
from backend.repo_kb.query_service import (
    get_entry_candidates,
    get_evidence,
    get_module_map,
    get_reading_path,
    get_repo_surfaces,
)

TOOL_NAME_ALIASES: dict[str, str] = {
    "repo.get_surfaces": "get_repo_surfaces",
    "repo.get_entry_candidates": "get_entry_candidates",
    "repo.get_module_map": "get_module_map",
    "repo.get_reading_path": "get_reading_path",
    "repo.get_evidence": "get_evidence",
    "repo.read_file_excerpt": "read_file_excerpt",
    "repo.search_text": "search_text",
}

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_repo_surfaces",
            "description": "读取仓库分区，区分产品代码区、工作区元目录、文档区和工具区。",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["teaching", "workspace"],
                        "default": "teaching",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_entry_candidates",
            "description": "读取按模式过滤后的入口候选，优先区分主产品入口和工具入口。",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["teaching", "workspace"],
                        "default": "teaching",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_module_map",
            "description": "读取按模式过滤后的模块地图，帮助决定从哪条主线开始讲。",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["teaching", "workspace"],
                        "default": "teaching",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_reading_path",
            "description": "读取当前教学目标或指定目标下的阅读路径建议。",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "mode": {
                        "type": "string",
                        "enum": ["teaching", "workspace"],
                        "default": "teaching",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_evidence",
            "description": "按 target 或 evidence_ids 检索证据。",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string"},
                    "evidence_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file_excerpt",
            "description": (
                "安全读取仓库中一个非敏感文件的指定行范围摘录。用于按需查看用户追问涉及的源码细节。"
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
    analysis: AnalysisBundle | None = None,
    teaching_skeleton: TeachingSkeleton | None = None,
) -> str:
    """Execute a single tool call and return a JSON string for the LLM."""
    tool_name = normalize_tool_name(tool_name)
    if tool_name == "get_repo_surfaces":
        result = _require_analysis(
            tool_name,
            analysis,
            lambda current: get_repo_surfaces(current, mode=arguments.get("mode", "teaching")),
        )
    elif tool_name == "get_entry_candidates":
        result = _require_analysis(
            tool_name,
            analysis,
            lambda current: get_entry_candidates(current, mode=arguments.get("mode", "teaching")),
        )
    elif tool_name == "get_module_map":
        result = _require_analysis(
            tool_name,
            analysis,
            lambda current: get_module_map(current, mode=arguments.get("mode", "teaching")),
        )
    elif tool_name == "get_reading_path":
        result = _require_analysis(
            tool_name,
            analysis,
            lambda current: get_reading_path(
                current,
                goal=arguments.get("goal"),
                mode=arguments.get("mode", "teaching"),
            ),
        )
    elif tool_name == "get_evidence":
        result = _require_analysis(
            tool_name,
            analysis,
            lambda current: get_evidence(
                current,
                evidence_ids=arguments.get("evidence_ids"),
                target=arguments.get("target"),
            ),
        )
    elif tool_name == "read_file_excerpt":
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


def normalize_tool_name(tool_name: str) -> str:
    return TOOL_NAME_ALIASES.get(tool_name, tool_name)


def _serialize_tool_result(result: LlmToolResult) -> str:
    payload = {
        "tool_name": result.tool_name,
        "summary": result.summary,
        **result.payload,
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


def _require_analysis(
    tool_name: str,
    analysis: AnalysisBundle | None,
    factory: Any,
) -> LlmToolResult:
    if analysis is None:
        return LlmToolResult(
            result_id=f"tool_missing_{tool_name}",
            tool_name=tool_name,
            source_module="m6_response.tool_executor",
            summary=f"{tool_name} 缺少分析上下文。",
            payload={"available": False, "reason": "analysis_not_available"},
            reference_only=True,
        )
    return factory(analysis)
