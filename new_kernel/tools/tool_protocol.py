"""Tool protocol primitives for read-only repository tools."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol


DEFAULT_MAX_LINES = 200
"""Default maximum lines returned by read-type tools."""


DEFAULT_MAX_SEARCH_HITS = 30
"""Default maximum hit count for search-type tools."""


DEFAULT_LANGUAGE = "zh"
"""Default language flag used by prompt-facing tools."""


@dataclass(frozen=True)
class ToolContext:
    """
    Immutable execution context injected into tool calls.

    Keep this object minimal and transport-only to avoid cross-module state coupling.
    """

    repo_root: str
    max_lines: int = DEFAULT_MAX_LINES
    max_search_hits: int = DEFAULT_MAX_SEARCH_HITS
    language: str = DEFAULT_LANGUAGE

    def __post_init__(self) -> None:
        if self.max_lines < 1:
            raise ValueError("max_lines must be positive")
        if self.max_search_hits < 1:
            raise ValueError("max_search_hits must be positive")
        if not self.language:
            raise ValueError("language must be a non-empty string")


@dataclass(frozen=True)
class ToolParameter:
    """One tool parameter in function-like metadata."""

    name: str
    type: str
    description: str = ""
    required: bool = True
    default: Any = None
    enum: list[str] | None = None

    def to_schema(self) -> dict[str, Any]:
        schema: dict[str, Any] = {"type": self.type, "description": self.description}
        if self.enum:
            schema["enum"] = self.enum
        if self.default is not None:
            schema["default"] = self.default
        return schema


@dataclass(frozen=True)
class ToolDefinition:
    """LLM-facing tool metadata."""

    name: str
    description: str
    parameters: list[ToolParameter] = field(default_factory=list)

    def to_openai_schema(self) -> dict[str, Any]:
        properties = {}
        required: list[str] = []
        for parameter in self.parameters:
            properties[parameter.name] = parameter.to_schema()
            if parameter.required:
                required.append(parameter.name)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }


@dataclass(frozen=True)
class ToolAlias:
    """Alternative action name exposed to the reading agent."""

    name: str
    description: str = ""
    input_format: str = ""


@dataclass(frozen=True)
class ToolPromptHints:
    """Optional hint bundle for prompt composition."""

    short_description: str = ""
    when_to_use: str = ""
    input_format: str = ""
    aliases: tuple[ToolAlias, ...] = ()


@dataclass
class ToolResult:
    """
    Standard tool result payload for read results and tool errors.

    `content` is the primary text observation.
    `metadata` contains structured extras (including truncation flags).
    `success` and `error_code` capture execution state.
    """

    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error_code: str | None = None

    def __str__(self) -> str:
        return self.content

    @classmethod
    def ok(
        cls,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> "ToolResult":
        return cls(content=content, metadata=dict(metadata or {}), success=True, error_code=None)

    @classmethod
    def fail(
        cls,
        content: str,
        *,
        error_code: str,
        metadata: dict[str, Any] | None = None,
    ) -> "ToolResult":
        return cls(
            content=content,
            metadata=dict(metadata or {}),
            success=False,
            error_code=error_code,
        )

    @classmethod
    def from_text_with_limit(
        cls,
        content: str,
        *,
        max_lines: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ToolResult":
        """
        Build a result with truncation metadata when output is oversized.
        """
        meta = dict(metadata or {})
        if max_lines is None or max_lines <= 0:
            return cls(content=content, metadata=meta, success=True, error_code=None)

        lines = content.splitlines()
        if len(lines) <= max_lines:
            return cls(content=content, metadata=meta, success=True, error_code=None)

        meta.update(
            {
                "truncated": True,
                "original_lines": len(lines),
                "returned_lines": max_lines,
            },
        )
        return cls(
            content="\n".join(lines[:max_lines]),
            metadata=meta,
            success=True,
            error_code=None,
        )


class BaseTool(ABC):
    """Base interface for all repository tools in v4."""

    @abstractmethod
    def get_definition(self) -> ToolDefinition:
        """Return LLM-facing definition for this tool."""

    @abstractmethod
    async def execute(self, *, ctx: ToolContext) -> ToolResult:
        """
        Execute tool with explicit context.

        Concrete tools add their own keyword-only parameters, but runtime
        context must be passed as `ctx` only.
        """

    def get_prompt_hints(self, language: str = DEFAULT_LANGUAGE) -> ToolPromptHints:
        _ = language
        definition = self.get_definition()
        return ToolPromptHints(short_description=definition.description)

    @property
    def name(self) -> str:
        return self.get_definition().name


class ToolRuntimeProtocol(Protocol):
    """Protocol for ToolRuntime-like wrappers."""

    @property
    def valid_actions(self) -> frozenset[str]:
        ...

    async def execute(
        self,
        action: str,
        action_input: dict[str, Any],
        *,
        ctx: ToolContext,
    ) -> ToolResult:
        ...

    def build_planner_description(self) -> str:
        ...

    def build_reader_description(self) -> str:
        ...


__all__ = [
    "BaseTool",
    "DEFAULT_LANGUAGE",
    "DEFAULT_MAX_LINES",
    "DEFAULT_MAX_SEARCH_HITS",
    "ToolAlias",
    "ToolContext",
    "ToolDefinition",
    "ToolParameter",
    "ToolPromptHints",
    "ToolResult",
    "ToolRuntimeProtocol",
]
