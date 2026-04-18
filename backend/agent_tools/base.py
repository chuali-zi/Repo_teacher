from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from backend.contracts.domain import (
    AnalysisBundle,
    ConversationState,
    FileTreeSnapshot,
    LlmToolDefinition,
    LlmToolResult,
    RepositoryContext,
    TeachingSkeleton,
)

ToolHandler = Callable[[dict[str, Any], "ToolContext"], LlmToolResult]


@dataclass(frozen=True)
class ToolContext:
    repository: RepositoryContext
    file_tree: FileTreeSnapshot
    analysis: AnalysisBundle | None = None
    teaching_skeleton: TeachingSkeleton | None = None
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

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.tool_name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True)
class SeedPlanItem:
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    max_chars: int = 6000
