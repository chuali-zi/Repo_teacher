from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.agent_tools import DEFAULT_TOOL_REGISTRY, ToolRegistry
from backend.contracts.domain import LlmToolDefinition, PromptBuildInput
from backend.contracts.enums import LearningGoal, PromptScenario

MAX_SELECTED_TOOLS = 5


@dataclass(frozen=True)
class ToolSelection:
    tool_names: tuple[str, ...]
    definitions: tuple[LlmToolDefinition, ...]
    openai_schemas: tuple[dict[str, Any], ...]


def select_tools_for_prompt_input(
    input_data: PromptBuildInput,
    *,
    registry: ToolRegistry = DEFAULT_TOOL_REGISTRY,
    max_tools: int = MAX_SELECTED_TOOLS,
) -> ToolSelection:
    return select_tools_for_turn(
        scenario=input_data.scenario,
        learning_goal=input_data.conversation_state.current_learning_goal,
        user_text=input_data.user_message or "",
        registry=registry,
        max_tools=max_tools,
    )


def select_tools_for_turn(
    *,
    scenario: PromptScenario | None,
    learning_goal: LearningGoal,
    user_text: str,
    registry: ToolRegistry = DEFAULT_TOOL_REGISTRY,
    max_tools: int = MAX_SELECTED_TOOLS,
) -> ToolSelection:
    names = _candidate_tool_names(
        scenario=scenario,
        learning_goal=learning_goal,
        user_text=user_text.casefold(),
    )
    selected_names: list[str] = []
    definitions: list[LlmToolDefinition] = []
    schemas: list[dict[str, Any]] = []
    for name in _dedupe_names(names):
        if len(selected_names) >= max_tools:
            break
        try:
            spec = registry.get(name)
        except KeyError:
            continue
        if spec.tool_name in selected_names:
            continue
        selected_names.append(spec.tool_name)
        definitions.append(spec.definition())
        schemas.append(spec.openai_schema())
    return ToolSelection(
        tool_names=tuple(selected_names),
        definitions=tuple(definitions),
        openai_schemas=tuple(schemas),
    )


def _candidate_tool_names(
    *,
    scenario: PromptScenario | None,
    learning_goal: LearningGoal,
    user_text: str,
) -> list[str]:
    names: list[str] = ["m2.list_relevant_files", "search_text"]
    if scenario == PromptScenario.INITIAL_REPORT:
        names.append("read_file_excerpt")
        return names

    if learning_goal in {
        LearningGoal.ENTRY,
        LearningGoal.FLOW,
        LearningGoal.MODULE,
        LearningGoal.DEPENDENCY,
        LearningGoal.LAYER,
    }:
        names.append("read_file_excerpt")
    elif needs_source_tools(user_text):
        names.append("read_file_excerpt")
    return names


def needs_source_tools(text: str) -> bool:
    return _contains_any(
        text,
        ("代码", "源码", "函数", "类", "实现", ".py", "/", "\\", "class ", "def "),
    )


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token.casefold() in text for token in tokens)


def _dedupe_names(names: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for name in names:
        if name in seen:
            continue
        deduped.append(name)
        seen.add(name)
    return deduped
