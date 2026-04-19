from __future__ import annotations

from collections import OrderedDict
from typing import Iterable

from backend.agent_tools.analysis_tools import build_analysis_tool_specs
from backend.agent_tools.base import ToolContext, ToolSpec, to_api_tool_name
from backend.agent_tools.repository_tools import build_repository_tool_specs
from backend.contracts.domain import LlmToolDefinition, LlmToolResult


class ToolRegistry:
    def __init__(self, specs: Iterable[ToolSpec]) -> None:
        self._tools: OrderedDict[str, ToolSpec] = OrderedDict()
        self._aliases: dict[str, str] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.tool_name] = spec
        self._aliases[spec.api_tool_name()] = spec.tool_name
        for alias in spec.aliases:
            self._aliases[alias] = spec.tool_name
            self._aliases[to_api_tool_name(alias)] = spec.tool_name

    def normalize_name(self, tool_name: str) -> str:
        return self._aliases.get(tool_name, tool_name)

    def get(self, tool_name: str) -> ToolSpec:
        normalized = self.normalize_name(tool_name)
        if normalized not in self._tools:
            raise KeyError(normalized)
        return self._tools[normalized]

    def execute(self, tool_name: str, arguments: dict, ctx: ToolContext) -> LlmToolResult:
        spec = self.get(tool_name)
        return spec.handler(arguments, ctx)

    def definitions(self) -> list[LlmToolDefinition]:
        return [spec.definition() for spec in self._tools.values()]

    def openai_schemas(self) -> list[dict]:
        return [spec.openai_schema() for spec in self._tools.values()]

    def api_name(self, tool_name: str) -> str:
        return self.get(tool_name).api_tool_name()

    def ids(self) -> list[str]:
        return list(self._tools.keys())


DEFAULT_TOOL_REGISTRY = ToolRegistry(
    [*build_analysis_tool_specs(), *build_repository_tool_specs()]
)
