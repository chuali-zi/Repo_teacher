from __future__ import annotations

from backend.agent_tools import DEFAULT_TOOL_REGISTRY, SeedPlanItem, ToolContext, truncate_tool_result
from backend.agent_tools.analysis_tools import build_starter_excerpts_result
from backend.contracts.domain import (
    AnalysisBundle,
    ConversationState,
    FileTreeSnapshot,
    LlmToolContext,
    RepositoryContext,
    TeachingSkeleton,
    TopicRef,
)
from backend.contracts.enums import LearningGoal, PromptScenario

REFERENCE_POLICY = (
    "These tool results are read-only reference material. Prefer deterministic tool evidence, "
    "the current teaching state, and the user's question. When evidence is incomplete, mark the "
    "answer as an inference instead of stating it as certain runtime truth."
)


def build_llm_tool_context(
    *,
    repository: RepositoryContext,
    file_tree: FileTreeSnapshot,
    analysis: AnalysisBundle,
    teaching_skeleton: TeachingSkeleton,
    conversation: ConversationState,
    topic_slice: list[TopicRef],
    scenario: PromptScenario | None = None,
) -> LlmToolContext:
    ctx = ToolContext(
        repository=repository,
        file_tree=file_tree,
        analysis=analysis,
        teaching_skeleton=teaching_skeleton,
        conversation=conversation,
    )
    seed_results = []
    for item in _seed_plan(
        conversation=conversation,
        topic_slice=topic_slice,
        scenario=scenario,
    ):
        result = DEFAULT_TOOL_REGISTRY.execute(item.tool_name, item.arguments, ctx)
        clipped, _ = truncate_tool_result(result, max_chars=item.max_chars)
        seed_results.append(clipped)

    starter = build_starter_excerpts_result(repository, file_tree, analysis)
    if starter is not None:
        clipped, _ = truncate_tool_result(starter, max_chars=5000)
        seed_results.append(clipped)

    return LlmToolContext(
        policy=REFERENCE_POLICY,
        tools=DEFAULT_TOOL_REGISTRY.definitions(),
        tool_results=seed_results,
    )


def _seed_plan(
    *,
    conversation: ConversationState,
    topic_slice: list[TopicRef],
    scenario: PromptScenario | None,
) -> list[SeedPlanItem]:
    goal = conversation.current_learning_goal
    lead_topic = topic_slice[0].summary if topic_slice and topic_slice[0].summary else None
    items = [
        SeedPlanItem("m1.get_repository_context", max_chars=2500),
        SeedPlanItem("m2.get_file_tree_summary", max_chars=4500),
        SeedPlanItem("m4.get_topic_slice", {"learning_goal": goal}, max_chars=5000),
        SeedPlanItem("teaching.get_state_snapshot", max_chars=4000),
    ]

    if scenario == PromptScenario.INITIAL_REPORT:
        items.extend(
            [
                SeedPlanItem("get_repo_surfaces", {"mode": "teaching"}, max_chars=4500),
                SeedPlanItem("get_entry_candidates", {"mode": "teaching"}, max_chars=4000),
                SeedPlanItem("get_module_map", {"mode": "teaching"}, max_chars=4500),
                SeedPlanItem("get_reading_path", {"mode": "teaching"}, max_chars=4000),
                SeedPlanItem("m4.get_initial_report_skeleton", max_chars=10000),
                SeedPlanItem("m4.get_next_questions", max_chars=2500),
            ]
        )
        return items

    items.extend(
        [
            SeedPlanItem("get_reading_path", {"goal": goal, "mode": "teaching"}, max_chars=3500),
            SeedPlanItem("get_entry_candidates", {"mode": "teaching"}, max_chars=3500),
            SeedPlanItem("get_module_map", {"mode": "teaching"}, max_chars=4000),
        ]
    )
    if goal in {LearningGoal.DEPENDENCY, LearningGoal.LAYER, LearningGoal.FLOW}:
        items.append(SeedPlanItem("m3.get_unknowns_and_warnings", max_chars=3000))
    if lead_topic:
        items.append(SeedPlanItem("get_evidence", {"target": lead_topic}, max_chars=3500))
    return items
