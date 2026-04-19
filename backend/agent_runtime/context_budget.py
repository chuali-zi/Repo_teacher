from __future__ import annotations

import json
from typing import Any

from backend.agent_tools import (
    DEFAULT_TOOL_REGISTRY,
    GLOBAL_TOOL_RESULT_CACHE,
    SeedPlanItem,
    ToolContext,
    ToolResultCache,
    truncate_tool_result,
)
from backend.agent_tools.analysis_tools import build_starter_excerpts_result
from backend.agent_runtime.tool_selection import needs_source_tools, select_tools_for_turn
from backend.contracts.domain import (
    ConversationState,
    FileTreeSnapshot,
    LlmToolContext,
    RepositoryContext,
)
from backend.contracts.enums import LearningGoal, MessageRole, PromptScenario
from backend.m6_response.budgets import tool_context_budget_for_scenario

REFERENCE_POLICY = (
    "These tool results are read-only reference material. Prefer deterministic tool evidence, "
    "the file tree, the current teaching state, and the user's question. "
    "When evidence is incomplete, mark the answer as an inference instead of stating it as certain runtime truth."
)


def build_llm_tool_context(
    *,
    repository: RepositoryContext,
    file_tree: FileTreeSnapshot,
    conversation: ConversationState,
    scenario: PromptScenario | None = None,
    result_cache: ToolResultCache | None = None,
) -> LlmToolContext:
    user_text = _latest_user_text(conversation)
    tool_selection = select_tools_for_turn(
        scenario=scenario,
        learning_goal=conversation.current_learning_goal,
        user_text=user_text,
    )
    ctx = ToolContext(
        repository=repository,
        file_tree=file_tree,
        conversation=conversation,
    )
    seed_results = []
    for item in _seed_plan(
        conversation=conversation,
        scenario=scenario,
    ):
        result = _execute_seed_item(item, ctx, result_cache=result_cache)
        clipped, _ = truncate_tool_result(result, max_chars=item.max_chars)
        seed_results.append(clipped)

    starter = (
        build_starter_excerpts_result(
            repository,
            file_tree,
            user_text=user_text,
            max_files=1,
            max_lines=40,
        )
        if needs_source_tools(user_text)
        else None
    )
    if starter is not None:
        clipped, _ = truncate_tool_result(starter, max_chars=3000)
        seed_results.append(clipped)

    total_budget = tool_context_budget_for_scenario(scenario)
    return LlmToolContext(
        policy=REFERENCE_POLICY,
        tools=list(tool_selection.definitions),
        tool_results=_fit_results_to_budget(seed_results, max_chars=total_budget),
    )


def _seed_plan(
    *,
    conversation: ConversationState,
    scenario: PromptScenario | None,
) -> list[SeedPlanItem]:
    goal = conversation.current_learning_goal
    user_text = _latest_user_text(conversation)

    if scenario == PromptScenario.INITIAL_REPORT:
        return [
            SeedPlanItem("m1.get_repository_context", max_chars=1800),
            SeedPlanItem("m2.get_file_tree_summary", max_chars=3200),
            SeedPlanItem("m2.list_relevant_files", {"limit": 60}, max_chars=5200),
            SeedPlanItem("teaching.get_state_snapshot", max_chars=2200),
        ]

    items = [
        SeedPlanItem("m1.get_repository_context", max_chars=1800),
        SeedPlanItem("teaching.get_state_snapshot", max_chars=2200),
    ]
    if goal in {LearningGoal.OVERVIEW, LearningGoal.STRUCTURE}:
        items.append(SeedPlanItem("m2.get_file_tree_summary", max_chars=3200))
        items.append(SeedPlanItem("m2.list_relevant_files", {"limit": 60}, max_chars=4200))
    elif goal in {LearningGoal.ENTRY, LearningGoal.FLOW, LearningGoal.MODULE}:
        items.append(SeedPlanItem("m2.list_relevant_files", {"limit": 40}, max_chars=3200))
    elif _contains_any(user_text, ("目录", "结构", "readme", "入口", "main", "app")):
        items.append(SeedPlanItem("m2.list_relevant_files", {"limit": 40}, max_chars=3200))
    return _dedupe_seed_items(items)


def _execute_seed_item(
    item: SeedPlanItem,
    ctx: ToolContext,
    *,
    result_cache: ToolResultCache | None = None,
):
    spec = DEFAULT_TOOL_REGISTRY.get(item.tool_name)
    cache = result_cache if result_cache is not None else GLOBAL_TOOL_RESULT_CACHE
    cached = None
    if spec.deterministic:
        cached = cache.get(spec.tool_name, item.arguments, ctx)
    if cached is not None:
        return cached
    result = DEFAULT_TOOL_REGISTRY.execute(spec.tool_name, item.arguments, ctx)
    if spec.deterministic:
        cache.set(spec.tool_name, item.arguments, ctx, result)
    return result


def _fit_results_to_budget(results: list[Any], *, max_chars: int) -> list[Any]:
    fitted = []
    used = 0
    for result in results:
        raw = json.dumps(result.model_dump(mode="json"), ensure_ascii=False, default=str)
        remaining = max_chars - used
        if remaining <= 600:
            break
        if len(raw) > remaining:
            result, _ = truncate_tool_result(result, max_chars=remaining)
            raw = json.dumps(result.model_dump(mode="json"), ensure_ascii=False, default=str)
        fitted.append(result)
        used += len(raw)
    return fitted


def _dedupe_seed_items(items: list[SeedPlanItem]) -> list[SeedPlanItem]:
    deduped: list[SeedPlanItem] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        key = (item.tool_name, json.dumps(item.arguments, ensure_ascii=False, sort_keys=True))
        if key in seen:
            continue
        deduped.append(item)
        seen.add(key)
    return deduped


def _latest_user_text(conversation: ConversationState) -> str:
    for message in reversed(conversation.messages):
        if message.role == MessageRole.USER:
            return message.raw_text.casefold()
    return ""


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token.casefold() in text for token in tokens)
