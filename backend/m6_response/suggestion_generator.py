from __future__ import annotations

from backend.contracts.domain import ConversationState, Suggestion, TopicRef
from backend.contracts.enums import LearningGoal

_GOAL_PRIORITY: tuple[LearningGoal, ...] = (
    LearningGoal.ENTRY,
    LearningGoal.FLOW,
    LearningGoal.MODULE,
    LearningGoal.LAYER,
    LearningGoal.DEPENDENCY,
    LearningGoal.STRUCTURE,
    LearningGoal.SUMMARY,
    LearningGoal.OVERVIEW,
)

_GOAL_TEMPLATES: dict[LearningGoal, str] = {
    LearningGoal.OVERVIEW: "想先重新梳理这个仓库的整体定位吗？",
    LearningGoal.STRUCTURE: "想继续看整体结构和目录分工吗？",
    LearningGoal.ENTRY: "想先看入口或启动点怎么定位吗？",
    LearningGoal.FLOW: "想继续顺着主流程往下看吗？",
    LearningGoal.MODULE: "想挑一个核心模块继续拆开讲吗？",
    LearningGoal.DEPENDENCY: "想看看关键依赖分别负责什么吗？",
    LearningGoal.LAYER: "想把分层关系再理清一点吗？",
    LearningGoal.SUMMARY: "想先做个阶段性总结吗？",
}


def generate_next_step_suggestions(
    conversation: ConversationState,
    topic_refs: list[TopicRef],
) -> list[Suggestion]:
    explained_keys = {(item.item_type, item.item_id) for item in conversation.explained_items}
    sorted_refs = sorted(
        topic_refs,
        key=lambda item: (
            0 if item.topic == conversation.current_learning_goal else 1,
            _goal_rank(item.topic),
            item.ref_id,
        ),
    )
    suggestions: list[Suggestion] = []
    seen_texts: set[str] = set()

    for ref in sorted_refs:
        if len(suggestions) >= 3:
            break
        if (ref.ref_type, ref.target_id) in explained_keys:
            continue
        text = _topic_text(ref)
        if text in seen_texts:
            continue
        suggestions.append(
            Suggestion(
                suggestion_id=f"sug_{ref.ref_id}",
                text=text,
                target_goal=ref.topic,
                related_topic_refs=[ref],
            )
        )
        seen_texts.add(text)

    if suggestions:
        return suggestions[:3]

    fallback_goals = [conversation.current_learning_goal, *_GOAL_PRIORITY]
    for goal in fallback_goals:
        if len(suggestions) >= 3:
            break
        text = _GOAL_TEMPLATES.get(goal)
        if not text or text in seen_texts:
            continue
        suggestions.append(
            Suggestion(
                suggestion_id=f"sug_{goal}_{len(suggestions) + 1}",
                text=text,
                target_goal=goal,
                related_topic_refs=[],
            )
        )
        seen_texts.add(text)
    return suggestions[:3]


def _goal_rank(goal: LearningGoal) -> int:
    try:
        return _GOAL_PRIORITY.index(goal)
    except ValueError:
        return len(_GOAL_PRIORITY)


def _topic_text(ref: TopicRef) -> str:
    if ref.summary:
        return ref.summary if ref.summary.endswith("？") else f"想继续看 {ref.summary} 吗？"
    template = _GOAL_TEMPLATES.get(ref.topic)
    if template:
        return template
    return "想继续沿着当前主题往下看吗？"
