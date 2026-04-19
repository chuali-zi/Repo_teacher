from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.contracts.domain import (
    ConversationState,
    FileTreeSnapshot,
    LlmToolDefinition,
    LlmToolResult,
    RepositoryContext,
)

ToolHandler = Callable[[dict[str, Any], "ToolContext"], LlmToolResult]
_API_TOOL_NAME_PATTERN = re.compile(r"[^a-zA-Z0-9_-]")


def to_api_tool_name(tool_name: str) -> str:
    """Return an OpenAI-compatible function name for an internal tool id."""
    safe_name = _API_TOOL_NAME_PATTERN.sub("_", tool_name).strip("_")
    return safe_name or "tool"


@dataclass(frozen=True)
class ToolContext:
    repository: RepositoryContext
    file_tree: FileTreeSnapshot
    conversation: ConversationState | None = None


@dataclass(frozen=True)
class ToolSpec:
    tool_name: str
    source_module: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    output_contract: str | None = None
    safety_notes: tuple[str, ...] = ()
    deterministic: bool = True
    aliases: tuple[str, ...] = ()
    seed_priority: int = 100
    preferred_seed: bool = False

    def definition(self) -> LlmToolDefinition:
        return LlmToolDefinition(
            tool_name=self.tool_name,
            source_module=self.source_module,
            description=self.description,
            input_schema=self.parameters,
            output_contract=self.output_contract,
            safety_notes=list(self.safety_notes),
            deterministic=self.deterministic,
        )

    def api_tool_name(self) -> str:
        return to_api_tool_name(self.tool_name)

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.api_tool_name(),
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True)
class SeedPlanItem:
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    max_chars: int = 6000
